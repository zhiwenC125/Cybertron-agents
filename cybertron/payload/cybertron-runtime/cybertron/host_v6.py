"""OpenCode host bridge for validated native subagent dispatch.

The host owns child sessions. This module owns plan validation, workspace diff,
and the event ledger. A returned background tool call never completes a node.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import itertools
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase
from functools import wraps
from pathlib import Path
from typing import Any

from .access import (DEFAULT_ACCESS_MODE, hard_denied, is_external_scope, normalize_access_mode,
                     resolve_scope, slugify_title)
from .graph import GraphRejected, PlanGraph, PlanNode, _scope_allowed
from .authority import can_escalate, denied_for_reviewer
from .fenced_shell import ShellRejected, run_fenced_shell
from .gates import Risk, diff_facts, diff_preview, risk_floor
from .grants import (GRANT_KINDS, MAX_TTL_SECONDS, GrantRejected, binding_hash,
                     clamp_ttl, covers, normalize_constraints, normalize_kind,
                     normalize_scope)
from .intent import Intent, IntentRejected, coverage
from .interceptor import classify
from .toolgate import infer as infer_grants
from .learning import (TemplateRejected, distill_template, instantiate, is_request_class,
                       list_templates, load_template, request_class_of, save_template)
from .metrics import MetricsError, collect, render_panel, run_metrics, summarize, template_summary
from .profiles import (CHECK_TARGETS, PROFILE_TOOLS, CheckRejected, detect_profile,
                       run_check, verification_tools)
from .scope_guard import FileState, ScopeGuard, Snapshot
from .scheduler_v6 import affected_subgraph, dispatchable, scopes_overlap


class HostBridgeError(RuntimeError):
    pass


class PlanValidationError(HostBridgeError):
    def __init__(self, findings: list[dict]) -> None:
        self.findings = findings
        super().__init__("; ".join(finding["message"] for finding in findings))


def _serialized(method):
    """Serialize run mutations across plugin bridge processes."""
    @wraps(method)
    def locked(self, run_id, *args, **kwargs):
        with (self._dir(run_id) / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return method(self, run_id, *args, **kwargs)
    return locked


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


def _new_ledger_id() -> str:
    """Create an event identifier when the QA sandbox denies /dev/urandom."""
    if os.environ.get("CYBERTRON_SANDBOX") == "1":
        return str(uuid.uuid5(uuid.NAMESPACE_URL,
                              f"{time.time_ns()}:{os.getpid()}:{next(_run_counter)}"))
    return str(uuid.uuid4())


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
        return [str(Path(os.path.abspath(self.project / Path(scope).expanduser())))
                for scope in node.external_scope]

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

    def _check_inputs_digest(self, target: str) -> str:
        """Hash exactly the source tree copied into a fixed isolated check."""
        snapshot = ScopeGuard(self.project, ()).snapshot()
        ignored = {".git", "node_modules", ".venv", "__pycache__"}
        if target != "sim":
            ignored.add("build")
        visible = {}
        for name, state in snapshot.entries.items():
            parts = name.split("/")
            if parts[0] == ".cybertron" or any(part in ignored for part in parts):
                continue
            visible[name] = (state.kind, state.mode, state.sha256)
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
        request_id = _new_ledger_id()
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
        grant_id = _new_ledger_id()
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
                     grant_kind=grant["kind"], call_id=call_id, used_utc=_utc())
        return {**grant, "uses": grant["uses"] + 1}

    @_serialized
    def check(self, run_id: str, target: str, call_id: str | None = None,
              node_id: str | None = None, child_session_id: str | None = None) -> dict:
        if target not in CHECK_TARGETS:
            raise HostBridgeError("invalid check target")
        graph = self._graph(run_id)
        planned = graph.planned_verification
        diagnostic = False
        if planned:
            node = graph.nodes.get(node_id)
            state = self.state(run_id)
            events = self.events(run_id)
            diagnostic = node is not None and node.capability == "diagnose"
            if (node is None or node.check_target != target
                    or not any(entry["call_id"] == call_id and entry["node_id"] == node_id
                               and child_session_id and entry["child_session_id"] == child_session_id
                               for entry in state["active_dispatches"])
                    or not any(event["type"] == "dispatch.bound" and event.get("call_id") == call_id
                               for event in events)):
                raise HostBridgeError("check requires its bound native verification child")
            if any(event["type"] in {"gate.check", "diagnostic.check"} and event.get("call_id") == call_id
                   for event in events):
                raise HostBridgeError("this verification attempt already has a check receipt")
        if call_id is not None:
            if not isinstance(call_id, str) or not call_id:
                raise HostBridgeError("call_id must be a nonempty string")
            started = next((event for event in self.events(run_id)
                            if event["type"] == "dispatch.started"
                            and event.get("call_id") == call_id), None)
            if started is None:
                raise HostBridgeError("no matching dispatch for call_id")
            if node_id is not None and node_id != started.get("node_id"):
                raise HostBridgeError("node_id differs from the bound dispatch")
            node_id = started.get("node_id")
        elif node_id is not None:
            if not isinstance(node_id, str) or not node_id:
                raise HostBridgeError("node_id must be a nonempty string")
            if node_id not in self._graph(run_id).nodes:
                raise HostBridgeError("node_id is not part of this run")
            current = self.state(run_id)
            active = {entry["node_id"] for entry in current["active_dispatches"]}
            completed = {item["node_id"] for item in current["nodes"]
                         if item["status"] == "completed"}
            if node_id not in current["ready_nodes"] and node_id not in active \
                    and node_id not in completed:
                raise HostBridgeError("node is not ready, active, or completed")
        result = self._run_check(run_id, graph, target, [node_id], call_id=call_id,
                                 diagnostic=diagnostic)
        return {**result, "run_id": run_id, "state": self.state(run_id)}

    def _run_check(self, run_id: str, graph: PlanGraph, target: str,
                   node_ids: list[str | None], *, call_id: str | None = None,
                   diagnostic: bool = False, inline: bool = False) -> dict:
        inputs_before = self._check_inputs_digest(target)
        try:
            result = run_check(self.project, target)
        except (CheckRejected, OSError) as exc:
            if not graph.planned_verification:
                raise
            result = {"status": "unavailable", "profile": None, "target": target,
                      "diagnostic": str(exc), "receipts": []}
        inputs_after = self._check_inputs_digest(target)
        if inputs_before != inputs_after:
            result = {**result, "status": "stale"}
        receipts = result["receipts"]
        last = receipts[-1] if receipts else None
        diagnosis = result.get("diagnostic") or (last["output"][-4000:] if last and result["status"] != "pass" else None)
        check_id = _new_ledger_id()
        for node_id in node_ids:
            self._append(run_id, "diagnostic.check" if diagnostic else "gate.check",
                         gate=target, status=result["status"], inline=inline, check_id=check_id,
                         profile=result["profile"], node_id=node_id, call_id=call_id,
                         plan_revision=graph.revision, diagnostic=diagnosis, receipt={
                             key: last[key] for key in ("source", "command", "exit", "utc", "sha256")
                         } if last else None, receipts=receipts,
                         inputs_sha256=inputs_after, input_target=target)
        return result

    @_serialized
    def verify_pending(self, run_id: str, *, retry: bool = False) -> dict:
        """Settle outstanding fixed checks after the active writers have returned."""
        state = self.state(run_id)
        checks = state.get("pending_checks", [])
        if (not checks or state["active_dispatches"] or not state["review_current"]
                or state["status"] == "superseded"):
            return state
        graph = self._graph(run_id)
        targets: dict[str, list[str | None]] = {}
        for check in checks:
            if check["status"] == "pending" or retry and check["can_retry"]:
                targets.setdefault(check["target"], []).append(check["node_id"])
        for target, node_ids in targets.items():
            self._run_check(run_id, graph, target, node_ids, inline=True)
        self._maybe_complete(run_id)
        return self._publish_plan(self.state(run_id))

    @_serialized
    def fenced_shell(self, run_id: str, call_id: str, child_session_id: str,
                     role: str, commands: object, cwd: str = ".") -> dict:
        state = self.state(run_id)
        graph = self._graph(run_id)
        active = next((entry for entry in state["active_dispatches"]
                       if entry["call_id"] == call_id and child_session_id
                       and entry["child_session_id"] == child_session_id), None)
        events = self.events(run_id)
        if (state["host"] != "opencode" or state["access_mode"] != "workspace-write"
                or not state["review_current"] or state["status"] != "running" or active is None
                or not any(event["type"] == "dispatch.bound" and event["call_id"] == call_id
                           and event["child_session_id"] == child_session_id for event in events)):
            raise HostBridgeError("cy_shell requires an active, verified project child")
        node = graph.nodes[active["node_id"]]
        if node.role != role or node.kind not in {"task", "review"} or node.check_target:
            raise HostBridgeError("cy_shell is not permitted for this node and role")
        try:
            result = run_fenced_shell(self.project, role, commands, cwd)
        except (ShellRejected, OSError) as exc:
            self._append(run_id, "shell.rejected", node_id=node.node_id, call_id=call_id,
                         role=role, plan_revision=graph.revision, diagnostic=str(exc))
            raise HostBridgeError(str(exc)) from exc
        self._append(run_id, "shell.executed", node_id=node.node_id, call_id=call_id,
                     role=role, plan_revision=graph.revision,
                     **{key: result[key] for key in ("cwd", "status", "inputs_sha256", "source_intact")},
                     receipts=[{key: value for key, value in item.items() if key != "output"}
                               for item in result["receipts"]])
        return result

    def capabilities(self) -> dict:
        from .graph import CAPABILITY_CATALOG
        return {capability: sorted(roles)
                for capability, roles in CAPABILITY_CATALOG.items()}

    def planning_tools(self) -> dict:
        from .registry import PRIME_ROLES
        return {"roles": self.capabilities(), "checks": verification_tools(self.project),
                "write_roots": {name: list(role.write_roots) for name, role in PRIME_ROLES.items()
                                if role.write_roots},
                "reviews": {"review.l1": "micronus-prime", "review.l2": "liege-maximo"},
                "diagnosis": {"kind": "task", "capability": "diagnose", "role": "quintus-prime",
                              "check_targets": ["test", "sim"]},
                "acceptance": {"kind": "verify", "capability": "accept", "role": "megatronus",
                               "receipt": "kernel", "tool": "cy_verify"}}

    @_serialized
    def planning_handoff(self, run_id: str, parent_session_id: str) -> dict:
        state = self.state(run_id)
        if state["active_dispatches"] or state["status"] in {"completed", "superseded"}:
            raise HostBridgeError("replanning requires a settled, unfinished run")
        if not any(action.get("agent") == "thirteenth" for action in state["next_actions"]):
            raise HostBridgeError("the run has no pending replanning action")
        self._append(run_id, "plan.handoff", parent_session_id=parent_session_id,
                     plan_revision=state["plan_revision"], feedback=state["replan_feedback"],
                     repair_feedback=state["repair_feedback"])
        return state

    @_serialized
    def verify_acceptance(self, run_id: str, call_id: str, child_session_id: str,
                          passed: bool, findings: str) -> dict:
        state = self.state(run_id)
        graph = self._graph(run_id)
        active = next((entry for entry in state["active_dispatches"]
                       if entry["call_id"] == call_id
                       and entry["child_session_id"] == child_session_id), None)
        events = self.events(run_id)
        if (active is None or graph.nodes[active["node_id"]].capability != "accept"
                or not any(event["type"] == "dispatch.bound" and event.get("call_id") == call_id
                           for event in events)):
            raise HostBridgeError("acceptance requires its bound native verification child")
        node_id = active["node_id"]
        if type(passed) is not bool or not isinstance(findings, str) or not findings.strip():
            raise HostBridgeError("acceptance requires a verdict and findings")
        unmet = [item["id"] for item in state["intent_coverage"]
                 if not item["satisfied"] and not (
                     item["evidence"] == "receipt" and node_id in item["covered_by"])]
        if passed and unmet:
            raise HostBridgeError("acceptance evidence is missing for: " + ", ".join(unmet))
        if passed and graph.adaptive_verification and set(state["pending_gates"]) - {"accept"}:
            raise HostBridgeError("required verification must pass before independent acceptance")
        result = {"passed": passed, "findings": findings[:4000],
                  "criteria": state["intent_coverage"]}
        self._append(run_id, "acceptance.checked", node_id=node_id, call_id=call_id,
                     plan_revision=graph.revision, **result)
        return result

    @_serialized
    def observe_review_read(self, run_id: str, call_id: str, child_session_id: str,
                            path: str, output_sha256: str) -> None:
        graph = self._graph(run_id)
        if not graph.planned_verification:
            return
        active = next((entry for entry in self.state(run_id)["active_dispatches"]
                       if entry["call_id"] == call_id and entry["child_session_id"] == child_session_id), None)
        if (active is None or graph.nodes[active["node_id"]].kind != "review"
                or not any(event["type"] == "dispatch.bound" and event.get("call_id") == call_id
                           for event in self.events(run_id))):
            return
        target = Path(path)
        try:
            relative = target.relative_to(self.project).as_posix()
        except ValueError:
            return
        if (denied_for_reviewer(relative) or hard_denied(relative) or not target.is_file()
                or target.resolve() != target or not re.fullmatch(r"[a-f0-9]{64}", output_sha256)):
            return
        self._append(run_id, "review.read", node_id=active["node_id"], call_id=call_id,
                     role=graph.nodes[active["node_id"]].role, path=relative,
                     output_sha256=output_sha256, file_sha256=_hash(target.read_bytes()),
                     plan_revision=graph.revision)

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

    def delete_path(self, run_id: str, node_id: str, path: str) -> dict:
        """Delete exactly one declared node path after a dangerous.confirm grant."""
        if not isinstance(path, str) or not path:
            raise HostBridgeError("delete path must be a nonempty string")
        graph = self._graph(run_id)
        node = graph.nodes.get(node_id)
        if node is None:
            raise HostBridgeError("delete path needs a node in this run")
        target = Path(path).resolve()
        allowed = {resolve_scope(scope, self.project) for scope in node.write_scope}
        if target not in allowed:
            raise HostBridgeError("delete path is outside the node write_scope")
        forbidden = {Path("/"), Path.home().resolve(),
                     Path(self.project).resolve()}
        if target in forbidden or any(part in {".git", ".opencode", ".cybertron"}
                                      for part in target.parts):
            raise HostBridgeError("delete path is hard-denied")
        grant = self.check_grant(run_id, node_id, "dangerous.confirm", {})
        if grant is None:
            return {"status": "needs_grant", "node_id": node_id,
                    "kind": "dangerous.confirm"}
        self.consume_grant(run_id, grant["grant_id"], node_id, None)
        if not target.exists() and not target.is_symlink():
            self._append(run_id, "delete.absent", node_id=node_id, path=str(target))
            return {"status": "absent", "path": str(target)}
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        self._append(run_id, "delete.performed", node_id=node_id, path=str(target))
        return {"status": "deleted", "path": str(target)}

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

    def intercept(self, run_id: str, tool: str, payload: dict | None = None,
                  node_id: str | None = None) -> dict:
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
        if grant is None and node_id is not None:
            # A node-level dangerous.confirm approval covers this node's
            # dangerous action; the command hash is still recorded below.
            grant = self.check_grant(run_id, node_id, "dangerous.confirm", {})
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

    @staticmethod
    def _assert_write_roles(nodes: list[PlanNode]) -> None:
        from .registry import THIRTEEN_PRIMES_REGISTRY
        profiles = {prime.agent_id: prime for prime in THIRTEEN_PRIMES_REGISTRY}
        for node in nodes:
            if not (node.write_scope or node.external_scope):
                continue
            profile = profiles.get(node.role)
            if profile is None:
                raise HostBridgeError(f"unknown role {node.role!r}")
            if not any(rule.action in {"write", "edit"}
                       and rule.effect.value == "allow"
                       for rule in profile.permissions):
                raise HostBridgeError(
                    f"role {node.role!r} has no write/edit permission for a write_scope node {node.node_id!r}")

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
             seed_from_run_id: str | None = None,
             planned_verification: bool = False, gates: list[str] | None = None,
             adaptive_verification: bool = False) -> dict:
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
                    check_target=source.check_target,
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
        graph_seed.adaptive_verification = adaptive_verification and host == "opencode" and mode == "workspace-write"
        graph_seed.planned_verification = planned_verification or graph_seed.adaptive_verification
        graph_seed.gates = list(gates or ())
        graph_seed.validate()
        require_isolated_workspace(self.project, mode)
        if any(node.status != "pending" for node in node_objects):
            raise HostBridgeError("new plan nodes must be pending")
        if request_class is None:
            request_class = request_class_of(graph_seed.nodes.values())
        if request_class is not None and not is_request_class(request_class):
            raise HostBridgeError("invalid request_class")
        if not isinstance(objective, str):
            raise HostBridgeError("objective must be a string")
        if host == "opencode":
            for node in graph_seed.nodes.values():
                paths = [Path(p) for p in self._external_paths(node)]
                canonical = [p.parent.resolve() / p.name for p in paths]
                if any(p.is_symlink() for p in paths) or any(
                        p == self.project or self.project in p.parents or hard_denied(str(p))
                        for p in canonical):
                    raise HostBridgeError("external scope must name a non-protected path outside the project")
                node.external_scope = tuple(dict.fromkeys(map(str, canonical)))
            graph_seed.validate()
        review = self._plan_review(graph_seed, host=host)
        if not review["approved"]:
            raise PlanValidationError(review["blocking"])
        exact_file = host == "opencode" and self._exact_file(graph_seed)
        nodes = [node.to_dict() for node in graph_seed.nodes.values()]
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
        plan_data = json.dumps(graph_seed.to_dict(), ensure_ascii=False).encode()
        (directory / "plan.json").write_bytes(plan_data)
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
                     plan_sha256=_hash(plan_data),
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
        self._append(run_id, "plan.reviewed", reviewer="kernel",
                     plan_revision=graph_seed.revision, plan_sha256=_hash(plan_data),
                     approved=True, findings=review["findings"])
        if supersedes_run_id is not None:
            self._mark_superseded(supersedes_run_id, run_id, change_reason)
        if exact_file:
            node = next(iter(graph_seed.nodes.values()))
            if node.write_scope:
                relative = node.write_scope[0]
                target = self.project / relative
                if (target.is_file() and not target.is_symlink()
                        and target.resolve() == target and target.stat().st_nlink == 1
                        and _hash(target.read_bytes()) == node.expected_content_sha256):
                    self._append(run_id, "node.completed", node_id=node.node_id,
                                 outcome="completed_without_change",
                                 artifacts={relative: node.expected_content_sha256},
                                 evidence={"source": "kernel", "command": "check-file-content",
                                           "exit": 0, "utc": _utc(),
                                           "sha256": node.expected_content_sha256})
                    self._maybe_complete(run_id)
        result = self.state(run_id)
        result["template_reused"] = template_id is not None
        result["request_class"] = request_class
        result["skipped_capabilities"] = list(skip or ())
        result["available_templates"] = self.template_hints(request_class)
        result["access_mode"] = mode
        result["title"] = title[:200]
        result["slug"] = slug
        return self._publish_plan(result)

    @staticmethod
    def _exact_file(graph: PlanGraph) -> bool:
        if graph.access_mode != "workspace-write" or len(graph.nodes) != 1 or graph.gates:
            return False
        node = next(iter(graph.nodes.values()))
        local_file = (len(node.write_scope) == 1 and node.capability in {"doc.write", "code.write"})
        external_file = (len(node.external_scope) == 1 and not node.write_scope
                         and Path(node.external_scope[0]).suffix in {".md", ".txt"})
        return (node.kind == "task" and node.expected_content_sha256 is not None
                and (local_file or external_file and node.capability == "doc.write")
                and not node.requires and node.verifiers == ("scope_guard",)
                and (graph.intent is None or
                     all(item.evidence == "artifact" and item.id in node.satisfies
                         for item in graph.intent.done)))

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

    def _plan_review(self, graph: PlanGraph, *, host: str) -> dict:
        """Validate the evidence and scope of a candidate plan."""
        findings: list[dict] = []
        blocking: list[dict] = []

        def add(severity: str, code: str, message: str, node_id: str | None = None) -> None:
            finding = {"severity": severity, "code": code, "message": message}
            if node_id is not None:
                finding["node_id"] = node_id
            findings.append(finding)
            if severity == "blocking":
                blocking.append(finding)

        if not graph.nodes:
            add("blocking", "graph.empty", "the plan requires at least one node")
        tools = verification_tools(self.project) if graph.planned_verification else {}
        test_tool = tools.get("test", {})
        python_tests_missing = (test_tool.get("profile") == "python"
                                and not any((self.project / "tests").rglob("test*.py")))
        gate_nodes = {"scope_guard": list(graph.nodes.values())}
        for node in graph.nodes.values():
            valid_kinds = {"task", "review", "verify"} if graph.planned_verification else {"task", "review"}
            if (node.kind not in valid_kinds or node.role in {"prima", "thirteenth"}
                    or node.capability in {"device.op", "deploy"}
                    or node.capability == "accept" and node.kind != "verify"):
                add("blocking", "node.dispatch", "node has no executable host binding", node.node_id)
            try:
                self._assert_write_roles([node])
            except HostBridgeError as exc:
                add("blocking", "node.write_scope", str(exc), node.node_id)
            if not node.acceptance:
                add("blocking", "node.acceptance", "node has no acceptance criteria", node.node_id)
            inline_targets = set(node.verifiers) & CHECK_TARGETS.keys()
            allowed = {"scope_guard", "loop1"}
            if graph.adaptive_verification and node.kind == "task":
                allowed.update(CHECK_TARGETS)
                for target in sorted(inline_targets):
                    gate_nodes.setdefault(target, []).append(node)
                    if graph.intent and CHECK_TARGETS[target][0] in graph.intent.forbidden_capabilities:
                        add("blocking", "intent.capability",
                            f"{target} requires a capability forbidden by the intent", node.node_id)
                    if not tools[target]["available"]:
                        add("warning", "check.unavailable",
                            f"{target} cannot run: {tools[target]['reason']}", node.node_id)
                    elif target == "test" and python_tests_missing:
                        add("warning", "check.tests_missing",
                            "Python test needs a discoverable suite when the task settles", node.node_id)
            if "scope_guard" not in node.verifiers or set(node.verifiers) - allowed:
                add("blocking", "node.scope_guard",
                    'use scope_guard and declare fixed checks on an eligible task or verify node',
                    node.node_id)
            if node.kind == "verify" and node.capability == "accept":
                dependencies = {other.node_id for other in graph.nodes.values()
                                if node.node_id != other.node_id
                                and node.node_id in affected_subgraph(graph, other.node_id)}
                if (node.check_target or node.write_scope or node.external_scope or node.requires
                        or not dependencies or any(
                            not any(done.id in graph.nodes[dep].satisfies for dep in dependencies)
                            for done in (graph.intent.done if graph.intent else ())
                            if done.id not in node.satisfies or done.evidence != "receipt")):
                    add("blocking", "accept.binding",
                        "acceptance verification needs read-only dependencies covering the acceptance criteria",
                        node.node_id)
                else:
                    gate_nodes.setdefault("accept", []).append(node)
            elif node.kind == "task" and node.capability == "diagnose" and node.check_target is not None:
                check = tools.get(node.check_target)
                if (node.check_target not in {"test", "sim"} or not check or not check["available"]
                        or node.write_scope or node.external_scope or node.requires):
                    add("blocking", "diagnosis.binding",
                        "diagnostic reproduction needs an available test or simulation and a read-only node",
                        node.node_id)
            elif node.kind == "verify" or node.check_target is not None:
                check = tools.get(node.check_target)
                if (node.kind != "verify" or check is None or node.write_scope or node.external_scope
                        or node.requires or (node.capability, node.role) != CHECK_TARGETS[node.check_target]):
                    add("blocking", "check.binding",
                        "verify node needs a fixed check target and its registered role, with no write scope or grants",
                        node.node_id)
                else:
                    if check["available"] or graph.adaptive_verification:
                        gate_nodes.setdefault(node.check_target, []).append(node)
                    severity = "warning" if graph.adaptive_verification else "blocking"
                    if not check["available"]:
                        add(severity, "check.unavailable",
                            f"{node.check_target} cannot run: {check['reason']}", node.node_id)
                    elif node.check_target == "test" and python_tests_missing:
                        producers = (other for other in graph.nodes.values()
                                     if node.node_id != other.node_id and
                                     node.node_id in affected_subgraph(graph, other.node_id))
                        if not any(other.capability == "test.write" and other.write_scope for other in producers):
                            add(severity, "check.tests_missing",
                                "Python test needs a tests/test*.py suite or a dependent test-writing step",
                                node.node_id)
            if node.kind == "review":
                if graph.planned_verification and (
                        node.capability not in {"review.l1", "review.l2"} or node.write_scope or node.external_scope):
                    add("blocking", "review.binding",
                        "review requires a registered L1/L2 reviewer and a read-only scope", node.node_id)
                gate_nodes.setdefault(node.capability, []).append(node)
            if node.external_scope and host == "opencode":
                paths = [Path(path) for path in self._external_paths(node)]
                if (len(paths) != 1 or any(
                        not path.parent.is_dir() or path.parent.resolve() != path.parent
                        or path.is_symlink() or
                        (path.exists() and (not path.is_file() or path.stat().st_nlink != 1))
                        for path in paths)):
                    add("blocking", "scope.external.unavailable",
                        "external write requires one regular file with an existing canonical parent",
                        node.node_id)
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
            covered: dict[str, list[PlanNode]] = {}
            for node in graph.nodes.values():
                for done_id in node.satisfies:
                    covered.setdefault(done_id, []).append(node)
            for done in graph.intent.done:
                if not covered.get(done.id):
                    add("warning" if graph.adaptive_verification else "blocking", "intent.done.uncovered",
                        f"done criterion {done.id!r} has no satisfying node")
                elif graph.planned_verification and not any(
                    done.evidence == "receipt"
                    or done.evidence == "artifact" and (node.write_scope or node.external_scope)
                    or done.evidence == "test" and node in (*gate_nodes.get("test", ()), *gate_nodes.get("sim", ()))
                    or done.evidence == "review" and node.kind == "review"
                    for node in covered[done.id]
                ):
                    add("warning" if graph.adaptive_verification else "blocking",
                        "intent.evidence", f"done criterion {done.id!r} needs an achievable "
                        f"{done.evidence} receipt", covered[done.id][0].node_id)
            forbidden_capabilities = set(graph.intent.forbidden_capabilities)
            for node in graph.nodes.values():
                if node.capability in forbidden_capabilities:
                    add("blocking", "intent.capability",
                        f"capability {node.capability!r} is forbidden by the intent",
                        node.node_id)
                for scope in (*node.write_scope, *node.external_scope):
                    if any(scope == pattern or fnmatchcase(scope, pattern)
                           or scopes_overlap((scope,), (pattern,))
                           for pattern in graph.intent.forbidden_paths):
                        add("blocking", "intent.path",
                            f"scope {scope!r} is forbidden by the intent", node.node_id)
                        break
        if graph.access_mode == "danger-full-access":
            add("warning", "access.danger",
                "danger-full-access requires explicit human authorization of the outer paths")
        if graph.planned_verification:
            for gate in graph.gates:
                base = "review.l2" if gate in {"review.l2.light", "review.l2.full"} else gate
                if base not in gate_nodes:
                    add("warning" if graph.adaptive_verification else "blocking",
                        "gate.unbound", f"required verification {gate!r} has no usable covering node")
            tests = [*gate_nodes.get("test", ()), *gate_nodes.get("sim", ())]
            if not graph.adaptive_verification and tests and not any(all(verifier.node_id in affected_subgraph(graph, test.node_id)
                                     for test in tests)
                                 for verifier in gate_nodes.get("accept", ())):
                add("blocking", "accept.unbound",
                    'A final verify node with role "megatronus" and capability "accept" must depend '
                    "on the test/simulation checks and the remaining acceptance evidence")
        return {"approved": not blocking, "blocking": blocking, "findings": findings}

    def _adaptive_gates(self, risk: Risk) -> set[str]:
        """Select native software checks from the detected profile and actual diff."""
        if risk == Risk.DOCUMENT:
            return set()
        try:
            gates = set(PROFILE_TOOLS[detect_profile(self.project)])
        except CheckRejected:
            gates = {"test"}
        if (self.project / "sim.resc").is_file() and (self.project / "sim.expect").is_file():
            if risk >= Risk.FIRMWARE:
                gates.add("sim")
        if risk >= Risk.INTERFACE:
            gates.update({"review.l2.full", "accept"})
        return gates

    def review_plan(self, run_id: str, *, reviewer: str = "prima") -> dict:
        """Record prima's review of the current plan revision before dispatch."""
        graph = self._graph(run_id)
        review = self._plan_review(graph, host=self._host(run_id))
        plan_path = self._dir(run_id) / "plan.json"
        digest = _hash(plan_path.read_bytes())
        self._append(run_id, "plan.reviewed", reviewer=reviewer,
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
        invalidated = {}
        for index, event in enumerate(events):
            node_id = event.get("node_id")
            if event["type"] == "plan.revised":
                for affected in event["invalidated_nodes"]:
                    invalidated[affected] = index
                    if affected in status:
                        status[affected] = "pending"
            elif event["type"] == "dispatch.started" and node_id in status:
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
        current_events = [event for index, event in enumerate(events)
                          if index > invalidated.get(event.get("node_id"), -1)]
        settled = graph.adaptive_verification and any(event["type"] == "run.completed" for event in events)
        required_gates = set(graph.gates)
        inline_targets: dict[str, set[str]] = {}
        if graph.planned_verification:
            required_gates.add("scope_guard")
            required_gates.update(node.check_target or node.capability for node in graph.nodes.values()
                                  if node.kind in {"verify", "review"})
        else:
            for event in events:
                if event["type"] == "gate.required":
                    required_gates.update(event["gates"])
        if graph.adaptive_verification:
            for node in graph.nodes.values():
                if node.kind == "task" and status[node.node_id] == "completed":
                    inline_targets[node.node_id] = set(node.verifiers) & CHECK_TARGETS.keys()
            for event in events:
                node_id = event.get("node_id")
                if event["type"] != "gate.required":
                    continue
                gates = set(event["gates"])
                required_gates.update(gates)
                if node_id not in inline_targets:
                    continue
                independent = {graph.nodes[dep].check_target
                               for dep in affected_subgraph(graph, node_id)
                               if graph.nodes[dep].kind == "verify"}
                inline_targets[node_id].update((gates & CHECK_TARGETS.keys()) - independent)
            for targets in inline_targets.values():
                required_gates.update(targets)
        passed_gates = set()
        passed_gate_nodes: dict[str, set[str]] = {}
        if "completed" in status.values():
            passed_gates.add("scope_guard")
        current_digest = self._workspace_digest() if any(
            event["type"] == "gate.check" and "inputs_sha256" not in event
            for event in events) else None
        input_digests: dict[str, str] = {}
        checks = {(event.get("node_id"), event["gate"]): event for event in current_events
                  if event["type"] == "gate.check"}
        pending_checks = []
        for node_id, targets in inline_targets.items():
            for target in sorted(targets):
                if graph.intent and CHECK_TARGETS[target][0] in graph.intent.forbidden_capabilities:
                    pending_checks.append({"node_id": node_id, "target": target, "status": "blocked",
                                           "diagnostic": "The intent forbids this check capability.",
                                           "can_retry": False})
                    continue
                if target == "test":
                    test_authors = [dependent for dependent in affected_subgraph(graph, node_id)
                                    if dependent != node_id and status[dependent] != "completed"
                                    and graph.nodes[dependent].kind == "task"
                                    and graph.nodes[dependent].capability == "test.write"
                                    and graph.nodes[dependent].write_scope]
                    if test_authors:
                        pending_checks.append({"node_id": node_id, "target": target,
                                               "status": "waiting_for_tests",
                                               "test_authors": test_authors, "can_retry": False})
                        continue
                latest = checks.get((node_id, target))
                if latest is None or not latest.get("inline"):
                    pending_checks.append({"node_id": node_id, "target": target,
                                           "status": "pending", "can_retry": False})
                    continue
                if not settled and target not in input_digests:
                    input_digests[target] = self._check_inputs_digest(target)
                digest = input_digests.get(target, latest["inputs_sha256"])
                if latest["inputs_sha256"] != digest:
                    pending_checks.append({"node_id": node_id, "target": target,
                                           "status": "pending", "can_retry": False})
                elif latest["status"] != "pass":
                    attempts = sum(event["type"] == "gate.check" and event.get("inline")
                                   and event.get("node_id") == node_id and event["gate"] == target
                                   and event["inputs_sha256"] == digest for event in current_events)
                    pending_checks.append({"node_id": node_id, "target": target,
                                           "status": latest["status"], "diagnostic": latest["diagnostic"],
                                           "can_retry": attempts < graph.nodes[node_id].budget["max_attempts"]})
        for (node_id, gate), event in checks.items():
            if event["status"] != "pass":
                continue
            if graph.planned_verification:
                if event.get("inline"):
                    if gate not in inline_targets.get(node_id, ()):
                        continue
                elif node_id not in graph.nodes or graph.nodes[node_id].check_target != gate:
                    continue
            if "inputs_sha256" in event:
                target = event.get("input_target")
                if target not in {"lint", "build", "test", "sim"}:
                    continue
                if not settled and target not in input_digests:
                    input_digests[target] = self._check_inputs_digest(target)
                valid = settled or event["inputs_sha256"] == input_digests[target]
            else:
                valid = event.get("workspace_sha256") == current_digest
            if valid:
                passed_gates.add(event["gate"])
                if isinstance(node_id, str) and node_id:
                    passed_gate_nodes.setdefault(event["gate"], set()).add(node_id)
        if graph.planned_verification:
            completed_events = {event["node_id"]: event for event in current_events
                                if event["type"] == "node.completed"}
            for node in graph.nodes.values():
                if status[node.node_id] != "completed":
                    continue
                stale = (node.kind == "verify" and node.check_target
                         and node.node_id not in passed_gate_nodes.get(node.check_target, ()))
                if graph.adaptive_verification and not settled and (
                        node.capability == "accept" or node.kind == "review"):
                    if "test" not in input_digests:
                        input_digests["test"] = self._check_inputs_digest("test")
                    evidence = completed_events.get(node.node_id, {})
                    stale = evidence.get("review_inputs_sha256") != input_digests["test"]
                if stale:
                    for dependent in affected_subgraph(graph, node.node_id):
                        if status[dependent] == "completed":
                            status[dependent] = "stale"
            for node in graph.nodes.values():
                if status[node.node_id] != "completed":
                    continue
                if node.capability == "accept":
                    passed_gates.add("accept")
                elif node.kind == "review":
                    passed_gates.add(node.capability)
                    if node.capability == "review.l2":
                        passed_gates.update(required_gates & {"review.l2.light", "review.l2.full"})
        for node_id, value in status.items():
            graph.nodes[node_id].status = value
        passed_gates.difference_update(item["target"] for item in pending_checks)
        pending_gates = sorted(required_gates - passed_gates)
        intent_coverage = coverage(graph.intent, graph.nodes, status, current_events, passed_gates,
                                   passed_gate_nodes)
        intent_blockers = [f"{item['id']}: {item['reason']}" for item in intent_coverage
                           if not item["satisfied"]]
        intent_ok = not intent_blockers
        ready = [node.node_id for node in dispatchable(graph,
                 tuple(entry["node_id"] for entry in active_calls.values()), max_writers=2)
                 if (node.kind != "verify" or not active_calls)
                 and sum(event["type"] == "dispatch.started" and event.get("node_id") == node.node_id
                         for event in current_events) < node.budget["max_attempts"]]
        if pending_checks:
            waiting = set()
            for item in pending_checks:
                node_id = item["node_id"]
                authors = item.get("test_authors", ())
                waiting.update(dependent for dependent in affected_subgraph(graph, node_id)
                               if dependent != node_id and not any(
                                   author in affected_subgraph(graph, dependent) for author in authors))
            ready = [node_id for node_id in ready if node_id not in waiting]
        if graph.adaptive_verification and set(pending_gates) - {"accept"}:
            ready = [node_id for node_id in ready if graph.nodes[node_id].capability != "accept"]
        repair_feedback = {}
        rejected_calls = {event.get("call_id") for event in events
                          if event["type"] == "review.rejected"}
        for event in current_events:
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
        external_stops = {event["node_id"]: {
            "target": event["target"], "outcome": event["type"].removeprefix("external.write."),
            "detail": event.get("detail"),
        } for event in events if event["type"] in {
            "external.write.denied", "external.write.blocked_by_host", "external.write.unverified"
        }}
        ready = [node_id for node_id in ready if node_id not in external_stops]
        completions = {event["node_id"]: event for event in current_events
                       if event["type"] == "node.completed"}
        last_revision = max((index for index, event in enumerate(events)
                             if event["type"] == "plan.revised"), default=-1)
        feedback = [event for event in events[last_revision + 1:]
                    if event["type"] in {"review.rejected", "loop2.escalated"}
                    or (event["type"] == "acceptance.checked" and not event["passed"])
                    or (event["type"] == "gate.check" and event["status"] in {"fail", "unavailable", "stale"})]
        if graph.planned_verification and not graph.adaptive_verification and feedback:
            ready = []
        nodes = [{"node_id": node.node_id, "status": status[node.node_id],
                  "card": self._card(node), "role": node.role, "kind": node.kind,
                  "objective": node.objective, "capability": node.capability,
                  "acceptance": list(node.acceptance), "depends_on": list(node.depends_on),
                  **({"check_target": node.check_target} if node.check_target else {}),
                  "write_scope": list(node.write_scope),
                  "external_scope": self._external_paths(node),
                  **({"artifacts": {str(self.project / path): sha for path, sha in
                                    completions[node.node_id].get("artifacts", {}).items()},
                      "outcome": completions[node.node_id].get("outcome", "completed")}
                     if status[node.node_id] == "completed" and node.node_id in completions else {})}
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
                  "repair_feedback": repair_feedback, "replan_feedback": feedback,
                  "planned_verification": graph.planned_verification,
                  "external_stops": external_stops,
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
        if graph.adaptive_verification:
            result.update({"adaptive_verification": True, "pending_checks": pending_checks,
                           "plan_path": str(run_dir / "plan.md")})
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
        if graph.planned_verification and not review_current:
            ready.clear()
            if result["status"] != "running":
                result["status"] = "blocked"
        if graph.planned_verification:
            result["planning_context"] = {
                "goal": graph.intent.goal if graph.intent else created.get("request"),
                "tools": self.planning_tools(),
                "diffs": [{key: event[key] for key in (
                    "node_id", "risk", "changed_paths", "changed_lines", "diff", "gates")
                    if key in event} for event in current_events if event["type"] == "gate.required"][-8:],
                "receipts": [event for event in completions.values()
                             if status.get(event["node_id"]) == "completed"],
                "checks": [*checks.values(), *[event for event in current_events
                                               if event["type"] == "diagnostic.check"]][-12:],
            }
        result.update({
            "review_required": False,
            "review": review,
            "review_current": review_current,
            "plan_sha256": plan_sha,
            "handoff": {
                "run_id": run_id,
                "plan_revision": graph.revision,
                "next_agent": "prima",
                "ready_nodes": ready,
                "ready_cards": [self._card(graph.nodes[node_id]) for node_id in ready],
                "access_mode": graph.access_mode,
                "required_gates": sorted(required_gates),
                "review_required": False,
                "review_current": review_current,
            },
        })
        if len(nodes) == 1 and (review_current or not graph.planned_verification):
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
        if result["status"] in {"completed", "superseded"}:
            next_actions = []
        elif active_calls:
            next_actions = [{"tool": "cy_state", "reason": "wait for active dispatch",
                             "arguments": {"wait": True}}]
        elif external_stops and not ready:
            next_actions = [{"reason": "report the external write outcome without retrying",
                             "external_stops": external_stops}]
        elif feedback and (not ready or graph.planned_verification and not graph.adaptive_verification) and not any(
                item["status"] == "pending" for item in pending_checks):
            next_actions = [{"tool": "subagent", "agent": "thirteenth", "reason": "replan the same run",
                             "run_id": run_id, "plan_revision": graph.revision}]
        elif not review_current and graph.planned_verification:
            next_actions = [{"tool": "subagent", "agent": "thirteenth",
                             "reason": "plan validation is missing for this revision"}]
        elif ready:
            next_actions = [{"tool": "subagent", "reason": "dispatch ready native nodes",
                             "node_ids": ready}]
        else:
            next_actions = []
            if any(item["status"] == "pending" for item in pending_checks):
                next_actions.append({"tool": "cy_state", "reason": "run pending fixed checks",
                                     "arguments": {"wait": True}})
            if pending_gates and not graph.planned_verification:
                next_actions.append({"tool": "cy_check", "reason": "verify pending gates",
                                     "gates": [gate for gate in pending_gates if gate in CHECK_TARGETS]})
            if (intent_blockers or pending_gates) and not next_actions:
                next_actions.append({"tool": "subagent", "agent": "thirteenth",
                                     "reason": "repair unmet evidence in the same run",
                                     "run_id": run_id, "plan_revision": graph.revision})
            if not next_actions:
                next_actions.append({"tool": "subagent", "agent": "thirteenth",
                                     "reason": "run has no dispatchable nodes"})
        if graph.adaptive_verification and result["status"] not in {"completed", "superseded", "running"}:
            if any(item["can_retry"] for item in pending_checks):
                next_actions.append({"tool": "cy_state", "reason": "retry a failed fixed check after resolving its cause",
                                     "arguments": {"wait": True, "retry_checks": True}})
        result["next_actions"] = next_actions
        return result

    @staticmethod
    def _publish_plan(state: dict) -> dict:
        """Refresh the human-readable projection at each settlement or revision."""
        if not state.get("adaptive_verification"):
            return state

        def plain(text: object) -> str:
            value = " ".join(str(text).split())
            return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        title = state.get("title") or state["run_id"]
        goal = (state.get("intent") or {}).get("goal")
        lines = [f"# {plain(title)}", "", f"Run `{state['run_id']}` · revision {state['plan_revision']} · {state['status']}"]
        if goal:
            lines += ["", plain(goal)]
        lines += ["", "## Tasks", ""]
        for node in state["nodes"]:
            dependencies = ", ".join(node["depends_on"])
            line = f"- **{plain(node['node_id'])}** · {node['role']} · {node['status']} · {plain(node['objective'])}"
            lines.append(line + (f" · depends on {plain(dependencies)}" if dependencies else ""))
        lines += ["", "## Verification", "",
                  "- Passed · " + (", ".join(map(plain, state["passed_gates"])) or "none"),
                  "- Outstanding · " + (", ".join(map(plain, state["pending_gates"])) or "none")]
        for check in state["pending_checks"]:
            detail = plain(check.get("diagnostic") or "")
            lines.append(f"- {plain(check['node_id'])} · {check['target']} · {check['status']}"
                         + (f" · {detail[:500]}" if detail else ""))
        for check in state["planning_context"]["checks"]:
            receipt = check.get("receipt")
            if receipt:
                lines.append(f"- {plain(check['node_id'])} · {check['gate']} · {check['status']}"
                             f" · exit {receipt['exit']} · SHA-256 {receipt['sha256']}")
        for finding in (state.get("review") or {}).get("findings", []):
            lines.append(f"- {finding['severity']} · {plain(finding['message'])}")
        if state["next_actions"]:
            lines += ["", "## Next actions", ""]
            lines.extend(f"- {plain(action['reason'])}" for action in state["next_actions"])
        target = Path(state["plan_path"])
        draft = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                             prefix=".plan-", delete=False) as handle:
                draft = Path(handle.name)
                handle.write("\n".join(lines) + "\n")
            draft.replace(target)
        except OSError as exc:
            state["plan_projection_error"] = str(exc)
        finally:
            if draft is not None:
                draft.unlink(missing_ok=True)
        return state

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

    def list_runs(self) -> dict:
        """Discover persisted runs without relying on an OpenCode session key."""
        items = []
        if not self.runs.is_dir() or self.runs.is_symlink():
            return {"runs": items}
        for directory in self.runs.iterdir():
            metadata = directory / "run.json"
            if directory.is_symlink() or not directory.is_dir() or \
                    metadata.is_symlink() or not metadata.is_file():
                continue
            try:
                record = json.loads(metadata.read_text())
                run_id = record["run_id"]
                state = self.state(run_id)
                events = self.events(run_id)
            except (OSError, ValueError, KeyError, TypeError, HostBridgeError):
                continue
            items.append({
                "run_id": run_id,
                "slug": record.get("slug"),
                "title": state.get("title"),
                "status": state["status"],
                "updated_utc": events[-1].get("utc") if events else record.get("created_utc"),
                "ready_nodes": state["ready_nodes"],
                "next_actions": state.get("next_actions", []),
                "superseded_by": state.get("superseded_by"),
            })
        items.sort(key=lambda item: (item["updated_utc"] or "", item["run_id"]), reverse=True)
        return {"runs": items}

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
                     human_interventions=sum(event["type"] in {"human.requested", "approval.granted", "external.write.requested"}
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

    @_serialized
    def plan_op(self, run_id: str, operation: dict, *, planner_session_id: str | None = None) -> dict:
        graph = self._graph(run_id)
        state = self.state(run_id)
        if state["active_dispatches"]:
            raise HostBridgeError("cannot replan during active dispatch")
        if state["status"] in {"completed", "superseded"}:
            raise HostBridgeError("terminal run cannot be replanned")
        old_graph = PlanGraph.from_dict(graph.to_dict())
        for item in state["nodes"]:
            graph.nodes[item["node_id"]].status = item["status"]
        prior = len(graph.events)
        try:
            graph.apply_op(operation)
            if graph.revision == old_graph.revision:
                return state
            if graph.planned_verification:
                self._validate_revision_scope(old_graph, graph)
            review = self._plan_review(graph, host=self._host(run_id))
            if not review["approved"]:
                raise PlanValidationError(review["blocking"])
        except (GraphRejected, HostBridgeError) as exc:
            self._append(run_id, "plan.op.rejected", op_id=operation.get("op_id"), reason=str(exc))
            if isinstance(exc, HostBridgeError):
                raise
            raise HostBridgeError(str(exc)) from exc
        for node in graph.nodes.values():
            node.status = "pending"
        affected = self._revision_invalidations(old_graph, graph, operation, state)
        if operation["op"] == "revise" and not graph.adaptive_verification:
            failed_checks = {event["node_id"] for event in state["replan_feedback"]
                             if event["type"] == "gate.check" and event.get("node_id")}
            if failed_checks - set(affected):
                raise HostBridgeError("revision needs to invalidate failed checks: "
                                      + ", ".join(sorted(failed_checks - set(affected))))
        if set(affected) & state["external_stops"].keys():
            raise HostBridgeError("revision cannot retry or replace a denied external write")
        if operation["op"] == "revise" and not affected and graph.gates == old_graph.gates:
            raise HostBridgeError("revision has no changes or invalidated nodes")
        plan_path = self._dir(run_id) / "plan.json"
        plan_data = json.dumps(graph.to_dict(), ensure_ascii=False).encode()
        temporary = plan_path.with_suffix(".tmp")
        temporary.write_bytes(plan_data)
        temporary.replace(plan_path)
        for event in graph.events[prior:]:
            self._append(run_id, event["type"], **{k: v for k, v in event.items() if k != "type"})
        if operation.get("op") == "retry_node":
            self._append(run_id, "node.retry", node_id=operation["node_id"])
        if graph.planned_verification:
            self._append(run_id, "plan.revised", plan_revision=graph.revision,
                         previous_revision=old_graph.revision, plan_sha256=_hash(plan_data),
                         reason=operation.get("reason") or operation["op"],
                         planner_session_id=planner_session_id, invalidated_nodes=affected,
                         reused_nodes=[item["node_id"] for item in state["nodes"]
                                       if item["status"] == "completed" and item["node_id"] not in affected],
                         feedback=state["replan_feedback"])
        self._append(run_id, "plan.reviewed", reviewer="kernel", plan_revision=graph.revision,
                     plan_sha256=_hash(plan_data), approved=True, findings=review["findings"])
        self._maybe_complete(run_id)
        return self._publish_plan(self.state(run_id))

    @staticmethod
    def _validate_revision_scope(old: PlanGraph, new: PlanGraph) -> None:
        """Stay inside the run's authorized paths and keep external writes on their original node."""
        scopes = tuple(scope for node in old.nodes.values() for scope in node.write_scope)
        for node in new.nodes.values():
            previous = old.nodes.get(node.node_id)
            if any(scope not in scopes and not _scope_allowed(scope, scopes) for scope in node.write_scope):
                raise HostBridgeError(f"{node.node_id}: revision exceeds the run's write scope")
            if node.external_scope and (previous is None or node.external_scope != previous.external_scope):
                raise HostBridgeError(f"{node.node_id}: revision cannot expand or move external scope")
        if not set(old.gates) <= set(new.gates):
            raise HostBridgeError("revision cannot remove a required gate")

    @staticmethod
    def _revision_invalidations(old: PlanGraph, new: PlanGraph, operation: dict, state: dict) -> list[str]:
        changed = {node_id for node_id in old.nodes.keys() | new.nodes.keys()
                   if old.nodes.get(node_id) != new.nodes.get(node_id)}
        changed.update(item["node_id"] for item in state["nodes"] if item["status"] == "stale")
        for item in state["nodes"]:
            for target, sha in item.get("artifacts", {}).items():
                path = Path(target)
                if not path.is_file() or path.is_symlink() or _hash(path.read_bytes()) != sha:
                    changed.add(item["node_id"])
        for graph in (old, new):
            for node_id in tuple(changed & graph.nodes.keys()):
                changed.update(affected_subgraph(graph, node_id))
        retries = set(operation.get("retry_nodes", ()))
        if any(item["node_id"] in retries - changed and item["status"] == "completed"
               for item in state["nodes"]):
            raise HostBridgeError("revision cannot retry an unaffected completed node")
        for node_id in retries:
            changed.update(affected_subgraph(new, node_id))
        return sorted(changed)

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

    @_serialized
    def before(self, run_id: str, node_id: str, role: str, card: str, call_id: str,
               active_token: str | None = None) -> dict:
        graph = self._graph(run_id)
        require_isolated_workspace(self.project, graph.access_mode)
        node = graph.nodes.get(node_id)
        reason = None
        state = self.state(run_id)
        if node is None or node_id not in state["ready_nodes"]:
            reason = "node is not ready"
        elif node_id in state["external_stops"]:
            reason = "the external write is blocked by a recorded host decision"
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
            if (kind == "external.write" and node.external_scope
                    and self._host(run_id) == "opencode"):
                # A scoped native write obtains its own exact-file host decision.
                continue
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
        guard = ScopeGuard(self.project, node.write_scope, access_mode=graph.access_mode,
                           host_manages_state=True)
        baseline = guard.snapshot()
        guard.assert_safe_before_dispatch(baseline)
        directory = self._dir(run_id)
        self._snapshot_path(run_id, call_id).write_bytes(_encode(baseline))
        self._append(run_id, "dispatch.started", node_id=node_id, role=role,
                     capability=node.capability, write_scope=list(node.write_scope),
                     external_scope=self._external_paths(node),
                     access_mode=graph.access_mode, call_id=call_id, plan_revision=graph.revision)
        return {"status": "running", "token": self._token(run_id, call_id),
                "node_id": node_id, "write_scope": list(node.write_scope),
                "kind": node.kind, "check_target": node.check_target,
                "planned_verification": graph.planned_verification,
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

    def external_write(self, run_id: str, call_id: str, tool_call_id: str, target: str,
                       content_sha256: str, outcome: str, detail: str | None = None,
                       changed_lines: int | None = None) -> dict:
        """Record the exact-file approval and the native write it authorizes."""
        if outcome not in {"inspect", "requested", "approved", "denied",
                           "blocked_by_host", "applied", "unverified"}:
            raise HostBridgeError("invalid external write outcome")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise HostBridgeError("native write tool call ID is required")
        if not isinstance(content_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", content_sha256):
            raise HostBridgeError("invalid external write content hash")
        if changed_lines is not None and (type(changed_lines) is not int or changed_lines < 0):
            raise HostBridgeError("invalid external write diff count")
        events = self.events(run_id)
        bound = next((event for event in events if event["type"] == "dispatch.bound"
                      and event["call_id"] == call_id), None)
        if (self._host(run_id) != "opencode" or not bound
                or bound.get("external_scope") != [target]):
            raise HostBridgeError("native write does not match the bound external file")
        node = self._graph(run_id).nodes[bound["node_id"]]
        if node.expected_content_sha256 and content_sha256 != node.expected_content_sha256:
            raise HostBridgeError("native write content differs from the planned file contents")
        previous = [(event["type"].removeprefix("external.write."), event)
                    for event in events if event["type"].startswith("external.write.")
                    and event.get("target") == target]
        own = [decision for decision, event in previous
               if event["call_id"] == call_id and event["tool_call_id"] == tool_call_id
               and event["content_sha256"] == content_sha256]
        if outcome in {"inspect", "requested"}:
            has_current_receipt = bool(previous)
            ancestor = run_id
            seen = {run_id}
            while not previous:
                metadata = json.loads((self._dir(ancestor) / "run.json").read_text())
                ancestor = metadata.get("supersedes_run_id")
                if not ancestor or ancestor in seen:
                    break
                seen.add(ancestor)
                previous.extend((event["type"].removeprefix("external.write."), event)
                                for event in self.events(ancestor)
                                if event["type"].startswith("external.write.")
                                and event.get("target") == target
                                and event.get("content_sha256") == content_sha256)
            if previous:
                decision, source = previous[-1]
                if not has_current_receipt and decision in {"denied", "blocked_by_host", "unverified"}:
                    self._append(run_id, "external.write." + decision, node_id=bound["node_id"],
                                 call_id=call_id, tool_call_id=tool_call_id, target=target,
                                 content_sha256=content_sha256,
                                 detail=source.get("detail") or "decision from a prior run",
                                 source="opencode")
                return {"outcome": {"requested": "approval_pending",
                                    "approved": "operation_outcome_unknown"}.get(decision, decision)}
            if outcome == "inspect":
                return {"outcome": "available"}
        elif outcome in own:
            return {"outcome": outcome}
        elif (outcome in {"approved", "denied"} and own != ["requested"]
              or outcome in {"applied", "unverified"} and own != ["requested", "approved"]
              or outcome == "blocked_by_host" and own not in ([], ["requested"])):
            raise HostBridgeError("external write receipt is out of order")
        self._append(run_id, "external.write." + outcome, node_id=bound["node_id"],
                     call_id=call_id, tool_call_id=tool_call_id, target=target,
                     content_sha256=content_sha256, detail=detail, source="opencode",
                     changed_lines=changed_lines)
        return {"outcome": outcome}

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

    @_serialized
    def finish(self, run_id: str, token: str, child_session_id: str | None,
               *, call_id: str | None = None, child_error: bool = False) -> dict:
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
        # The host owns all run ledgers and learned templates in the project.
        # Other sessions may create them while this dispatch is active.
        guard = ScopeGuard(self.project, node.write_scope, access_mode=graph.access_mode,
                           host_manages_state=True)
        baseline = guard.project_snapshot(_decode(self._snapshot_path(run_id, call_id).read_bytes()))
        current = guard.snapshot()
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
        external_failure = None
        external_write = None
        host = self._host(run_id)
        if node.external_scope:
            # Outside the project there is no baseline to diff or roll back.
            # Evidence is the artifact hash plus proof that the host gate ran.
            approved = {resource for event in all_events
                        if (event["type"] == "permission.granted" or
                            (event["type"] == "permission.resolved" and
                             event.get("reply") in {"once", "always"}))
                        and event.get("call_id") == call_id
                        for resource in (event.get("resources") or ())}
            scoped_writes = [event for event in all_events
                             if event["type"].startswith("external.write.")
                             and event.get("call_id") == call_id]
            if scoped_writes:
                latest = scoped_writes[-1]
                if latest["type"] == "external.write.applied":
                    external_write = latest
                    external_artifacts = self._collect_scope_artifacts([latest["target"]])
                if (latest["type"] != "external.write.applied"
                        or external_artifacts.get(latest["target"]) != latest["content_sha256"]):
                    external_failure = latest["type"].removeprefix("external.write.")
                    if external_failure == "applied":
                        external_failure = "content_mismatch"
                    if latest["detail"]:
                        external_failure += ": " + latest["detail"]
                    external_artifacts = {}
            else:
                external_artifacts = self._collect_scope_artifacts(self._external_paths(node))
            if not scoped_writes and host == "opencode":
                # OpenCode gates each external write through its own
                # ask/always/reject rules; the kernel verifies that the gate
                # ran. DSH approves through its sandbox mode and one-shot
                # escalation, which the kernel cannot observe, so it records
                # the artifact hash without demanding a kernel-side receipt.
                unapproved_external = sorted(path for path in external_artifacts
                                             if path not in approved)
            artifacts.update(external_artifacts)
        no_change = False
        wrong_content = False
        if node.expected_content_sha256 and not external_failure:
            expected_path = (self._external_paths(node) or list(node.write_scope))[0]
            if (not node.external_scope and graph.access_mode == "workspace-write"
                    and not report.changed_paths):
                existing = current_after.entries.get(expected_path)
                if (existing and existing.kind == "file"
                        and existing.sha256 == node.expected_content_sha256):
                    artifacts[expected_path] = existing.sha256
                    no_change = True
            wrong_content = artifacts.get(expected_path) != node.expected_content_sha256
        rejection = next((event for event in reversed(all_events)
                          if event["type"] == "review.rejected" and event.get("call_id") == call_id), None)
        bound_check = next((event for event in reversed(all_events)
                            if event["type"] == "gate.check"
                            and event.get("call_id") == call_id and event["gate"] == node.check_target), None)
        acceptance = next((event for event in reversed(all_events)
                           if event["type"] == "acceptance.checked" and event["call_id"] == call_id), None)
        diagnostic_check = next((event for event in reversed(all_events)
                                 if event["type"] == "diagnostic.check" and event["call_id"] == call_id), None)
        review_reads = []
        for event in all_events:
            if event["type"] != "review.read" or event["call_id"] != call_id:
                continue
            path = self.project / event["path"]
            if path.is_file() and path.resolve() == path and _hash(path.read_bytes()) == event["file_sha256"]:
                review_reads.append(event)
        evidence_failure = None
        if graph.planned_verification and node.kind == "verify":
            if node.check_target:
                if bound_check is None:
                    evidence_failure = f"{node.check_target} tool receipt is missing"
                elif bound_check["status"] != "pass":
                    evidence_failure = bound_check["diagnostic"] or bound_check["status"]
            elif not (acceptance and acceptance["passed"]):
                evidence_failure = acceptance["findings"] if acceptance else "acceptance verdict is missing"
        elif graph.planned_verification and node.kind == "review" and not review_reads:
            evidence_failure = "review needs an observed read of a current project file"
        elif node.capability == "diagnose" and node.check_target and not (
                diagnostic_check and diagnostic_check["receipts"]
                and diagnostic_check["status"] in {"pass", "fail"}):
            evidence_failure = "diagnostic reproduction receipt is missing or stale"
        dangerous_used = any(
            event["type"] == "grant.used" and event.get("node_id") == node.node_id
            and event.get("grant_kind") == "dangerous.confirm"
            for event in all_events)
        declared = [resolve_scope(scope, self.project) for scope in node.write_scope]
        destructive = "dangerous.confirm" in node.requires
        destructive_exists = destructive and any(path.exists() for path in declared)
        removed_paths: list[str] = []
        if (not artifacts and node.write_scope and dangerous_used):
            if declared and all(not path.exists() for path in declared):
                removed_paths = [str(path) for path in declared]
        if returned["tool_status"] == "cancelled":
            status = "cancelled"
        elif external_failure:
            status = "blocked"
        elif child_error:
            status = "failed"
        elif (unapproved_external or rejection or evidence_failure or report.rejected_paths
              or returned["tool_status"] == "error"):
            status = "failed"
        elif destructive_exists:
            status = "blocked"
        elif wrong_content:
            status = "blocked"
        elif not artifacts and (node.write_scope or node.external_scope) and not removed_paths:
            status = "blocked"
        elif not node.write_scope and report.changed_paths:
            status = "failed"
        else:
            status = "completed"
        diagnostic = (rejection["diagnostic"] if rejection else
                      "external write stopped: " + external_failure if external_failure else
                      evidence_failure if evidence_failure else
                      "child tool error" if child_error else
                      "external write without host approval: " + ", ".join(unapproved_external) if unapproved_external else
                      "write_scope violation: " + ", ".join(report.rejected_paths) if report.rejected_paths else
                      "native subagent error" if returned["tool_status"] == "error" else
                      "dangerous target still exists" if destructive_exists else
                      "file contents differ from the planned SHA-256" if wrong_content else
                      "no accepted artifact" if status == "blocked" else None)
        fingerprint = _hash(json.dumps({"status": status, "diagnostic": diagnostic,
                                        "paths": report.rejected_paths}, sort_keys=True).encode())
        if status == "completed" and artifacts and not no_change and graph.access_mode != "danger-full-access":
            facts = diff_facts(baseline, current_after)
            risk, floor = risk_floor(facts)
            changed_paths, changed_lines = list(facts.paths), facts.changed_lines
            if external_write is not None:
                changed_paths.append(external_write["target"])
                external_lines = external_write.get("changed_lines")
                if external_lines is not None:
                    changed_lines += external_lines
                if (not facts.paths and node.capability == "doc.write"
                        and Path(external_write["target"]).suffix in {".md", ".txt"}
                        and external_lines is not None and external_lines <= 200):
                    risk, floor = Risk.DOCUMENT, frozenset({"scope_guard"})
            if graph.adaptive_verification:
                if (node.capability == "doc.write" and facts.paths
                        and all(Path(path).suffix == ".md" for path in facts.paths)):
                    risk = Risk.DOCUMENT
                floor = {"scope_guard"} | self._adaptive_gates(risk)
            self._append(run_id, "gate.required", node_id=node.node_id,
                         risk=risk.name.lower(), gates=sorted(floor),
                         changed_paths=changed_paths, changed_lines=changed_lines,
                         diff=diff_preview(baseline, current_after, facts.paths)
                         if graph.planned_verification else "")
        self._append(run_id, "node." + status, node_id=node.node_id, call_id=call_id,
                     artifacts=artifacts, rejected_paths=list(report.rejected_paths),
                     removed_paths=removed_paths,
                     **({"outcome": "completed_without_change"} if status == "completed" and no_change else {}),
                     **({"review_reads": review_reads} if review_reads else {}),
                     **({"review_inputs_sha256": self._check_inputs_digest("test")}
                        if graph.adaptive_verification and status == "completed"
                        and (node.kind == "review" or node.capability == "accept") else {}),
                     diagnostic=diagnostic, failure_fingerprint=fingerprint if status in {"failed", "blocked"} else None,
                     evidence=bound_check["receipt"] if bound_check else
                     {"source": "kernel", "command": "check-file-content", "exit": 0,
                      "utc": _utc(), "sha256": node.expected_content_sha256}
                     if status == "completed" and node.expected_content_sha256 else
                     {"source": "host", "command": "native.subagent",
                               "exit": 0 if returned["tool_status"] == "completed" and not child_error else 1,
                               "utc": _utc(), "sha256": returned["output_sha256"],
                               "session_id": child_session_id})
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
        elif (status in {"failed", "blocked"} and not external_failure
              and not (bound_check and bound_check["status"] != "pass")
              and not (acceptance and not acceptance["passed"])):
            last_revision = max((index for index, event in enumerate(all_events)
                                 if event["type"] == "plan.revised" and
                                 node.node_id in event["invalidated_nodes"]), default=-1)
            failures = [event for event in self.events(run_id)[last_revision + 1:]
                        if event["type"] in {"node.failed", "node.blocked"}
                        and event.get("node_id") == node.node_id
                        and event.get("failure_fingerprint") == fingerprint]
            used = sum(event["type"] == "dispatch.started" and event.get("node_id") == node.node_id
                       for event in all_events[last_revision + 1:])
            if len(failures) >= 2 or used >= node.budget["max_attempts"]:
                self._append(run_id, "loop2.escalated", node_id=node.node_id,
                             reason="repeated failure fingerprint" if len(failures) >= 2 else "max_attempts exhausted",
                             failure_fingerprint=fingerprint)
            else:
                self._append(run_id, "node.retry", node_id=node.node_id,
                             diagnostic=diagnostic, failure_fingerprint=fingerprint,
                             attempt=used + 1)
        self._maybe_complete(run_id)
        return self._publish_plan(self.state(run_id))
