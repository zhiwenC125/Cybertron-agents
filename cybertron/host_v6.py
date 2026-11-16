"""M0c OpenCode host bridge for a single native subagent dispatch.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graph import GraphRejected, PlanGraph, PlanNode
from .scope_guard import FileState, ScopeGuard, Snapshot


class HostBridgeError(RuntimeError):
    pass


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
        directory = self.runs / run_id
        if directory.is_symlink() or not directory.is_dir():
            raise HostBridgeError("run does not exist or is unsafe")
        return directory

    @staticmethod
    def _card(node: PlanNode) -> str:
        return f"[{node.node_id}] {node.capability} | {', '.join(node.write_scope) or '(read only)'}"

    def _graph(self, run_id: str) -> PlanGraph:
        return PlanGraph.from_dict(json.loads((self._dir(run_id) / "plan.json").read_text()))

    def _append(self, run_id: str, kind: str, **fields: Any) -> None:
        path = self._dir(run_id) / "events.jsonl"
        event = {"type": kind, "utc": _utc(), **fields}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def events(self, run_id: str) -> list[dict]:
        path = self._dir(run_id) / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines() if line]

    def plan(self, node_data: dict, host_session_id: str) -> dict:
        try:
            node = PlanNode.from_dict(node_data)
            graph = PlanGraph([node])
        except (GraphRejected, TypeError) as exc:
            raise HostBridgeError(str(exc)) from exc
        if node.status != "pending" or node.kind != "task" or node.role == "prima":
            raise HostBridgeError("M0c requires one pending subagent task")
        if set(node.verifiers) != {"scope_guard"}:
            raise HostBridgeError("M0c only supports scope_guard")
        if not isinstance(host_session_id, str) or not host_session_id:
            raise HostBridgeError("host session ID is required")
        # A run ID is an identifier, not a secret. The macOS verification
        # sandbox denies /dev/urandom, so uuid4 would make tests fail there.
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                f"{self.project}:{time.time_ns()}:{os.getpid()}:{next(_run_counter)}"))
        directory = self.runs / run_id
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "plan.json").write_text(json.dumps(graph.to_dict(), ensure_ascii=False))
        (directory / "events.jsonl").touch()
        self._append(run_id, "plan.created", node_id=node.node_id,
                     host_session_id=host_session_id, plan_revision=graph.revision)
        return {"run_id": run_id, "node_id": node.node_id, "card": self._card(node),
                "status": "ready", "write_scope": list(node.write_scope)}

    def state(self, run_id: str) -> dict:
        graph = self._graph(run_id)
        node = next(iter(graph.nodes.values()))
        events = self.events(run_id)
        terminal = next((event for event in reversed(events)
                         if event["type"] in {"node.completed", "node.failed", "node.blocked", "node.cancelled"}), None)
        started = any(event["type"] == "dispatch.started" for event in events)
        returned = next((event for event in reversed(events) if event["type"] == "dispatch.returned"), None)
        return {"run_id": run_id, "node_id": node.node_id,
                "status": terminal["type"].split(".", 1)[1] if terminal else "running" if started else "ready",
                "card": self._card(node),
                "child_session_id": returned.get("child_session_id") if returned else None,
                "event_seq": len(events), "events_path": str(self._dir(run_id) / "events.jsonl")}

    def ask(self, run_id: str, question: str) -> dict:
        if not isinstance(question, str) or not question.strip():
            raise HostBridgeError("question is required")
        if self.state(run_id)["status"] == "running":
            raise HostBridgeError("cannot request human input during an active dispatch")
        self._append(run_id, "human.requested", question=question.strip())
        return self.state(run_id)

    def _token(self, run_id: str) -> str:
        directory = self._dir(run_id)
        return _hash((directory / "snapshot.json").read_bytes() + b"\0" +
                     (directory / "events.jsonl").read_bytes())

    def _verify_token(self, run_id: str, token: str) -> None:
        if not isinstance(token, str) or self._token(run_id) != token:
            raise HostBridgeError("dispatch snapshot or event log changed")

    def before(self, run_id: str, node_id: str, role: str, card: str, call_id: str,
               active_token: str | None = None) -> dict:
        graph = self._graph(run_id)
        if len(graph.nodes) != 1:
            raise HostBridgeError("M0c requires one node")
        node = next(iter(graph.nodes.values()))
        reason = None
        if self.state(run_id)["status"] != "ready":
            reason = "node is not ready"
        elif node_id != node.node_id or role != node.role or card != self._card(node):
            reason = "node, role, capability, or write_scope differs from plan"
        elif not isinstance(call_id, str) or not call_id:
            reason = "host tool call ID is required"
        if reason:
            if self.state(run_id)["status"] == "running":
                self._verify_token(run_id, active_token)
                self._append(run_id, "plan.op.rejected", node_id=node_id, reason=reason)
                return {"rejected": True, "reason": reason, "token": self._token(run_id)}
            self._append(run_id, "plan.op.rejected", node_id=node_id, reason=reason)
            raise HostBridgeError(reason)
        guard = ScopeGuard(self.project, node.write_scope)
        guard.assert_safe_before_dispatch(guard.snapshot())
        baseline = guard.snapshot()
        directory = self._dir(run_id)
        (directory / "snapshot.json").write_bytes(_encode(baseline))
        self._append(run_id, "dispatch.started", node_id=node_id, role=role,
                     capability=node.capability, write_scope=list(node.write_scope), call_id=call_id)
        return {"status": "running", "token": self._token(run_id), "node_id": node_id}

    def after(self, run_id: str, call_id: str, token: str, child_session_id: str | None,
              tool_status: str, duration_ms: int, output_sha256: str | None = None) -> dict:
        self._verify_token(run_id, token)
        started = next((event for event in reversed(self.events(run_id)) if event["type"] == "dispatch.started"), None)
        if not started or started["call_id"] != call_id or any(
                event["type"] == "dispatch.returned" for event in self.events(run_id)):
            raise HostBridgeError("no matching active dispatch")
        if tool_status not in {"completed", "error", "cancelled"} or type(duration_ms) is not int or duration_ms < 0:
            raise HostBridgeError("invalid host tool result")
        if tool_status == "completed" and (not isinstance(child_session_id, str) or not child_session_id):
            raise HostBridgeError("native subagent session ID is required")
        self._append(run_id, "dispatch.returned", call_id=call_id,
                     child_session_id=child_session_id, tool_status=tool_status,
                     duration_ms=duration_ms, output_sha256=output_sha256 or _hash(b""))
        if tool_status in {"error", "cancelled"}:
            return self.finish(run_id, self._token(run_id), child_session_id)
        return {"status": "running", "token": self._token(run_id),
                "child_session_id": child_session_id}

    def finish(self, run_id: str, token: str, child_session_id: str | None) -> dict:
        self._verify_token(run_id, token)
        state = self.state(run_id)
        if state["status"] != "running" or state["child_session_id"] != child_session_id:
            raise HostBridgeError("no matching returned subagent")
        returned = next(event for event in reversed(self.events(run_id)) if event["type"] == "dispatch.returned")
        node = next(iter(self._graph(run_id).nodes.values()))
        guard = ScopeGuard(self.project, node.write_scope)
        baseline = _decode((self._dir(run_id) / "snapshot.json").read_bytes())
        current = guard.snapshot()
        # These two files are written only by this bridge. Their bytes were
        # authenticated against the token held by the host plugin.
        for name in ("snapshot.json", "events.jsonl"):
            rel = f".cybertron/runs/{run_id}/{name}"
            baseline.entries[rel] = current.entries[rel]
        report = guard.verify_and_rollback(baseline)
        if report.rejected_paths:
            self._append(run_id, "plan.op.rejected", node_id=node.node_id,
                         reason="write_scope violation", paths=list(report.rejected_paths))
        artifacts = {path: value.sha256 for path, value in guard.snapshot().entries.items()
                     if path in report.changed_paths and path not in report.rejected_paths and value.kind == "file"}
        if returned["tool_status"] == "cancelled":
            status = "cancelled"
        elif report.rejected_paths or returned["tool_status"] == "error":
            status = "failed"
        elif not artifacts:
            status = "blocked"
        else:
            status = "completed"
        self._append(run_id, "node." + status, node_id=node.node_id,
                     artifacts=artifacts, rejected_paths=list(report.rejected_paths),
                     evidence={"source": "host", "command": "native.subagent",
                               "exit": 0 if returned["tool_status"] == "completed" else 1,
                               "utc": _utc(), "sha256": returned["output_sha256"],
                               "session_id": child_session_id})
        return self.state(run_id)
