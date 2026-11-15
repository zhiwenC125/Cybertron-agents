"""M0b single-node execution boundary; event log owns the outcome."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .graph import PlanGraph, PlanNode
from .scope_guard import ScopeGuard


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DispatchOutcome:
    """Tool or host adapter output; no model claims are accepted here."""

    command: str
    exit_code: int
    output: bytes
    source: str
    session_id: str | None = None


@dataclass(frozen=True)
class NodeRunResult:
    status: str
    node_id: str
    context_path: Path
    events_path: Path
    changed_paths: tuple[str, ...]
    rejected_paths: tuple[str, ...]


class SingleNodeKernel:
    def __init__(self, workspace: Path, plan_path: Path, run_id: str) -> None:
        self.workspace = Path(workspace).resolve()
        self.plan_path = Path(plan_path)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", run_id):
            raise ValueError("invalid run_id")
        self.run_dir = self.workspace / ".cybertron" / "runs" / run_id
        self.events_path = self.run_dir / "events.jsonl"

    def _event(self, kind: str, **payload: object) -> None:
        event = {"type": kind, "utc": _utc(), **payload}
        data = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(data + "\n")

    @staticmethod
    def _context(node: PlanNode) -> str:
        return (
            f"# {node.node_id}: {node.objective}\n\n"
            f"Capability: {node.capability}\nRole: {node.role}\n"
            f"Read scope: {', '.join(node.read_scope) or '(none)'}\n"
            f"Write scope: {', '.join(node.write_scope) or '(none)'}\n"
            f"Acceptance: {'; '.join(node.acceptance) or '(none)'}\n"
            f"Verifiers: {', '.join(node.verifiers)}\n"
        )

    def run(self, dispatch: Callable[[PlanNode, Path], DispatchOutcome]) -> NodeRunResult:
        if (self.workspace / ".cybertron").is_symlink() or (self.workspace / ".cybertron" / "runs").is_symlink():
            raise ValueError("run storage may not be a symlink")
        graph = PlanGraph.from_dict(json.loads(self.plan_path.read_text(encoding="utf-8")))
        if len(graph.nodes) != 1 or len(graph.ready_nodes()) != 1:
            raise ValueError("M0b kernel requires exactly one ready node")
        node = graph.ready_nodes()[0]
        if set(node.verifiers) != {"scope_guard"}:
            raise ValueError("M0b only supports the scope_guard verifier")
        if self.run_dir.exists() or self.run_dir.is_symlink():
            raise ValueError("run_id already exists")
        self.run_dir.mkdir(parents=True)
        context = self.run_dir / "context.md"
        context.write_text(self._context(node), encoding="utf-8")
        guard = ScopeGuard(self.workspace, node.write_scope)
        guard.assert_safe_before_dispatch(guard.snapshot())
        self._event("dispatch.started", node_id=node.node_id, role=node.role,
                    capability=node.capability, write_scope=list(node.write_scope))
        before = guard.snapshot()
        outcome = None
        error = None
        try:
            outcome = dispatch(node, context)
        except Exception as exc:
            error = f"dispatch raised {type(exc).__name__}: {exc}"
        report = guard.verify_and_rollback(before)
        if report.rejected_paths:
            self._event("plan.op.rejected", node_id=node.node_id,
                        reason="write_scope violation", paths=list(report.rejected_paths))

        valid = (isinstance(outcome, DispatchOutcome)
                 and outcome.source in {"tool", "sandbox", "host"}
                 and isinstance(outcome.command, str) and bool(outcome.command)
                 and type(outcome.exit_code) is int and isinstance(outcome.output, bytes))
        evidence = None
        if valid:
            evidence = {"source": outcome.source, "command": outcome.command,
                        "exit": outcome.exit_code, "utc": _utc(),
                        "sha256": hashlib.sha256(outcome.output).hexdigest(),
                        "session_id": outcome.session_id}
        artifacts = {path: state.sha256 for path, state in guard.snapshot().entries.items()
                     if path in report.changed_paths and state.kind == "file"
                     and path not in report.rejected_paths}
        if report.rejected_paths or error or (valid and outcome.exit_code != 0):
            status = "failed"
        elif not valid or not artifacts:
            status = "blocked"
        else:
            status = "completed"
        self._event("node." + status, node_id=node.node_id, evidence=evidence,
                    artifacts=artifacts,
                    changed_paths=list(report.changed_paths),
                    rejected_paths=list(report.rejected_paths), reason=error)
        return NodeRunResult(status, node.node_id, context, self.events_path,
                             report.changed_paths, report.rejected_paths)
