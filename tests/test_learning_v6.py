import json
import tempfile
import unittest
from pathlib import Path

from cybertron.graph import PlanGraph, PlanNode
from cybertron.learning import (
    TemplateRejected,
    distill_template,
    instantiate,
    list_templates,
    load_template,
    match_template,
    plan_digest,
    save_template,
    validate_template,
)
from cybertron.templates import bug_fix_template


def completed_events() -> list[dict]:
    return [
        {"type": "plan.created", "utc": "2026-11-16T00:00:00+00:00", "request": "Fix parser null dereference"},
        {"type": "dispatch.started", "utc": "2026-11-16T00:00:01+00:00", "node_id": "scan-static", "call_id": "c1"},
        {"type": "node.completed", "utc": "2026-11-16T00:00:02+00:00", "node_id": "scan-static"},
        {"type": "dispatch.started", "utc": "2026-11-16T00:00:03+00:00", "node_id": "scan-history", "call_id": "c2"},
        {"type": "node.completed", "utc": "2026-11-16T00:00:04+00:00", "node_id": "scan-history"},
        {"type": "human.requested", "utc": "2026-11-16T00:00:05+00:00", "question": "Which parser?"},
        {"type": "dispatch.started", "utc": "2026-11-16T00:00:06+00:00", "node_id": "fix", "call_id": "c3"},
        {"type": "node.failed", "utc": "2026-11-16T00:00:07+00:00", "node_id": "fix",
         "failure_fingerprint": "f" * 64},
        {"type": "node.retry", "utc": "2026-11-16T00:00:08+00:00", "node_id": "fix"},
        {"type": "dispatch.started", "utc": "2026-11-16T00:00:09+00:00", "node_id": "fix", "call_id": "c4"},
        {"type": "node.completed", "utc": "2026-11-16T00:00:10+00:00", "node_id": "fix"},
        {"type": "dispatch.started", "utc": "2026-11-16T00:00:11+00:00", "node_id": "review", "call_id": "c5"},
        {"type": "node.completed", "utc": "2026-11-16T00:00:12+00:00", "node_id": "review"},
        {"type": "gate.check", "utc": "2026-11-16T00:00:13+00:00", "gate": "lint", "status": "fail"},
        {"type": "gate.check", "utc": "2026-11-16T00:00:14+00:00", "gate": "lint", "status": "pass"},
    ]


class TemplateDistillationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.graph = bug_fix_template("Fix parser null dereference", ("src/parser.py",))

    def distill(self) -> dict:
        return distill_template(self.graph, completed_events(),
                                completed_node_ids=self.graph.nodes,
                                request_class="bug-fix",
                                run_id="run-1",
                                request="Fix parser null dereference")

    def test_completed_run_distills_into_replayable_template(self):
        template = self.distill()
        self.assertEqual(template["metrics"]["node_count"], 4)
        self.assertEqual(template["learned"]["dispatch_count"], 5)
        self.assertEqual(template["learned"]["human_interventions"], 1)
        self.assertEqual(template["learned"]["retry_fingerprints"], ["f" * 64])
        self.assertEqual(template["learned"]["gate_failures"], 1)
        save_template(self.project, template)
        loaded = load_template(self.project, template["template_id"])
        self.assertEqual(loaded["source_plan_sha256"], plan_digest(self.graph))
        replay = instantiate(loaded, objective="Fix parser null dereference",
                             target_scope=("src/parser.py",))
        self.assertEqual(sorted(replay.nodes), sorted(self.graph.nodes))
        self.assertEqual([node.node_id for node in replay.nodes.values()][:2],
                         ["scan-static", "scan-history"])
        self.assertEqual(replay.nodes["fix"].objective, "Fix the root cause of: Fix parser null dereference")
        self.assertEqual(replay.nodes["fix"].write_scope, ("src/parser.py",))
        self.assertEqual(replay.nodes["scan-static"].write_scope, ())

    def test_objective_placeholder_replays_new_request(self):
        template = self.distill()
        replay = instantiate(template, objective="Fix tokenizer crash",
                             target_scope=("src/tokenizer.py",))
        self.assertIn("Fix tokenizer crash", replay.nodes["fix"].objective)
        self.assertNotIn("parser null dereference", replay.nodes["fix"].objective)

    def test_incomplete_run_is_not_distilled(self):
        with self.assertRaises(TemplateRejected):
            distill_template(self.graph, completed_events(),
                             completed_node_ids={"scan-static"},
                             request_class="bug-fix", run_id="run-1")

    def test_tampered_template_fails_validation(self):
        template = self.distill()
        tampered = json.loads(json.dumps(template))
        tampered["nodes"][2]["role"] = "prima"
        with self.assertRaises(TemplateRejected):
            validate_template(tampered)
        bad_slot = json.loads(json.dumps(template))
        bad_slot["nodes"][0]["scope_slot"] = "tests"
        with self.assertRaises(TemplateRejected):
            validate_template(bad_slot)
        unknown = json.loads(json.dumps(template))
        unknown["unexpected"] = True
        with self.assertRaises(TemplateRejected):
            validate_template(unknown)

    def test_skip_drops_read_only_discovery_and_rewires_dependencies(self):
        nodes = [
            PlanNode("scan", "task", "scan.static", "onyx-prime", "Survey the docs directory",
                     acceptance=("Paths known [review]",), verifiers=("scope_guard",)),
            PlanNode("doc", "task", "doc.write", "alpha-trion", "Write docs/notes.md",
                     depends_on=("scan",), write_scope=("docs/notes.md",),
                     acceptance=("exists",), verifiers=("scope_guard",)),
        ]
        graph = PlanGraph(nodes)
        template = distill_template(graph, completed_events(),
                                    completed_node_ids=graph.nodes,
                                    request_class="doc-scan", run_id="run-4",
                                    request="Write docs/notes.md")
        replay = instantiate(template, objective="Write docs/notes.md",
                             target_scope=("docs/notes.md",), skip=("scan.static",))
        self.assertEqual(list(replay.nodes), ["doc"])
        self.assertEqual(replay.nodes["doc"].depends_on, ())
        self.assertEqual([node.node_id for node in replay.ready_nodes()], ["doc"])
        with self.assertRaises(TemplateRejected):
            instantiate(template, objective="Write docs/notes.md",
                        target_scope=("docs/notes.md",), skip=("doc.write",))
        with self.assertRaises(TemplateRejected):
            instantiate(template, objective="Write docs/notes.md",
                        target_scope=("docs/notes.md",), skip=("scan.history",))

    def test_multi_writer_template_keeps_literal_paths(self):
        nodes = [
            PlanNode("spec", "task", "doc.write", "alpha-trion", "Write docs/spec.md",
                     write_scope=("docs/spec.md",), acceptance=("exists",),
                     verifiers=("scope_guard",)),
            PlanNode("notes", "task", "doc.write", "alpha-trion", "Write docs/notes.md",
                     write_scope=("docs/notes.md",), acceptance=("exists",),
                     verifiers=("scope_guard",)),
        ]
        graph = PlanGraph(nodes)
        template = distill_template(graph, completed_events(),
                                    completed_node_ids=graph.nodes,
                                    request_class="doc-pair", run_id="run-3",
                                    request="Write two docs")
        self.assertEqual({node["scope_slot"] for node in template["nodes"]}, {"literal"})
        replay = instantiate(template, objective="Write two docs again")
        self.assertEqual(replay.nodes["spec"].write_scope, ("docs/spec.md",))
        self.assertEqual(replay.nodes["notes"].write_scope, ("docs/notes.md",))
        with self.assertRaises(TemplateRejected):
            instantiate(template, objective="Write two docs again", target_scope=("docs/other.md",))

    def test_replay_without_required_scope_is_rejected(self):
        template = self.distill()
        with self.assertRaises(TemplateRejected):
            instantiate(template, objective="Fix parser null dereference")

    def test_replay_that_exceeds_role_roots_is_rejected(self):
        template = self.distill()
        with self.assertRaises(TemplateRejected):
            instantiate(template, objective="Fix parser null dereference",
                        target_scope=("tests/parser.py",))

    def test_template_storage_rejects_tampering_and_symlink(self):
        template = self.distill()
        path = save_template(self.project, template)
        rewritten = json.loads(path.read_text())
        rewritten["nodes"][2]["capability"] = "review.l2"
        path.write_text(json.dumps(rewritten))
        with self.assertRaises(TemplateRejected):
            load_template(self.project, template["template_id"])
        path.unlink()
        path.symlink_to(Path(self.temp.name) / "outside.json")
        with self.assertRaises(TemplateRejected):
            load_template(self.project, template["template_id"])

    def test_duplicate_template_id_with_different_content_is_rejected(self):
        template = self.distill()
        save_template(self.project, template)
        changed = json.loads(json.dumps(template))
        changed["metrics"]["node_count"] = 99
        with self.assertRaises(TemplateRejected):
            save_template(self.project, changed)
        save_template(self.project, template)

    def test_match_template_prefers_fewer_nodes(self):
        small = self.distill()
        save_template(self.project, small)
        extra = PlanNode("extra-scan", "task", "scan.static", "onyx-prime",
                         "Extra static pass", acceptance=("Coordinates [review]",),
                         verifiers=("scope_guard",))
        larger_graph = PlanGraph(list(bug_fix_template(
            "Fix parser null dereference", ("src/parser.py",)).nodes.values()) + [extra])
        big = distill_template(larger_graph, completed_events(),
                               completed_node_ids=larger_graph.nodes,
                               request_class="bug-fix", run_id="run-2",
                               request="Fix parser null dereference")
        big["template_id"] = "bug-fix-nine"
        save_template(self.project, big)
        chosen = match_template(self.project, "bug-fix")
        self.assertEqual(chosen["template_id"], small["template_id"])
        self.assertIsNone(match_template(self.project, "feature"))
        self.assertEqual(len(list_templates(self.project)), 2)

    def test_auto_class_is_derived_from_capabilities(self):
        template = distill_template(self.graph, completed_events(),
                                    completed_node_ids=self.graph.nodes,
                                    request_class="auto:code.write+review.l2+scan.history+scan.static",
                                    run_id="run-2")
        self.assertTrue(template["request_class"].startswith("auto:"))
        self.assertTrue(template["template_id"].startswith("auto-"))


if __name__ == "__main__":
    unittest.main()
