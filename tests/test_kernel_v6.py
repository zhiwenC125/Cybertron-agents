import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cybertron.graph import PlanGraph, PlanNode
from cybertron.kernel import DispatchOutcome, SingleNodeKernel


class KernelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        node = PlanNode("n1", "task", "doc.write", "alpha-trion", "Write notes",
                        write_scope=("notes.md",), acceptance=("notes exists",),
                        verifiers=("scope_guard",))
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_text(json.dumps(PlanGraph([node]).to_dict()))

    def _subprocess_dispatch(self, code):
        def dispatch(node, context):
            self.assertEqual(node.node_id, "n1")
            self.assertIn("notes.md", context.read_text())
            command = [sys.executable, "-c", code]
            result = subprocess.run(command, cwd=self.root, capture_output=True)
            return DispatchOutcome(command=" ".join(command[:2]), exit_code=result.returncode,
                                   output=result.stdout + result.stderr, source="tool")
        return dispatch

    def test_real_subprocess_dispatch_completes_and_records_events(self):
        dispatch = self._subprocess_dispatch("from pathlib import Path; Path('notes.md').write_text('done')")
        result = SingleNodeKernel(self.root, self.plan_path, "run1").run(dispatch)
        self.assertEqual(result.status, "completed")
        self.assertEqual((self.root / "notes.md").read_text(), "done")
        events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
        self.assertEqual([e["type"] for e in events], ["dispatch.started", "node.completed"])
        self.assertEqual(events[-1]["evidence"]["source"], "tool")
        self.assertEqual(len(events[-1]["evidence"]["sha256"]), 64)
        self.assertEqual(events[-1]["artifacts"]["notes.md"], hashlib.sha256(b"done").hexdigest())

    def test_out_of_scope_write_is_rolled_back_and_node_fails(self):
        dispatch = self._subprocess_dispatch("from pathlib import Path; Path('notes.md').write_text('done'); Path('escape.txt').write_text('bad')")
        result = SingleNodeKernel(self.root, self.plan_path, "run2").run(dispatch)
        self.assertEqual(result.status, "failed")
        self.assertFalse((self.root / "escape.txt").exists())
        self.assertEqual((self.root / "notes.md").read_text(), "done")
        events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
        self.assertIn("plan.op.rejected", [event["type"] for event in events])

    def test_claim_without_real_change_cannot_complete(self):
        result = SingleNodeKernel(self.root, self.plan_path, "run3").run(
            lambda node, context: DispatchOutcome(command="claimed success", exit_code=0,
                                                  output=b"I wrote notes.md", source="tool"))
        self.assertEqual(result.status, "blocked")

    def test_model_source_cannot_complete_even_with_artifact(self):
        def dispatch(node, context):
            (self.root / "notes.md").write_text("done")
            return DispatchOutcome(command="model claim", exit_code=0, output=b"done", source="model")
        result = SingleNodeKernel(self.root, self.plan_path, "run_model").run(dispatch)
        self.assertEqual(result.status, "blocked")

    def test_dispatch_cannot_tamper_with_run_events(self):
        def dispatch(node, context):
            (self.root / "notes.md").write_text("done")
            context.with_name("events.jsonl").write_text("forged\n")
            return DispatchOutcome(command="host tool", exit_code=0, output=b"done", source="tool")
        result = SingleNodeKernel(self.root, self.plan_path, "run_tamper").run(dispatch)
        self.assertEqual(result.status, "failed")
        events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
        self.assertEqual([e["type"] for e in events],
                         ["dispatch.started", "plan.op.rejected", "node.failed"])

    def test_multiple_nodes_are_rejected_before_dispatch(self):
        graph = PlanGraph.from_dict(json.loads(self.plan_path.read_text()))
        graph.apply_op({"op_id": "n2", "plan_revision": 0, "op": "add_node",
                        "node": PlanNode("n2", "task", "doc.write", "alpha-trion", "Other", write_scope=("other.md",)).to_dict()})
        self.plan_path.write_text(json.dumps(graph.to_dict()))
        with self.assertRaises(ValueError):
            SingleNodeKernel(self.root, self.plan_path, "run4").run(lambda *_: self.fail("dispatched"))

    def test_symlinked_run_storage_is_rejected_before_dispatch(self):
        external = self.root / "external"
        external.mkdir()
        (self.root / ".cybertron").symlink_to(external, target_is_directory=True)
        with self.assertRaises(ValueError):
            SingleNodeKernel(self.root, self.plan_path, "run5").run(lambda *_: self.fail("dispatched"))


if __name__ == "__main__":
    unittest.main()
