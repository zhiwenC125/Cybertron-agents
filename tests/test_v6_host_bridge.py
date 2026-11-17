import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cybertron.host_v6 import HostBridgeError, V6HostBridge, require_isolated_workspace


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
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["ready_nodes"], ["n1"])
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

    def test_answered_question_is_recorded_even_during_dispatch(self):
        plan = self.bridge.plan(self.node, "parent")
        self.bridge.before(plan["run_id"], "n1", "alpha-trion", plan["card"], "call1")
        self.bridge.ask(plan["run_id"], "Which parser?", ["native"])
        events = self.bridge.events(plan["run_id"])
        answered = [event for event in events if event["type"] == "human.answered"]
        self.assertEqual(len(answered), 1)
        self.assertEqual(answered[0]["answers"], ["native"])
        self.assertEqual(answered[0]["source"], "opencode.question")

    def test_approved_question_records_approval_event(self):
        plan = self.bridge.plan(self.node, "parent")
        self.bridge.ask(plan["run_id"], "Proceed with notes.md?", approved=True)
        approved = [event for event in self.bridge.events(plan["run_id"])
                    if event["type"] == "approval.granted"]
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["source"], "opencode.permission")
        self.assertEqual([event["type"] for event in self.bridge.events(plan["run_id"])
                          if event["type"].startswith("human.")],
                         ["human.requested"])

    def test_user_home_workspace_is_rejected_before_planning(self):
        for project in (Path.home(), Path("/")):
            with self.subTest(project=str(project)):
                with self.assertRaisesRegex(HostBridgeError, "isolated project directory"):
                    require_isolated_workspace(project)

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

    def test_m3_disjoint_writers_have_independent_snapshots_and_receipts(self):
        first = dict(self.node, node_id="a", objective="Write docs/a.md",
                     write_scope=["docs/a.md"])
        second = dict(self.node, node_id="b", objective="Write docs/b.md",
                      write_scope=["docs/b.md"])
        plan = self.bridge.plan([first, second], "parent")
        self.assertEqual(plan["ready_nodes"], ["a", "b"])
        a = self.bridge.before(plan["run_id"], "a", "alpha-trion",
                               plan["nodes"][0]["card"], "call-a")
        self.bridge.after(plan["run_id"], "call-a", a["token"], "child-a", "completed", 1)
        self.bridge.bind(plan["run_id"], "call-a", a["token"], "child-a", ["docs/a.md"])
        b = self.bridge.before(plan["run_id"], "b", "alpha-trion",
                               plan["nodes"][1]["card"], "call-b")
        self.assertEqual(len(self.bridge.state(plan["run_id"])["active_dispatches"]), 2)
        self.bridge.after(plan["run_id"], "call-b", b["token"], "child-b", "completed", 1)
        self.bridge.bind(plan["run_id"], "call-b", b["token"], "child-b", ["docs/b.md"])
        (self.root / "docs").mkdir()
        (self.root / "docs/a.md").write_text("a")
        (self.root / "docs/b.md").write_text("b")
        self.bridge.finish(plan["run_id"], a["token"], "child-a", call_id="call-a")
        self.assertEqual((self.root / "docs/b.md").read_text(), "b")
        state = self.bridge.finish(plan["run_id"], b["token"], "child-b", call_id="call-b")
        self.assertEqual(state["status"], "completed")
        self.assertEqual([node["status"] for node in state["nodes"]], ["completed", "completed"])

    def test_m3_overlapping_writer_waits_for_lock(self):
        first = dict(self.node, node_id="a", objective="Write docs/a.md",
                     write_scope=["docs/a.md"])
        second = dict(self.node, node_id="b", objective="Write docs folder",
                      write_scope=["docs/**"])
        plan = self.bridge.plan([first, second], "parent")
        self.assertEqual(plan["ready_nodes"], ["a"])
        started = self.bridge.before(plan["run_id"], "a", "alpha-trion",
                                     plan["nodes"][0]["card"], "call-a")
        self.assertEqual(self.bridge.state(plan["run_id"])["ready_nodes"], [])
        rejected = self.bridge.before(plan["run_id"], "b", "alpha-trion",
                                      plan["nodes"][1]["card"], "call-b", started["token"])
        self.assertTrue(rejected["rejected"])

    def test_m3_read_only_native_result_can_complete_without_artifact(self):
        read_node = {"node_id": "read", "kind": "task", "capability": "scan.static",
                     "role": "onyx-prime", "objective": "Inspect project",
                     "write_scope": [], "acceptance": ["report"], "verifiers": ["scope_guard"]}
        plan = self.bridge.plan(read_node, "parent")
        started = self.bridge.before(plan["run_id"], "read", "onyx-prime", plan["card"], "call-read")
        self.bridge.after(plan["run_id"], "call-read", started["token"], "child-read", "completed", 1)
        state = self.bridge.finish(plan["run_id"], started["token"], "child-read")
        self.assertEqual(state["status"], "completed")

    def test_m3_loop1_retries_then_escalates_repeated_failure(self):
        plan = self.bridge.plan(self.node, "parent")
        run_id = plan["run_id"]
        for attempt in (1, 2):
            started = self.bridge.before(run_id, "n1", "alpha-trion", plan["card"], f"call-{attempt}")
            self.bridge.after(run_id, f"call-{attempt}", started["token"],
                              f"child-{attempt}", "completed", 1)
            (self.root / "escape.txt").write_text("bad")
            state = self.bridge.finish(run_id, started["token"], f"child-{attempt}")
            self.assertFalse((self.root / "escape.txt").exists())
            self.assertIn("write_scope violation", state["repair_feedback"]["n1"])
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["ready_nodes"], [])
        self.assertEqual(sum(event["type"] == "node.retry" for event in self.bridge.events(run_id)), 1)
        self.assertEqual(sum(event["type"] == "loop2.escalated" for event in self.bridge.events(run_id)), 1)

    def test_m3_loop1_retry_can_repair_without_escalation(self):
        plan = self.bridge.plan(self.node, "parent")
        run_id = plan["run_id"]
        first = self.bridge.before(run_id, "n1", "alpha-trion", plan["card"], "call-1")
        self.bridge.after(run_id, "call-1", first["token"], "child-1", "completed", 1)
        state = self.bridge.finish(run_id, first["token"], "child-1")
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["ready_nodes"], ["n1"])
        self.assertEqual(state["repair_feedback"]["n1"], "no accepted artifact")
        self.assertEqual(sum(event["type"] == "node.blocked" for event in self.bridge.events(run_id)), 1)

        second = self.bridge.before(run_id, "n1", "alpha-trion", plan["card"], "call-2")
        self.bridge.after(run_id, "call-2", second["token"], "child-2", "completed", 1)
        (self.root / "notes.md").write_text("done")
        state = self.bridge.finish(run_id, second["token"], "child-2")
        self.assertEqual(state["status"], "completed")
        self.assertEqual((self.root / "notes.md").read_text(), "done")
        self.assertEqual(state["repair_feedback"], {})
        events = self.bridge.events(run_id)
        self.assertEqual(sum(event["type"] == "node.retry" for event in events), 1)
        self.assertEqual(sum(event["type"] == "loop2.escalated" for event in events), 0)
        self.assertEqual(sum(event["type"] == "dispatch.started" for event in events), 2)

    def test_m3_completed_peer_cannot_mask_later_out_of_scope_write(self):
        first = dict(self.node, node_id="b", objective="Write docs/b.md",
                     write_scope=["docs/b.md"])
        second = dict(self.node, node_id="a", objective="Write notes.md after b",
                      write_scope=["notes.md"], depends_on=["b"])
        plan = self.bridge.plan([first, second], "parent")
        run_id = plan["run_id"]
        started = self.bridge.before(run_id, "b", "alpha-trion", plan["nodes"][0]["card"], "call-b")
        self.bridge.after(run_id, "call-b", started["token"], "child-b", "completed", 1)
        (self.root / "docs").mkdir()
        (self.root / "docs/b.md").write_text("b")
        state = self.bridge.finish(run_id, started["token"], "child-b")
        self.assertEqual(state["status"], "ready")

        started = self.bridge.before(run_id, "a", "alpha-trion", plan["nodes"][1]["card"], "call-a")
        self.bridge.after(run_id, "call-a", started["token"], "child-a", "completed", 1)
        (self.root / "notes.md").write_text("ok")
        (self.root / "docs/b.md").write_text("bad")
        state = self.bridge.finish(run_id, started["token"], "child-a")
        self.assertEqual(state["status"], "ready")
        self.assertEqual((self.root / "docs/b.md").read_text(), "b")
        rejections = [event for event in self.bridge.events(run_id)
                      if event["type"] == "plan.op.rejected"
                      and event.get("reason") == "write_scope violation"]
        self.assertTrue(any("docs/b.md" in event["paths"] for event in rejections))

    def test_m3_l2_rejection_reruns_only_affected_subgraph(self):
        fix = dict(self.node, node_id="fix", objective="Write docs/fix.md",
                   write_scope=["docs/fix.md"])
        unrelated = dict(self.node, node_id="unrelated", objective="Write docs/other.md",
                         write_scope=["docs/other.md"])
        review = {"node_id": "review", "kind": "review", "capability": "review.l2",
                  "role": "liege-maximo", "objective": "Review fix", "depends_on": ["fix"],
                  "write_scope": [], "acceptance": ["no high findings"],
                  "verifiers": ["scope_guard"]}
        deliver = dict(self.node, node_id="deliver", objective="Write docs/deliver.md",
                       write_scope=["docs/deliver.md"], depends_on=["review"])
        plan = self.bridge.plan([fix, unrelated, review, deliver], "parent")
        run_id = plan["run_id"]
        (self.root / "docs").mkdir()

        def run_writer(node_id, call_id, content):
            card = next(item["card"] for item in self.bridge.state(run_id)["nodes"]
                        if item["node_id"] == node_id)
            started = self.bridge.before(run_id, node_id, "alpha-trion", card, call_id)
            self.bridge.after(run_id, call_id, started["token"], call_id + "-child", "completed", 1)
            (self.root / f"docs/{node_id if node_id != 'unrelated' else 'other'}.md").write_text(content)
            return self.bridge.finish(run_id, started["token"], call_id + "-child")

        run_writer("fix", "fix-1", "first")
        run_writer("unrelated", "other-1", "independent")
        review_card = next(item["card"] for item in self.bridge.state(run_id)["nodes"]
                           if item["node_id"] == "review")
        started = self.bridge.before(run_id, "review", "liege-maximo", review_card, "review-1")
        self.bridge.after(run_id, "review-1", started["token"], "review-child-1", "completed", 1)
        self.bridge.bind(run_id, "review-1", started["token"], "review-child-1", [])
        with self.assertRaises(HostBridgeError):
            self.bridge.review_reject(run_id, "review-1", started["token"],
                                      "review-child-1", "unrelated", "wrong producer")
        self.bridge.review_reject(run_id, "review-1", started["token"],
                                  "review-child-1", "fix", "L2 injected rejection")
        state = self.bridge.finish(run_id, started["token"], "review-child-1")
        statuses = {item["node_id"]: item["status"] for item in state["nodes"]}
        self.assertEqual(statuses, {"fix": "stale", "unrelated": "completed",
                                    "review": "stale", "deliver": "stale"})
        self.assertEqual(state["repair_feedback"], {"fix": "L2 injected rejection"})
        self.assertEqual(state["ready_nodes"], ["fix"])
        run_writer("fix", "fix-2", "repaired")
        started = self.bridge.before(run_id, "review", "liege-maximo", review_card, "review-2")
        self.bridge.after(run_id, "review-2", started["token"], "review-child-2", "completed", 1)
        state = self.bridge.finish(run_id, started["token"], "review-child-2")
        self.assertIn("deliver", state["ready_nodes"])
        self.assertEqual(sum(event["type"] == "dispatch.started" and event.get("node_id") == "unrelated"
                             for event in self.bridge.events(run_id)), 1)

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

    def test_read_only_scan_template_creates_unexecuted_read_only_run(self):
        command = [sys.executable, "-m", "cybertron.host_v6_cli", "plan",
                   "--project", str(self.root)]
        result = subprocess.run(command, input=json.dumps({
            "template": {"type": "read_only_scan", "objective": "List the temporary project layout"},
            "host_session_id": "parent",
        }), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["ready_nodes"], ["scan"])
        self.assertEqual(state["write_scope"], [])
        self.assertEqual(self.bridge.events(state["run_id"])[0]["type"], "plan.created")
        self.assertFalse(any(event["type"] == "dispatch.started"
                             for event in self.bridge.events(state["run_id"])))


if __name__ == "__main__":
    unittest.main()
