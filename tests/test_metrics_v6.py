import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cybertron.metrics import (
    MetricsError,
    collect,
    compare,
    main,
    render_panel,
    run_metrics,
    summarize,
)


def node(node_id: str, capability: str = "code.write") -> dict:
    return {"node_id": node_id, "kind": "task", "capability": capability,
            "role": "solus-prime", "objective": f"work {node_id}",
            "depends_on": [], "read_scope": [], "write_scope": ["src/**"],
            "acceptance": ["done"], "verifiers": ["scope_guard"],
            "budget": {"max_attempts": 2}, "status": "pending"}


def write_run(root: Path, run_id: str, nodes: list[dict], events: list[dict],
              *, schema_version: int = 2, gates: list[str] | None = None) -> Path:
    directory = root / run_id
    directory.mkdir(parents=True)
    plan = {"schema_version": schema_version, "plan_revision": 1, "nodes": nodes,
            "events": [], "applied_ops": {}, "gates": gates or [],
            "human_requests": [], "attempts": {}, "complete": False}
    (directory / "plan.json").write_text(json.dumps(plan))
    (directory / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n")
    return directory


def completed_events(*, template_id: str | None = None) -> list[dict]:
    return [
        {"type": "plan.created", "utc": "2026-11-16T00:00:00+00:00",
         "request_class": "bug-fix", "template_id": template_id},
        {"type": "dispatch.started", "utc": "2026-11-16T00:00:01+00:00", "node_id": "n1"},
        {"type": "node.completed", "utc": "2026-11-16T00:00:02+00:00", "node_id": "n1"},
        {"type": "dispatch.started", "utc": "2026-11-16T00:00:03+00:00", "node_id": "n2"},
        {"type": "node.completed", "utc": "2026-11-16T00:00:04+00:00", "node_id": "n2"},
        {"type": "dispatch.started", "utc": "2026-11-16T00:00:05+00:00", "node_id": "n3"},
        {"type": "node.failed", "utc": "2026-11-16T00:00:06+00:00", "node_id": "n3"},
        {"type": "node.retry", "utc": "2026-11-16T00:00:07+00:00", "node_id": "n3"},
        {"type": "dispatch.started", "utc": "2026-11-16T00:00:08+00:00", "node_id": "n3"},
        {"type": "node.completed", "utc": "2026-11-16T00:00:09+00:00", "node_id": "n3"},
        {"type": "dispatch.started", "utc": "2026-11-16T00:00:10+00:00", "node_id": "n4"},
        {"type": "human.requested", "utc": "2026-11-16T00:00:11+00:00", "question": "Which module?"},
        {"type": "node.completed", "utc": "2026-11-16T00:00:12+00:00", "node_id": "n4"},
        {"type": "gate.check", "utc": "2026-11-16T00:00:13+00:00", "gate": "lint", "status": "fail"},
        {"type": "gate.check", "utc": "2026-11-16T00:00:14+00:00", "gate": "lint", "status": "pass"},
    ]


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.runs = self.project / ".cybertron" / "runs"
        self.runs.mkdir(parents=True)

    def test_run_metrics_counts_dispatches_retries_and_interventions(self):
        write_run(self.runs, "run-a", [node("n1"), node("n2"), node("n3"), node("n4")],
                  completed_events())
        result = run_metrics(self.runs / "run-a")
        self.assertEqual(result["node_count"], 4)
        self.assertEqual(result["dispatch_count"], 5)
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["human_interventions"], 1)
        self.assertEqual(result["gate_checks"], 2)
        self.assertEqual(result["gate_failures"], 1)
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["first_pass"])
        self.assertAlmostEqual(result["duration_s"], 14.0, places=3)

    def test_pending_gate_marks_run_gated(self):
        write_run(self.runs, "run-b", [node("n1")],
                  [{"type": "plan.created", "utc": "2026-11-16T00:00:00+00:00"},
                   {"type": "dispatch.started", "utc": "2026-11-16T00:00:01+00:00", "node_id": "n1"},
                   {"type": "node.completed", "utc": "2026-11-16T00:00:02+00:00", "node_id": "n1"},
                   {"type": "gate.required", "utc": "2026-11-16T00:00:03+00:00",
                    "gates": ["lint", "test"], "risk": "low"}])
        result = run_metrics(self.runs / "run-b")
        self.assertEqual(result["status"], "gated")

    def test_legacy_schema_is_skipped_and_corruption_fails_closed(self):
        write_run(self.runs, "legacy", [node("step-1")], [], schema_version=1)
        write_run(self.runs, "run-a", [node("n1")], completed_events()[:3])
        self.assertEqual([run["run_id"] for run in collect(self.project)], ["run-a"])
        (self.runs / "run-a" / "events.jsonl").write_text("not json\n")
        with self.assertRaises(MetricsError):
            collect(self.project)

    def test_compare_reports_reductions_for_second_run(self):
        write_run(self.runs, "run-a", [node("n1"), node("n2"), node("n3"), node("n4")],
                  completed_events())
        write_run(self.runs, "run-b", [node("n1"), node("n2"), node("n3")],
                  [{"type": "plan.created", "utc": "2026-11-17T00:00:00+00:00",
                    "request_class": "bug-fix", "template_id": "bug-fix-12345678"},
                   {"type": "dispatch.started", "utc": "2026-11-17T00:00:01+00:00", "node_id": "n1"},
                   {"type": "node.completed", "utc": "2026-11-17T00:00:02+00:00", "node_id": "n1"},
                   {"type": "dispatch.started", "utc": "2026-11-17T00:00:03+00:00", "node_id": "n2"},
                   {"type": "node.completed", "utc": "2026-11-17T00:00:04+00:00", "node_id": "n2"},
                   {"type": "dispatch.started", "utc": "2026-11-17T00:00:05+00:00", "node_id": "n3"},
                   {"type": "node.completed", "utc": "2026-11-17T00:00:06+00:00", "node_id": "n3"}])
        runs = {run["run_id"]: run for run in collect(self.project)}
        delta = compare(runs["run-a"], runs["run-b"])
        self.assertTrue(delta["nodes_reduced"])
        self.assertTrue(delta["interventions_reduced"])
        self.assertEqual(delta["delta"]["node_count"], -1)
        self.assertEqual(delta["delta"]["human_interventions"], -1)
        summary = summarize(list(runs.values()))
        self.assertEqual(summary["runs"], 2)
        self.assertEqual(summary["completed"], 2)
        self.assertEqual(summary["template_runs"], 1)

    def test_panel_and_cli_render_ledger_rows(self):
        write_run(self.runs, "run-a", [node("n1")], completed_events()[:3])
        runs = collect(self.project)
        summary = summarize(runs)
        panel = render_panel(runs, summary, {"count": 0, "classes": {}})
        self.assertIn("| run-a |", panel)
        self.assertIn("runs: 1", panel)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--project", str(self.project), "--json"]), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["summary"]["runs"], 1)
        self.assertEqual(payload["runs"][0]["run_id"], "run-a")


if __name__ == "__main__":
    unittest.main()
