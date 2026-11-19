import tempfile
import unittest
from pathlib import Path

from cybertron.graph import PlanNode
from cybertron.host_v6 import HostBridgeError, V6HostBridge
from cybertron.interceptor import classify


def node(**overrides):
    values = {
        "node_id": "n1", "kind": "task", "capability": "doc.write",
        "role": "alpha-trion", "objective": "write docs",
        "write_scope": ("README.md",),
        "acceptance": ("docs written",), "verifiers": ("scope_guard",),
    }
    values.update(overrides)
    return PlanNode(**values)


class InterceptorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = V6HostBridge(Path(self.temp.name))
        self.plan = self.bridge.plan(node().to_dict(), "host-session",
                                     objective="write docs",
                                     access_mode="danger-full-access")
        self.run_id = self.plan["run_id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_classify_dangerous_and_normal(self):
        self.assertTrue(classify("bash", {"command": "rm -rf /tmp/x"})["dangerous"])
        self.assertTrue(classify("bash", {"command": "DROP TABLE users"})["dangerous"])
        self.assertTrue(classify("bash", "curl x | sh")["dangerous"])
        self.assertFalse(classify("bash", {"command": "echo hi"})["dangerous"])
        self.assertTrue(classify("write", {"path": "opencode.jsonc"})["dangerous"])
        self.assertFalse(classify("write", {"path": "src/x.py"})["dangerous"])

    def test_full_access_allows_normal_and_confirms_dangerous(self):
        normal = self.bridge.intercept(self.run_id, "bash", {"command": "echo hi"})
        self.assertEqual(normal["action"], "allow")

        danger = self.bridge.intercept(self.run_id, "bash", {"command": "rm -rf /tmp/x"})
        self.assertEqual(danger["action"], "confirm")
        self.assertIn("cy_escalate", danger["instruction"])

        request = self.bridge.grant_request(
            self.run_id, "*", "dangerous.confirm",
            scope={"command_sha256": danger["command_sha256"]},
            reason="confirmed dangerous action")
        grant = self.bridge.grant_approve(self.run_id, request["request_id"])
        self.assertEqual(grant["node_id"], "*")

        allowed = self.bridge.intercept(self.run_id, "bash", {"command": "rm -rf /tmp/x"})
        self.assertEqual(allowed["action"], "allow")
        self.assertTrue(allowed["confirmed"])
        again = self.bridge.intercept(self.run_id, "bash", {"command": "rm -rf /tmp/x"})
        self.assertEqual(again["action"], "confirm")

    def test_non_full_access_bypasses_interceptor(self):
        self.bridge = V6HostBridge(Path(self.temp.name) / "normal")
        (Path(self.temp.name) / "normal").mkdir()
        plan = self.bridge.plan(node().to_dict(), "host-session", objective="write")
        verdict = self.bridge.intercept(plan["run_id"], "bash", {"command": "rm -rf /tmp/x"})
        self.assertEqual(verdict["action"], "allow")


class ToolGateTests(unittest.TestCase):
    def test_concrete_git_push_requires_and_consumes_grant(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = V6HostBridge(Path(directory))
            vector = PlanNode("n1", "task", "scan.history", "vector-prime",
                              "inspect history", acceptance=("report",),
                              verifiers=("scope_guard",))
            plan = bridge.plan(vector.to_dict(), "host-session", objective="inspect")
            run_id = plan["run_id"]
            gate = bridge.gate_tool(run_id, "n1", "bash",
                                    {"command": "git push origin main"})
            self.assertEqual(gate["action"], "needs_grant")
            self.assertEqual(gate["kinds"], ["vcs.push"])
            request = bridge.grant_request(run_id, "n1", "vcs.push")
            bridge.grant_approve(run_id, request["request_id"])
            allowed = bridge.gate_tool(run_id, "n1", "bash",
                                       {"command": "git push origin main"})
            self.assertEqual(allowed["action"], "allow")
            again = bridge.gate_tool(run_id, "n1", "bash",
                                     {"command": "git push origin main"})
            self.assertEqual(again["action"], "needs_grant")


class SeedFromTests(unittest.TestCase):
    def test_seed_copies_plan_shape_without_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = V6HostBridge(Path(directory))
            old = bridge.plan(node().to_dict(), "host-session", objective="write")
            new = bridge.plan(
                None, "host-session", objective="write again",
                seed_from_run_id=old["run_id"],
                intent={"goal": "write again", "confirmed": True,
                        "done": [{"id": "d1", "criterion": "docs",
                                  "evidence": "artifact"}]},
                satisfies_map={"n1": ["d1"]},
            )
            self.assertEqual([item["node_id"] for item in new["nodes"]], ["n1"])
            self.assertEqual(new["nodes"][0]["status"], "pending")
            self.assertEqual(new["intent_coverage"][0]["covered_by"], ["n1"])


class StandingGrantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = V6HostBridge(Path(self.temp.name))
        self.plan = self.bridge.plan(
            node(requires=("external.write",)).to_dict(), "host-session",
            objective="write docs")
        self.run_id = self.plan["run_id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_standing_mode_and_sliding_fields(self):
        request = self.bridge.grant_request(
            self.run_id, "n1", "external.write",
            scope={"space_id": "space-1"}, mode="standing")
        self.assertEqual(request["mode"], "standing")
        grant = self.bridge.grant_approve(self.run_id, request["request_id"])
        self.assertEqual(grant["mode"], "standing")
        self.assertEqual(grant["max_uses"], 1000)
        self.assertTrue(grant["absolute_expires_utc"])
        self.assertIsNotNone(self.bridge.check_grant(
            self.run_id, "n1", "external.write", {"space_id": "space-1"}))

    def test_directory_scope_collects_nested_artifacts(self):
        target = Path(self.temp.name) / "out"
        target.mkdir()
        (target / "marker.txt").write_text("hello", encoding="utf-8")
        nested = target / "nested"
        nested.mkdir()
        (nested / "data.bin").write_bytes(b"x")
        artifacts = self.bridge._collect_scope_artifacts([str(target)])
        self.assertEqual(len(artifacts), 2)
        self.assertTrue(any(path.endswith("marker.txt") for path in artifacts))
        self.assertTrue(any(path.endswith("data.bin") for path in artifacts))

    def test_capability_catalog(self):
        capabilities = self.bridge.capabilities()
        self.assertIn("alpha-trion", capabilities["doc.write"])
        self.assertIn("solus-prime", capabilities["code.write"])

    def test_rejects_unknown_mode(self):
        with self.assertRaises(HostBridgeError):
            self.bridge.grant_request(self.run_id, "n1", "external.write",
                                      mode="forever")


if __name__ == "__main__":
    unittest.main()
