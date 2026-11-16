import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cybertron.host_v6 import HostBridgeError, V6HostBridge


class V6M5LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bridge = V6HostBridge(self.root)
        self.node = {"node_id": "n1", "kind": "task", "capability": "doc.write",
                     "role": "alpha-trion", "objective": "Write notes.md",
                     "write_scope": ["notes.md"], "acceptance": ["notes.md exists"],
                     "verifiers": ["scope_guard"]}

    def complete_run(self, request_class="doc-single") -> tuple[str, str]:
        plan = self.bridge.plan(self.node, "parent", request_class=request_class,
                                objective="Write notes.md")
        started = self.bridge.before(plan["run_id"], "n1", "alpha-trion", plan["card"], "call1")
        self.bridge.after(plan["run_id"], "call1", started["token"], "child-session", "completed", 10)
        (self.root / "notes.md").write_text("done\n")
        state = self.bridge.finish(plan["run_id"], started["token"], "child-session")
        self.assertEqual(state["status"], "completed")
        events = self.bridge.events(plan["run_id"])
        distilled = [event for event in events if event["type"] == "template.distilled"]
        self.assertEqual(len(distilled), 1, events)
        return plan["run_id"], distilled[0]["template_id"]

    def test_completed_run_distills_and_replays_without_revalidation_gaps(self):
        run_id, template_id = self.complete_run()
        events = self.bridge.events(run_id)
        self.assertIn("run.completed", [event["type"] for event in events])
        self.assertFalse([event for event in events if event["type"] == "template.distill_failed"])
        stored = self.bridge.templates()
        self.assertEqual(stored["summary"]["count"], 1)
        self.assertEqual(stored["templates"][0]["template_id"], template_id)
        replay = self.bridge.plan(None, "parent", template_id=template_id,
                                  objective="Write notes.md", write_scope=["notes.md"])
        self.assertTrue(replay["template_reused"])
        self.assertEqual(replay["request_class"], "doc-single")
        self.assertEqual(len(replay["nodes"]), 1)
        self.assertEqual(replay["ready_nodes"], ["n1"])
        self.assertEqual(replay["available_templates"][0]["template_id"], template_id)

    def test_template_replay_can_skip_read_only_discovery(self):
        self.node = {"node_id": "scan", "kind": "task", "capability": "scan.static",
                     "role": "onyx-prime", "objective": "Survey docs",
                     "acceptance": ["paths known"], "verifiers": ["scope_guard"]}
        write = {"node_id": "doc", "kind": "task", "capability": "doc.write",
                 "role": "alpha-trion", "objective": "Write docs/notes.md",
                 "depends_on": ["scan"], "write_scope": ["docs/notes.md"],
                 "acceptance": ["notes exists"], "verifiers": ["scope_guard"]}
        plan = self.bridge.plan([self.node, write], "parent", request_class="doc-scan",
                                objective="Write docs/notes.md")
        started = self.bridge.before(plan["run_id"], "scan", "onyx-prime",
                                     next(item["card"] for item in plan["nodes"]
                                          if item["node_id"] == "scan"), "call-scan")
        self.bridge.after(plan["run_id"], "call-scan", started["token"], "child-scan", "completed", 5)
        self.bridge.finish(plan["run_id"], started["token"], "child-scan")
        started = self.bridge.before(plan["run_id"], "doc", "alpha-trion",
                                     next(item["card"] for item in plan["nodes"]
                                          if item["node_id"] == "doc"), "call-doc")
        self.bridge.after(plan["run_id"], "call-doc", started["token"], "child-doc", "completed", 5)
        (self.root / "docs").mkdir(exist_ok=True)
        (self.root / "docs" / "notes.md").write_text("ok\n")
        self.bridge.finish(plan["run_id"], started["token"], "child-doc")
        template_id = next(event["template_id"] for event in self.bridge.events(plan["run_id"])
                           if event["type"] == "template.distilled")
        replay = self.bridge.plan(None, "parent", template_id=template_id,
                                  objective="Write docs/notes.md",
                                  write_scope=["docs/notes.md"], skip=["scan.static"])
        self.assertEqual(len(replay["nodes"]), 1)
        self.assertEqual(replay["nodes"][0]["node_id"], "doc")
        self.assertEqual(replay["ready_nodes"], ["doc"])
        self.assertEqual(replay["skipped_capabilities"], ["scan.static"])

    def test_tampered_template_is_rejected_at_plan_time(self):
        _, template_id = self.complete_run()
        path = self.root / ".cybertron" / "templates" / f"{template_id}.json"
        data = json.loads(path.read_text())
        data["nodes"][0]["role"] = "prima"
        path.write_text(json.dumps(data))
        with self.assertRaises(HostBridgeError):
            self.bridge.plan(None, "parent", template_id=template_id,
                             objective="Write notes.md", write_scope=["notes.md"])

    def test_failed_run_is_not_distilled(self):
        plan = self.bridge.plan(self.node, "parent", request_class="doc-single")
        started = self.bridge.before(plan["run_id"], "n1", "alpha-trion", plan["card"], "call1")
        self.bridge.after(plan["run_id"], "call1", started["token"], "child-session", "completed", 10)
        state = self.bridge.finish(plan["run_id"], started["token"], "child-session")
        self.assertEqual(state["status"], "ready")
        self.assertIn("n1", state["ready_nodes"])
        events = [event["type"] for event in self.bridge.events(plan["run_id"])]
        self.assertNotIn("template.distilled", events)
        self.assertNotIn("run.completed", events)

    def test_metrics_and_templates_are_available_through_cli(self):
        self.complete_run()
        for operation in ("templates", "metrics"):
            command = [sys.executable, "-m", "cybertron.host_v6_cli", operation,
                       "--project", str(self.root)]
            result = subprocess.run(command, input="{}", text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            parsed = json.loads(result.stdout)
            self.assertIn("templates" if operation == "templates" else "summary", parsed)
        metrics = self.bridge.metrics()
        self.assertEqual(metrics["summary"]["runs"], 1)
        self.assertEqual(metrics["runs"][0]["status"], "completed")
        self.assertEqual(metrics["runs"][0]["dispatch_count"], 1)
        self.assertEqual(metrics["templates"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
