"""M4 device broker rejection and rollback tests with a scripted ST-LINK."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cybertron.deployment import DeviceTarget, FirmwareArtifact, FlashPlan
from cybertron.device_broker import (
    ApprovalReceipt,
    ApprovalRejected,
    DeviceBroker,
    DeviceRejected,
)

APP_START = 0x08002000
APP_BYTES = 0xDC00
FULL_START = 0x08000000
FULL_BYTES = 0x10000


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeStlink:
    """A tiny deterministic ST-LINK surface; no hardware is touched."""

    def __init__(self, full_flash: bytearray, *, mode: str = "ok") -> None:
        self.flash = bytearray(full_flash)
        self.mode = mode
        self.commands: list[list[str]] = []
        self.erase_count = 0
        self.sram_counter = 0
        self.marker = 0xC7B70001

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        command = argv[2]
        if command == "read":
            path, address, size = Path(argv[3]), int(argv[4], 16), int(argv[5], 16)
            if address == 0x20000000:
                if self.mode == "heartbeat_wrong":
                    marker = 0xDEADBEEF
                else:
                    marker = self.marker
                self.sram_counter += 1
                data = marker.to_bytes(4, "little") + self.sram_counter.to_bytes(4, "little")
                data += b"\x00" * (size - len(data))
            else:
                data = bytes(self.flash[address - FULL_START:address - FULL_START + size])
            path.write_bytes(data)
            return subprocess.CompletedProcess(argv, 0, stdout="read ok")
        if command == "erase":
            self.erase_count += 1
            if self.mode == "rollback_erase_fail" and self.erase_count >= 2:
                return subprocess.CompletedProcess(argv, 1, stdout="rollback erase failed")
            address, size = int(argv[3], 16), int(argv[4], 16)
            start = address - FULL_START
            self.flash[start:start + size] = b"\xFF" * size
            return subprocess.CompletedProcess(argv, 0, stdout="erase ok")
        if command == "write":
            if self.mode == "timeout_write" and "heartbeat" in Path(argv[3]).name:
                raise subprocess.TimeoutExpired(argv, 1)
            if self.mode == "write_fail" and "heartbeat" in Path(argv[3]).name:
                return subprocess.CompletedProcess(argv, 1, stdout="write failed")
            path, address = Path(argv[3]), int(argv[4], 16)
            data = path.read_bytes()
            start = address - FULL_START
            self.flash[start:start + len(data)] = data
            return subprocess.CompletedProcess(argv, 0, stdout="write ok")
        if command == "reset":
            self.marker = 0xC7B70001
            self.sram_counter = 0
            return subprocess.CompletedProcess(argv, 0, stdout="reset ok")
        return subprocess.CompletedProcess(argv, 2, stdout="unknown command")


class DeviceBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rollback_bytes = bytes((index * 7) % 251 for index in range(APP_BYTES))
        self.firmware_bytes = bytes(range(100))
        self.firmware = self.root / "heartbeat.bin"
        self.firmware.write_bytes(self.firmware_bytes)
        self.rollback = self.root / "rollback.bin"
        self.rollback.write_bytes(self.rollback_bytes)
        self.full = bytearray(b"\xAA" * 0x2000 + self.rollback_bytes + b"\x5A" * 0x400)
        self.target = DeviceTarget("stlink:test/STM32F1xx_MD:0x410",
                                   "STM32F103C8T6", "ST-LINK SWD",
                                   FULL_START, FULL_START + FULL_BYTES)
        self.plan = FlashPlan.prepare(
            self.target, FirmwareArtifact.inspect(self.firmware),
            FirmwareArtifact.inspect(self.rollback),
            erase_start=APP_START, erase_end=APP_START + APP_BYTES,
            rollback_procedure="erase App, write rollback, read full flash, compare",
            heartbeat_marker="SRAM[0x20000000] == 0xC7B70001",
            heartbeat_address=0x20000000, heartbeat_value=0xC7B70001)
        self.output = self.root / "run"
        self.fake = FakeStlink(self.full)
        self.broker = DeviceBroker(self.root, self.output, runner=self.fake,
                                   sleeper=lambda seconds: None)

    def approval(self, plan=None, **overrides):
        plan = plan or self.plan
        values = {
            "approval_id": "chat-approval-1",
            "source": "human",
            "approver_id": "developer",
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "plan_digest": plan.plan_digest,
            "device_id": plan.target.device_id,
            "firmware_sha256": plan.firmware.sha256,
            "erase_start": plan.erase_start,
            "erase_end": plan.erase_end,
            "rollback_sha256": plan.rollback.sha256,
            "message_sha256": _digest(b"continue M4"),
            "session_id": "session-m4",
        }
        values.update(overrides)
        return ApprovalReceipt(**values)

    def snapshot(self):
        return self.broker.snapshot(self.target, app_start=APP_START,
                                    app_end=APP_START + APP_BYTES)

    def destructive_commands(self):
        return [command for command in self.fake.commands
                if command[2] in {"erase", "write", "reset"}]

    def test_success_flashes_heartbeat_and_restores_exact_preflight(self):
        before = bytes(self.full)
        snapshot = self.snapshot()
        self.assertEqual(snapshot["app_sha256"], self.plan.rollback.sha256)
        before_execute = len(self.fake.commands)
        result = self.broker.execute(self.plan, self.approval(),
                                     expected_full_sha256=snapshot["full_sha256"])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["restored"])
        self.assertTrue(result["heartbeat"]["passed"])
        self.assertTrue(result["rollback"]["matches_preflight"])
        self.assertEqual(bytes(self.fake.flash), before)
        self.assertEqual(len(result["receipts"]), len(self.fake.commands) - before_execute)
        self.assertTrue(all(item["source"] == "tool" for item in result["receipts"]))
        self.assertTrue(all(item["utc"] for item in result["receipts"]))
        self.assertTrue((self.output / "device-approvals.json").is_file())
        used = (self.output / "device-approvals.json").read_text()
        self.assertIn("chat-approval-1", used)

    def test_approval_must_bind_the_exact_plan(self):
        snapshot = bytes(self.full)
        cases = {
            "plan_digest": self.approval(plan_digest="0" * 64),
            "device_id": self.approval(device_id="another-device"),
            "firmware_sha256": self.approval(firmware_sha256="1" * 64),
            "erase_start": self.approval(erase_start=APP_START + 0x400),
            "rollback_sha256": self.approval(rollback_sha256="2" * 64),
        }
        for label, approval in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ApprovalRejected):
                    self.broker.execute(self.plan, approval)
        self.assertEqual(self.destructive_commands(), [])
        self.assertEqual(bytes(self.fake.flash), snapshot)

    def test_approval_is_single_use_and_not_replayed(self):
        snapshot = self.snapshot()
        approval = self.approval()
        self.broker.execute(self.plan, approval,
                            expected_full_sha256=snapshot["full_sha256"])
        commands = len(self.fake.commands)
        with self.assertRaises(ApprovalRejected):
            self.broker.execute(self.plan, approval,
                                expected_full_sha256=snapshot["full_sha256"])
        self.assertEqual(len(self.fake.commands), commands)

    def test_device_change_after_snapshot_is_rejected_before_write(self):
        snapshot = self.snapshot()
        self.fake.flash[0] ^= 0xFF
        with self.assertRaises(DeviceRejected):
            self.broker.execute(self.plan, self.approval(),
                                expected_full_sha256=snapshot["full_sha256"])
        self.assertEqual(self.destructive_commands(), [])

    def test_current_app_must_match_rollback_image(self):
        snapshot = self.snapshot()
        self.fake.flash[APP_START - FULL_START] ^= 0xFF
        with self.assertRaises(DeviceRejected):
            self.broker.execute(self.plan, self.approval(),
                                expected_full_sha256=snapshot["full_sha256"])
        self.assertEqual(self.destructive_commands(), [])

    def test_heartbeat_failure_rolls_back_and_preserves_preflight(self):
        before = bytes(self.full)
        self.fake.mode = "heartbeat_wrong"
        snapshot = self.snapshot()
        result = self.broker.execute(self.plan, self.approval(),
                                     expected_full_sha256=snapshot["full_sha256"])
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["restored"])
        self.assertIn("heartbeat", result["error"])
        self.assertEqual(bytes(self.fake.flash), before)

    def test_unknown_write_outcome_is_not_retried_and_still_rolls_back(self):
        before = bytes(self.full)
        self.fake.mode = "timeout_write"
        snapshot = self.snapshot()
        result = self.broker.execute(self.plan, self.approval(),
                                     expected_full_sha256=snapshot["full_sha256"])
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertTrue(result["restored"])
        self.assertEqual(bytes(self.fake.flash), before)
        writes = [command for command in self.fake.commands
                  if command[2] == "write" and "heartbeat" in command[3]]
        self.assertEqual(len(writes), 1)

    def test_rollback_failure_is_outcome_unknown(self):
        self.fake.mode = "rollback_erase_fail"
        snapshot = self.snapshot()
        result = self.broker.execute(self.plan, self.approval(),
                                     expected_full_sha256=snapshot["full_sha256"])
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertFalse(result["restored"])
        self.assertIn("rollback", result["rollback"]["error"])

    def test_plan_tampering_is_rejected(self):
        from dataclasses import replace
        with self.assertRaisesRegex(ValueError, "plan changed"):
            replace(self.plan, erase_end=self.plan.erase_end - 0x400).verify()

    def test_snapshot_rejects_short_read(self):
        class ShortRead(FakeStlink):
            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if argv[2] == "read":
                    path = Path(argv[3])
                    path.write_bytes(path.read_bytes()[:-1])
                return result
        broker = DeviceBroker(self.root, self.root / "short", runner=ShortRead(self.full),
                              sleeper=lambda seconds: None)
        with self.assertRaises(DeviceRejected):
            broker.snapshot(self.target, app_start=APP_START,
                            app_end=APP_START + APP_BYTES)


if __name__ == "__main__":
    unittest.main()
