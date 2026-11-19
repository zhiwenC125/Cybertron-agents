import tempfile
import unittest
from pathlib import Path

from cybertron.graph import PlanNode
from cybertron.host_v6 import HostBridgeError, V6HostBridge


def node(**overrides):
    values = {
        "node_id": "n1", "kind": "task", "capability": "doc.write",
        "role": "alpha-trion", "objective": "write docs",
        "write_scope": ("README.md",),
        "acceptance": ("docs written",), "verifiers": ("scope_guard",),
        "requires": ("write.expand",),
    }
    values.update(overrides)
    return PlanNode(**values)


class GrantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = V6HostBridge(Path(self.temp.name))
        self.plan = self.bridge.plan(node().to_dict(), "host-session",
                                     objective="write docs")
        self.run_id = self.plan["run_id"]

    def tearDown(self):
        self.temp.cleanup()

    def request(self, **overrides):
        payload = {"run_id": self.run_id, "node_id": "n1", "kind": "write.expand",
                   "scope": {"paths": ["/tmp/out.md"]}, "reason": "outside write"}
        payload.update(overrides)
        return self.bridge.grant_request(**payload)

    def test_before_requires_a_grant(self):
        result = self.bridge.before(self.run_id, "n1", "alpha-trion",
                                    self.bridge._card(node()), "call-1")
        self.assertTrue(result["rejected"])
        self.assertEqual(result["needs_grant"], ["write.expand"])

    def test_only_human_can_approve_and_grant_is_single_use(self):
        request = self.request()
        with self.assertRaises(HostBridgeError):
            self.bridge.grant_approve(self.run_id, request["request_id"],
                                      approver="model")
        grant = self.bridge.grant_approve(self.run_id, request["request_id"])
        self.assertEqual(grant["status"], "active")
        self.assertEqual(grant["issued_by"], "human")
        self.assertTrue(grant["binding_sha256"])

        first = self.bridge.before(self.run_id, "n1", "alpha-trion",
                                   self.bridge._card(node()), "call-1")
        self.assertNotIn("rejected", first)
        self.assertIsNone(self.bridge.check_grant(
            self.run_id, "n1", "write.expand", {"paths": ["/tmp/out.md"]}))

    def test_scope_mismatch_and_revoke(self):
        request = self.request(scope={"paths": ["/tmp/out.md"]})
        grant = self.bridge.grant_approve(self.run_id, request["request_id"])
        self.assertIsNotNone(self.bridge.check_grant(
            self.run_id, "n1", "write.expand", {"paths": ["/tmp/out.md"]}))
        self.assertIsNone(self.bridge.check_grant(
            self.run_id, "n1", "write.expand", {"paths": ["/tmp/other.md"]}))
        self.bridge.grant_revoke(self.run_id, grant["grant_id"], "not needed")
        self.assertIsNone(self.bridge.check_grant(
            self.run_id, "n1", "write.expand", {"paths": ["/tmp/out.md"]}))

    def test_deny_and_pending_state(self):
        request = self.request()
        self.bridge.grant_deny(self.run_id, request["request_id"], "no")
        grants = self.bridge.grants(self.run_id)
        self.assertTrue(any(item.get("status") == "denied" for item in grants))
        with self.assertRaises(HostBridgeError):
            self.bridge.grant_approve(self.run_id, request["request_id"])

    def test_unknown_kind_and_node_are_rejected(self):
        with self.assertRaises(HostBridgeError):
            self.request(kind="root")
        with self.assertRaises(HostBridgeError):
            self.request(node_id="missing")

    def test_state_exposes_grants(self):
        self.request()
        state = self.bridge.state(self.run_id)
        self.assertTrue(state["grants"])
        self.assertEqual(state["grants"][0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
