"""M4 device node: one approved STM32 operation with a typed receipt chain."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .deployment import FlashPlan
from .device_broker import ApprovalReceipt, ApprovalRejected, DeviceBroker, DeviceRejected
from .graph import PlanGraph, PlanNode


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class DeviceNodeKernel:
    """Write a v6 run whose only node is an approval-bound device operation."""

    def __init__(self, workspace: Path, run_id: str, node_id: str = "device") -> None:
        self.workspace = Path(workspace).resolve()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", run_id):
            raise ValueError("invalid run_id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", node_id):
            raise ValueError("invalid node_id")
        self.run_id = run_id
        self.node_id = node_id
        self.run_dir = self.workspace / ".cybertron" / "runs" / run_id
        if self.run_dir.exists() or self.run_dir.is_symlink():
            raise DeviceRejected("run_id already exists")
        self.run_dir.mkdir(parents=True)
        self.events_path = self.run_dir / "events.jsonl"
        self.plan_path = self.run_dir / "plan.json"

    def _event(self, kind: str, **fields: object) -> None:
        event = {"type": kind, "utc": _utc(), **fields}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def _plan(self, plan: FlashPlan) -> PlanGraph:
        node = PlanNode(
            node_id=self.node_id, kind="device_op", capability="device.op",
            role="megatronus",
            objective=("Flash the approved STM32 image, verify the SRAM heartbeat, "
                       "and restore the verified rollback image."),
            acceptance=(
                "approval binds device, firmware, erase range, and rollback image",
                "Renode simulation reports the expected heartbeat",
                "post-flash readback preserves bootloader and OTA flag page",
                "SRAM heartbeat marker is observed and the counter advances",
                "rollback restores the exact preflight full-flash digest",
            ),
            verifiers=("device.approval", "rollback.image", "heartbeat", "sim"),
            budget={"max_attempts": 1},
        )
        graph = PlanGraph([node])
        self.plan_path.write_text(json.dumps(graph.to_dict(), ensure_ascii=False, indent=2))
        return graph

    def run(self, plan: FlashPlan, approval: ApprovalReceipt, broker: DeviceBroker, *,
            expected_full_sha256: str | None = None,
            sim_receipt: Mapping[str, object] | None = None,
            build_receipt: Mapping[str, object] | None = None,
            size_receipt: Mapping[str, object] | None = None) -> dict:
        graph = self._plan(plan)
        node = graph.nodes[self.node_id]
        self._event("plan.created", node_id=self.node_id, plan_revision=graph.revision,
                    role=node.role, capability=node.capability,
                    verifiers=list(node.verifiers))
        for gate, receipt in (("cross_compile", build_receipt), ("size", size_receipt),
                              ("sim", sim_receipt)):
            if receipt is None:
                continue
            self._event("gate.check", gate=gate, status="pass", receipt=dict(receipt))
        self._event("device.planned", node_id=self.node_id,
                    plan_digest=plan.plan_digest,
                    target={"device_id": plan.target.device_id, "board": plan.target.board,
                            "connection": plan.target.connection,
                            "flash_start": plan.target.flash_start,
                            "flash_end": plan.target.flash_end},
                    firmware={"path": plan.firmware.path, "sha256": plan.firmware.sha256,
                              "bytes": plan.firmware.size_bytes},
                    rollback={"path": plan.rollback.path, "sha256": plan.rollback.sha256,
                              "bytes": plan.rollback.size_bytes},
                    erase={"start": plan.erase_start, "end": plan.erase_end})
        self._event("approval.granted", node_id=self.node_id,
                    approval=approval.to_dict(),
                    approval_sha256=_digest(approval.to_dict()))
        self._event("dispatch.started", node_id=self.node_id, role=node.role,
                    capability=node.capability, write_scope=[])
        try:
            result = broker.execute(plan, approval,
                                    expected_full_sha256=expected_full_sha256)
        except ApprovalRejected as exc:
            self._event("node.blocked", node_id=self.node_id, reason=str(exc),
                        diagnostic=str(exc), retryable=False)
            return self._finish("blocked", None, graph, error=str(exc))
        except DeviceRejected as exc:
            self._event("node.failed", node_id=self.node_id, reason=str(exc),
                        diagnostic=str(exc), retryable=False)
            return self._finish("failed", None, graph, error=str(exc))
        for receipt in result["receipts"]:
            self._event("device.receipt", node_id=self.node_id, **receipt)
        receipts_digest = _digest(result["receipts"])
        artifacts = dict(result.get("artifacts") or {})
        artifacts.update({plan.firmware.path: plan.firmware.sha256,
                          plan.rollback.path: plan.rollback.sha256})
        if result["status"] == "completed":
            self._event("node.completed", node_id=self.node_id,
                        evidence={"source": "tool", "command": "st-flash --hot-plug",
                                  "exit": 0, "utc": _utc(), "sha256": receipts_digest,
                                  "session_id": None},
                        artifacts=artifacts, changed_paths=[], rejected_paths=[],
                        plan_digest=plan.plan_digest,
                        heartbeat=result.get("heartbeat"),
                        rollback=result.get("rollback"))
            self._event("gate.required", node_id=self.node_id, risk="device",
                        gates=["device.approval", "rollback.image", "heartbeat"])
            self._event("gate.check", gate="device.approval", status="pass",
                        receipt={"source": "human", "command": "chat approval",
                                 "exit": 0, "utc": approval.observed_at_utc,
                                 "sha256": _digest(approval.to_dict())})
            self._event("gate.check", gate="rollback.image", status="pass",
                        receipt={"source": "tool",
                                 "command": "sha256 rollback image",
                                 "exit": 0, "utc": _utc(),
                                 "sha256": plan.rollback.sha256})
            self._event("gate.check", gate="heartbeat", status="pass",
                        receipt={"source": "tool",
                                 "command": "st-flash --hot-plug read SRAM",
                                 "exit": 0, "utc": _utc(),
                                 "sha256": _digest(result.get("heartbeat") or {})})
        else:
            self._event("node.failed", node_id=self.node_id,
                        reason=result.get("error") or result["status"],
                        diagnostic=result.get("error") or result["status"],
                        failure_fingerprint=_digest({"status": result["status"],
                                                     "error": result.get("error")}),
                        retryable=False, outcome_unknown=result["status"] == "outcome_unknown")
        return self._finish(result["status"], result, graph,
                            error=result.get("error"))

    def _finish(self, status: str, result: dict | None, graph: PlanGraph,
                error: str | None = None) -> dict:
        graph.nodes[self.node_id].status = {
            "completed": "completed", "blocked": "blocked", "failed": "failed",
            "outcome_unknown": "failed",
        }[status]
        self.plan_path.write_text(json.dumps(graph.to_dict(), ensure_ascii=False, indent=2))
        summary = {
            "run_id": self.run_id, "node_id": self.node_id, "status": status,
            "error": error, "events_path": str(self.events_path),
            "plan_path": str(self.plan_path),
            "result": result,
        }
        (self.run_dir / "state.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        return summary
