"""Workspace-write nodes may declare external paths that need host approval."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from cybertron.graph import GraphRejected, PlanGraph, PlanNode
from cybertron.host_v6 import HostBridgeError, V6HostBridge


def node(**overrides):
    data = {"node_id": "n1", "kind": "task", "capability": "doc.write",
            "role": "alpha-trion", "objective": "Write the report",
            "write_scope": ["notes.md"], "acceptance": ["notes.md exists"],
            "verifiers": ["scope_guard"]}
    data.update(overrides)
    return data


class ExternalScopeGraphTests(unittest.TestCase):
    def test_workspace_write_accepts_literal_external_paths(self):
        graph = PlanGraph([PlanNode.from_dict(node(external_scope=["/tmp/report.md"]))])
        self.assertEqual(graph.nodes["n1"].external_scope, ("/tmp/report.md",))
        restored = PlanGraph.from_dict(graph.to_dict())
        self.assertEqual(restored.nodes["n1"].external_scope, ("/tmp/report.md",))

    def test_read_only_and_full_access_reject_external_scope(self):
        for mode in ("read-only", "danger-full-access"):
            with self.subTest(mode=mode):
                with self.assertRaises(GraphRejected):
                    PlanGraph([PlanNode.from_dict(node(external_scope=["/tmp/report.md"]))],
                              access_mode=mode)

    def test_external_scope_rejects_globs_relative_and_hard_denied_paths(self):
        for scope in ("../escape.md", "report.md", "/tmp/*.md", "~/.git/config",
                      "/tmp/../etc/passwd"):
            with self.subTest(scope=scope):
                with self.assertRaises(GraphRejected):
                    PlanGraph([PlanNode.from_dict(node(external_scope=[scope]))])


class ExternalScopeHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.external = tempfile.TemporaryDirectory()
        self.addCleanup(self.external.cleanup)
        self.root = Path(self.temp.name)
        self.outside = Path(self.external.name)
        self.target = (self.outside / "report.md").resolve()
        self.bridge = V6HostBridge(self.root)
        self.node = node(external_scope=[str(self.target)])

    def dispatch(self):
        plan = self.bridge.plan(self.node, "parent")
        started = self.bridge.before(plan["run_id"], "n1", "alpha-trion",
                                     plan["card"], "call1")
        returned = self.bridge.after(plan["run_id"], "call1", started["token"],
                                     "child-session", "completed", 120)
        return plan, started, returned

    def test_before_returns_resolved_external_scope(self):
        plan, started, _ = self.dispatch()
        self.assertEqual(started["external_scope"], [str(self.target)])
        self.assertIn("external:", plan["card"])
        state = self.bridge.state(plan["run_id"])
        self.assertEqual(state["nodes"][0]["external_scope"], [str(self.target)])

    def test_external_artifact_without_gate_fails_the_node(self):
        plan, _, returned = self.dispatch()
        self.target.write_text("outside")
        self.bridge.finish(plan["run_id"], returned["token"], "child-session")
        failed = [event for event in self.bridge.events(plan["run_id"])
                  if event["type"] == "node.failed"][0]
        self.assertIn("external write without host approval", failed["diagnostic"])

    def test_recorded_gate_completes_with_hashed_external_artifact(self):
        plan, _, returned = self.dispatch()
        (self.root / "notes.md").write_text("inside")
        self.target.write_text("outside")
        self.bridge.permission(plan["run_id"], "call1", "req-1", "edit", [str(self.target)])
        self.bridge.permission(plan["run_id"], "call1", "req-1", "edit", [str(self.target)],
                               reply="once")
        result = self.bridge.finish(plan["run_id"], returned["token"], "child-session")
        self.assertEqual(result["nodes"][0]["status"], "completed")
        completed = [event for event in self.bridge.events(plan["run_id"])
                     if event["type"] == "node.completed"][0]
        self.assertIn(str(self.target), completed["artifacts"])

    def test_rejected_external_permission_does_not_count_as_approval(self):
        plan, _, returned = self.dispatch()
        self.bridge.permission(plan["run_id"], "call1", "req-1", "edit", [str(self.target)])
        self.bridge.permission(plan["run_id"], "call1", "req-1", "edit", [str(self.target)],
                               reply="reject")
        self.target.write_text("unapproved")
        self.bridge.finish(plan["run_id"], returned["token"], "child-session")
        failures = [event for event in self.bridge.events(plan["run_id"])
                    if event["type"] == "node.failed"]
        self.assertEqual(len(failures), 1)
        self.assertIn("external write without host approval", failures[0]["diagnostic"])

    def test_standing_grant_completes_without_a_per_write_request(self):
        plan, _, returned = self.dispatch()
        self.target.write_text("outside")
        self.bridge.permission(plan["run_id"], "call1", "grant-1", "edit",
                               [str(self.target)], granted=True)
        result = self.bridge.finish(plan["run_id"], returned["token"], "child-session")
        self.assertEqual(result["nodes"][0]["status"], "completed")
        types = [event["type"] for event in self.bridge.events(plan["run_id"])]
        self.assertIn("permission.granted", types)
        self.assertNotIn("permission.requested", types)

    def test_dsh_run_hashes_external_artifacts_without_kernel_receipts(self):
        plan = self.bridge.plan(self.node, "parent", host="dsh")
        self.assertEqual(self.bridge.state(plan["run_id"])["host"], "dsh")
        started = self.bridge.before(plan["run_id"], "n1", "alpha-trion",
                                     plan["card"], "call1")
        returned = self.bridge.after(plan["run_id"], "call1", started["token"],
                                     "child-session", "completed", 120)
        self.target.write_text("outside")
        result = self.bridge.finish(plan["run_id"], returned["token"], "child-session")
        self.assertEqual(result["nodes"][0]["status"], "completed")
        completed = [event for event in self.bridge.events(plan["run_id"])
                     if event["type"] == "node.completed"][0]
        self.assertIn(str(self.target), completed["artifacts"])

    def test_unknown_host_is_rejected(self):
        with self.assertRaises(HostBridgeError):
            self.bridge.plan(self.node, "parent", host="other")

    def test_replies_are_recorded_and_evidence_level_is_explicit(self):
        plan, _, _ = self.dispatch()
        self.assertEqual(self.bridge.state(plan["run_id"])["evidence_level"], "kernel-receipt")
        self.bridge.permission(plan["run_id"], "call1", "req-1", "edit",
                               [str(self.target)], reply="once")
        resolved = [event for event in self.bridge.events(plan["run_id"])
                    if event["type"] == "permission.resolved"]
        self.assertEqual(resolved[0]["reply"], "once")
        dsh = self.bridge.plan(self.node, "parent", host="dsh")
        self.assertEqual(self.bridge.state(dsh["run_id"])["evidence_level"], "host-approved")

    def test_permission_requests_are_deduplicated(self):
        plan, _, _ = self.dispatch()
        for _ in range(3):
            self.bridge.permission(plan["run_id"], "call1", "req-1", "edit", [str(self.target)])
        requested = [event for event in self.bridge.events(plan["run_id"])
                     if event["type"] == "permission.requested"]
        self.assertEqual(len(requested), 1)

    def test_bind_rejects_a_different_external_scope(self):
        plan, started, returned = self.dispatch()
        with self.assertRaises(HostBridgeError):
            self.bridge.bind(plan["run_id"], "call1", started["token"], "child-session",
                             ["notes.md"], ["/tmp/other.md"])

    def test_exact_file_receipt_completes_without_project_code_gates(self):
        content = "approved\n"
        expected = hashlib.sha256(content.encode()).hexdigest()
        self.node = node(write_scope=[], external_scope=[str(self.target)],
                         expected_content_sha256=expected)
        plan, _, returned = self.dispatch()
        run_id = plan["run_id"]
        self.assertTrue(plan["review_current"])
        self.bridge.bind(run_id, "call1", returned["token"], "child-session", [],
                         [str(self.target)])
        args = (run_id, "call1", "write-1", str(self.target), expected)
        self.assertEqual(self.bridge.external_write(*args, "requested")["outcome"], "requested")
        self.assertEqual(self.bridge.external_write(*args, "requested")["outcome"], "approval_pending")
        self.bridge.external_write(*args, "approved")
        self.target.write_text(content)
        self.bridge.external_write(*args, "applied", changed_lines=1)
        final = self.bridge.finish(run_id, returned["token"], "child-session")
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["nodes"][0]["artifacts"], {str(self.target): expected})

    def test_rejected_file_stays_blocked_across_repeated_calls_and_supersede(self):
        expected = hashlib.sha256(b"declined").hexdigest()
        self.node = node(write_scope=[], external_scope=[str(self.target)])
        plan, _, returned = self.dispatch()
        run_id = plan["run_id"]
        self.bridge.bind(run_id, "call1", returned["token"], "child-session", [],
                         [str(self.target)])
        args = (run_id, "call1", "write-1", str(self.target), expected)
        self.bridge.external_write(*args, "requested")
        self.bridge.external_write(*args, "denied")
        final = self.bridge.finish(run_id, returned["token"], "child-session")
        self.assertEqual(final["ready_nodes"], [])
        self.assertEqual(final["external_stops"]["n1"]["outcome"], "denied")
        self.assertFalse(self.target.exists())
        replacement = self.bridge.plan(self.node, "next-parent", supersedes_run_id=run_id,
                                       change_reason="Test persisted rejection")
        replacement_id = replacement["run_id"]
        active = self.bridge.before(replacement_id, "n1", "alpha-trion", replacement["card"], "call2")
        result = self.bridge.after(replacement_id, "call2", active["token"], "child-two", "completed", 20)
        self.bridge.bind(replacement_id, "call2", result["token"], "child-two", [], [str(self.target)])
        self.assertEqual(self.bridge.external_write(replacement_id, "call2", "write-2",
                         str(self.target), expected, "inspect"), {"outcome": "denied"})

    def test_exact_document_with_existing_contents_needs_no_dispatch(self):
        content = b"already correct\n"
        target = self.bridge.project / "notes.md"
        target.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        plan = self.bridge.plan(node(expected_content_sha256=expected, satisfies=["file"]),
                                "parent", intent={"goal": "Ensure notes.md has the expected text",
                                "confirmed": False, "done": [{"id": "file",
                                "criterion": "File has the requested content", "evidence": "artifact"}]})
        self.assertEqual(plan["status"], "completed")
        self.assertEqual(plan["nodes"][0]["outcome"], "completed_without_change")
        self.assertEqual(plan["nodes"][0]["artifacts"], {str(target): expected})
        self.assertNotIn("dispatch.started", [event["type"] for event in self.bridge.events(plan["run_id"])])


if __name__ == "__main__":
    unittest.main()


class PlanSchemaTests(unittest.TestCase):
    def test_plugin_schema_exposes_external_scope(self):
        root = Path(__file__).resolve().parent.parent
        needle = "external_scope: { type: 'array', items: { type: 'string' } }"
        for relative in ("cybertron/v6_plugin/cybertron.js", "cybertron/payload/plugins/cybertron.js"):
            with self.subTest(path=relative):
                self.assertIn(needle, (root / relative).read_text())
