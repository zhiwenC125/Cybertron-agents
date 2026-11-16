"""Capture real OpenCode host evidence for the M5 learning gate.

A cold run plans a read-only discovery node plus a writer and records one
human question. A warm run of the same request class reuses the distilled
template and skips the discovery node. The script records both ledgers, the
metrics panel, and the comparison; it calls a real model, so it is not part
of the unit suite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGES = ROOT / "docs" / "stages"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "payload", "v6_plugin")

COLD = """Cybertron v6 M5 learning acceptance, cold run. Do not edit files yourself.
Step 1: call cy_templates and note the count.
Step 2: call cy_plan exactly once with request_class "m5-doc-scan", objective "Write docs/m5-cold.md containing exactly m5 ok", and these two nodes, both verifiers ["scope_guard"]:
- {"node_id":"scan","kind":"task","capability":"scan.static","role":"onyx-prime","objective":"Survey the docs directory and report candidate Markdown paths","write_scope":[],"acceptance":["candidate paths reported"]}
- {"node_id":"doc","kind":"task","capability":"doc.write","role":"alpha-trion","objective":"Create docs/m5-cold.md containing exactly m5 ok","depends_on":["scan"],"write_scope":["docs/m5-cold.md"],"acceptance":["docs/m5-cold.md contains exactly m5 ok"]}
Step 3: call cy_ask once with question "Confirm docs/m5-cold.md is the intended path". Treat the answer as yes.
Step 4: dispatch scan with its exact returned card as the description; the child only reads and reports. Then call cy_state with wait=true.
Step 5: dispatch doc with its exact returned card; the child's first and only action is to write exactly "m5 ok" to docs/m5-cold.md and then reply. Then call cy_state with wait=true. If cy_state reports doc ready again (the artifact was not accepted yet), dispatch doc again with the same card, up to three attempts, until the run is completed.
Step 6: report the run_id, plan node count, dispatch count, and how many times you called cy_ask. Do not call cy_metrics yourself."""

WARM = """Cybertron v6 M5 learning acceptance, warm run. Do not edit files yourself.
Step 1: call cy_templates and find the template whose request_class is "m5-doc-scan". Report its node and human-intervention counts.
Step 2: call cy_plan exactly once with that template_id, objective "Write docs/m5-warm.md containing exactly m5-warm ok", write_scope ["docs/m5-warm.md"], request_class "m5-doc-scan", and skip ["scan.static"]. The skipped scan is deliberate: its discovery result is already in the template.
Step 3: do not call cy_ask.
Step 4: dispatch the single ready doc node with its exact returned card; the child's first and only action is to write exactly "m5-warm ok" to docs/m5-warm.md and then reply. Then call cy_state with wait=true. If cy_state reports doc ready again (the artifact was not accepted yet), dispatch doc again with the same card, up to three attempts, until the run is completed.
Step 5: report the run_id, plan node count, dispatch count, skipped capabilities, and how many times you called cy_ask. Do not call cy_metrics yourself."""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_fixture() -> Path:
    fixture = Path(tempfile.mkdtemp(prefix="cybertron-v6-m5-host-"))
    (fixture / "docs").mkdir()
    shutil.copytree(ROOT / ".opencode", fixture / ".opencode")
    shutil.rmtree(fixture / ".opencode" / "commands", ignore_errors=True)
    shutil.rmtree(fixture / ".opencode" / "plugins" / "cybertron", ignore_errors=True)
    shutil.copytree(ROOT / "cybertron", fixture / "cybertron", ignore=IGNORE)
    shutil.copy2(ROOT / "AGENTS.md", fixture / "AGENTS.md")
    config = json.loads((ROOT / "opencode.jsonc").read_text())
    config["plugins"] = ["-cybertron.runtime"]
    (fixture / "opencode.jsonc").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    # Keep a pristine config home so a user-global plugin cannot shadow the
    # project plugin; the local model profile still selects the prima route.
    (fixture / ".config").mkdir()
    models = Path.home() / ".config" / "cybertron" / "models.json"
    (fixture / ".cybertron").mkdir()
    if models.exists():
        (fixture / ".cybertron" / "models.json").write_text(models.read_text())
    return fixture


def run_ledger(fixture: Path) -> dict | None:
    runs = list((fixture / ".cybertron" / "runs").glob("*/plan.json"))
    if not runs:
        return None
    plan_path = max(runs, key=lambda path: path.stat().st_mtime)
    run_id = plan_path.parent.name
    events_path = plan_path.parent / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    parent = None
    children: list[dict] = []
    starts: dict[str, str] = {}
    interventions = 0
    skipped: list[str] = []
    for event in events:
        if event["type"] == "plan.created":
            parent = event.get("host_session_id")
            skipped = event.get("skipped_capabilities") or []
        elif event["type"] == "dispatch.started":
            starts[event["call_id"]] = event["node_id"]
        elif event["type"] == "dispatch.returned" and event.get("child_session_id"):
            node_id = starts.get(event["call_id"])
            if node_id:
                children.append({"node_id": node_id, "call_id": event["call_id"],
                                 "session_id": event["child_session_id"]})
        elif event["type"] in {"human.requested", "approval.granted"}:
            interventions += 1
    plan = json.loads(plan_path.read_text())
    statuses = {node.get("node_id"): "pending" for node in plan.get("nodes", [])}
    for event in events:
        node_id = event.get("node_id")
        if node_id in statuses and event["type"].startswith("node."):
            statuses[node_id] = ("pending" if event["type"] == "node.retry"
                                 else event["type"].split(".", 1)[1])
    required = set(plan.get("gates", ()))
    for event in events:
        if event["type"] == "gate.required":
            required.update(event.get("gates", ()))
    passed = {event.get("gate") for event in events
              if event["type"] == "gate.check" and event.get("status") == "pass"}
    if any(event["type"] == "node.completed" for event in events):
        passed.add("scope_guard")
    status = ("completed" if statuses and all(value == "completed" for value in statuses.values())
              and not (required - passed) else "incomplete")
    return {"run_id": run_id, "plan_path": plan_path, "events_path": events_path,
            "status": status,
            "parent_session_id": parent, "child_sessions": children,
            "node_count": len(plan.get("nodes", [])), "interventions": interventions,
            "skipped_capabilities": skipped}


def export_session(fixture: Path, session_id: str, target: Path) -> None:
    result = subprocess.run(["opencode2", "session", "export", session_id],
                            cwd=fixture, text=True, capture_output=True, timeout=120)
    if result.returncode != 0:
        raise SystemExit(f"session export failed for {session_id}: {result.stderr[-500:]}")
    target.write_text(result.stdout)


def scenario(fixture: Path, tag: str, prompt: str) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    env = {key: value for key, value in os.environ.items()
           if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
    env["XDG_CONFIG_HOME"] = str(fixture / ".config")
    command = ["opencode2", "--standalone", "run", "--agent", "prima",
               "--format", "json", "--auto", prompt]
    try:
        result = subprocess.run(command, cwd=fixture, env=env, text=True,
                                capture_output=True, timeout=600)
        code, output = result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired as exc:
        code = 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        output = stdout + stderr
    log_path = STAGES / f"v6-m5-host-{tag}.jsonl"
    log_path.write_text(output)
    ledger = run_ledger(fixture)
    receipt = {"scenario": tag, "started_utc": started,
               "utc": datetime.now(timezone.utc).isoformat(), "exit": code,
               "output_path": str(log_path.relative_to(ROOT)),
               "output_sha256": digest(log_path), "ledger": None, "sessions": [],
               "artifacts": {}}
    if ledger:
        meta = {key: ledger[key] for key in ("run_id", "node_count", "interventions",
                                             "skipped_capabilities", "parent_session_id",
                                             "child_sessions", "status")}
        events_copy = STAGES / f"v6-m5-host-{tag}-events.jsonl"
        events_copy.write_bytes(ledger["events_path"].read_bytes())
        plan_copy = STAGES / f"v6-m5-host-{tag}-plan.json"
        plan_copy.write_bytes(ledger["plan_path"].read_bytes())
        meta.update({"events_path": str(events_copy.relative_to(ROOT)),
                     "events_sha256": digest(events_copy),
                     "plan_path": str(plan_copy.relative_to(ROOT)),
                     "plan_sha256": digest(plan_copy)})
        receipt["ledger"] = meta
        if ledger["parent_session_id"]:
            target = STAGES / f"v6-m5-host-{tag}-parent-session.json"
            export_session(fixture, ledger["parent_session_id"], target)
            receipt["sessions"].append({"node_id": "parent", "path": str(target.relative_to(ROOT)),
                                        "sha256": digest(target)})
        counts: dict[str, int] = {}
        for child in ledger["child_sessions"]:
            node_id = child["node_id"]
            counts[node_id] = counts.get(node_id, 0) + 1
            suffix = node_id if counts[node_id] == 1 else f"{node_id}-attempt{counts[node_id]}"
            target = STAGES / f"v6-m5-host-{tag}-{suffix}-session.json"
            export_session(fixture, child["session_id"], target)
            receipt["sessions"].append({"node_id": node_id, "call_id": child["call_id"],
                                        "path": str(target.relative_to(ROOT)),
                                        "sha256": digest(target)})
    for path in sorted(fixture.glob("docs/**/*")):
        if path.is_file():
            receipt["artifacts"][str(path.relative_to(fixture))] = {
                "sha256": digest(path), "size": path.stat().st_size}
    receipt_path = STAGES / f"v6-m5-host-{tag}-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=("cold", "warm"))
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    fixture = args.fixture or build_fixture()
    receipts = {}
    if args.only in (None, "cold"):
        receipts["cold"] = scenario(fixture, "cold", COLD)
        print(json.dumps(receipts["cold"], ensure_ascii=False, indent=2))
        if args.only == "cold":
            return
    receipts["warm"] = scenario(fixture, "warm", WARM)
    print(json.dumps(receipts["warm"], ensure_ascii=False, indent=2))

    metrics = subprocess.run([sys.executable, "-m", "cybertron.metrics",
                              "--project", str(fixture), "--json"],
                             cwd=ROOT, text=True, capture_output=True)
    panel = json.loads(metrics.stdout) if metrics.returncode == 0 else {"error": metrics.stderr[-800:]}
    (STAGES / "v6-m5-metrics.json").write_text(json.dumps(panel, ensure_ascii=False, indent=2) + "\n")

    cold = receipts["cold"].get("ledger") or {}
    warm = receipts["warm"].get("ledger") or {}
    comparison = {
        "cold_run_id": cold.get("run_id"), "warm_run_id": warm.get("run_id"),
        "status": {"cold": cold.get("status"), "warm": warm.get("status")},
        "node_count": {"cold": cold.get("node_count"), "warm": warm.get("node_count")},
        "interventions": {"cold": cold.get("interventions"), "warm": warm.get("interventions")},
        "skipped_capabilities": warm.get("skipped_capabilities"),
        "nodes_reduced": bool(cold.get("node_count") and warm.get("node_count")
                              and warm["node_count"] < cold["node_count"]),
        "interventions_reduced": bool(cold.get("interventions") is not None
                                      and warm.get("interventions") is not None
                                      and warm["interventions"] < cold["interventions"]),
    }
    acceptance = {
        "milestone": "M5",
        "host": "opencode2 --standalone (real model)",
        "fixture": str(fixture),
        "utc": datetime.now(timezone.utc).isoformat(),
        "receipts": {tag: str((STAGES / f"v6-m5-host-{tag}-receipt.json").relative_to(ROOT))
                     for tag in receipts},
        "metrics_path": "docs/stages/v6-m5-metrics.json",
        "metrics_sha256": digest(STAGES / "v6-m5-metrics.json"),
        "comparison": comparison,
    }
    (STAGES / "v6-m5-host-acceptance.json").write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(acceptance, ensure_ascii=False, indent=2))
    if not (comparison["nodes_reduced"] and comparison["interventions_reduced"]
            and cold.get("status") == "completed" and warm.get("status") == "completed"):
        raise SystemExit("M5 learning gate not met: both runs must complete and the second run "
                         "must reduce nodes and interventions")


if __name__ == "__main__":
    main()
