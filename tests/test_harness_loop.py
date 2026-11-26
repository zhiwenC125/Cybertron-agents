import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from cybertron.host_v6 import HostBridgeError, PlanValidationError, V6HostBridge


def node(node_id, capability, role, *, kind="task", **fields):
    return {"node_id": node_id, "kind": kind, "capability": capability, "role": role,
            "objective": node_id, "acceptance": ["Record the required evidence"],
            "write_scope": [], "verifiers": ["scope_guard"], **fields}


class HarnessLoopTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name).resolve()
        self.bridge = V6HostBridge(self.project)

    def dispatch(self, run_id, node_id, attempt=1):
        entry = next(n for n in self.bridge.state(run_id)["nodes"] if n["node_id"] == node_id)
        call, child = f"{node_id}-{attempt}", f"child-{node_id}-{attempt}"
        token = self.bridge.before(run_id, node_id, entry["role"], entry["card"], call)["token"]
        self.bridge.after(run_id, call, token, child, "completed", 1)
        self.bridge.bind(run_id, call, token, child, entry["write_scope"], entry["external_scope"])
        return call, child, token

    def finish(self, run_id, dispatch):
        call, child, token = dispatch
        return self.bridge.finish(run_id, token, child, call_id=call)

    def test_exact_content_settles_at_creation_without_dispatch(self):
        content = b"already delivered\n"
        (self.project / "notes.md").write_bytes(content)
        sha = hashlib.sha256(content).hexdigest()
        plan = self.bridge.plan(node("doc", "doc.write", "alpha-trion",
                                     write_scope=["notes.md"], expected_content_sha256=sha),
                                "planner-session", planned_verification=True)
        self.assertEqual(plan["status"], "completed")
        events = self.bridge.events(plan["run_id"])
        complete = next(e for e in events if e["type"] == "node.completed")
        self.assertEqual(complete["evidence"]["sha256"], sha)
        end = next(e for e in events if e["type"] == "run.completed")
        self.assertEqual((end["dispatch_count"], end["human_interventions"]), (0, 0))

    def test_submission_rejects_unusable_checks_and_protected_targets(self):
        test = node("test", "test.write", "alchemist", kind="verify", check_target="test")
        with self.assertRaises(PlanValidationError) as missing:
            self.bridge.plan(test, "planner", planned_verification=True)
        self.assertEqual(missing.exception.findings[0]["code"], "check.unavailable")
        scan = node("scan", "scan.static", "onyx-prime")
        with self.assertRaises(PlanValidationError) as unbound:
            self.bridge.plan(scan, "planner", planned_verification=True, gates=["test"])
        self.assertEqual(unbound.exception.findings[-1]["code"], "gate.unbound")
        with self.assertRaisesRegex(HostBridgeError, "read-only"):
            self.bridge.plan(node("doc", "doc.write", "alpha-trion", write_scope=["notes.md"]),
                             "planner", access_mode="read-only", planned_verification=True)
        with self.assertRaisesRegex(HostBridgeError, "protected|generated config"):
            self.bridge.plan(node("code", "code.write", "solus-prime",
                                  write_scope=["cybertron/registry.py"]),
                             "planner", access_mode="danger-full-access", planned_verification=True)

    def test_adaptive_admits_unavailable_check_but_reports_it_before_completion(self):
        write = node("write", "doc.write", "alpha-trion", write_scope=["notes.md"],
                     verifiers=["scope_guard", "build"])
        state = self.bridge.plan(write, "planner", adaptive_verification=True)
        self.assertEqual(state["ready_nodes"], ["write"])
        self.assertTrue(any(finding["code"] == "check.unavailable" and finding["severity"] == "warning"
                            for finding in state["review"]["findings"]))
        run_id = state["run_id"]
        dispatch = self.dispatch(run_id, "write")
        (self.project / "notes.md").write_text("Delivered.\n")
        self.finish(run_id, dispatch)
        state = self.bridge.verify_pending(run_id)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["pending_checks"][0]["status"], "unavailable")
        self.assertNotIn("run.completed", {event["type"] for event in self.bridge.events(run_id)})
        self.assertIn("unavailable", Path(state["plan_path"]).read_text())

    @unittest.skipUnless(shutil.which("sandbox-exec"), "requires macOS sandbox runner")
    @unittest.skipIf(os.environ.get("CYBERTRON_SANDBOX") == "1",
                     "nested sandbox-exec is unsupported")
    def test_adaptive_code_diff_runs_real_checks_and_preserves_independent_work(self):
        (self.project / "pyproject.toml").write_text('[project]\nname = "example"\n')
        (self.project / "src").mkdir()
        (self.project / "tests").mkdir()
        path = self.project / "src" / "value.py"
        path.write_text("VALUE = 1\n")
        (self.project / "tests" / "test_value.py").write_text(
            "import unittest\nfrom src.value import VALUE\n"
            "class Check(unittest.TestCase):\n"
            "    def test_value(self): self.assertEqual(VALUE, 3)\n"
        )
        fix = node("fix", "code.write", "solus-prime", write_scope=["src/value.py"])
        scan = node("scan", "scan.static", "onyx-prime")
        follow = node("follow", "scan.static", "onyx-prime", depends_on=["fix"])
        state = self.bridge.plan([fix, scan, follow], "planner", adaptive_verification=True)
        run_id = state["run_id"]
        dispatch = self.dispatch(run_id, "fix")
        path.write_text("VALUE = 2\n")
        state = self.finish(run_id, dispatch)
        self.assertEqual(state["pending_gates"], ["test"])
        state = self.bridge.verify_pending(run_id)
        self.assertEqual(state["ready_nodes"], ["scan"])
        self.assertEqual(state["pending_checks"][0]["status"], "fail")
        self.assertTrue(state["pending_checks"][0]["can_retry"])
        failed = next(e for e in self.bridge.events(run_id) if e["type"] == "gate.check")
        self.assertTrue(failed["inline"])
        self.assertEqual(failed["receipt"]["exit"], 1)
        self.finish(run_id, self.dispatch(run_id, "scan"))
        self.bridge.verify_pending(run_id)
        self.assertEqual(len([e for e in self.bridge.events(run_id) if e["type"] == "gate.check"]), 1)

        revised = self.bridge.plan_op(run_id, {
            "op": "revise", "op_id": "correct", "plan_revision": 0, "reason": "Wrong value",
            "nodes": [dict(fix, objective="Set the value to 3")],
        })
        self.assertEqual(revised["ready_nodes"], ["fix"])
        dispatch = self.dispatch(run_id, "fix", 2)
        path.write_text("VALUE = 3\n")
        self.finish(run_id, dispatch)
        self.assertEqual(self.bridge.verify_pending(run_id)["ready_nodes"], ["follow"])
        state = self.finish(run_id, self.dispatch(run_id, "follow"))
        self.assertEqual(state["status"], "completed")
        receipts = [e["receipt"]["exit"] for e in self.bridge.events(run_id) if e["type"] == "gate.check"]
        self.assertEqual(receipts, [1, 0])
        path.write_text("VALUE = 4\n")
        self.assertEqual(self.bridge.state(run_id)["status"], "completed")

    @unittest.skipUnless(shutil.which("sandbox-exec"), "requires macOS sandbox runner")
    @unittest.skipIf(os.environ.get("CYBERTRON_SANDBOX") == "1",
                     "nested sandbox-exec is unsupported")
    def test_adaptive_interface_requires_review_and_acceptance_after_real_test(self):
        (self.project / "pyproject.toml").write_text('[project]\nname = "example"\n')
        (self.project / "src").mkdir()
        (self.project / "tests").mkdir()
        path = self.project / "src" / "interfaces.py"
        path.write_text("VALUE = 1\n")
        (self.project / "tests" / "test_interface.py").write_text(
            "import unittest\nfrom src.interfaces import VALUE\n"
            "class Check(unittest.TestCase):\n"
            "    def test_value(self): self.assertEqual(VALUE, 2)\n"
        )
        fix = node("fix", "code.write", "solus-prime", write_scope=["src/interfaces.py"])
        state = self.bridge.plan(fix, "planner", adaptive_verification=True)
        run_id = state["run_id"]
        dispatch = self.dispatch(run_id, "fix")
        path.write_text("VALUE = 2\n")
        self.finish(run_id, dispatch)
        state = self.bridge.verify_pending(run_id)
        self.assertEqual(state["pending_gates"], ["accept", "review.l2.full"])
        self.assertEqual(state["status"], "blocked")
        review = node("review", "review.l2", "liege-maximo", kind="review", depends_on=["fix"])
        accept = node("accept", "accept", "megatronus", kind="verify", depends_on=["review"])
        state = self.bridge.plan_op(run_id, {"op": "revise", "op_id": "review-risk",
                                            "plan_revision": 0, "reason": "Interface diff",
                                            "nodes": [review, accept]})
        self.assertEqual(state["ready_nodes"], ["review"])
        dispatch = self.dispatch(run_id, "review")
        self.bridge.observe_review_read(run_id, dispatch[0], dispatch[1], str(path), "a" * 64)
        self.assertEqual(self.finish(run_id, dispatch)["ready_nodes"], ["accept"])
        dispatch = self.dispatch(run_id, "accept")
        self.bridge.verify_acceptance(run_id, dispatch[0], dispatch[1], True, "Verified interface.")
        self.assertEqual(self.finish(run_id, dispatch)["status"], "completed")

    @unittest.skipUnless(shutil.which("sandbox-exec"), "requires macOS sandbox runner")
    @unittest.skipIf(os.environ.get("CYBERTRON_SANDBOX") == "1",
                     "nested sandbox-exec is unsupported")
    def test_adaptive_waits_for_planned_test_author_and_runs_the_suite_once(self):
        (self.project / "pyproject.toml").write_text('[project]\nname = "example"\n')
        (self.project / "src").mkdir()
        (self.project / "tests").mkdir()
        fix = node("fix", "code.write", "solus-prime", write_scope=["src/value.py"])
        tests = node("write-tests", "test.write", "alchemist", depends_on=["fix"],
                     write_scope=["tests/test_value.py"])
        state = self.bridge.plan([fix, tests], "planner", adaptive_verification=True)
        run_id = state["run_id"]
        dispatch = self.dispatch(run_id, "fix")
        (self.project / "src" / "value.py").write_text("VALUE = 2\n")
        state = self.finish(run_id, dispatch)
        self.assertEqual(state["ready_nodes"], ["write-tests"])
        self.assertEqual(state["pending_checks"][0]["status"], "waiting_for_tests")
        self.bridge.verify_pending(run_id)
        self.assertEqual(self.bridge.metrics(run_id)["run"]["gate_checks"], 0)
        dispatch = self.dispatch(run_id, "write-tests")
        (self.project / "tests" / "test_value.py").write_text(
            "import unittest\nfrom src.value import VALUE\n"
            "class Check(unittest.TestCase):\n"
            "    def test_value(self): self.assertEqual(VALUE, 2)\n"
        )
        self.finish(run_id, dispatch)
        state = self.bridge.verify_pending(run_id)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(self.bridge.metrics(run_id)["run"]["gate_checks"], 1)

    @unittest.skipUnless(shutil.which("sandbox-exec"), "requires macOS sandbox runner")
    @unittest.skipIf(os.environ.get("CYBERTRON_SANDBOX") == "1",
                     "nested sandbox-exec is unsupported")
    def test_real_regression_revises_same_run_and_reuses_unrelated_receipt(self):
        (self.project / "pyproject.toml").write_text('[project]\nname = "example"\n')
        (self.project / "src").mkdir()
        (self.project / "tests").mkdir()
        code_path = self.project / "src" / "normal.py"
        code_path.write_text("def trim(value):\n    return value\n")
        (self.project / "tests" / "test_normal.py").write_text(
            'import unittest\nfrom src.normal import trim\n'
            'class Labels(unittest.TestCase):\n'
            '    def test_tabs(self): self.assertEqual(trim("\\tx "), "x")\n')
        scan = node("scan", "scan.static", "onyx-prime")
        fix = node("fix", "code.write", "solus-prime", write_scope=["src/normal.py"])
        check = node("check", "test.write", "alchemist", kind="verify", check_target="test",
                     depends_on=["fix"], satisfies=["regression"])
        accept = node("accept", "accept", "megatronus", kind="verify", depends_on=["check"])
        intent = {"goal": "trim whitespace", "done": [
            {"id": "regression", "criterion": "regression passes", "evidence": "test"}]}
        state = self.bridge.plan([scan, fix, check, accept], "prima-native",
                                 intent=intent, planned_verification=True)
        run_id = state["run_id"]
        revise = {"op": "revise", "op_id": "adjust", "plan_revision": 0, "reason": "tabs remain",
                  "nodes": [dict(fix, objective="strip every whitespace character")]}
        first_scan = self.dispatch(run_id, "scan")
        with self.assertRaisesRegex(HostBridgeError, "active dispatch"):
            self.bridge.plan_op(run_id, revise)
        self.finish(run_id, first_scan)
        first_fix = self.dispatch(run_id, "fix")
        code_path.write_text('def trim(value):\n    return value.strip(" ")\n')
        self.finish(run_id, first_fix)
        with self.assertRaisesRegex(HostBridgeError, "bound native"):
            self.bridge.check(run_id, "test", node_id="check")
        dispatch = self.dispatch(run_id, "check")
        fail = self.bridge.check(run_id, "test", dispatch[0], "check", dispatch[1])
        self.assertEqual(fail["receipts"][-1]["exit"], 1)
        state = self.finish(run_id, dispatch)
        self.assertEqual(state["next_actions"][0]["agent"], "thirteenth")
        self.assertIn("AssertionError", state["replan_feedback"][-1]["diagnostic"])
        self.assertIn('return value.strip(" ")', state["planning_context"]["diffs"][0]["diff"])
        self.bridge.planning_handoff(run_id, "prima-native")
        for operation, error in (
            (dict(revise, plan_revision=50), "stale plan_revision"),
            (dict(revise, nodes=[dict(fix, depends_on=["check"])]), "dependency cycle"),
            (dict(revise, nodes=[dict(fix, write_scope=["src/extra.py"])]), "exceeds the run's write scope"),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(HostBridgeError, error):
                self.bridge.plan_op(run_id, operation)
        revised = self.bridge.plan_op(run_id, revise, planner_session_id="thirteenth-native")
        self.assertEqual((revised["run_id"], revised["plan_revision"]), (run_id, 1))
        revision_event = next(e for e in self.bridge.events(run_id) if e["type"] == "plan.revised")
        self.assertEqual(revision_event["reused_nodes"], ["scan"])
        self.assertEqual(revision_event["invalidated_nodes"], ["accept", "check", "fix"])
        self.assertEqual(revised["ready_nodes"], ["fix"])
        with self.assertRaisesRegex(HostBridgeError, "stale plan_revision"):
            self.bridge.plan_op(run_id, dict(revise, op_id="stale"))
        second_fix = self.dispatch(run_id, "fix", 2)
        code_path.write_text("def trim(value):\n    return value.strip()\n")
        self.finish(run_id, second_fix)
        dispatch = self.dispatch(run_id, "check", 2)
        passed = self.bridge.check(run_id, "test", dispatch[0], "check", dispatch[1])
        self.assertEqual(passed["receipts"][-1]["exit"], 0)
        acceptance_ready = self.finish(run_id, dispatch)
        self.assertEqual(acceptance_ready["ready_nodes"], ["accept"])
        dispatch = self.dispatch(run_id, "accept")
        self.bridge.verify_acceptance(run_id, dispatch[0], dispatch[1], True, "Regression receipt passed")
        self.assertEqual(self.finish(run_id, dispatch)["status"], "completed")
        launches = [e["node_id"] for e in self.bridge.events(run_id) if e["type"] == "dispatch.started"]
        self.assertEqual(launches, ["scan", "fix", "check", "fix", "check", "accept"])
