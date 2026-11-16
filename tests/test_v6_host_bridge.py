import json
import subprocess
import sys
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

    def test_m1_multi_node_plan_dispatches_ready_nodes_in_order(self):
        nodes = []
        for index in range(4):
            item = dict(self.node)
            item["node_id"] = f"n{index}"
            item["objective"] = f"Write docs/n{index}.md"
            item["write_scope"] = [f"docs/n{index}.md"]
            item["depends_on"] = [f"n{index - 1}"] if index else []
            nodes.append(item)
        plan = self.bridge.plan(nodes, "parent")
        self.assertEqual(plan["ready_nodes"], ["n0"])
        for index in range(4):
            current = self.bridge.state(plan["run_id"])
            self.assertEqual(current["ready_nodes"], [f"n{index}"])
            card = current["nodes"][index]["card"]
            started = self.bridge.before(plan["run_id"], f"n{index}", "alpha-trion", card, f"call-{index}")
            returned = self.bridge.after(plan["run_id"], f"call-{index}", started["token"],
                                         f"child-{index}", "completed", 1)
            (self.root / "docs").mkdir(exist_ok=True)
            (self.root / "docs" / f"n{index}.md").write_text(f"{index}")
            settled = self.bridge.finish(plan["run_id"], returned["token"], f"child-{index}")
            self.assertEqual(settled["nodes"][index]["status"], "completed")
        self.assertEqual(settled["status"], "completed")
        self.assertEqual(sum(event["type"] == "dispatch.started" for event in self.bridge.events(plan["run_id"])), 4)

    def test_m1_replan_adds_node_and_rejects_stale_revision(self):
        plan = self.bridge.plan(self.node, "parent")
        second = dict(self.node, node_id="n2", objective="Write docs/n2.md",
                      write_scope=["docs/n2.md"], depends_on=["n1"])
        operation = {"op_id": "add-n2", "plan_revision": 0, "op": "add_node", "node": second}
        changed = self.bridge.plan_op(plan["run_id"], operation)
        self.assertEqual(changed["plan_revision"], 1)
        self.assertEqual(len(changed["nodes"]), 2)
        with self.assertRaises(HostBridgeError):
            self.bridge.plan_op(plan["run_id"], {**operation, "op_id": "stale"})
        self.assertIn("plan.op.rejected", [e["type"] for e in self.bridge.events(plan["run_id"])])

    def test_m1_bug_template_is_available_through_cli(self):
        command = [sys.executable, "-m", "cybertron.host_v6_cli", "plan",
                   "--project", str(self.root)]
        result = subprocess.run(command, input=json.dumps({
            "template": {"type": "bug_fix", "objective": "Fix parser null dereference",
                         "write_scope": ["src/parser.py"]},
            "host_session_id": "parent",
        }), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(len(state["nodes"]), 4)
        self.assertEqual(set(state["ready_nodes"]), {"scan-static", "scan-history"})


if __name__ == "__main__":
    unittest.main()
