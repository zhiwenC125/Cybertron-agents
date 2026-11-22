"""M5 metrics panel derived from the run event ledger.

The panel is a *ledger projection*: it reports what a run recorded, not what
the current workspace would validate now. Live gate validity stays with the
host bridge, which re-checks workspace digests. A legacy or incomplete run is
skipped (or reported) rather than guessed at.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .learning import TemplateRejected, list_templates


class MetricsError(ValueError):
    """A run ledger is corrupt or has an unsupported schema."""


def _events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if path.is_symlink() or not path.is_file():
        raise MetricsError("event log is missing or unsafe")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MetricsError("event log is unreadable") from exc
    events = []
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise MetricsError("event log is corrupt") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise MetricsError("event log is corrupt")
        events.append(event)
    return events


def _plan(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "plan.json"
    if path.is_symlink() or not path.is_file():
        raise MetricsError("plan is missing or unsafe")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MetricsError("plan is corrupt") from exc
    if plan.get("schema_version") != 2 or not isinstance(plan.get("nodes"), list):
        raise MetricsError("unsupported plan schema")
    return plan


def _first(events: Sequence[Mapping[str, Any]], kind: str) -> Mapping[str, Any] | None:
    return next((event for event in events if event.get("type") == kind), None)


def _duration(events: Sequence[Mapping[str, Any]]) -> float:
    stamps = []
    for event in events:
        value = event.get("utc")
        if not isinstance(value, str):
            continue
        try:
            stamps.append(datetime.fromisoformat(value))
        except ValueError:
            continue
    if len(stamps) < 2:
        return 0.0
    return max(0.0, (max(stamps) - min(stamps)).total_seconds())


def run_metrics(run_dir: Path) -> dict[str, Any]:
    """Project one run's ledger into a metrics row."""
    plan = _plan(run_dir)
    events = _events(run_dir)
    nodes = {node["node_id"]: "pending" for node in plan["nodes"]
             if isinstance(node, dict) and isinstance(node.get("node_id"), str)}
    for event in events:
        node_id = event.get("node_id")
        if node_id not in nodes:
            continue
        if event.get("type") == "dispatch.started":
            nodes[node_id] = "running"
        elif event.get("type") == "node.retry":
            nodes[node_id] = "pending"
        elif event.get("type", "").startswith("node."):
            nodes[node_id] = event["type"].split(".", 1)[1]
    required = set(plan.get("gates", ()))
    for event in events:
        if event.get("type") == "gate.required":
            required.update(event.get("gates", ()))
    passed = {event.get("gate") for event in events
              if event.get("type") == "gate.check" and event.get("status") == "pass"}
    if any(event.get("type") == "node.completed" for event in events):
        # The bridge runs the scope guard before it writes node.completed.
        passed.add("scope_guard")
    pending_gates = sorted(required - passed)
    statuses = list(nodes.values())
    if any(value != "completed" for value in statuses):
        status = "running" if any(value == "running" for value in statuses) else "blocked"
    elif pending_gates:
        status = "gated"
    else:
        status = "completed"
    created = _first(events, "plan.created") or {}
    dispatches = sum(event.get("type") == "dispatch.started" for event in events)
    retries = sum(event.get("type") == "node.retry" for event in events)
    interventions = sum(event.get("type") in {"human.requested", "approval.granted", "external.write.requested"}
                        for event in events)
    gate_checks = sum(event.get("type") == "gate.check" for event in events)
    gate_failures = sum(event.get("type") == "gate.check" and event.get("status") != "pass"
                        for event in events)
    grants_requested = sum(event.get("type") == "grant.requested" for event in events)
    grants_granted = sum(event.get("type") == "grant.granted" for event in events)
    grants_denied = sum(event.get("type") == "grant.denied" for event in events)
    grants_used = sum(event.get("type") == "grant.used" for event in events)
    interceptor_allowed = sum(event.get("type") == "interceptor.allowed" for event in events)
    confirm_required = sum(event.get("type") == "interceptor.confirm_required" for event in events)
    confirm_granted = sum(event.get("type") == "interceptor.confirmed" for event in events)
    return {
        "run_id": run_dir.name,
        "request_class": created.get("request_class"),
        "template_id": created.get("template_id"),
        "node_count": len(nodes),
        "dispatch_count": dispatches,
        "retry_count": retries,
        "human_interventions": interventions,
        "gate_checks": gate_checks,
        "gate_failures": gate_failures,
        "grants_requested": grants_requested,
        "grants_granted": grants_granted,
        "grants_denied": grants_denied,
        "grants_used": grants_used,
        "interceptor_allowed": interceptor_allowed,
        "confirm_required": confirm_required,
        "confirm_granted": confirm_granted,
        "first_pass": retries == 0 and gate_failures == 0 and status == "completed",
        "duration_s": round(_duration(events), 3),
        "started_utc": events[0].get("utc") if events else None,
        "status": status,
    }


def collect(project: Path) -> list[dict[str, Any]]:
    """Read every v2 run under ``.cybertron/runs``; legacy runs are skipped."""
    root = Path(project) / ".cybertron" / "runs"
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise MetricsError("run storage is not a safe directory")
    runs = []
    for directory in sorted(root.iterdir()):
        if directory.is_symlink() or not directory.is_dir():
            continue
        try:
            runs.append(run_metrics(directory))
        except MetricsError as exc:
            if "unsupported plan schema" in str(exc):
                continue
            raise
    runs.sort(key=lambda run: (run.get("started_utc") or "", run["run_id"]))
    return runs


