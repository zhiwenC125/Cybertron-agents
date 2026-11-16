import hashlib
import unittest

from cybertron.gates import GateLedger, GateRejected, Risk, diff_facts, risk_floor
from cybertron.profiles import CheckReceipt
from cybertron.scope_guard import FileState, Snapshot


def receipt(*, source="sandbox", exit=0, **extra):
    return {"source": source, "command": "clang-tidy -p build src/main.c",
            "exit": exit, "utc": "2026-11-16T00:00:00+00:00",
            "sha256": hashlib.sha256(b"tool output").hexdigest(), **extra}


class GateV6Tests(unittest.TestCase):
    def test_risk_floor_comes_from_actual_snapshot(self):
        empty = Snapshot({})
        for path, expected in (("docs/readme.md", Risk.DOCUMENT),
                               ("src/main.c", Risk.CODE),
                               ("include/api.h", Risk.INTERFACE),
                               ("firmware/main.c", Risk.FIRMWARE)):
            with self.subTest(path=path):
                after = Snapshot({path: FileState("file", b"int main(void) { return 0; }\n")})
                risk, floor = risk_floor(diff_facts(empty, after))
                self.assertEqual(risk, expected)
                self.assertIn("scope_guard", floor)
        risk, floor = risk_floor(diff_facts(empty, empty, device_operation=True))
        self.assertEqual(risk, Risk.DEVICE)
        self.assertIn("device.approval", floor)

    def test_code_gate_floor_cannot_be_removed_or_marked_na(self):
        ledger = GateLedger(frozenset({"scope_guard", "lint", "test"}))
        ledger.add("build")
        self.assertEqual(ledger.required, {"scope_guard", "lint", "test", "build"})
        with self.assertRaises(GateRejected):
            ledger.record("test", "not_applicable", receipt(profile_probe="test_framework_absent"))
        with self.assertRaises(GateRejected):
            ledger.record("build", "not_applicable", receipt(profile_probe="test_framework_absent"))
        self.assertFalse(ledger.complete())

    def test_model_claim_and_fake_waiver_rejected(self):
        ledger = GateLedger(frozenset({"lint"}))
        with self.assertRaises(GateRejected):
            ledger.record("lint", "pass", receipt(source="model"))
        with self.assertRaises(GateRejected):
            ledger.record("lint", "pass", receipt(exit=1))
        with self.assertRaises(GateRejected):
            ledger.record("lint", "waived", receipt(source="host"))
        with self.assertRaises(GateRejected):
            ledger.record("lint", "pass", receipt())
        trusted = CheckReceipt("sandbox", "clang-tidy -p build src/main.c", 0,
                               "2026-11-16T00:00:00+00:00",
                               hashlib.sha256(b"tool output").hexdigest(), "tool output")
        ledger.trust_check("lint", trusted)
        ledger.record("lint", "pass", trusted.to_dict())
        self.assertTrue(ledger.complete())


if __name__ == "__main__":
    unittest.main()
