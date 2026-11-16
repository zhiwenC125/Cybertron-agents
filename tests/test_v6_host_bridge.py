import json
import tempfile
import unittest
from pathlib import Path

from cybertron.host_v6 import HostBridgeError, V6HostBridge


class V6HostBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bridge = V6HostBridge(self.root)
        self.node = {"node_id": "n1", "kind": "task", "capability": "doc.write",
                     "role": "alpha-trion", "objective": "Write notes.md",
                     "write_scope": ["notes.md"], "acceptance": ["notes.md exists"],
                     "verifiers": ["scope_guard"]}

    def test_mismatched_role_and_duplicate_dispatch_are_rejected(self):
        plan = self.bridge.plan(self.node, "parent")
        with self.assertRaises(HostBridgeError):
            self.bridge.before(plan["run_id"], "n1", "solus-prime", plan["card"], "call1")
        started = self.bridge.before(plan["run_id"], "n1", "alpha-trion", plan["card"], "call1")
        self.assertEqual(started["status"], "running")
        rejected = self.bridge.before(plan["run_id"], "n1", "alpha-trion",
                                      plan["card"], "call2", started["token"])
        self.assertTrue(rejected["rejected"])
        self.assertIn("not ready", rejected["reason"])
        self.assertIn("plan.op.rejected", [e["type"] for e in self.bridge.events(plan["run_id"])])

    def test_after_is_background_until_explicit_finish(self):
        plan = self.bridge.plan(self.node, "parent")
        started = self.bridge.before(plan["run_id"], "n1", "alpha-trion", plan["card"], "call1")
        returned = self.bridge.after(plan["run_id"], "call1", started["token"],
                                     "child-session", "completed", 120)
        self.assertEqual(self.bridge.state(plan["run_id"])["status"], "running")
        (self.root / "notes.md").write_text("done")
        result = self.bridge.finish(plan["run_id"], returned["token"], "child-session")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.bridge.state(plan["run_id"])["status"], "completed")

    def test_out_of_scope_write_rolls_back_on_finish(self):
        plan = self.bridge.plan(self.node, "parent")
        started = self.bridge.before(plan["run_id"], "n1", "alpha-trion", plan["card"], "call1")
        returned = self.bridge.after(plan["run_id"], "call1", started["token"],
                                     "child-session", "completed", 120)
        (self.root / "notes.md").write_text("done")
        (self.root / "escape.txt").write_text("bad")
        result = self.bridge.finish(plan["run_id"], returned["token"], "child-session")
        self.assertEqual(result["status"], "failed")
        self.assertFalse((self.root / "escape.txt").exists())

    def test_bad_card_and_model_claim_are_rejected(self):
        plan = self.bridge.plan(self.node, "parent")
        with self.assertRaises(HostBridgeError):
            self.bridge.before(plan["run_id"], "n1", "alpha-trion", "write notes", "call1")
        self.assertEqual(self.bridge.state(plan["run_id"])["status"], "ready")

    def test_cancel_before_child_id_is_terminal(self):
        plan = self.bridge.plan(self.node, "parent")
        started = self.bridge.before(plan["run_id"], "n1", "alpha-trion", plan["card"], "call1")
        result = self.bridge.after(plan["run_id"], "call1", started["token"],
                                   None, "cancelled", 10)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.bridge.state(plan["run_id"])["status"], "cancelled")

    def test_tampered_event_log_rejects_host_receipt(self):
        plan = self.bridge.plan(self.node, "parent")
        started = self.bridge.before(plan["run_id"], "n1", "alpha-trion", plan["card"], "call1")
        path = Path(self.bridge.state(plan["run_id"])["events_path"])
        path.write_text(path.read_text() + "forged\n")
        with self.assertRaises(HostBridgeError):
            self.bridge.after(plan["run_id"], "call1", started["token"],
                              "child-session", "completed", 10)

    def test_human_question_cannot_invalidate_active_dispatch(self):
        plan = self.bridge.plan(self.node, "parent")
        started = self.bridge.before(plan["run_id"], "n1", "alpha-trion", plan["card"], "call1")
        with self.assertRaises(HostBridgeError):
            self.bridge.ask(plan["run_id"], "Question during dispatch")
        returned = self.bridge.after(plan["run_id"], "call1", started["token"],
                                     "child-session", "completed", 1)
        self.assertEqual(returned["status"], "running")


if __name__ == "__main__":
    unittest.main()