def summarize(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate the panel; empty runs yield zeroed, not invented, values."""
    completed = [run for run in runs if run["status"] == "completed"]
    reusable = [run for run in runs if run.get("template_id")]
    gate_checks = sum(run["gate_checks"] for run in runs)
    gate_failures = sum(run["gate_failures"] for run in runs)
    grants_requested = sum(run["grants_requested"] for run in runs)
    grants_granted = sum(run["grants_granted"] for run in runs)
    grants_used = sum(run["grants_used"] for run in runs)
    confirm_required = sum(run["confirm_required"] for run in runs)

    def average(field: str) -> float:
        return round(sum(run[field] for run in runs) / len(runs), 3) if runs else 0.0

    return {
        "runs": len(runs),
        "completed": len(completed),
        "pass_rate": round(len(completed) / len(runs), 3) if runs else 0.0,
        "avg_node_count": average("node_count"),
        "avg_dispatch_count": average("dispatch_count"),
        "avg_human_interventions": average("human_interventions"),
        "avg_duration_s": average("duration_s"),
        "gate_checks": gate_checks,
        "gate_failures": gate_failures,
        "gate_failure_ratio": round(gate_failures / gate_checks, 3) if gate_checks else 0.0,
        "grants_requested": grants_requested,
        "grants_granted": grants_granted,
        "grants_used": grants_used,
        "confirm_required": confirm_required,
        "template_runs": len(reusable),
    }


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Delta of two runs; negative node/intervention values mean fewer."""
    fields = ("node_count", "dispatch_count", "human_interventions", "duration_s")
    delta = {field: after[field] - before[field] for field in fields}
    return {
        "before": before["run_id"], "after": after["run_id"],
        "delta": delta,
        "nodes_reduced": delta["node_count"] < 0,
        "interventions_reduced": delta["human_interventions"] < 0,
        "dispatches_reduced": delta["dispatch_count"] < 0,
    }


def template_summary(project: Path) -> dict[str, Any]:
    try:
        templates = list_templates(project)
    except TemplateRejected:
        return {"count": 0, "classes": {}}
    classes: dict[str, int] = {}
    for template in templates:
        classes[template["request_class"]] = classes.get(template["request_class"], 0) + 1
    return {"count": len(templates), "classes": classes}


def render_panel(runs: Sequence[Mapping[str, Any]], summary: Mapping[str, Any],
                 templates: Mapping[str, Any] | None = None) -> str:
    lines = ["# Cybertron v6 metrics", ""]
    lines.append("| run | class | template | nodes | dispatches | retries | human | gates (fail/check) "
                 "| grants (used/req) | confirms | duration | status |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for run in runs:
        row = {**run, "request_class": run.get("request_class") or "-",
               "template_id": run.get("template_id") or "-"}
        lines.append("| {run_id} | {request_class} | {template_id} | {node_count} | {dispatch_count} "
                     "| {retry_count} | {human_interventions} | {gate_failures}/{gate_checks} "
                     "| {grants_used}/{grants_requested} | {confirm_required} "
                     "| {duration_s}s | {status} |".format(**row))
    lines.extend([
        "", "## aggregate", "",
        f"- runs: {summary['runs']} ({summary['completed']} completed, "
        f"pass rate {summary['pass_rate']:.1%})",
        f"- average nodes: {summary['avg_node_count']}, dispatches: {summary['avg_dispatch_count']}, "
        f"human interventions: {summary['avg_human_interventions']}",
        f"- gate failures: {summary['gate_failures']}/{summary['gate_checks']} "
        f"({summary['gate_failure_ratio']:.1%})",
        f"- grants: {summary['grants_granted']}/{summary['grants_requested']} granted, "
        f"{summary['grants_used']} used; full-access confirmations: {summary['confirm_required']}",
        f"- template-seeded runs: {summary['template_runs']}",
    ])
    if templates is not None:
        lines.append(f"- stored templates: {templates['count']} "
                     f"({', '.join(sorted(templates['classes'])) or 'none'})")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cybertron-v6-metrics")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args(argv)
    runs = collect(args.project)
    summary = summarize(runs)
    templates = template_summary(args.project)
    if args.compare:
        by_id = {run["run_id"]: run for run in runs}
        missing = [run_id for run_id in args.compare if run_id not in by_id]
        if missing:
            print(json.dumps({"error": f"unknown runs: {', '.join(missing)}"}))
            return 2
        result = compare(by_id[args.compare[0]], by_id[args.compare[1]])
        if args.json:
            print(json.dumps({"runs": runs, "summary": summary,
                              "templates": templates, "compare": result},
                             ensure_ascii=False, indent=2))
        else:
            print(render_panel(runs, summary, templates))
            print(f"compare {result['before']} -> {result['after']}: {result['delta']}")
        return 0
    if args.json:
        print(json.dumps({"runs": runs, "summary": summary, "templates": templates},
                         ensure_ascii=False, indent=2))
    else:
        print(render_panel(runs, summary, templates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
