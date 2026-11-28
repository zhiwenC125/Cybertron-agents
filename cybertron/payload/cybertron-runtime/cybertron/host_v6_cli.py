"""JSON stdin/stdout bridge for OpenCode V2's native subagent hook."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from .host_v6 import HostBridgeError, PlanValidationError, V6HostBridge
from .templates import bug_fix_template, read_only_scan_template
from .profiles import CheckRejected, run_check


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cybertron-v6-host")
    parser.add_argument("operation", choices=("plan", "plan_op", "state", "runs", "review_plan", "ask",
                                             "before", "after", "bind", "permission", "external_write",
                                             "review_reject", "finish", "record_interruption",
                                             "check", "fenced_shell", "templates", "metrics",
                                             "grant_request", "grant_approve", "grant_deny",
                                             "grant_revoke", "grants", "intercept",
                                             "gate_tool", "capabilities", "planning_tools", "verify_acceptance",
                                             "planning_handoff", "review_read", "delete_path"))
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args(argv)
    data = json.load(sys.stdin)
    bridge = V6HostBridge(args.project) if args.operation != "check" else None
    try:
        if args.operation == "check":
            result = (V6HostBridge(args.project).check(
                data["run_id"], data["target"], data.get("call_id"),
                data.get("node_id"), data.get("child_session_id"))
                      if data.get("run_id") else run_check(args.project, data["target"]))
        elif args.operation == "fenced_shell":
            def cancel(_signum, _frame):
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, cancel)
            result = bridge.fenced_shell(data["run_id"], data["call_id"], data["child_session_id"],
                                         data["role"], data["commands"], data.get("cwd", "."))
        elif args.operation == "templates":
            result = V6HostBridge(args.project).templates()
        elif args.operation == "runs":
            result = V6HostBridge(args.project).list_runs()
        elif args.operation == "grant_request":
            result = bridge.grant_request(
                data["run_id"], data["node_id"], data["kind"],
                data.get("scope"), data.get("constraints"),
                data.get("reason", ""), data.get("ttl_seconds"),
                data.get("mode", "once"))
        elif args.operation == "grant_approve":
            result = bridge.grant_approve(
                data["run_id"], data["request_id"],
                approver=data.get("approver", "human"),
                via=data.get("via", "host"), mode=data.get("mode", "once"),
                ttl_seconds=data.get("ttl_seconds"))
        elif args.operation == "grant_deny":
            result = bridge.grant_deny(data["run_id"], data["request_id"],
                                       data.get("reason", ""))
        elif args.operation == "grant_revoke":
            result = bridge.grant_revoke(data["run_id"], data["grant_id"],
                                         data.get("reason", ""))
        elif args.operation == "grants":
            result = bridge.grants(data["run_id"])
        elif args.operation == "intercept":
            result = bridge.intercept(data["run_id"], data["tool"],
                                      data.get("input"), data.get("node_id"))
        elif args.operation == "gate_tool":
            result = bridge.gate_tool(data["run_id"], data["node_id"],
                                      data["tool"], data.get("input"))
        elif args.operation == "capabilities":
            result = bridge.capabilities()
        elif args.operation == "planning_tools":
            result = bridge.planning_tools()
        elif args.operation == "verify_acceptance":
            result = bridge.verify_acceptance(data["run_id"], data["call_id"],
                                              data["child_session_id"], data["passed"], data["findings"])
        elif args.operation == "planning_handoff":
            result = bridge.planning_handoff(data["run_id"], data["parent_session_id"])
        elif args.operation == "record_interruption":
            result = bridge.record_interruption(data["run_id"], data["session_id"],
                                                data["stage"], data["reason"], data.get("event_id"))
        elif args.operation == "review_read":
            bridge.observe_review_read(data["run_id"], data["call_id"], data["child_session_id"],
                                       data["path"], data["output_sha256"])
            result = {"recorded": True}
        elif args.operation == "delete_path":
            result = bridge.delete_path(data["run_id"], data["node_id"], data["path"])
        elif args.operation == "metrics":
            result = V6HostBridge(args.project).metrics(data.get("run_id"))
        elif args.operation == "plan":
            nodes = data.get("nodes", data.get("node"))
            objective = data.get("objective", "")
            request_class = data.get("request_class")
            access_mode = data.get("access_mode")
            if "template" in data:
                template = data["template"]
                objective = template["objective"]
                if template.get("type") == "bug_fix":
                    graph = bug_fix_template(
                        objective, tuple(template["write_scope"]),
                        lightweight=bool(data.get("adaptive_verification"))
                        and access_mode in {None, "workspace-write"} and data.get("host", "opencode") == "opencode")
                    request_class = "bug-fix"
                elif template.get("type") == "read_only_scan":
                    if template.get("write_scope"):
                        raise ValueError("read_only_scan cannot have write_scope")
                    graph = read_only_scan_template(objective)
                    access_mode = "read-only"
                    request_class = "read-only-scan"
                else:
                    raise ValueError("unknown plan template")
                nodes = [node.to_dict() for node in graph.nodes.values()]
            result = bridge.plan(
                nodes, data["host_session_id"], request_class=request_class,
                template_id=data.get("template_id"), objective=objective,
                write_scope=data.get("write_scope"), test_scope=data.get("test_scope"),
                skip=data.get("skip"), access_mode=access_mode,
                session_title=data.get("session_title", ""), slug=data.get("slug", ""),
                host=data.get("host", "opencode"), intent=data.get("intent"),
                satisfies_map=data.get("satisfies"), parent_run_id=data.get("parent_run_id"),
                supersedes_run_id=data.get("supersedes_run_id"),
                change_reason=data.get("change_reason", ""), seed_from_run_id=data.get("seed_from_run_id"),
                planned_verification=bool(data.get("planned_verification")),
                adaptive_verification=bool(data.get("adaptive_verification")), gates=data.get("gates"))
        elif args.operation == "plan_op":
            result = bridge.plan_op(data["run_id"], data["operation"],
                                    planner_session_id=data.get("planner_session_id"))
        elif args.operation == "state":
            result = (bridge.verify_pending(data["run_id"], retry=bool(data.get("retry_checks")))
                      if data.get("verify_pending") else bridge.published_state(data["run_id"]))
        elif args.operation == "review_plan":
            result = bridge.review_plan(data["run_id"])
        elif args.operation == "ask":
            result = bridge.ask(data["run_id"], data["question"], data.get("answers"),
                                approved=bool(data.get("approved")))
        elif args.operation == "before":
            result = bridge.before(data["run_id"], data["node_id"], data["role"],
                                   data["card"], data["call_id"], data.get("active_token"))
        elif args.operation == "after":
            result = bridge.after(data["run_id"], data["call_id"], data["token"],
                                  data.get("child_session_id"), data["tool_status"],
                                  data["duration_ms"], data.get("output_sha256"))
        elif args.operation == "bind":
            result = bridge.bind(data["run_id"], data["call_id"], data["token"],
                                 data["child_session_id"], data["write_scope"],
                                 data.get("external_scope"))
        elif args.operation == "permission":
            result = bridge.permission(data["run_id"], data["call_id"], data["request_id"],
                                       data["action"], data["resources"], data.get("reply"),
                                       granted=bool(data.get("granted")))
        elif args.operation == "external_write":
            result = bridge.external_write(data["run_id"], data["call_id"],
                                           data["tool_call_id"], data["target"],
                                           data["content_sha256"], data["outcome"],
                                           data.get("detail"), data.get("changed_lines"))
        elif args.operation == "review_reject":
            result = bridge.review_reject(data["run_id"], data["call_id"], data["token"],
                                          data["child_session_id"], data["affected_node_id"],
                                          data["diagnostic"])
        else:
            result = bridge.finish(data["run_id"], data["token"], data["child_session_id"],
                                   call_id=data.get("call_id"),
                                   child_error=bool(data.get("child_error")))
    except PlanValidationError as exc:
        print(json.dumps({"error": str(exc), "findings": exc.findings}, ensure_ascii=False))
        return 2
    except (HostBridgeError, CheckRejected, KeyError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
