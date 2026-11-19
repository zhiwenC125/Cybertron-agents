import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from cybertron.graph import PlanNode
from cybertron.host_v6 import V6HostBridge
from cybertron.v6_cli import main


class V6CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        bridge = V6HostBridge(self.project)
        plan = bridge.plan(
            PlanNode("n1", "task", "doc.write", "alpha-trion", "write docs",
                     write_scope=("README.md",), acceptance=("docs",),
                     verifiers=("scope_guard",)).to_dict(),
            "host-session", objective="write docs",
            intent={"goal": "write docs", "confirmed": True,
                    "done": [{"id": "d1", "criterion": "docs", "evidence": "artifact"}]})
        self.run_id = plan["run_id"]
        self.slug = plan["slug"]

    def tearDown(self):
        self.temp.cleanup()

    def output(self, argv):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(argv + ["--project", str(self.project)])
        return code, buffer.getvalue()

    def test_runs_and_show(self):
        code, text = self.output(["runs"])
        self.assertEqual(code, 0)
        self.assertIn(self.slug, text)
        self.assertIn("0/1", text)

        code, text = self.output(["show", self.run_id])
        self.assertEqual(code, 0)
        self.assertIn("coverage: 0/1", text)
        self.assertIn("d1", text)

    def test_grants_and_lineage(self):
        bridge = V6HostBridge(self.project)
        request = bridge.grant_request(self.run_id, "n1", "write.expand")
        bridge.grant_approve(self.run_id, request["request_id"])
        code, text = self.output(["grants", self.run_id])
        self.assertEqual(code, 0)
        self.assertIn("write.expand", text)

        code, text = self.output(["lineage", self.run_id])
        self.assertEqual(code, 0)
        self.assertIn(self.slug, text)


if __name__ == "__main__":
    unittest.main()
