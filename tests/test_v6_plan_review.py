import json
import tempfile
import unittest
from pathlib import Path

from cybertron.host_v6 import V6HostBridge


class V6PlanReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bridge = V6HostBridge(self.root)
        self.node = {"node_id": "n1", "kind": "task", "capability": "doc.write",
                     "role": "alpha-trion", "objective": "Write notes.md",
                     "write_scope": ["notes.md"], "acceptance": ["notes.md exists"],
                     "verifiers": ["scope_guard"]}

    def test_review_is_required_and_handoff_names_prima(self):
        plan = self.bridge.plan(self.node, "thirteenth")
        state = self.bridge.state(plan["run_id"])
        self.assertFalse(state["review_current"])
        self.assertTrue(state["review_required"])
        self.assertEqual(state["handoff"]["next_agent"], "prima")
        self.assertEqual(state["handoff"]["ready_nodes"], ["n1"])
        self.assertEqual(state["handoff"]["ready_cards"], [plan["card"]])
        review = self.bridge.review_plan(plan["run_id"])
        self.assertTrue(review["approved"])
        state = self.bridge.state(plan["run_id"])
        self.assertTrue(state["review_current"])
        self.assertEqual(state["review"]["reviewer"], "prima")
        self.assertEqual(state["handoff"]["review_current"], True)

    def test_plan_revision_invalidates_the_previous_review(self):
        plan = self.bridge.plan(self.node, "thirteenth")
        review = self.bridge.review_plan(plan["run_id"])
        self.assertTrue(review["approved"])
        self.assertTrue(self.bridge.state(plan["run_id"])["review_current"])
        self.bridge.plan_op(plan["run_id"], {
            "op": "insert_gate", "op_id": "gate-1", "plan_revision": 0,
            "gate": "extra_review",
        })
        state = self.bridge.state(plan["run_id"])
        self.assertEqual(state["plan_revision"], 1)
        self.assertFalse(state["review_current"])
        self.assertIsNone(state["review"])

    def test_plan_json_is_a_projection_not_runtime_truth(self):
        plan = self.bridge.plan(self.node, "thirteenth")
        self.bridge.review_plan(plan["run_id"])
        plan_path = Path(plan["run_dir"]) / "plan.json"
        data = json.loads(plan_path.read_text())
        data["nodes"][0]["status"] = "completed"
        plan_path.write_text(json.dumps(data))
        state = self.bridge.state(plan["run_id"])
        # Runtime status comes from events.jsonl, not the editable projection.
        self.assertEqual(state["nodes"][0]["status"], "pending")
        # A direct edit also invalidates the review hash binding.
        self.assertFalse(state["review_current"])

    def test_review_warns_about_overlapping_write_scopes(self):
        second = dict(self.node, node_id="n2", objective="Write the same notes",
                      write_scope=["notes.md"])
        plan = self.bridge.plan([self.node, second], "thirteenth")
        review = self.bridge.review_plan(plan["run_id"])
        self.assertTrue(review["approved"])
        self.assertIn("scope.overlap",
                      [finding["code"] for finding in review["findings"]])


if __name__ == "__main__":
    unittest.main()
