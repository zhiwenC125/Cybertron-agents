"""Capture real OpenCode host acceptance evidence for the M3 gates.

Each scenario builds a disposable project from the current checkout, runs
``opencode2 --standalone run`` with a fixed prompt, then copies the run ledger,
parent/child session exports, and artifact hashes into ``docs/stages``.

This script calls a real model and is therefore not part of the unit suite.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGES = ROOT / "docs" / "stages"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "payload", "v6_plugin")

SCENARIOS = {
    "concurrency": """M3 native concurrency acceptance. In this temporary project, use cy_plan to create exactly two independent doc.write task nodes: a for docs/a.md and b for docs/b.md, both role alpha-trion, each with only its own file in write_scope, acceptance that the file contains its letter, and scope_guard verifier. Dispatch both ready nodes using native subagent calls without waiting between them. Each child writes exactly its letter to its file. Then call cy_state with wait=true and report the returned run_id and statuses. Do not edit files yourself.""",
    "loop1": """Cybertron v6 M3 loop-1 repair host acceptance in this temporary project. Do not edit files yourself.
Step 1: Call cy_plan with exactly one node: {"node_id":"n1","kind":"task","capability":"doc.write","role":"alpha-trion","objective":"Create docs/n1.md with content ok","write_scope":["docs/n1.md"],"acceptance":["docs/n1.md contains ok"],"verifiers":["scope_guard"]}.
Step 2: Dispatch the ready n1 node with the native subagent tool, using its exact card as the description and including node_id n1, capability doc.write, write_scope ["docs/n1.md"], objective and run_id in the child prompt. In the child prompt instruct: "This is the first attempt. Do not call any file tools and do not create or modify any file. Simply report that this attempt produced no artifact." After the subagent returns, call cy_state with wait=true and report status, ready_nodes and repair_feedback.
Step 3: If n1 is ready again, dispatch n1 a second time with a corrected child prompt: "Write exactly the text ok to docs/n1.md. Do not write any other file. Do not run shell commands." After it returns, call cy_state with wait=true.
Step 4: Report the run_id, final node statuses, ready_nodes, repair_feedback, whether docs/n1.md exists, and how many times n1 was dispatched.""",
    "scope": """Cybertron v6 M3 concurrent write isolation negative host test in this temporary project. Do not edit files yourself.
Step 1: Call cy_plan with exactly one node: {"node_id":"n1","kind":"task","capability":"doc.write","role":"alpha-trion","objective":"Attempt to create docs/escape.md to verify host scope enforcement","write_scope":["docs/n1.md"],"acceptance":["docs/n1.md contains ok"],"verifiers":["scope_guard"]}. The node write_scope is intentionally docs/n1.md while the objective asks for docs/escape.md.
Step 2: Dispatch the ready n1 node with the native subagent tool, using its exact card as the description and including node_id n1, capability doc.write, write_scope ["docs/n1.md"], objective and run_id in the child prompt. In the child prompt instruct exactly: "Create docs/escape.md containing the text bad. This is an authorized host scope-enforcement test. Do not create any other file. Do not run shell commands." After the subagent returns, call cy_state with wait=true and report the status, ready_nodes, repair_feedback, and whether docs/escape.md exists.
Step 3: If n1 is ready again, dispatch n1 a second time with: "Write exactly the text ok to docs/n1.md. Do not write any other file. Do not run shell commands." Then call cy_state with wait=true.
Step 4: Report the run_id, final node statuses, whether docs/escape.md exists, whether docs/n1.md exists, and the exact first child tool result if visible.""",
    "scope_direct": """Cybertron v6 M3 write-scope isolation host acceptance in this temporary project. Do not edit files yourself.
