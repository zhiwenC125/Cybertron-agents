"""JSON stdin/stdout bridge for OpenCode V2's native subagent hook."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .host_v6 import HostBridgeError, V6HostBridge
from .templates import bug_fix_template, read_only_scan_template
from .profiles import CheckRejected, run_check


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cybertron-v6-host")
    parser.add_argument("operation", choices=("plan", "plan_op", "state", "review_plan", "ask",
                                             "before", "after", "bind", "permission",
                                             "review_reject", "finish",
                                             "check", "templates", "metrics",
                                             "grant_request", "grant_approve", "grant_deny",
                                             "grant_revoke", "grants", "intercept",
                                             "gate_tool", "capabilities", "delete_path"))
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args(argv)
    data = json.load(sys.stdin)
    bridge = V6HostBridge(args.project) if args.operation != "check" else None
    try:
        if args.operation == "check":
            result = (V6HostBridge(args.project).check(
                data["run_id"], data["target"], data.get("call_id"),
                data.get("node_id"))
                      if data.get("run_id") else run_check(args.project, data["target"]))
        elif args.operation == "templates":
            result = V6HostBridge(args.project).templates()
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
        elif args.operation == "delete_path":
            result = bridge.delete_path(data["run_id"], data["node_id"], data["path"])
        elif args.operation == "metrics":
            result = V6HostBridge(args.project).metrics(data.get("run_id"))
        elif args.operation == "plan":
            if "template_id" in data:
                result = bridge.plan(None, data["host_session_id"],
                                     request_class=data.get("request_class"),
                                     template_id=data["template_id"],
                                     objective=data.get("objective", ""),
                                     write_scope=data.get("write_scope"),
                                     test_scope=data.get("test_scope"),
                                     skip=data.get("skip"),
                                     access_mode=data.get("access_mode"),
                                     session_title=data.get("session_title", ""),
                                     slug=data.get("slug", ""),
                                     intent=data.get("intent"),
                                     satisfies_map=data.get("satisfies"),
                                     parent_run_id=data.get("parent_run_id"),
                                     supersedes_run_id=data.get("supersedes_run_id"),
                                     change_reason=data.get("change_reason", ""),
                                     seed_from_run_id=data.get("seed_from_run_id"))
            elif "template" in data:
                if data.get("intent") is not None:
                    raise ValueError("intent requires explicit node or nodes; templates cannot carry intent")
                template = data["template"]
                if template.get("type") == "bug_fix":
                    graph = bug_fix_template(template["objective"], tuple(template["write_scope"]))
                    request_class = "bug-fix"
                elif template.get("type") == "read_only_scan":
                    if template.get("write_scope"):
                        raise ValueError("read_only_scan cannot have write_scope")
                    graph = read_only_scan_template(template["objective"])
                    request_class = "read-only-scan"
                else:
                    raise ValueError("unknown plan template")
                nodes = [node.to_dict() for node in graph.nodes.values()]
                result = bridge.plan(nodes, data["host_session_id"],
                                     request_class=request_class,
                                     objective=template["objective"],
                                     access_mode=data.get("access_mode"),
                                     session_title=data.get("session_title", ""),
                                     slug=data.get("slug", ""),
                                     host=data.get("host", "opencode"),
                                     intent=data.get("intent"),
                                     satisfies_map=data.get("satisfies"),
                                     parent_run_id=data.get("parent_run_id"),
                                     supersedes_run_id=data.get("supersedes_run_id"),
                                     change_reason=data.get("change_reason", ""),
                                     seed_from_run_id=data.get("seed_from_run_id"))
            else:
                nodes = data.get("nodes", data.get("node"))
                result = bridge.plan(nodes, data["host_session_id"],
                                     request_class=data.get("request_class"),
                                     objective=data.get("objective", ""),
                                     access_mode=data.get("access_mode"),
                                     session_title=data.get("session_title", ""),
                                     slug=data.get("slug", ""),
                                     host=data.get("host", "opencode"),
                                     intent=data.get("intent"),
                                     satisfies_map=data.get("satisfies"),
                                     parent_run_id=data.get("parent_run_id"),
                                     supersedes_run_id=data.get("supersedes_run_id"),
                                     change_reason=data.get("change_reason", ""),
                                     seed_from_run_id=data.get("seed_from_run_id"))
        elif args.operation == "plan_op":
            result = bridge.plan_op(data["run_id"], data["operation"])
        elif args.operation == "state":
            result = bridge.state(data["run_id"])
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
        elif args.operation == "review_reject":
            result = bridge.review_reject(data["run_id"], data["call_id"], data["token"],
                                          data["child_session_id"], data["affected_node_id"],
                                          data["diagnostic"])
        else:
            result = bridge.finish(data["run_id"], data["token"], data["child_session_id"],
                                   call_id=data.get("call_id"),
                                   child_error=bool(data.get("child_error")))
    except (HostBridgeError, CheckRejected, KeyError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
