"""OpenCode host bridge for validated native subagent dispatch.

The host owns child sessions. This module owns plan validation, workspace diff,
and the event ledger. A returned background tool call never completes a node.
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .access import (DEFAULT_ACCESS_MODE, is_external_scope, normalize_access_mode,
                     resolve_scope, slugify_title)
from .graph import GraphRejected, PlanGraph, PlanNode
from .authority import can_escalate
from .gates import diff_facts, risk_floor
from .grants import (GRANT_KINDS, MAX_TTL_SECONDS, GrantRejected, binding_hash,
                     clamp_ttl, covers, normalize_constraints, normalize_kind,
                     normalize_scope)
from .intent import Intent, IntentRejected, coverage
from .interceptor import classify
from .toolgate import infer as infer_grants
from .learning import (TemplateRejected, distill_template, instantiate, is_request_class,
                       list_templates, load_template, request_class_of, save_template)
from .metrics import MetricsError, collect, render_panel, run_metrics, summarize, template_summary
from .profiles import run_check
from .scope_guard import FileState, ScopeGuard, Snapshot
from .scheduler_v6 import affected_subgraph, dispatchable, scopes_overlap


class HostBridgeError(RuntimeError):
    pass


def require_isolated_workspace(project: Path, access_mode: str = DEFAULT_ACCESS_MODE) -> None:
    """Reject a user-home workspace before it can create an undispatchable run.

    A whole-home snapshot is both unbounded and semantically wrong: every
    Desktop/Downloads/Library path is outside the project write model, and a
    socket or unreadable file under the home directory used to abort every
    dispatch.  The supported setup is one isolated project directory.
    """
    if access_mode in {"read-only", "danger-full-access"}:
        # Read-only never writes and full mode is explicitly user-authorized;
        # neither needs a bounded workspace snapshot, so home is acceptable.
        return
    resolved = Path(project).resolve()
    if resolved == Path("/").resolve() or resolved == Path.home().resolve():
        raise HostBridgeError(
            "project workspace is the user home directory; Cybertron requires an "
            "isolated project directory. Open OpenCode inside a project folder "
            "(for example ~/projects/<name>) and retry. Paths outside the project "
            "(Desktop, Downloads, Library) are not Cybertron workspace writes.")


_DISPATCH_END_EVENTS = {"node.completed", "node.failed", "node.blocked", "node.cancelled"}


def _peer_was_concurrent(events: list[dict], peer_id: str, current_start: int) -> bool:
    """True when a peer node's active window overlaps the current dispatch.

    A peer that reached a terminal state before the current dispatch started
    is not concurrent; its writes are already part of the current baseline and
    may not be excluded from verification.
    """
    starts = [index for index, event in enumerate(events)
              if event["type"] == "dispatch.started" and event.get("node_id") == peer_id]
    if not starts:
        return False
    last_start = starts[-1]
    if last_start > current_start:
        return True
    ends = [index for index in range(last_start + 1, len(events))
            if events[index]["type"] in _DISPATCH_END_EVENTS
            and events[index].get("node_id") == peer_id]
    return not ends or ends[-1] > current_start


_run_counter = itertools.count()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encode(snapshot: Snapshot) -> bytes:
    payload = {name: {"kind": state.kind, "mode": state.mode,
                      "content": base64.b64encode(state.content).decode("ascii")}
               for name, state in snapshot.entries.items()}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()


def _decode(data: bytes) -> Snapshot:
    raw = json.loads(data)
    return Snapshot({name: FileState(value["kind"], base64.b64decode(value["content"]), value["mode"])
                     for name, value in raw.items()})


class V6HostBridge:
    def __init__(self, project: Path) -> None:
        self.project = Path(project).resolve()
        self.runs = self.project / ".cybertron" / "runs"
        if (self.project / ".cybertron").is_symlink() or self.runs.is_symlink():
            raise HostBridgeError("run storage may not be a symlink")

    def _dir(self, run_id: str) -> Path:
        try:
            if str(uuid.UUID(run_id)) != run_id:
                raise ValueError("noncanonical run ID")
        except (TypeError, ValueError) as exc:
            raise HostBridgeError("invalid run ID") from exc
        direct = self.runs / run_id
        if direct.is_dir() and not direct.is_symlink():
            return direct
        if self.runs.is_dir() and not self.runs.is_symlink():
            for candidate in self.runs.iterdir():
                if candidate.is_symlink() or not candidate.is_dir():
                    continue
                metadata = candidate / "run.json"
                if not metadata.is_file() or metadata.is_symlink():
                    continue
                try:
                    data = json.loads(metadata.read_text())
                except (OSError, ValueError):
                    continue
                if data.get("run_id") == run_id:
                    return candidate
        raise HostBridgeError("run does not exist or is unsafe")

    @staticmethod
    def _card(node: PlanNode) -> str:
        scope = ", ".join(node.write_scope) or "(read only)"
        if node.external_scope:
            scope = f"{scope}; external: {', '.join(node.external_scope)}"
        return f"[{node.node_id}] {node.capability} | {scope}"

    def _external_paths(self, node: PlanNode) -> list[str]:
        return [str(resolve_scope(scope, self.project)) for scope in node.external_scope]

    def _host(self, run_id: str) -> str:
        run_file = self._dir(run_id) / "run.json"
        if not run_file.is_file() or run_file.is_symlink():
            return "opencode"
        try:
            return json.loads(run_file.read_text()).get("host", "opencode")
        except (OSError, ValueError):
            return "opencode"

    def _graph(self, run_id: str) -> PlanGraph:
        return PlanGraph.from_dict(json.loads((self._dir(run_id) / "plan.json").read_text()))

    def _append(self, run_id: str, kind: str, **fields: Any) -> None:
        path = self._dir(run_id) / "events.jsonl"
        event = {"type": kind, "utc": _utc(), **fields}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def events(self, run_id: str) -> list[dict]:
        path = self._dir(run_id) / "events.jsonl"
        try:
            return [json.loads(line) for line in path.read_text().splitlines() if line]
        except (ValueError, TypeError) as exc:
            raise HostBridgeError("event log is corrupt") from exc

    def _workspace_digest(self) -> str:
        snapshot = ScopeGuard(self.project, ()).snapshot()
        visible = {name: (state.kind, state.mode, state.sha256)
                   for name, state in snapshot.entries.items()
                   if not name.startswith((".git/", ".cybertron/runs/"))
                   and name not in {".git", ".cybertron/runs"}}
        return _hash(json.dumps(visible, sort_keys=True).encode())

    @staticmethod
    def _grant_time(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def grant_request(self, run_id: str, node_id: str, kind: str,
                      scope: dict | None = None, constraints: dict | None = None,
                      reason: str = "", ttl_seconds: int | None = None,
                      mode: str = "once") -> dict:
        self._dir(run_id)
        try:
            kind = normalize_kind(kind)
            scope = normalize_scope(scope)
            constraints = normalize_constraints(constraints)
            ttl = clamp_ttl(ttl_seconds)
        except GrantRejected as exc:
            raise HostBridgeError(str(exc)) from exc
        if mode not in {"once", "run", "standing"}:
            raise HostBridgeError("grant mode must be once, run, or standing")
        if not (node_id == "*" and kind == "dangerous.confirm"):
            graph = self._graph(run_id)
            if not isinstance(node_id, str) or node_id not in graph.nodes:
                raise HostBridgeError("grant request needs a node in this run")
            role = graph.nodes[node_id].role
            if not can_escalate(role, kind):
                raise HostBridgeError(f"role {role!r} cannot escalate {kind!r}")
        request_id = str(uuid.uuid4())
        self._append(run_id, "grant.requested", request_id=request_id,
                     node_id=node_id, grant_kind=kind, scope=scope,
                     constraints=constraints, reason=(reason or "")[:500],
                     ttl_seconds=ttl, mode=mode, requested_utc=_utc())
        return {"request_id": request_id, "run_id": run_id, "node_id": node_id,
                "kind": kind, "status": "pending", "scope": scope,
                "constraints": constraints, "ttl_seconds": ttl, "mode": mode}

    def grant_approve(self, run_id: str, request_id: str, *,
                      approver: str = "human", via: str = "host",
                      mode: str | None = None, ttl_seconds: int | None = None) -> dict:
        if approver != "human":
            raise HostBridgeError("only a human approval may issue a grant")
        if mode is None:
            mode = None  # resolved from the request below
        if mode is not None and mode not in {"once", "run", "standing"}:
            raise HostBridgeError("grant mode must be once, run, or standing")
        events = self.events(run_id)
        requested = next((event for event in events
                          if event["type"] == "grant.requested"
                          and event.get("request_id") == request_id), None)
        if requested is None:
            raise HostBridgeError("grant request does not exist")
        if any(event["type"] in {"grant.granted", "grant.denied"}
               and event.get("request_id") == request_id for event in events):
            raise HostBridgeError("grant request already resolved")
        mode = mode or requested.get("mode", "once")
        if mode not in {"once", "run", "standing"}:
            raise HostBridgeError("grant mode must be once, run, or standing")
        try:
            ttl = clamp_ttl(ttl_seconds if ttl_seconds is not None
                            else requested.get("ttl_seconds"))
        except GrantRejected as exc:
            raise HostBridgeError(str(exc)) from exc
        now = datetime.now(timezone.utc)
        cap = self._grant_time(requested["requested_utc"]) + timedelta(seconds=MAX_TTL_SECONDS)
        expires = min(now + timedelta(seconds=ttl), cap)
        grant_id = str(uuid.uuid4())
        grant = {
            "grant_id": grant_id, "request_id": request_id,
            "run_id": run_id, "node_id": requested["node_id"],
            "kind": requested["grant_kind"], "scope": requested.get("scope") or {},
            "constraints": requested.get("constraints") or {},
            "mode": mode, "max_uses": 1 if mode == "once" else (10 if mode == "run" else 1000),
            "issued_by": "human", "issued_via": via,
            "issued_utc": now.isoformat(), "expires_utc": expires.isoformat(),
            "absolute_expires_utc": cap.isoformat(),
            "nonce": request_id,
        }
        grant["binding_sha256"] = binding_hash(
            run_id, grant["node_id"], grant["kind"], grant["scope"],
            grant["constraints"], grant["nonce"])
        payload = {key: value for key, value in grant.items()
                   if key not in {"kind", "run_id"}}
        payload["grant_kind"] = grant["kind"]
        self._append(run_id, "grant.granted", **payload)
        return {**grant, "status": "active", "uses": 0}

    def grant_deny(self, run_id: str, request_id: str, reason: str = "") -> dict:
        events = self.events(run_id)
        requested = next((event for event in events
                          if event["type"] == "grant.requested"
                          and event.get("request_id") == request_id), None)
        if requested is None:
            raise HostBridgeError("grant request does not exist")
        if any(event["type"] in {"grant.granted", "grant.denied"}
               and event.get("request_id") == request_id for event in events):
            raise HostBridgeError("grant request already resolved")
        self._append(run_id, "grant.denied", request_id=request_id,
                     reason=(reason or "")[:500])
        return {"request_id": request_id, "status": "denied", "reason": reason}

    def grant_revoke(self, run_id: str, grant_id: str, reason: str = "") -> dict:
        existing = next((grant for grant in self.grants(run_id)
                         if grant["grant_id"] == grant_id), None)
        if existing is None:
            raise HostBridgeError("grant does not exist")
        self._append(run_id, "grant.revoked", grant_id=grant_id,
                     reason=(reason or "")[:500])
        return {"grant_id": grant_id, "status": "revoked", "reason": reason}

    def grants(self, run_id: str) -> list[dict]:
        events = self.events(run_id)
        requests = {event["request_id"]: event for event in events
                    if event["type"] == "grant.requested"}
        resolved = {event["request_id"] for event in events
                    if event["type"] in {"grant.granted", "grant.denied"}}
        denied = {event["request_id"] for event in events
                  if event["type"] == "grant.denied"}
        grants: list[dict] = []
        for event in events:
            if event["type"] != "grant.granted":
                continue
            grant = {key: event.get(key) for key in (
                "grant_id", "request_id", "run_id", "node_id", "scope",
                "constraints", "mode", "max_uses", "issued_by", "issued_via",
                "issued_utc", "expires_utc", "absolute_expires_utc",
                "nonce", "binding_sha256")}
            grant["kind"] = event.get("grant_kind")
            grant["uses"] = sum(1 for item in events
                                if item["type"] == "grant.used"
                                and item.get("grant_id") == grant["grant_id"])
            revoked = any(item["type"] == "grant.revoked"
                          and item.get("grant_id") == grant["grant_id"] for item in events)
            now = datetime.now(timezone.utc)
            if grant["mode"] == "standing":
                used = [item["used_utc"] for item in events
                        if item["type"] == "grant.used"
                        and item.get("grant_id") == grant["grant_id"]]
                anchor = self._grant_time(max(used)) if used else self._grant_time(grant["issued_utc"])
                absolute = self._grant_time(grant["absolute_expires_utc"])
                expires = min(anchor + timedelta(seconds=8 * 60 * 60), absolute)
            else:
                expires = self._grant_time(grant["expires_utc"])
            expired = expires < now
            if revoked:
                grant["status"] = "revoked"
            elif grant["uses"] >= grant["max_uses"]:
                grant["status"] = "used"
            elif expired:
                grant["status"] = "expired"
            else:
                grant["status"] = "active"
            grants.append(grant)
        for request_id, request in requests.items():
            if request_id not in resolved:
                grants.append({**request, "kind": request.get("grant_kind"),
                               "status": "pending"})
            elif request_id in denied:
                grants.append({**request, "kind": request.get("grant_kind"),
                               "status": "denied"})
        return grants

    def active_grants(self, run_id: str) -> list[dict]:
        return [grant for grant in self.grants(run_id) if grant["status"] == "active"]

    def check_grant(self, run_id: str, node_id: str, kind: str,
                    scope: dict | None = None) -> dict | None:
        try:
            kind = normalize_kind(kind)
            scope = normalize_scope(scope)
        except GrantRejected as exc:
            raise HostBridgeError(str(exc)) from exc
        for grant in self.active_grants(run_id):
            if covers(grant, node_id, kind, scope):
                return grant
        return None

    def consume_grant(self, run_id: str, grant_id: str, node_id: str,
                      call_id: str | None = None) -> dict:
        grant = next((item for item in self.active_grants(run_id)
                      if item["grant_id"] == grant_id), None)
        if grant is None:
            raise HostBridgeError("grant is not active")
        self._append(run_id, "grant.used", grant_id=grant_id, node_id=node_id,
                     call_id=call_id, used_utc=_utc())
        return {**grant, "uses": grant["uses"] + 1}

    def check(self, run_id: str, target: str, call_id: str | None = None,
              node_id: str | None = None) -> dict:
        if target not in {"lint", "build", "test", "sim"}:
            raise HostBridgeError("invalid check target")
        self._dir(run_id)
        node_id = None
        if call_id is not None:
            if not isinstance(call_id, str) or not call_id:
                raise HostBridgeError("call_id must be a nonempty string")
            started = next((event for event in self.events(run_id)
                            if event["type"] == "dispatch.started"
                            and event.get("call_id") == call_id), None)
            if started is None:
                raise HostBridgeError("no matching dispatch for call_id")
            node_id = started.get("node_id")
        elif node_id is not None:
            if not isinstance(node_id, str) or not node_id:
                raise HostBridgeError("node_id must be a nonempty string")
            if node_id not in self._graph(run_id).nodes:
                raise HostBridgeError("node_id is not part of this run")
            current = self.state(run_id)
            active = {entry["node_id"] for entry in current["active_dispatches"]}
            if node_id not in current["ready_nodes"] and node_id not in active:
                raise HostBridgeError("node is not ready or active")
        result = run_check(self.project, target)
        last = result["receipts"][-1]
        self._append(run_id, "gate.check", gate=target, status=result["status"],
                     profile=result["profile"], node_id=node_id, call_id=call_id,
                     receipt={
                         key: last[key] for key in ("source", "command", "exit", "utc", "sha256")
                     }, workspace_sha256=self._workspace_digest())
        return {**result, "run_id": run_id, "state": self.state(run_id)}

    def capabilities(self) -> dict:
        from .graph import CAPABILITY_CATALOG
        return {capability: sorted(roles)
                for capability, roles in CAPABILITY_CATALOG.items()}

    @staticmethod
    def _apply_satisfies_map(node_objects: list[PlanNode],
                             satisfies_map: dict | None) -> None:
        if satisfies_map is None:
            return
        if not isinstance(satisfies_map, dict):
            raise HostBridgeError("satisfies must be an object")
        by_id = {node.node_id: node for node in node_objects}
        for node_id, done_ids in satisfies_map.items():
            if node_id not in by_id:
                raise HostBridgeError(f"satisfies refers to unknown node {node_id!r}")
            if not isinstance(done_ids, (list, tuple)) or any(
                    not isinstance(item, str) or not item for item in done_ids):
                raise HostBridgeError(f"satisfies for {node_id!r} must be a string list")
            by_id[node_id].satisfies = tuple(done_ids)

    def gate_tool(self, run_id: str, node_id: str, tool: str,
                  payload: dict | str | None = None) -> dict:
        """Infer and enforce Grants for a concrete tool call."""
        if node_id not in self._graph(run_id).nodes:
            raise HostBridgeError("tool gate needs a node in this run")
        kinds = infer_grants(tool, payload, self.project)
        if not kinds:
            return {"action": "allow"}
        missing = [kind for kind in kinds
                   if self.check_grant(run_id, node_id, kind, {}) is None]
        if missing:
            self._append(run_id, "grant.required", node_id=node_id,
                         kinds=missing, tool=tool, source="inferred")
            return {"action": "needs_grant", "node_id": node_id,
                    "kinds": missing, "tool": tool}
        for kind in kinds:
            grant = self.check_grant(run_id, node_id, kind, {})
            if grant is not None:
                self.consume_grant(run_id, grant["grant_id"], node_id, None)
        return {"action": "allow", "kinds": kinds}

    def intercept(self, run_id: str, tool: str, payload: dict | None = None) -> dict:
        """Apply the full-access execution interceptor before a tool runs."""
        state = self.state(run_id)
        if state["access_mode"] != "danger-full-access":
            return {"action": "allow", "mode": state["access_mode"]}
        verdict = classify(tool, payload)
        if not verdict["dangerous"]:
            self._append(run_id, "interceptor.allowed", tool=tool,
                         command_sha256=verdict["command_sha256"],
                         access_mode=state["access_mode"])
            return {"action": "allow", "mode": state["access_mode"],
                    "command_sha256": verdict["command_sha256"]}
        scope = {"command_sha256": verdict["command_sha256"]}
        grant = self.check_grant(run_id, "*", "dangerous.confirm", scope)
        if grant is not None:
            self.consume_grant(run_id, grant["grant_id"], "*", None)
            self._append(run_id, "interceptor.confirmed", tool=tool,
                         command_sha256=verdict["command_sha256"],
                         reason=verdict["reason"])
            return {"action": "allow", "mode": state["access_mode"],
                    "confirmed": True, "command_sha256": verdict["command_sha256"]}
        self._append(run_id, "interceptor.confirm_required", tool=tool,
                     command_sha256=verdict["command_sha256"],
                     reason=verdict["reason"], category=verdict["category"])
        return {"action": "confirm", "mode": state["access_mode"],
                "command_sha256": verdict["command_sha256"],
                "reason": verdict["reason"], "category": verdict["category"],
                "instruction": ("call cy_escalate with kind=dangerous.confirm, "
                                "node_id='*', scope.command_sha256, then cy_ask")}

    def plan(self, node_data: dict | list[dict] | None, host_session_id: str, *,
             request_class: str | None = None, template_id: str | None = None,
             objective: str = "", write_scope: list[str] | None = None,
             test_scope: list[str] | None = None, skip: list[str] | None = None,
             access_mode: str | None = None, session_title: str = "",
             slug: str = "", host: str = "opencode",
             intent: dict | None = None,
             satisfies_map: dict | None = None,
             parent_run_id: str | None = None,
             supersedes_run_id: str | None = None,
             change_reason: str = "",
             seed_from_run_id: str | None = None) -> dict:
        if not isinstance(host_session_id, str) or not host_session_id:
            raise HostBridgeError("host session ID is required")
        if host not in {"opencode", "dsh"}:
            raise HostBridgeError("host must be opencode or dsh")
        try:
            mode = normalize_access_mode(access_mode)
        except ValueError as exc:
            raise HostBridgeError(str(exc)) from exc
        requested_mode = access_mode
        intent_obj = None
        if intent is not None:
            try:
                intent_obj = Intent.from_dict(intent)
            except IntentRejected as exc:
                raise HostBridgeError(str(exc)) from exc
        if intent_obj is not None and not intent_obj.confirmed:
            raise HostBridgeError("intent must be confirmed before creating a run")
        if parent_run_id is not None:
            self._dir(parent_run_id)
        if seed_from_run_id is not None:
            self._dir(seed_from_run_id)
            if node_data is not None or template_id is not None:
                raise HostBridgeError("seed_from_run_id cannot combine with nodes or a template")
        if supersedes_run_id is not None:
            old = self.state(supersedes_run_id)
            if old["active_dispatches"] or old["status"] == "running":
                raise HostBridgeError("cannot supersede a run with an active dispatch")
            if old["status"] == "superseded":
                raise HostBridgeError("run is already superseded")
            if old["status"] == "completed":
                supersedes_run_id = None
        if intent_obj is not None and template_id is not None and satisfies_map is None:
            raise HostBridgeError("intent with a template_id seed requires a satisfies map")
        if seed_from_run_id is not None:
            old = self._graph(seed_from_run_id)
            node_objects = [
                PlanNode(
                    node_id=source.node_id, kind=source.kind,
                    capability=source.capability, role=source.role,
                    objective=source.objective,
                    depends_on=tuple(source.depends_on),
                    read_scope=tuple(source.read_scope),
                    write_scope=tuple(source.write_scope),
                    external_scope=tuple(source.external_scope),
                    acceptance=tuple(source.acceptance),
                    verifiers=tuple(source.verifiers),
                    budget=dict(source.budget),
                )
                for source in old.nodes.values()
            ]
            self._apply_satisfies_map(node_objects, satisfies_map)
            graph_seed = PlanGraph(node_objects, access_mode=mode, intent=intent_obj)
        elif template_id is not None:
            try:
                template = load_template(self.project, template_id)
                graph_seed = instantiate(template, objective=objective,
                                         target_scope=tuple(write_scope or ()),
                                         test_scope=tuple(test_scope or ()),
                                         skip=tuple(skip or ()))
            except TemplateRejected as exc:
                raise HostBridgeError(str(exc)) from exc
            node_objects = list(graph_seed.nodes.values())
            if requested_mode is None:
                mode = graph_seed.access_mode
            self._apply_satisfies_map(node_objects, satisfies_map)
            graph_seed = PlanGraph(node_objects, access_mode=mode, intent=intent_obj)
            request_class = request_class or template["request_class"]
        else:
            try:
                node_objects = [PlanNode.from_dict(data) for data in
                                (node_data if isinstance(node_data, list) else [node_data])]
                self._apply_satisfies_map(node_objects, satisfies_map)
                graph_seed = PlanGraph(node_objects, access_mode=mode, intent=intent_obj)
            except (GraphRejected, TypeError) as exc:
                raise HostBridgeError(str(exc)) from exc
        require_isolated_workspace(self.project, mode)
        if not node_objects or any(node.status != "pending" or node.kind not in {"task", "review"} or node.role == "prima" for node in node_objects):
            raise HostBridgeError("plan requires pending subagent task or review nodes")
        if any("scope_guard" not in node.verifiers or
               set(node.verifiers) - {"scope_guard", "loop1"} for node in node_objects):
            raise HostBridgeError("unsupported host verifier")
        if request_class is None:
            request_class = request_class_of(graph_seed.nodes.values())
        if request_class is not None and not is_request_class(request_class):
            raise HostBridgeError("invalid request_class")
        if not isinstance(objective, str):
            raise HostBridgeError("objective must be a string")
        nodes = [node.to_dict() for node in node_objects]
        # A run ID is an identifier, not a secret. The macOS verification
        # sandbox denies /dev/urandom, so uuid4 would make tests fail there.
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                f"{self.project}:{time.time_ns()}:{os.getpid()}:{next(_run_counter)}"))
        title = (session_title or "").strip() or objective.strip()
        slug = slugify_title(slug or title, fallback="run")
        directory = self.runs / slug
        suffix = 2
        while directory.exists() or directory.is_symlink():
            directory = self.runs / f"{slug}-{suffix}"
            suffix += 1
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "plan.json").write_text(json.dumps(graph_seed.to_dict(), ensure_ascii=False))
        (directory / "run.json").write_text(json.dumps({
            "run_id": run_id, "title": title[:200], "slug": slug,
            "host_session_id": host_session_id, "access_mode": mode, "host": host,
            "evidence_level": ("kernel-receipt" if host == "opencode" else "host-approved"),
            "created_utc": _utc(),
            "parent_run_id": parent_run_id,
            "supersedes_run_id": supersedes_run_id,
            "change_reason": change_reason[:500],
            "seed_from_run_id": seed_from_run_id,
        }, ensure_ascii=False))
        (directory / "events.jsonl").touch()
        self._append(run_id, "plan.created", node_id=nodes[0]["node_id"] if len(nodes) == 1 else None,
                     node_ids=[node["node_id"] for node in nodes],
                     host_session_id=host_session_id, plan_revision=graph_seed.revision,
                     request_class=request_class, template_id=template_id,
                     skipped_capabilities=list(skip or ()),
                     access_mode=mode, title=title[:200], slug=slug,
                     request=objective.strip(),
                     intent=intent_obj.to_dict() if intent_obj else None,
                     done_ids=sorted(intent_obj.done_ids) if intent_obj else [],
                     parent_run_id=parent_run_id,
                     supersedes_run_id=supersedes_run_id,
                     change_reason=change_reason[:500],
                     seed_from_run_id=seed_from_run_id)
        if supersedes_run_id is not None:
            self._mark_superseded(supersedes_run_id, run_id, change_reason)
        result = self.state(run_id)
        result["template_reused"] = template_id is not None
        result["request_class"] = request_class
        result["skipped_capabilities"] = list(skip or ())
        result["available_templates"] = self.template_hints(request_class)
        result["access_mode"] = mode
        result["title"] = title[:200]
        result["slug"] = slug
        return result

    def _mark_superseded(self, old_run_id: str, new_run_id: str,
                         reason: str) -> None:
        directory = self._dir(old_run_id)
        run_file = directory / "run.json"
        data = json.loads(run_file.read_text())
        data["superseded_by"] = new_run_id
        data["superseded_utc"] = _utc()
        data["supersede_reason"] = (reason or "")[:500]
        run_file.write_text(json.dumps(data, ensure_ascii=False))
        self._append(old_run_id, "run.superseded", superseded_by=new_run_id,
                     reason=(reason or "")[:500])

    def _plan_review(self, graph: PlanGraph) -> dict:
        """Deterministic plan-feasibility review before the first dispatch."""
        findings: list[dict] = []
        blocking: list[dict] = []

        def add(severity: str, code: str, message: str, node_id: str | None = None) -> None:
            finding = {"severity": severity, "code": code, "message": message}
            if node_id is not None:
                finding["node_id"] = node_id
            findings.append(finding)
            if severity == "blocking":
                blocking.append(finding)

        try:
            graph.validate()
        except GraphRejected as exc:
            add("blocking", "graph.invalid", str(exc))
        for node in graph.nodes.values():
            if not node.acceptance:
                add("blocking", "node.acceptance", "node has no acceptance criteria", node.node_id)
            if "scope_guard" not in node.verifiers:
                add("blocking", "node.scope_guard",
                    "node lacks the mandatory scope_guard verifier", node.node_id)
            if node.kind == "device_op" or node.role == "megatronus":
                add("warning", "device.operation",
                    "physical device operation requires explicit human approval", node.node_id)
            for scope in node.write_scope:
                if is_external_scope(scope):
                    add("warning", "scope.external",
                        f"external write scope {scope!r} requires explicit authorization",
                        node.node_id)
        node_ids = list(graph.nodes)
        for index, left_id in enumerate(node_ids):
            left = graph.nodes[left_id]
            if not left.write_scope:
                continue
            for right_id in node_ids[index + 1:]:
                right = graph.nodes[right_id]
                if right.write_scope and scopes_overlap(left.write_scope, right.write_scope):
                    add("warning", "scope.overlap",
                        f"{left_id} and {right_id} share write scope; the scheduler serializes "
                        "overlapping writers, so verify the dependency order", left_id)
        if graph.intent is not None:
            if not graph.intent.confirmed:
                add("warning", "intent.unconfirmed",
                    "intent has not been confirmed by the human; confirm it before dispatch")
            covered: dict[str, list[str]] = {}
            for node in graph.nodes.values():
                for done_id in node.satisfies:
                    covered.setdefault(done_id, []).append(node.node_id)
            for done in graph.intent.done:
                if not covered.get(done.id):
                    add("blocking", "intent.done.uncovered",
                        f"done criterion {done.id!r} has no satisfying node")
            forbidden_capabilities = set(graph.intent.forbidden_capabilities)
            for node in graph.nodes.values():
                if node.capability in forbidden_capabilities:
                    add("blocking", "intent.capability",
                        f"capability {node.capability!r} is forbidden by the intent",
                        node.node_id)
                for scope in (*node.write_scope, *node.external_scope):
                    if any(scope == pattern or fnmatchcase(scope, pattern)
                           for pattern in graph.intent.forbidden_paths):
                        add("blocking", "intent.path",
                            f"scope {scope!r} is forbidden by the intent", node.node_id)
                        break
        if graph.access_mode == "danger-full-access":
            add("warning", "access.danger",
                "danger-full-access requires explicit human authorization of the outer paths")
        if not graph.gates:
            add("info", "gates.none", "no extra gates declared; scope_guard still applies")
        return {"approved": not blocking, "blocking": blocking, "findings": findings}

    def review_plan(self, run_id: str) -> dict:
        """Record prima's review of the current plan revision before dispatch."""
        graph = self._graph(run_id)
        review = self._plan_review(graph)
        plan_path = self._dir(run_id) / "plan.json"
        digest = _hash(plan_path.read_bytes())
        self._append(run_id, "plan.reviewed", reviewer="prima",
                     plan_revision=graph.revision, plan_sha256=digest,
                     approved=review["approved"], findings=review["findings"])
        state = self.state(run_id)
        return {**review, "run_id": run_id, "plan_revision": graph.revision,
                "plan_sha256": digest, "state": state}

    def state(self, run_id: str) -> dict:
        graph = self._graph(run_id)
        events = self.events(run_id)
        status = {node_id: "pending" for node_id in graph.nodes}
        child = {}
        starts = {}
        active_calls = {}
        for event in events:
            node_id = event.get("node_id")
            if event["type"] == "dispatch.started" and node_id in status:
                status[node_id] = "running"
                starts[event["call_id"]] = node_id
                active_calls[event["call_id"]] = {"node_id": node_id, "call_id": event["call_id"],
                                                  "child_session_id": None}
            elif event["type"] == "dispatch.returned" and event.get("call_id"):
                if event["call_id"] in starts:
                    child[starts[event["call_id"]]] = event.get("child_session_id")
                    if event["call_id"] in active_calls:
                        active_calls[event["call_id"]]["child_session_id"] = event.get("child_session_id")
            elif event["type"].startswith("node.") and node_id in status:
                status[node_id] = "pending" if event["type"] == "node.retry" else event["type"].split(".", 1)[1]
                if event["type"] != "node.retry":
                    for call_id, entry in list(active_calls.items()):
                        if entry["node_id"] == node_id:
                            del active_calls[call_id]
        for node_id, value in status.items():
            graph.nodes[node_id].status = value
        required_gates = set(graph.gates)
        for event in events:
            if event["type"] == "gate.required":
                required_gates.update(event["gates"])
        passed_gates = set()
        passed_gate_nodes: dict[str, set[str]] = {}
        if any(event["type"] == "node.completed" for event in events):
            passed_gates.add("scope_guard")
        current_digest = self._workspace_digest() if any(
            event["type"] == "gate.check" for event in events) else None
        for event in events:
            if (event["type"] == "gate.check" and event["status"] == "pass"
                    and event["workspace_sha256"] == current_digest):
                passed_gates.add(event["gate"])
                node_id = event.get("node_id")
                if isinstance(node_id, str) and node_id:
                    passed_gate_nodes.setdefault(event["gate"], set()).add(node_id)
        pending_gates = sorted(required_gates - passed_gates)
        intent_coverage = coverage(graph.intent, graph.nodes, status, events, passed_gates,
                                   passed_gate_nodes)
        intent_blockers = [f"{item['id']}: {item['reason']}" for item in intent_coverage
                           if not item["satisfied"]]
        intent_ok = not intent_blockers
        ready = [node.node_id for node in dispatchable(graph,
                 tuple(entry["node_id"] for entry in active_calls.values()), max_writers=2)
                 if sum(event["type"] == "dispatch.started" and event.get("node_id") == node.node_id
                        for event in events) < node.budget["max_attempts"]]
        repair_feedback = {}
        rejected_calls = {event.get("call_id") for event in events
                          if event["type"] == "review.rejected"}
        for event in events:
            if event["type"] in {"node.failed", "node.blocked"} and event.get("node_id"):
                if event.get("call_id") in rejected_calls:
                    continue
                repair_feedback[event["node_id"]] = event.get("diagnostic") or event.get("reason")
            elif event["type"] == "review.rejected" and event.get("affected_node_id"):
                repair_feedback[event["affected_node_id"]] = (
                    event.get("diagnostic") or event.get("reason"))
        # Feedback is actionable only while the node still needs a retry.
        repair_feedback = {node_id: value for node_id, value in repair_feedback.items()
                           if status.get(node_id) != "completed"}
        nodes = [{"node_id": node.node_id, "status": status[node.node_id],
                  "card": self._card(node), "role": node.role,
                  "write_scope": list(node.write_scope),
                  "external_scope": self._external_paths(node)}
                 for node in graph.nodes.values()]
        active = next(iter(active_calls.values()), None)
        created = next((event for event in events if event["type"] == "plan.created"), {})
        run_dir = self._dir(run_id)
        metadata = {}
        if (run_dir / "run.json").is_file() and not (run_dir / "run.json").is_symlink():
            try:
                metadata = json.loads((run_dir / "run.json").read_text())
            except (OSError, ValueError):
                metadata = {}
        computed_status = ("running" if active else
                           "ready" if ready else "completed"
                           if all(v == "completed" for v in status.values())
                           and not pending_gates and intent_ok else "blocked")
        if metadata.get("superseded_by") and computed_status != "completed":
            computed_status = "superseded"
        result = {"run_id": run_id, "status": computed_status,
                  "plan_revision": graph.revision, "nodes": nodes, "ready_nodes": ready,
                  "required_gates": sorted(required_gates), "passed_gates": sorted(passed_gates),
                  "pending_gates": pending_gates,
                  "repair_feedback": repair_feedback,
                  "intent": graph.intent.to_dict() if graph.intent is not None else None,
                  "intent_coverage": intent_coverage,
                  "intent_blockers": intent_blockers,
                  "grants": self.grants(run_id),
                  "active_grants": self.active_grants(run_id),
                  "parent_run_id": metadata.get("parent_run_id"),
                  "superseded_by": metadata.get("superseded_by"),
                  "supersede_reason": metadata.get("supersede_reason"),
                  "change_reason": metadata.get("change_reason"),
                  "request_class": created.get("request_class"),
                  "template_id": created.get("template_id"),
                  "child_session_id": active["child_session_id"] if active else None,
                  "active_dispatches": list(active_calls.values()),
                  "access_mode": graph.access_mode,
                  "host": self._host(run_id),
                  "evidence_level": metadata.get("evidence_level", "kernel-receipt"),
                  "title": metadata.get("title") or created.get("title"),
                  "slug": metadata.get("slug") or created.get("slug"),
                  "run_dir": str(run_dir),
                  "event_seq": len(events), "events_path": str(run_dir / "events.jsonl")}
        plan_path = run_dir / "plan.json"
        plan_sha = _hash(plan_path.read_bytes()) if plan_path.is_file() else ""
        reviews = [event for event in events if event["type"] == "plan.reviewed"]
        current_review = next((event for event in reversed(reviews)
                               if event.get("plan_revision") == graph.revision
                               and event.get("plan_sha256") == plan_sha), None)
        review = None if current_review is None else {
            "reviewer": current_review.get("reviewer"),
            "plan_revision": current_review.get("plan_revision"),
            "approved": bool(current_review.get("approved")),
            "findings": current_review.get("findings", []),
        }
        review_current = bool(current_review and current_review.get("approved"))
        result.update({
            "review_required": True,
            "review": review,
            "review_current": review_current,
            "handoff": {
                "run_id": run_id,
                "plan_revision": graph.revision,
                "next_agent": "prima",
                "ready_nodes": ready,
                "ready_cards": [self._card(graph.nodes[node_id]) for node_id in ready],
                "access_mode": graph.access_mode,
                "required_gates": sorted(required_gates),
                "review_required": True,
                "review_current": review_current,
            },
        })
        if len(nodes) == 1:
            single_status = nodes[0]["status"]
            if metadata.get("superseded_by"):
                single_status = "superseded"
            elif single_status == "running":
                pass
            elif single_status not in {"failed", "cancelled"}:
                single_status = ("ready" if ready else "blocked"
                                 if (pending_gates or intent_blockers) else single_status)
            result.update({"node_id": nodes[0]["node_id"], "card": nodes[0]["card"],
                           "write_scope": nodes[0]["write_scope"],
                           "status": single_status})
        return result

    def ask(self, run_id: str, question: str,
            answers: list[str] | None = None, approved: bool = False) -> dict:
        if not isinstance(question, str) or not question.strip():
            raise HostBridgeError("question is required")
        if answers is not None:
            if not isinstance(answers, list) or any(not isinstance(item, str) for item in answers):
                raise HostBridgeError("answers must be a string list")
        # An unanswered question must not invalidate an active dispatch.  A
        # question the user already answered or approved through the OpenCode
        # host is a completed fact and may be recorded at any time.
        if answers is None and not approved and self.state(run_id)["status"] == "running":
            raise HostBridgeError("cannot request human input during an active dispatch")
        self._append(run_id, "human.requested", question=question.strip())
        if answers is not None:
            self._append(run_id, "human.answered", question=question.strip(),
                         answers=list(answers), source="opencode.question")
        if approved:
            self._append(run_id, "approval.granted", question=question.strip(),
                         source="opencode.permission")
        return self.state(run_id)

    def template_hints(self, request_class: str | None) -> list[dict]:
        if not isinstance(request_class, str) or not request_class:
            return []
        try:
            templates = [template for template in list_templates(self.project)
                         if template["request_class"] == request_class]
        except TemplateRejected:
            return []
        return [{"template_id": template["template_id"],
                 "node_count": len(template["nodes"]),
                 "dispatch_count": template["metrics"]["dispatch_count"],
                 "human_interventions": template["metrics"]["human_interventions"],
                 "source_run_id": template["source_run_id"]} for template in templates]

    def templates(self) -> dict:
        try:
            items = [{"template_id": template["template_id"],
                      "request_class": template["request_class"],
                      "node_count": len(template["nodes"]),
                      "dispatch_count": template["metrics"]["dispatch_count"],
                      "human_interventions": template["metrics"]["human_interventions"],
                      "source_run_id": template["source_run_id"],
                      "created_utc": template["created_utc"]}
                     for template in list_templates(self.project)]
        except TemplateRejected:
            items = []
        return {"templates": items, "summary": template_summary(self.project)}

    def metrics(self, run_id: str | None = None) -> dict:
        if run_id is not None:
            try:
                return {"run": run_metrics(self._dir(run_id))}
            except MetricsError as exc:
                raise HostBridgeError(str(exc)) from exc
        runs = collect(self.project)
        summary = summarize(runs)
        templates = template_summary(self.project)
        return {"runs": runs, "summary": summary, "templates": templates,
                "panel": render_panel(runs, summary, templates)}

    def _maybe_complete(self, run_id: str) -> None:
        """Record completion once, then distill an advisory template."""
        state = self.state(run_id)
        if state["status"] == "superseded":
            return
        if state["status"] != "completed":
            blockers = state.get("intent_blockers") or []
            if blockers and all(item["status"] == "completed" for item in state["nodes"]):
                events = self.events(run_id)
                if not any(event["type"] == "intent.unmet" and event.get("blockers") == blockers
                           for event in events):
                    self._append(run_id, "intent.unmet", blockers=blockers,
                                 plan_revision=state["plan_revision"])
            return
        events = self.events(run_id)
        if any(event["type"] == "run.completed" for event in events):
            return
        self._append(run_id, "run.completed", node_count=len(state["nodes"]),
                     dispatch_count=sum(event["type"] == "dispatch.started" for event in events),
                     human_interventions=sum(event["type"] in {"human.requested", "approval.granted"}
                                             for event in events))
        graph = self._graph(run_id)
        created = next((event for event in events if event["type"] == "plan.created"), {})
        request_class = created.get("request_class") or request_class_of(graph.nodes.values())
        completed = {event["node_id"] for event in events if event["type"] == "node.completed"}
        try:
            template = distill_template(graph, events,
                                        completed_node_ids=completed,
                                        request_class=request_class, run_id=run_id,
                                        request=created.get("request") or "")
            path = save_template(self.project, template)
        except (TemplateRejected, OSError) as exc:
            self._append(run_id, "template.distill_failed", reason=str(exc))
            return
        self._append(run_id, "template.distilled", template_id=template["template_id"],
                     request_class=request_class, path=str(path))

    def plan_op(self, run_id: str, operation: dict) -> dict:
        if self.state(run_id)["status"] == "running":
            raise HostBridgeError("cannot replan during active dispatch")
        graph = self._graph(run_id)
        state = self.state(run_id)
        for item in state["nodes"]:
            graph.nodes[item["node_id"]].status = item["status"]
        prior = len(graph.events)
        try:
            graph.apply_op(operation)
        except GraphRejected as exc:
            for event in graph.events[prior:]:
                self._append(run_id, event["type"], **{k: v for k, v in event.items() if k != "type"})
            raise HostBridgeError(str(exc)) from exc
        for event in graph.events[prior:]:
            self._append(run_id, event["type"], **{k: v for k, v in event.items() if k != "type"})
        if operation.get("op") == "retry_node":
            self._append(run_id, "node.retry", node_id=operation["node_id"])
        # Runtime state belongs to the event ledger, not the plan projection.
        for node in graph.nodes.values():
            node.status = "pending"
        (self._dir(run_id) / "plan.json").write_text(json.dumps(graph.to_dict(), ensure_ascii=False))
        return self.state(run_id)

    def _snapshot_path(self, run_id: str, call_id: str) -> Path:
        if not isinstance(call_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call_id):
            raise HostBridgeError("invalid host tool call ID")
        return self._dir(run_id) / f"snapshot-{call_id}.json"

    def _token(self, run_id: str, call_id: str) -> str:
        directory = self._dir(run_id)
        started = next((event for event in self.events(run_id)
                        if event["type"] == "dispatch.started" and event.get("call_id") == call_id), None)
        if started is None:
            raise HostBridgeError("no matching dispatch")
        return _hash(self._snapshot_path(run_id, call_id).read_bytes() + b"\0" +
                     json.dumps(started, sort_keys=True).encode() + b"\0" +
                     (directory / "plan.json").read_bytes())

    def _verify_token(self, run_id: str, call_id: str, token: str) -> None:
        if not isinstance(token, str) or self._token(run_id, call_id) != token:
            raise HostBridgeError("dispatch snapshot or plan changed")

    def before(self, run_id: str, node_id: str, role: str, card: str, call_id: str,
               active_token: str | None = None) -> dict:
        graph = self._graph(run_id)
        require_isolated_workspace(self.project, graph.access_mode)
        node = graph.nodes.get(node_id)
        reason = None
        state = self.state(run_id)
        if node is None or node_id not in state["ready_nodes"]:
            reason = "node is not ready"
        elif role != node.role or card != self._card(node):
            reason = "node, role, capability, or write_scope differs from plan"
        elif not isinstance(call_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call_id):
            reason = "host tool call ID is required"
        elif any(event.get("call_id") == call_id for event in self.events(run_id)):
            reason = "host tool call ID already used"
        elif node is not None and node.write_scope and any(
                self._graph(run_id).nodes[entry["node_id"]].write_scope
                and not any(event["type"] == "dispatch.bound" and event.get("call_id") == entry["call_id"]
                            for event in self.events(run_id))
                for entry in state["active_dispatches"]):
            reason = "active writer has no host permission binding"
        if reason:
            self._append(run_id, "plan.op.rejected", node_id=node_id, reason=reason)
            if state["active_dispatches"]:
                return {"rejected": True, "reason": reason, "token": active_token}
            raise HostBridgeError(reason)
        missing: list[str] = []
        matched: list[dict] = []
        for kind in node.requires:
            grant = self.check_grant(run_id, node.node_id, kind, {})
            if grant is None:
                missing.append(kind)
            else:
                matched.append(grant)
        if missing:
            self._append(run_id, "grant.required", node_id=node.node_id,
                         kinds=missing, call_id=call_id)
            return {"rejected": True, "node_id": node.node_id,
                    "reason": "grant required: " + ", ".join(missing),
                    "needs_grant": missing}
        for grant in matched:
            self.consume_grant(run_id, grant["grant_id"], node.node_id, call_id)
        guard = ScopeGuard(self.project, node.write_scope, access_mode=graph.access_mode)
        baseline = guard.snapshot()
        guard.assert_safe_before_dispatch(baseline)
        directory = self._dir(run_id)
        self._snapshot_path(run_id, call_id).write_bytes(_encode(baseline))
        self._append(run_id, "dispatch.started", node_id=node_id, role=role,
                     capability=node.capability, write_scope=list(node.write_scope),
                     external_scope=self._external_paths(node),
                     access_mode=graph.access_mode, call_id=call_id)
        return {"status": "running", "token": self._token(run_id, call_id),
                "node_id": node_id, "write_scope": list(node.write_scope),
                "external_scope": self._external_paths(node),
                "access_mode": graph.access_mode}

    def bind(self, run_id: str, call_id: str, token: str,
             child_session_id: str, write_scope: list[str],
             external_scope: list[str] | None = None) -> dict:
        """Record a host-verified child session permission binding."""
        self._verify_token(run_id, call_id, token)
        events = self.events(run_id)
        start = next((event for event in events if event["type"] == "dispatch.started"
                      and event.get("call_id") == call_id), None)
        returned = next((event for event in events if event["type"] == "dispatch.returned"
                         and event.get("call_id") == call_id), None)
        if not start or not returned or returned.get("child_session_id") != child_session_id:
            raise HostBridgeError("child session does not match dispatch")
        node = self._graph(run_id).nodes[start["node_id"]]
        if write_scope != list(node.write_scope):
            raise HostBridgeError("child permission scope differs from plan")
        if external_scope is not None and list(external_scope) != self._external_paths(node):
            raise HostBridgeError("child external scope differs from plan")
        prior = next((event for event in events if event["type"] == "dispatch.bound"
                      and event.get("call_id") == call_id), None)
        if prior:
            if prior.get("child_session_id") != child_session_id:
                raise HostBridgeError("dispatch already bound to another child")
            return self.state(run_id)
        self._append(run_id, "dispatch.bound", call_id=call_id,
                     node_id=node.node_id, child_session_id=child_session_id,
                     write_scope=write_scope,
                     external_scope=self._external_paths(node))
        return self.state(run_id)

    def permission(self, run_id: str, call_id: str, request_id: str,
                   action: str, resources: list[str],
                   reply: str | None = None, granted: bool = False) -> dict:
        """Record one host permission request or reply for a dispatch.

        The OpenCode plugin calls this from its permission hook. A write to a
        declared external path is accepted by ``finish`` only when the host
        gate actually ran for it, so a silent bypass fails the node.
        """
        if not isinstance(request_id, str) or not request_id:
            raise HostBridgeError("request_id is required")
        if not isinstance(action, str) or not action:
            raise HostBridgeError("action is required")
        if not isinstance(resources, list) or not resources or any(
                not isinstance(item, str) or not item for item in resources):
            raise HostBridgeError("resources must be a nonempty string list")
        if reply is not None and reply not in {"once", "always", "reject"}:
            raise HostBridgeError("reply must be once, always, or reject")
        events = self.events(run_id)
        start = next((event for event in events if event["type"] == "dispatch.started"
                      and event.get("call_id") == call_id), None)
        if start is None:
            raise HostBridgeError("no dispatch for call_id")
        if granted:
            if any(event["type"] == "permission.granted"
                   and event.get("call_id") == call_id
                   and event.get("action") == action
                   and event.get("resources") == list(resources)
                   for event in events):
                return self.state(run_id)
            self._append(run_id, "permission.granted", call_id=call_id,
                         node_id=start["node_id"], request_id=request_id,
                         action=action, resources=list(resources),
                         source="opencode.permission")
        elif reply is None:
            if any(event["type"] == "permission.requested"
                   and event.get("call_id") == call_id
                   and event.get("action") == action
                   and event.get("resources") == list(resources)
                   for event in events):
                return self.state(run_id)
            self._append(run_id, "permission.requested", call_id=call_id,
                         node_id=start["node_id"], request_id=request_id,
                         action=action, resources=list(resources),
                         source="opencode.permission")
        else:
            if any(event["type"] == "permission.resolved"
                   and event.get("call_id") == call_id
                   and event.get("request_id") == request_id
                   and event.get("reply") == reply
                   for event in events):
                return self.state(run_id)
            self._append(run_id, "permission.resolved", call_id=call_id,
                         node_id=start["node_id"], request_id=request_id,
                         action=action, resources=list(resources), reply=reply,
                         source="opencode.permission")
        return self.state(run_id)

    def review_reject(self, run_id: str, call_id: str, token: str,
                      child_session_id: str, affected_node_id: str,
                      diagnostic: str) -> dict:
        """Record a negative L2 finding from the bound native reviewer."""
        self._verify_token(run_id, call_id, token)
        if not isinstance(diagnostic, str) or not diagnostic.strip():
            raise HostBridgeError("L2 rejection requires a diagnostic")
        graph = self._graph(run_id)
        starts = [event for event in self.events(run_id)
                  if event["type"] == "dispatch.started" and event.get("call_id") == call_id]
        bound = [event for event in self.events(run_id)
                 if event["type"] == "dispatch.bound" and event.get("call_id") == call_id
                 and event.get("child_session_id") == child_session_id]
        if len(starts) != 1 or len(bound) != 1:
            raise HostBridgeError("L2 review has no bound native child")
        reviewer = graph.nodes[starts[0]["node_id"]]
        if reviewer.kind != "review" or reviewer.capability != "review.l2":
            raise HostBridgeError("only an L2 review node can reject")
        if affected_node_id not in reviewer.depends_on:
            raise HostBridgeError("rejected producer must be a direct review dependency")
        if any(event["type"] == "review.rejected" and event.get("call_id") == call_id
               for event in self.events(run_id)):
            raise HostBridgeError("review call already rejected")
        state = self.state(run_id)
        producer = next(item for item in state["nodes"] if item["node_id"] == affected_node_id)
        if producer["status"] != "completed":
            raise HostBridgeError("rejected producer has not completed")
        self._append(run_id, "review.rejected", node_id=reviewer.node_id,
                     call_id=call_id, child_session_id=child_session_id,
                     affected_node_id=affected_node_id, diagnostic=diagnostic.strip(),
                     source="host")
        return self.state(run_id)

    def after(self, run_id: str, call_id: str, token: str, child_session_id: str | None,
              tool_status: str, duration_ms: int, output_sha256: str | None = None) -> dict:
        self._verify_token(run_id, call_id, token)
        started = next((event for event in reversed(self.events(run_id))
                        if event["type"] == "dispatch.started" and event.get("call_id") == call_id), None)
        if not started or started["call_id"] != call_id or any(
                event["type"] == "dispatch.returned" and event.get("call_id") == call_id
                for event in self.events(run_id)):
            raise HostBridgeError("no matching active dispatch")
        if tool_status not in {"completed", "error", "cancelled"} or type(duration_ms) is not int or duration_ms < 0:
            raise HostBridgeError("invalid host tool result")
        if tool_status == "completed" and (not isinstance(child_session_id, str) or not child_session_id):
            raise HostBridgeError("native subagent session ID is required")
        self._append(run_id, "dispatch.returned", call_id=call_id,
                     child_session_id=child_session_id, tool_status=tool_status,
                     duration_ms=duration_ms, output_sha256=output_sha256 or _hash(b""))
        if tool_status in {"error", "cancelled"}:
            return self.finish(run_id, token, child_session_id, call_id=call_id)
        return {"status": "running", "token": token,
                "child_session_id": child_session_id, "call_id": call_id}

    def _collect_scope_artifacts(self, paths: list[str], *,
                                 max_files: int = 5000) -> dict[str, str]:
        """Hash declared files, or files under a declared directory scope."""
        artifacts: dict[str, str] = {}
        for target in paths:
            path = Path(target)
            if path.is_symlink():
                continue
            if path.is_file():
                artifacts[str(path)] = _hash(path.read_bytes())
                continue
            if not path.is_dir():
                continue
            for child in sorted(path.rglob("*")):
                if len(artifacts) >= max_files:
                    break
                if child.is_symlink() or not child.is_file():
                    continue
                if ".cybertron" in child.parts and "runs" in child.parts:
                    continue
                artifacts[str(child)] = _hash(child.read_bytes())
        return artifacts

    def finish(self, run_id: str, token: str, child_session_id: str | None,
               *, call_id: str | None = None) -> dict:
        state = self.state(run_id)
        if call_id is None:
            matches = [entry for entry in state["active_dispatches"]
                       if entry["child_session_id"] == child_session_id]
            if len(matches) != 1:
                raise HostBridgeError("ambiguous or missing returned subagent")
            call_id = matches[0]["call_id"]
        self._verify_token(run_id, call_id, token)
        if not any(entry["call_id"] == call_id and entry["child_session_id"] == child_session_id
                   for entry in state["active_dispatches"]):
            raise HostBridgeError("no matching returned subagent")
        returned = next((event for event in reversed(self.events(run_id))
                         if event["type"] == "dispatch.returned" and event.get("call_id") == call_id), None)
        if returned is None:
            raise HostBridgeError("subagent has not returned")
        started = next(event for event in reversed(self.events(run_id))
                       if event["type"] == "dispatch.started" and event["call_id"] == call_id)
        graph = self._graph(run_id)
        node = graph.nodes[started["node_id"]]
        all_events = self.events(run_id)
        start_index = next(index for index, event in enumerate(all_events)
                           if event["type"] == "dispatch.started" and event.get("call_id") == call_id)
        concurrent_writers = any(
            peer.node_id != node.node_id and peer.write_scope
            and _peer_was_concurrent(all_events, peer.node_id, start_index)
            for peer in graph.nodes.values())
        if node.write_scope and concurrent_writers and not any(
                event["type"] == "dispatch.bound" and event.get("call_id") == call_id
                for event in all_events):
            raise HostBridgeError("concurrent writer lacks host permission binding")
        guard = ScopeGuard(self.project, node.write_scope, access_mode=graph.access_mode)
        baseline = _decode(self._snapshot_path(run_id, call_id).read_bytes())
        current = guard.snapshot()
        # This run's ledger/snapshot files are written only by this bridge; their
        # bytes were authenticated against the token held by the host plugin.
        run_rel = self._dir(run_id).relative_to(self.project).as_posix()
        for rel in current.entries:
            if rel.startswith(run_rel + "/"):
                baseline.entries[rel] = current.entries[rel]
        # A concurrent peer has its own node scope and a host-bound narrow
        # session permission. Exclude that peer's writes only while its active
        # window overlaps this dispatch; a peer that finished earlier cannot
        # mask an out-of-scope write here.
        for peer in graph.nodes.values():
            if peer.node_id == node.node_id or not peer.write_scope:
                continue
            if not _peer_was_concurrent(all_events, peer.node_id, start_index):
                continue
            peer_guard = ScopeGuard(self.project, peer.write_scope, access_mode=graph.access_mode)
            for rel, value in current.entries.items():
                if peer_guard._allowed(rel, is_dir=value.kind == "directory"):
                    baseline.entries[rel] = value
            for rel in list(baseline.entries):
                if rel not in current.entries and peer_guard._allowed(
                        rel, is_dir=baseline.entries[rel].kind == "directory"):
                    del baseline.entries[rel]
        report = guard.verify_and_rollback(baseline)
        if report.rejected_paths:
            self._append(run_id, "plan.op.rejected", node_id=node.node_id,
                         reason="write_scope violation", paths=list(report.rejected_paths))
        current_after = guard.snapshot()
        artifacts = {path: value.sha256 for path, value in current_after.entries.items()
                     if path in report.changed_paths and path not in report.rejected_paths and value.kind == "file"}
        if graph.access_mode == "danger-full-access":
            # Full access does not snapshot the workspace. Hash the declared
            # artifacts directly so a completed child still has real evidence.
            # A write_scope may name a directory (for example a temp tree).
            declared = [str(resolve_scope(scope, self.project))
                        for scope in node.write_scope]
            artifacts.update(self._collect_scope_artifacts(declared))
        external_artifacts: dict[str, str] = {}
        unapproved_external: list[str] = []
        host = self._host(run_id)
        if node.external_scope:
            # Outside the project there is no baseline to diff or roll back.
            # Evidence is the artifact hash plus proof that the host gate ran.
            external_artifacts = self._collect_scope_artifacts(
                [str(path) for path in self._external_paths(node)])
            requested = {resource for event in all_events
                         if event["type"] in {"permission.requested", "permission.granted"}
                         and event.get("call_id") == call_id
                         for resource in (event.get("resources") or ())}
            if host == "opencode":
                # OpenCode gates each external write through its own
                # ask/always/reject rules; the kernel verifies that the gate
                # ran. DSH approves through its sandbox mode and one-shot
                # escalation, which the kernel cannot observe, so it records
                # the artifact hash without demanding a kernel-side receipt.
                unapproved_external = sorted(path for path in external_artifacts
                                             if path not in requested)
            artifacts.update(external_artifacts)
        rejection = next((event for event in reversed(all_events)
                          if event["type"] == "review.rejected" and event.get("call_id") == call_id), None)
        if returned["tool_status"] == "cancelled":
            status = "cancelled"
        elif (unapproved_external or rejection or report.rejected_paths
              or returned["tool_status"] == "error"):
            status = "failed"
        elif not artifacts and (node.write_scope or node.external_scope):
            status = "blocked"
        elif not node.write_scope and report.changed_paths:
            status = "failed"
        else:
            status = "completed"
        diagnostic = (rejection["diagnostic"] if rejection else
                      "external write without host approval: " + ", ".join(unapproved_external) if unapproved_external else
                      "write_scope violation: " + ", ".join(report.rejected_paths) if report.rejected_paths else
                      "native subagent error" if returned["tool_status"] == "error" else
                      "no accepted artifact" if status == "blocked" else None)
        fingerprint = _hash(json.dumps({"status": status, "diagnostic": diagnostic,
                                        "paths": report.rejected_paths}, sort_keys=True).encode())
        self._append(run_id, "node." + status, node_id=node.node_id, call_id=call_id,
                     artifacts=artifacts, rejected_paths=list(report.rejected_paths),
                     diagnostic=diagnostic, failure_fingerprint=fingerprint if status in {"failed", "blocked"} else None,
                     evidence={"source": "host", "command": "native.subagent",
                               "exit": 0 if returned["tool_status"] == "completed" else 1,
                               "utc": _utc(), "sha256": returned["output_sha256"],
                               "session_id": child_session_id})
        if status == "completed" and artifacts and graph.access_mode != "danger-full-access":
            facts = diff_facts(baseline, guard.snapshot())
            risk, floor = risk_floor(facts)
            self._append(run_id, "gate.required", node_id=node.node_id,
                         risk=risk.name.lower(), gates=sorted(floor),
                         changed_paths=list(facts.paths), changed_lines=facts.changed_lines)
        if rejection:
            producer_id = rejection["affected_node_id"]
            prior = [event for event in all_events if event["type"] == "review.rejected"
                     and event.get("affected_node_id") == producer_id
                     and event.get("diagnostic") == rejection["diagnostic"]
                     and event.get("call_id") != call_id]
            producer = self._graph(run_id).nodes[producer_id]
            used = sum(event["type"] == "dispatch.started" and event.get("node_id") == producer_id
                       for event in all_events)
            if prior or used >= producer.budget["max_attempts"]:
                self._append(run_id, "loop2.escalated", node_id=producer_id,
                             reason="repeated L2 finding" if prior else "max_attempts exhausted",
                             failure_fingerprint=fingerprint)
            else:
                for affected_id in affected_subgraph(self._graph(run_id), producer_id):
                    self._append(run_id, "node.stale", node_id=affected_id,
                                 cause="review.l2.reject", reviewer=node.node_id)
        elif status in {"failed", "blocked"}:
            failures = [event for event in self.events(run_id)
                        if event["type"] in {"node.failed", "node.blocked"}
                        and event.get("node_id") == node.node_id
                        and event.get("failure_fingerprint") == fingerprint]
            used = sum(event["type"] == "dispatch.started" and event.get("node_id") == node.node_id
                       for event in self.events(run_id))
            if len(failures) >= 2 or used >= node.budget["max_attempts"]:
                self._append(run_id, "loop2.escalated", node_id=node.node_id,
                             reason="repeated failure fingerprint" if len(failures) >= 2 else "max_attempts exhausted",
                             failure_fingerprint=fingerprint)
            else:
                self._append(run_id, "node.retry", node_id=node.node_id,
                             diagnostic=diagnostic, failure_fingerprint=fingerprint,
                             attempt=used + 1)
        self._maybe_complete(run_id)
        return self.state(run_id)
