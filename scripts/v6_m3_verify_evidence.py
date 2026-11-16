"""Independently verify the recorded M3 host evidence against its ledgers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGES = ROOT / "docs" / "stages"
CHECKS: list[dict] = []


def check(name: str, condition: bool, detail: object = None) -> None:
    CHECKS.append({"check": name, "passed": bool(condition), "detail": detail})
    if not condition:
        raise SystemExit(f"verification failed: {name}")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(tag: str) -> tuple[dict, list[dict], list[dict]]:
    receipt = json.loads((STAGES / f"v6-m3-host-{tag}-receipt.json").read_text())
    events = [json.loads(line) for line in
              (STAGES / f"v6-m3-host-{tag}-events.jsonl").read_text().splitlines() if line]
    sessions = []
    for item in receipt["sessions"]:
        name = Path(item["path"]).name
        sessions.append({"node_id": item["node_id"], "path": name,
                         "call_id": item.get("call_id"),
                         "data": json.loads((STAGES / name).read_text())})
    return receipt, events, sessions


def tools(session: dict) -> list[dict]:
    found = []
    for message in session.get("messages", []):
        if message.get("type") != "assistant":
            continue
        for part in message.get("content", []):
            if part.get("type") == "tool":
                found.append(part)
    return found


def path_matches(value: object, expected: str) -> bool:
    return isinstance(value, str) and (value == expected or value.endswith("/" + expected))


def starts(events: list[dict], node_id: str) -> list[dict]:
    return [event for event in events
            if event["type"] == "dispatch.started" and event.get("node_id") == node_id]


def completed(events: list[dict], node_id: str) -> list[dict]:
    return [event for event in events
            if event["type"] == "node.completed" and event.get("node_id") == node_id]


def verify_integrity(tag: str, receipt: dict) -> None:
    check(f"{tag}: host process exited zero", receipt["exit"] == 0, receipt["exit"])
    check(f"{tag}: logged output hash matches",
          digest(STAGES / f"v6-m3-host-{tag}.jsonl") == receipt["output_sha256"])
    check(f"{tag}: ledger hash matches",
          digest(STAGES / f"v6-m3-host-{tag}-events.jsonl") == receipt["events_sha256"])
    for item in receipt["sessions"]:
        check(f"{tag}: session {item['node_id']} hash matches",
              digest(STAGES / Path(item["path"]).name) == item["sha256"])


def verify_concurrency() -> dict:
    tag = "concurrency-r2"
    receipt, events, sessions = load(tag)
    verify_integrity(tag, receipt)
    node_sessions = {item["node_id"]: item["data"] for item in sessions}
    for node_id in ("a", "b"):
        check(f"concurrency: {node_id} started once", len(starts(events, node_id)) == 1)
        bound = [event for event in events
                 if event["type"] == "dispatch.bound" and event.get("node_id") == node_id]
        check(f"concurrency: {node_id} has a host binding", len(bound) == 1)
        finished = completed(events, node_id)
        check(f"concurrency: {node_id} completed", len(finished) == 1)
        check(f"concurrency: {node_id} artifact recorded",
              finished[0]["artifacts"].get(f"docs/{node_id}.md") ==
              receipt["artifacts"][f"docs/{node_id}.md"]["sha256"])
        info = node_sessions[node_id]["info"]
        permissions = info.get("permissions", [])
        check(f"concurrency: {node_id} session denies all edits",
              {"action": "edit", "resource": "*", "effect": "deny"} in permissions)
        check(f"concurrency: {node_id} session allows only its node file",
              {"action": "edit", "resource": f"docs/{node_id}.md", "effect": "allow"} in permissions)
        writes = [part for part in tools(node_sessions[node_id])
                  if part.get("name") == "write" and part.get("state", {}).get("status") == "completed"]
        check(f"concurrency: {node_id} child wrote only its node file",
              any(path_matches(part["state"].get("input", {}).get("path"), f"docs/{node_id}.md")
                  for part in writes))
    check("concurrency: no scope rejection events",
          not [event for event in events if event["type"] == "plan.op.rejected"])
    check("concurrency: both writers overlapped",
          {event["node_id"] for event in events if event["type"] == "dispatch.started"} == {"a", "b"})
    return {"run_id": receipt["run_id"], "artifacts": receipt["artifacts"],
            "binds": [event["child_session_id"] for event in events
                      if event["type"] == "dispatch.bound"]}


def verify_loop1() -> dict:
    tag = "loop1-r5"
    receipt, events, sessions = load(tag)
    verify_integrity(tag, receipt)
    blocked = [event for event in events if event["type"] == "node.blocked"]
    retries = [event for event in events if event["type"] == "node.retry"]
    check("loop1: first attempt blocked", len(blocked) == 1)
    check("loop1: blocked diagnostic is no accepted artifact",
          blocked[0]["diagnostic"] == "no accepted artifact", blocked[0]["diagnostic"])
    check("loop1: kernel requeued the node", len(retries) == 1 and retries[0]["attempt"] == 2)
    check("loop1: node dispatched twice", len(starts(events, "n1")) == 2)
    check("loop1: retry completed", len(completed(events, "n1")) == 1)
    attempts = [item for item in receipt["sessions"] if item["node_id"] == "n1"]
    check("loop1: two native child sessions", len(attempts) == 2)
    attempt_sessions = [item["data"] for item in sessions if item["node_id"] == "n1"]
    first = attempt_sessions[0]
    first_writes = [part for part in tools(first) if part.get("name") == "write"]
    check("loop1: first child produced no write", not first_writes)
    second = attempt_sessions[1]
    second_writes = [part for part in tools(second)
                     if part.get("name") == "write" and part.get("state", {}).get("status") == "completed"]
    check("loop1: retry child wrote docs/n1.md",
          any(path_matches(part["state"]["input"].get("path"), "docs/n1.md") for part in second_writes))
    check("loop1: artifact hash matches receipt",
          completed(events, "n1")[0]["artifacts"]["docs/n1.md"] ==
          receipt["artifacts"]["docs/n1.md"]["sha256"])
    return {"run_id": receipt["run_id"], "blocked_diagnostic": blocked[0]["diagnostic"],
            "artifact": receipt["artifacts"]["docs/n1.md"]}


def verify_scope_denial() -> dict:
    tag = "scope-exec-r1"
    receipt, events, sessions = load(tag)
    verify_integrity(tag, receipt)
    blocked = [event for event in events if event["type"] == "node.blocked"]
    check("scope: out-of-scope attempt produced no artifact", not completed(events, "n1"))
    check("scope: node blocked", len(blocked) == 1)
    check("scope: escape file was never written", "docs/escape.md" not in receipt["artifacts"])
    writes = [part for part in tools(next(item["data"] for item in sessions
                                          if item["node_id"] == "n1")) if part.get("name") == "write"]
    check("scope: child attempted docs/escape.md",
          any(path_matches(part["state"].get("input", {}).get("path"), "docs/escape.md")
              for part in writes))
    denied = [part for part in writes
              if part["state"].get("status") == "error"
              and part["state"].get("error", {}).get("type") == "permission.rejected"]
    check("scope: host returned permission.rejected", len(denied) == 1)
    check("scope: required gate never passed", not [
        event for event in events if event["type"] == "node.completed"])
    return {"run_id": receipt["run_id"], "denial": denied[0]["state"]["error"],
            "artifacts": receipt["artifacts"]}


def verify_l2_rework() -> dict:
    tag = "l2-r6"
    receipt, events, sessions = load(tag)
    verify_integrity(tag, receipt)
    rejections = [event for event in events if event["type"] == "review.rejected"]
    check("l2: one host-recorded rejection", len(rejections) == 1)
    check("l2: rejection targets fix", rejections[0]["affected_node_id"] == "fix")
    check("l2: rejection diagnostic is the real finding",
          rejections[0]["diagnostic"] == "docs/fix.md does not contain repaired")
    stale = {event["node_id"] for event in events if event["type"] == "node.stale"}
    check("l2: affected subgraph is stale", stale == {"fix", "review", "deliver"}, sorted(stale))
    check("l2: unrelated node not stale", "unrelated" not in stale)
    check("l2: unrelated dispatched once", len(starts(events, "unrelated")) == 1)
    check("l2: fix reworked once", len(starts(events, "fix")) == 2)
    check("l2: review rerun once", len(starts(events, "review")) == 2)
    check("l2: deliver completed after review", len(completed(events, "deliver")) == 1)
    check("l2: final fix artifact matches receipt",
          completed(events, "fix")[-1]["artifacts"]["docs/fix.md"] ==
          receipt["artifacts"]["docs/fix.md"]["sha256"])
    review_session = next(item["data"] for item in sessions if item["node_id"] == "review")
    review_tools = [part for part in tools(review_session)
                    if part.get("name") == "cy_review_reject"]
    check("l2: reviewer used cy_review_reject",
          len(review_tools) == 1 and review_tools[0]["state"].get("status") == "completed")
    check("l2: reviewer rejected fix",
          review_tools[0]["state"]["input"].get("affected_node_id") == "fix")
    return {"run_id": receipt["run_id"], "rejection": rejections[0],
            "stale": sorted(stale), "artifacts": receipt["artifacts"]}


def main() -> None:
    result = {
        "milestone": "M3",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "concurrency": verify_concurrency(),
        "loop1": verify_loop1(),
        "scope_denial": verify_scope_denial(),
        "l2_rework": verify_l2_rework(),
        "checks": CHECKS,
        "all_passed": all(item["passed"] for item in CHECKS),
    }
    target = STAGES / "v6-m3-host-verification.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in
                      ("milestone", "verified_at_utc", "all_passed", "checks")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
