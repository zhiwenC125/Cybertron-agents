"""M4 device node event-chain tests with a scripted broker."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cybertron.deployment import DeviceTarget, FirmwareArtifact, FlashPlan
from cybertron.device_broker import ApprovalReceipt, ApprovalRejected
from cybertron.device_node import DeviceNodeKernel


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class StubBroker:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def execute(self, plan, approval, *, expected_full_sha256=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def completed_result(plan):
    return {
        "status": "completed", "plan_digest": plan.plan_digest,
        "approval_id": "approval-1", "preflight": {"full_sha256": "a" * 64},
        "flash": {"region_matches_fixture_and_erased_tail": True,
                  "bootloader_unchanged": True, "ota_flag_page_unchanged": True},
        "heartbeat": {"passed": True, "marker_1": "0xc7b70001",
                      "marker_2": "0xc7b70001", "counter_1": 1, "counter_2": 2},
        "rollback": {"matches_preflight": True, "full_sha256": "a" * 64},
        "restored": True, "error": None,
        "receipts": [{"argv": ["st-flash", "--hot-plug", "reset"], "command": "st-flash reset",
                      "exit": 0, "utc": "2026-11-17T00:00:00+00:00", "sha256": "b" * 64,
                      "source": "tool"}],
        "artifacts": {"preflight-full.bin": "c" * 64},
    }


class DeviceNodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        firmware = self.root / "heartbeat.bin"
        firmware.write_bytes(bytes(range(100)))
        rollback = self.root / "rollback.bin"
        rollback.write_bytes(b"\xAA" * 0xDC00)
        target = DeviceTarget("stlink:test", "STM32F103C8T6", "ST-LINK SWD",
                              0x08000000, 0x08010000)
        self.plan = FlashPlan.prepare(
            target, FirmwareArtifact.inspect(firmware), FirmwareArtifact.inspect(rollback),
            erase_start=0x08002000, erase_end=0x0800FC00,
            rollback_procedure="restore and verify",
            heartbeat_marker="SRAM[0x20000000] == 0xC7B70001",
            heartbeat_address=0x20000000, heartbeat_value=0xC7B70001)
        self.approval = ApprovalReceipt(
            approval_id="approval-1", source="human", approver_id="developer",
            observed_at_utc=datetime.now(timezone.utc).isoformat(),
            plan_digest=self.plan.plan_digest, device_id=self.plan.target.device_id,
            firmware_sha256=self.plan.firmware.sha256,
            erase_start=self.plan.erase_start, erase_end=self.plan.erase_end,
            rollback_sha256=self.plan.rollback.sha256,
            message_sha256=_digest(b"continue M4"), session_id="session-m4")

    def events(self, result):
        return [json.loads(line) for line in Path(result["events_path"]).read_text().splitlines()]

    def test_completed_node_has_approval_receipts_and_device_evidence(self):
        broker = StubBroker(completed_result(self.plan))
        result = DeviceNodeKernel(self.root, "run-1", "device").run(
            self.plan, self.approval, broker,
            expected_full_sha256="a" * 64,
            sim_receipt={"source": "sandbox", "command": "renode sim", "exit": 0,
                         "utc": "2026-11-17T00:00:00+00:00", "sha256": "d" * 64})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(broker.calls, 1)
        events = self.events(result)
        types = [event["type"] for event in events]
        for expected in ("plan.created", "gate.check", "device.planned",
                         "approval.granted", "dispatch.started", "device.receipt",
                         "node.completed", "gate.required"):
            self.assertIn(expected, types)
        completed = next(event for event in events if event["type"] == "node.completed")
        self.assertEqual(completed["evidence"]["source"], "tool")
        self.assertEqual(completed["evidence"]["exit"], 0)
        self.assertEqual(len(completed["evidence"]["sha256"]), 64)
        gates = {event["gate"] for event in events if event["type"] == "gate.check"}
        self.assertTrue({"sim", "device.approval", "rollback.image", "heartbeat"} <= gates)
        plan = json.loads(Path(result["plan_path"]).read_text())
        self.assertEqual(plan["nodes"][0]["status"], "completed")
        self.assertEqual(json.loads(Path(result["events_path"]).read_text().splitlines()[0])["type"],
                         "plan.created")

    def test_rejected_approval_blocks_without_node_completion(self):
        broker = StubBroker(error=ApprovalRejected("approval was already used"))
        result = DeviceNodeKernel(self.root, "run-2", "device").run(
            self.plan, self.approval, broker)
        self.assertEqual(result["status"], "blocked")
        types = [event["type"] for event in self.events(result)]
        self.assertIn("node.blocked", types)
        self.assertNotIn("node.completed", types)

    def test_outcome_unknown_is_terminal_and_not_retryable(self):
        result_value = completed_result(self.plan)
        result_value.update({"status": "outcome_unknown", "restored": False,
                             "error": "fixture write timed out; result is unknown"})
        broker = StubBroker(result_value)
        result = DeviceNodeKernel(self.root, "run-3", "device").run(
            self.plan, self.approval, broker)
        self.assertEqual(result["status"], "outcome_unknown")
        events = self.events(result)
        failed = next(event for event in events if event["type"] == "node.failed")
        self.assertTrue(failed["outcome_unknown"])
        self.assertFalse(failed["retryable"])
        self.assertNotIn("node.retry", [event["type"] for event in events])


if __name__ == "__main__":
    unittest.main()
