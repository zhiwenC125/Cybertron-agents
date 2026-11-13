"""Meaningful offline stage 7 gates; no physical device is involved."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cybertron.deployment import DeviceTarget, FirmwareArtifact, FlashPlan, simulate_flash


class DeploymentStage7Tests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.firmware_path = root / "candidate.bin"
        self.rollback_path = root / "golden.bin"
        self.firmware_path.write_bytes(b"new-firmware")
        self.rollback_path.write_bytes(b"golden-firmware")
        self.target = DeviceTarget("fixture-board-1", "fixture-board", "fake://port/1", 0x1000, 0x2000)

    def plan(self, **overrides):
        values = {
            "target": self.target,
            "firmware": FirmwareArtifact.inspect(self.firmware_path),
            "rollback": FirmwareArtifact.inspect(self.rollback_path),
            "erase_start": 0x1000,
            "erase_end": 0x1800,
            "rollback_procedure": "Restore golden image and verify heartbeat",
            "heartbeat_marker": "READY",
        }
        values.update(overrides)
        return FlashPlan.prepare(values.pop("target"), values.pop("firmware"),
                                 values.pop("rollback"), **values)

    def test_assessment_and_simulated_heartbeat(self):
        plan = self.plan()
        assessment = plan.assessment()
        self.assertEqual(assessment["firmware"]["sha256"], plan.firmware.sha256)
        self.assertEqual(assessment["rollback"]["sha256"], plan.rollback.sha256)
        self.assertTrue(assessment["requires_human_approval"])
        receipt = simulate_flash(plan, "booting\nREADY\n")
        self.assertTrue(receipt.simulated)
        self.assertTrue(receipt.heartbeat_observed)
        self.assertEqual(receipt.plan_digest, assessment["plan_digest"])

    def test_missing_rollback_or_invalid_target_fails_before_simulation(self):
        self.rollback_path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.plan()
        self.rollback_path.write_bytes(b"golden-firmware")
        with self.assertRaisesRegex(ValueError, "Erase range"):
            self.plan(erase_end=0x3000)
        with self.assertRaisesRegex(ValueError, "device_id"):
            self.plan(target=replace(self.target, device_id=""))

    def test_changed_firmware_invalidates_plan(self):
        plan = self.plan()
        self.firmware_path.write_bytes(b"changed-firmware")
        with self.assertRaisesRegex(ValueError, "changed"):
            plan.assessment()
        with self.assertRaisesRegex(ValueError, "changed"):
            simulate_flash(plan, "READY")

    def test_plan_tampering_and_missing_heartbeat_fail(self):
        plan = self.plan()
        with self.assertRaisesRegex(ValueError, "plan changed"):
            replace(plan, erase_end=0x1900).assessment()
        with self.assertRaisesRegex(ValueError, "heartbeat"):
            simulate_flash(plan, "boot failed")

    def test_raw_firmware_must_fit_erase_range(self):
        with self.assertRaisesRegex(ValueError, "does not fit"):
            self.plan(erase_end=0x1004)

    def test_symlink_firmware_is_rejected(self):
        alias = self.firmware_path.parent / "alias.bin"
        alias.symlink_to(self.firmware_path)
        with self.assertRaisesRegex(ValueError, "regular"):
            FirmwareArtifact.inspect(alias)


if __name__ == "__main__":
    unittest.main()
