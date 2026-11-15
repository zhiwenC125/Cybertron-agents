import itertools
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cybertron.runstore import RunCorrupt, RunStore, RunStoreError
from cybertron.side_effects import ApprovalRequired, OutcomeUnknown, SideEffectGuard


class SideEffectGuardTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CYBERTRON_SANDBOX"):
            numbers = itertools.count(200)
            patcher = patch("cybertron.side_effects.uuid.uuid4",
                            side_effect=lambda: uuid.UUID(int=next(numbers)))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scratch = tempfile.TemporaryDirectory(prefix="cybertron-side-effect-")
        self.workspace = Path(self.scratch.name)
        (self.workspace / "opencode.jsonc").write_text('{"default_agent":"prima"}\n')
        self.store = RunStore(self.workspace)
        self.run_id = self.store.create("离线审批测试")["run_id"]
        self.guard = SideEffectGuard(
            self.store,
            verify_approval=lambda receipt: receipt["host_request_id"] == "verified-request",
            verify_tool_receipt=lambda receipt: receipt["host_tool_call_id"] == "verified-tool",
        )

    def tearDown(self):
        self.scratch.cleanup()

    def flash_plan(self, firmware="a" * 64, target="stm32-board-one"):
        return self.guard.plan(
            self.run_id, kind="flash", target_id=target, action="write-firmware",
            firmware_sha256=firmware, erase_ranges=("0x08002800-0x0800ffff",),
            rollback_sha256="b" * 64, scope="one-app-partition",
        )

    def approval(self, plan, approval_id=None):
        return {
            "approval_id": approval_id or str(uuid.UUID(int=999)),
            "run_id": self.run_id,
            "plan_id": plan["plan_id"],
            "plan_sha256": plan["plan_sha256"],
            "target_id": plan["target_id"],
            "action": plan["action"],
            "scope": plan["scope"],
            "host_request_id": "verified-request",
            "approver_id": "test-human",
            "observed_at_utc": "2026-11-15T00:00:00+00:00",
        }

    def tool_receipt(self, plan):
        return {
            "run_id": self.run_id,
            "plan_id": plan["plan_id"],
            "idempotency_key": plan["idempotency_key"],
            "host_tool_call_id": "verified-tool",
            "observed_at_utc": "2026-11-15T00:01:00+00:00",
            "output_sha256": "c" * 64,
            "reference": "host://receipt/test",
            "exit_code": 0,
            "outcome": "completed",
        }

    def test_hardware_plan_requires_exact_binding_fields(self):
        with self.assertRaises(ValueError):
            self.flash_plan(firmware="")
        with self.assertRaises(ValueError):
            self.guard.plan(self.run_id, kind="power_on", target_id="board",
                            action="power-on", scope="one-board")
        plan = self.flash_plan()
        self.assertEqual(self.guard.status(self.run_id, plan["plan_id"])["status"], "planned")

    def test_approval_requires_host_verification_and_exact_plan(self):
        plan = self.flash_plan()
        receipt = self.approval(plan)
        with self.assertRaises(ApprovalRequired):
            SideEffectGuard(self.store).grant(self.run_id, plan["plan_id"], receipt)
        changed = dict(receipt, target_id="other-board")
        with self.assertRaises(ApprovalRequired):
            self.guard.grant(self.run_id, plan["plan_id"], changed)
        changed = dict(receipt, host_request_id="model-claim")
        with self.assertRaises(ApprovalRequired):
            self.guard.grant(self.run_id, plan["plan_id"], changed)
        self.assertEqual(self.guard.grant(self.run_id, plan["plan_id"], receipt)["status"], "approved")

    def test_started_without_receipt_is_outcome_unknown_and_never_retried(self):
        plan = self.flash_plan()
        self.guard.grant(self.run_id, plan["plan_id"], self.approval(plan))
        self.assertEqual(self.guard.begin(self.run_id, plan["plan_id"])["status"], "outcome_unknown")
        with self.assertRaises(OutcomeUnknown):
            SideEffectGuard(self.store).begin(self.run_id, plan["plan_id"])
        with self.assertRaises(RunStoreError):
            self.guard.finish(self.run_id, plan["plan_id"], dict(self.tool_receipt(plan),
                                                                  idempotency_key="wrong"))
        self.assertEqual(self.guard.finish(self.run_id, plan["plan_id"], self.tool_receipt(plan))["status"],
                         "completed")
        with self.assertRaises(ApprovalRequired):
            self.guard.begin(self.run_id, plan["plan_id"])

    def test_approval_cannot_be_reused_for_changed_firmware(self):
        first = self.flash_plan()
        second = self.flash_plan(firmware="d" * 64)
        self.assertNotEqual(first["plan_sha256"], second["plan_sha256"])
        receipt = self.approval(first)
        self.guard.grant(self.run_id, first["plan_id"], receipt)
        with self.assertRaises(ApprovalRequired):
            self.guard.grant(self.run_id, second["plan_id"], receipt)
        second_receipt = self.approval(second, approval_id=receipt["approval_id"])
        with self.assertRaises(ApprovalRequired):
            self.guard.grant(self.run_id, second["plan_id"], second_receipt)

    def test_approval_is_bound_to_run_id(self):
        first = self.flash_plan()
        other_run = self.store.create("另一项任务")["run_id"]
        other = self.guard.plan(other_run, kind="flash", target_id="stm32-board-one",
                                action="write-firmware", firmware_sha256="a" * 64,
                                erase_ranges=("0x08002800-0x0800ffff",),
                                rollback_sha256="b" * 64, scope="one-app-partition")
        reused = dict(self.approval(first), plan_id=other["plan_id"],
                      plan_sha256=other["plan_sha256"])
        with self.assertRaises(ApprovalRequired):
            self.guard.grant(other_run, other["plan_id"], reused)

    def test_feishu_space_scope_and_payload_tampering(self):
        plan = self.guard.plan(self.run_id, kind="feishu_write", target_id="test-space",
                               action="append-document", scope="node-123")
        wrong = dict(self.approval(plan), scope="other-node")
        with self.assertRaises(ApprovalRequired):
            self.guard.grant(self.run_id, plan["plan_id"], wrong)
        directory, _ = self.store._locate(self.run_id)
        log = directory / "events.jsonl"
        events = [json.loads(line) for line in log.read_text().splitlines()]
        events[-1]["payload"]["target_id"] = "other-space"
        log.write_text("\n".join(json.dumps(event) for event in events) + "\n")
        with self.assertRaises(RunCorrupt):
            self.guard.status(self.run_id, plan["plan_id"])


if __name__ == "__main__":
    unittest.main()