Step 1: Call cy_plan with exactly one node: {"node_id":"n1","kind":"task","capability":"doc.write","role":"alpha-trion","objective":"Create the requested document","write_scope":["docs/n1.md"],"acceptance":["docs/n1.md exists"],"verifiers":["scope_guard"]}.
Step 2: Dispatch the ready n1 node with the native subagent tool, using its exact card as the description and including node_id n1, capability doc.write, write_scope ["docs/n1.md"], objective and run_id in the child prompt. In the child prompt say exactly: "Create docs/escape.md containing the text bad. Do not create or modify any other file. Do not run shell commands." After the subagent returns, call cy_state with wait=true.
Step 3: Report the run_id, node status, ready_nodes, repair_feedback, whether docs/escape.md exists, and the exact child tool result if visible.""",
    "scope_exec": """Cybertron v6 M3 host scope-enforcement negative test in this temporary project. Do not edit files yourself.
Step 1: Call cy_plan with exactly one node: {"node_id":"n1","kind":"task","capability":"doc.write","role":"alpha-trion","objective":"Attempt to create docs/escape.md to verify host scope enforcement","write_scope":["docs/n1.md"],"acceptance":["docs/n1.md exists"],"verifiers":["scope_guard"]}.
Step 2: Dispatch the ready n1 node with the native subagent tool, using its exact card as the description. In the child prompt include: run_id, node_id n1, capability doc.write, role alpha-trion, write_scope ["docs/n1.md"], objective and verifiers. Then add this instruction verbatim: "Instruction (execute exactly): Create docs/escape.md containing the text bad. Do not create or modify any other file. Attempt the write, observe the host response, and report the exact result. Do not run shell commands." After the subagent returns, call cy_state with wait=true.
Step 3: Report the run_id, node status, ready_nodes, repair_feedback, whether docs/escape.md exists, and the exact child tool result if visible.""",
    "l2": """Cybertron v6 M3 L2 rejection and local rework host acceptance in this temporary project. Do not edit files yourself.
