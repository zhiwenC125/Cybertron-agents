import json
import tempfile
import unittest
from pathlib import Path

from cybertron.graph import GraphRejected, PlanGraph, PlanNode
from cybertron.host_v6 import V6HostBridge
from cybertron.intent import Intent, IntentRejected, coverage


def node(satisfies=("d1",), *, capability="doc.write", role="alpha-trion",
         write_scope=("README.md",), node_id="n1"):
    return PlanNode(
        node_id, "task", capability, role, "update README",
        write_scope=write_scope,
        acceptance=("acceptance recorded",),
        verifiers=("scope_guard",),
        satisfies=satisfies,
    )


def intent(**overrides):
    payload = {
        "goal": "update README",
        "source": "chat",
        "confirmed": True,
        "done": [{"id": "d1", "criterion": "README updated", "evidence": "artifact"}],
    }
    payload.update(overrides)
    return payload


class IntentModelTests(unittest.TestCase):
    def test_roundtrip_and_defaults(self):
        parsed = Intent.from_dict({
            "goal": "fix login",
            "done": [{"id": "d1", "criterion": "regression passes", "evidence": "test"}],
        })
        self.assertFalse(parsed.confirmed)
        self.assertEqual(parsed.done_ids, frozenset({"d1"}))
        self.assertEqual(Intent.from_dict(parsed.to_dict()), parsed)

    def test_rejects_duplicate_ids_and_unknown_evidence(self):
        with self.assertRaises(IntentRejected):
            Intent.from_dict({"goal": "x", "done": [
                {"id": "d1", "criterion": "a"},
                {"id": "d1", "criterion": "b"},
            ]})
        with self.assertRaises(IntentRejected):
            Intent.from_dict({"goal": "x", "done": [
                {"id": "d1", "criterion": "a", "evidence": "model-text"},
            ]})
        with self.assertRaises(IntentRejected):
            Intent.from_dict({"goal": "", "done": [{"id": "d1", "criterion": "a"}]})
        with self.assertRaises(IntentRejected):
            Intent.from_dict({"goal": "x", "done": [], "unknown": True})


class PlanIntentTests(unittest.TestCase):
    def test_intent_roundtrip_and_satisfies(self):
        graph = PlanGraph([node()], intent=Intent.from_dict(intent()))
        restored = PlanGraph.from_dict(graph.to_dict())
        self.assertEqual(restored.intent.done_ids, frozenset({"d1"}))
        self.assertEqual(restored.nodes["n1"].satisfies, ("d1",))

    def test_satisfies_requires_intent_and_known_id(self):
        with self.assertRaises(GraphRejected):
            PlanGraph([node()])
        with self.assertRaises(GraphRejected):
            PlanGraph([node(satisfies=("missing",))],
                      intent=Intent.from_dict(intent()))

    def test_apply_op_keeps_intent(self):
        graph = PlanGraph([node()], intent=Intent.from_dict(intent()))
        operation = {
            "op_id": "add-2", "plan_revision": 0, "op": "add_node",
            "node": PlanNode("n2", "task", "doc.write", "alpha-trion", "more",
                             depends_on=("n1",), write_scope=("docs/x.md",),
                             acceptance=("done",), verifiers=("scope_guard",),
                             satisfies=("d1",)).to_dict(),
        }
        graph.apply_op(operation)
        self.assertEqual(graph.to_dict()["intent"]["goal"], "update README")
        self.assertEqual(graph.nodes["n2"].satisfies, ("d1",))


class HostIntentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = V6HostBridge(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def create(self, intent_payload=None, nodes=None):
        if intent_payload is None:
            intent_payload = intent()
        nodes = nodes or [node().to_dict()]
        return self.bridge.plan(nodes, "host-session", objective="update README",
                                intent=intent_payload)

    def test_review_blocks_uncovered_done(self):
        result = self.create(intent(done=[
            {"id": "d1", "criterion": "README updated", "evidence": "artifact"},
            {"id": "d2", "criterion": "test passes", "evidence": "test"},
        ]))
        review = self.bridge.review_plan(result["run_id"])
        self.assertFalse(review["approved"])
        self.assertIn("intent.done.uncovered", [item["code"] for item in review["blocking"]])

    def test_review_blocks_forbidden_capability_and_path(self):
        by_capability = self.create(intent(forbidden_capabilities=["doc.write"]))
        review = self.bridge.review_plan(by_capability["run_id"])
        self.assertIn("intent.capability", [item["code"] for item in review["blocking"]])

        self.bridge = V6HostBridge(Path(self.temp.name) / "second")
        self.bridge._dir if False else None
        (Path(self.temp.name) / "second").mkdir()
        self.bridge = V6HostBridge(Path(self.temp.name) / "second")
        by_path = self.create(intent(forbidden_paths=["README.md"]))
        review = self.bridge.review_plan(by_path["run_id"])
        self.assertIn("intent.path", [item["code"] for item in review["blocking"]])

    def test_unconfirmed_intent_is_rejected_at_creation(self):
        with self.assertRaises(Exception):
            self.create(intent(confirmed=False))

    def test_completion_requires_artifact_evidence(self):
        result = self.create()
        run_id = result["run_id"]
        self.bridge._append(run_id, "node.completed", node_id="n1",
                            artifacts={"README.md": "sha"}, evidence={"source": "host"})
        state = self.bridge.state(run_id)
        self.assertEqual(state["status"], "completed")
        self.assertTrue(all(item["satisfied"] for item in state["intent_coverage"]))

    def test_completion_blocks_when_test_evidence_missing(self):
        result = self.create(intent(done=[
            {"id": "d1", "criterion": "test passes", "evidence": "test"},
        ]))
        run_id = result["run_id"]
        self.bridge._append(run_id, "node.completed", node_id="n1",
                            artifacts={"README.md": "sha"}, evidence={"source": "host"})
        state = self.bridge.state(run_id)
        self.assertEqual(state["status"], "blocked")
        self.assertIn("d1", " ".join(state["intent_blockers"]))
        self.bridge._maybe_complete(run_id)
        events = self.bridge.events(run_id)
        self.assertTrue(any(event["type"] == "intent.unmet" for event in events))

        digest = self.bridge._workspace_digest()
        self.bridge._append(run_id, "gate.check", gate="test", status="pass",
                            node_id="n1", workspace_sha256=digest,
                            receipt={"command": "pytest"})
        state = self.bridge.state(run_id)
        self.assertEqual(state["status"], "completed")

    def test_test_gate_is_bound_to_covering_node(self):
        second = PlanNode(
            "n2", "task", "code.write", "solus-prime", "write code",
            write_scope=("src/x.py",), acceptance=("code written",),
            verifiers=("scope_guard",),
        )
        result = self.create(
            intent(done=[{"id": "d1", "criterion": "test passes", "evidence": "test"}]),
            nodes=[node().to_dict(), second.to_dict()],
        )
        run_id = result["run_id"]
        self.bridge._append(run_id, "node.completed", node_id="n1",
                            artifacts={"README.md": "sha"}, evidence={"source": "host"})
        self.bridge._append(run_id, "node.completed", node_id="n2",
                            artifacts={"src/x.py": "sha"}, evidence={"source": "host"})
        digest = self.bridge._workspace_digest()
        self.bridge._append(run_id, "gate.check", gate="test", status="pass",
                            node_id="n2", workspace_sha256=digest,
                            receipt={"command": "pytest"})
        state = self.bridge.state(run_id)
        self.assertEqual(state["status"], "blocked")
        self.assertFalse(state["intent_coverage"][0]["satisfied"])

        self.bridge._append(run_id, "gate.check", gate="test", status="pass",
                            node_id="n1", workspace_sha256=digest,
                            receipt={"command": "pytest"})
        state = self.bridge.state(run_id)
        self.assertEqual(state["status"], "completed")
        self.assertTrue(state["intent_coverage"][0]["satisfied"])

    def test_satisfies_map_assigns_nodes_without_node_level_satisfies(self):
        result = self.bridge.plan(
            node(satisfies=()).to_dict(), "host-session", objective="update README",
            intent=intent(), satisfies_map={"n1": ["d1"]},
        )
        self.assertEqual(result["intent_coverage"][0]["covered_by"], ["n1"])
        self.assertFalse(result["intent_coverage"][0]["satisfied"])

        with self.assertRaises(Exception):
            self.bridge.plan(
                node(satisfies=()).to_dict(), "host-session", objective="update README",
                intent=intent(), satisfies_map={"missing": ["d1"]},
            )

    def test_supersede_links_and_terminates_old(self):
        old = self.create()
        new = self.bridge.plan(
            node().to_dict(), "host-session", objective="update README again",
            intent=intent(done=[{"id": "d1", "criterion": "README updated",
                                 "evidence": "artifact"}]),
            parent_run_id=old["run_id"], supersedes_run_id=old["run_id"],
            change_reason="user clarified the acceptance wording",
        )
        old_state = self.bridge.state(old["run_id"])
        self.assertEqual(old_state["status"], "superseded")
        self.assertEqual(old_state["superseded_by"], new["run_id"])
        self.assertEqual(new["parent_run_id"], old["run_id"])
        self.assertEqual(new["change_reason"], "user clarified the acceptance wording")
        self.assertTrue(any(event["type"] == "run.superseded"
                            for event in self.bridge.events(old["run_id"])))

    def test_cannot_supersede_active_run(self):
        result = self.create()
        run_id = result["run_id"]
        self.bridge._append(run_id, "dispatch.started", node_id="n1",
                            call_id="call-1", role="alpha-trion", card="[n1] doc.write",
                            write_scope=["README.md"])
        with self.assertRaises(Exception):
            self.bridge.plan(node().to_dict(), "host-session", objective="again",
                             intent=intent(), parent_run_id=run_id,
                             supersedes_run_id=run_id,
                             change_reason="clarified")

    def test_running_single_node_is_not_downgraded_to_blocked(self):
        result = self.create()
        run_id = result["run_id"]
        self.bridge._append(run_id, "dispatch.started", node_id="n1",
                            call_id="call-1", role="alpha-trion",
                            card=self.bridge._card(node()),
                            write_scope=["README.md"])
        state = self.bridge.state(run_id)
        self.assertEqual(state["status"], "running")
        self.assertTrue(state["active_dispatches"])

    def test_plan_without_intent_keeps_legacy_completion(self):
        result = self.bridge.plan(node(satisfies=()).to_dict(), "host-session",
                                  objective="update README")
        run_id = result["run_id"]
        self.bridge._append(run_id, "node.completed", node_id="n1",
                            artifacts={"README.md": "sha"}, evidence={"source": "host"})
        state = self.bridge.state(run_id)
        self.assertEqual(state["status"], "completed")
        self.assertIsNone(state["intent"])
        self.assertEqual(state["intent_coverage"], [])

    def test_invalid_intent_is_rejected_at_plan(self):
        with self.assertRaises(Exception):
            self.create({"goal": "x", "done": []})


if __name__ == "__main__":
    unittest.main()


class PluginSchemaTests(unittest.TestCase):
    def test_plugin_schema_exposes_intent_and_satisfies(self):
        root = Path(__file__).resolve().parent.parent
        for relative in ("cybertron/v6_plugin/cybertron.js",
                         ".opencode/plugins/cybertron.js",
                         "cybertron/payload/plugins/cybertron.js"):
            with self.subTest(path=relative):
                text = (root / relative).read_text()
                self.assertIn("satisfies: { type: 'array'", text)
                self.assertIn("intent: { type: 'object'", text)
                self.assertIn("new_run: { type: 'boolean' }", text)
                self.assertIn("satisfies: { type: 'object'", text)
