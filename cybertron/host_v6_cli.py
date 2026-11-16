"""JSON stdin/stdout bridge for OpenCode V2's native subagent hook."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .host_v6 import HostBridgeError, V6HostBridge


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cybertron-v6-host")
    parser.add_argument("operation", choices=("plan", "state", "ask", "before", "after", "finish"))
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args(argv)
    data = json.load(sys.stdin)
    bridge = V6HostBridge(args.project)
    try:
        if args.operation == "plan":
            result = bridge.plan(data["node"], data["host_session_id"])
        elif args.operation == "state":
            result = bridge.state(data["run_id"])
        elif args.operation == "ask":
            result = bridge.ask(data["run_id"], data["question"])
        elif args.operation == "before":
            result = bridge.before(data["run_id"], data["node_id"], data["role"],
                                   data["card"], data["call_id"], data.get("active_token"))
        elif args.operation == "after":
            result = bridge.after(data["run_id"], data["call_id"], data["token"],
                                  data.get("child_session_id"), data["tool_status"],
                                  data["duration_ms"], data.get("output_sha256"))
        else:
            result = bridge.finish(data["run_id"], data["token"], data["child_session_id"])
    except (HostBridgeError, KeyError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