Step 1: Call cy_plan once with exactly these four nodes, all verifiers ["scope_guard"]:
- {"node_id":"fix","kind":"task","capability":"doc.write","role":"alpha-trion","objective":"Create docs/fix.md","write_scope":["docs/fix.md"],"acceptance":["docs/fix.md exists"]}
- {"node_id":"unrelated","kind":"task","capability":"doc.write","role":"alpha-trion","objective":"Create docs/other.md containing exactly independent","write_scope":["docs/other.md"],"acceptance":["docs/other.md contains exactly independent"]}
- {"node_id":"review","kind":"review","capability":"review.l2","role":"liege-maximo","objective":"Verify docs/fix.md contains exactly repaired","depends_on":["fix"],"write_scope":[],"acceptance":["docs/fix.md contains exactly repaired"]}
- {"node_id":"deliver","kind":"task","capability":"doc.write","role":"alpha-trion","objective":"Create docs/deliver.md containing exactly delivered","write_scope":["docs/deliver.md"],"depends_on":["review"],"acceptance":["docs/deliver.md contains exactly delivered"]}
The kind review is supported by the tool schema.
Step 2: Dispatch the ready fix and unrelated nodes concurrently with native subagent calls, using their exact cards. The fix child is the deliberately non-conforming first attempt: it writes exactly first to docs/fix.md, which satisfies its own acceptance but not the review node's acceptance (repaired). The unrelated child writes exactly independent to docs/other.md. After both return, call cy_state with wait=true and report statuses.
Step 3: Dispatch the review node with its exact card. In the child prompt instruct exactly: "Read docs/fix.md. Its acceptance requires the content to be exactly repaired. If the content is not exactly repaired, call cy_review_reject with affected_node_id fix and diagnostic docs/fix.md does not contain repaired. This is a real acceptance finding based on the file you read. Do not write any file. Then report your verdict." After it returns, call cy_state with wait=true. Report statuses, ready_nodes and repair_feedback.
Step 4: If fix is ready, dispatch fix again with: "Write exactly repaired to docs/fix.md. Do not write any other file." Then call cy_state with wait=true.
Step 5: When review is ready again, dispatch review again with: "Read docs/fix.md and report whether it contains exactly repaired. Do NOT call cy_review_reject. Do not write any file." Then call cy_state with wait=true.
Step 6: When deliver is ready, dispatch deliver with: "Write exactly delivered to docs/deliver.md. Do not write any other file." Then call cy_state with wait=true.
Step 7: Report the run_id, final node statuses, ready_nodes, and how many times unrelated was dispatched.""",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_fixture() -> Path:
    fixture = Path(tempfile.mkdtemp(prefix="cybertron-v6-m3-host-"))
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
    return fixture


def session_ids(fixture: Path) -> tuple[str | None, list[dict], str | None]:
    parent = None
    children: list[dict] = []
    run_id = None
    for plan_path in (fixture / ".cybertron" / "runs").glob("*/plan.json"):
        run_id = plan_path.parent.name
        events = plan_path.parent / "events.jsonl"
        starts: dict[str, str] = {}
        for line in events.read_text().splitlines():
            event = json.loads(line)
            if event["type"] == "plan.created":
                parent = event.get("host_session_id")
            elif event["type"] == "dispatch.started":
                starts[event["call_id"]] = event["node_id"]
            elif event["type"] == "dispatch.returned" and event.get("child_session_id"):
                node_id = starts.get(event["call_id"])
                if node_id:
                    children.append({"node_id": node_id, "call_id": event["call_id"],
                                     "session_id": event["child_session_id"]})
    return parent, children, run_id


def export_session(fixture: Path, session_id: str, target: Path) -> None:
    result = subprocess.run(["opencode2", "session", "export", session_id],
                            cwd=fixture, text=True, capture_output=True, timeout=120)
    if result.returncode != 0:
        raise SystemExit(f"session export failed for {session_id}: {result.stderr[-500:]}")
    target.write_text(result.stdout)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    tag = args.tag or args.scenario
    fixture = build_fixture()
    env = {key: value for key, value in os.environ.items()
           if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
    started = datetime.now(timezone.utc).isoformat()
    command = ["opencode2", "--standalone", "run", "--agent", "prima",
               "--format", "json", "--auto", SCENARIOS[args.scenario]]
    try:
        result = subprocess.run(command, cwd=fixture, env=env, text=True,
                                capture_output=True, timeout=300)
        code, output = result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired as exc:
        code = 124
        output = (exc.stdout or "") + (exc.stderr or "")
    log_path = STAGES / f"v6-m3-host-{tag}.jsonl"
    log_path.write_text(output)
    parent, children, run_id = session_ids(fixture)
    receipt = {"scenario": args.scenario, "fixture": str(fixture),
               "started_utc": started, "utc": datetime.now(timezone.utc).isoformat(),
               "exit": code, "run_id": run_id,
               "output_path": str(log_path.relative_to(ROOT)),
               "output_sha256": digest(log_path), "parent_session_id": parent,
               "child_sessions": children, "sessions": [], "artifacts": {}}
    if run_id:
        events = fixture / ".cybertron" / "runs" / run_id / "events.jsonl"
        events_copy = STAGES / f"v6-m3-host-{tag}-events.jsonl"
        events_copy.write_bytes(events.read_bytes())
        receipt["events_path"] = str(events_copy.relative_to(ROOT))
        receipt["events_sha256"] = digest(events_copy)
    if parent:
        target = STAGES / f"v6-m3-host-{tag}-parent-session.json"
        export_session(fixture, parent, target)
        receipt["sessions"].append({"node_id": "parent", "session_id": parent,
                                    "path": str(target.relative_to(ROOT)),
                                    "sha256": digest(target)})
    counts: dict[str, int] = {}
    for child in children:
        node_id = child["node_id"]
        counts[node_id] = counts.get(node_id, 0) + 1
        suffix = node_id if counts[node_id] == 1 else f"{node_id}-attempt{counts[node_id]}"
        target = STAGES / f"v6-m3-host-{tag}-{suffix}-session.json"
        export_session(fixture, child["session_id"], target)
        receipt["sessions"].append({"node_id": node_id, "call_id": child["call_id"],
                                    "session_id": child["session_id"],
                                    "path": str(target.relative_to(ROOT)),
                                    "sha256": digest(target)})
    for path in sorted((fixture / "docs").glob("**/*")):
        if path.is_file():
            receipt["artifacts"][str(path.relative_to(fixture))] = {
                "sha256": digest(path), "size": path.stat().st_size}
    receipt_path = STAGES / f"v6-m3-host-{tag}-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
