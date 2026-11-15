"""JSON bridge called by the OpenCode plugin without shell interpolation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .hosts import OpenCodeWorkflowHost
from .orchestrator import RunCoordinator
from .runstore import RunStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cybertron-plugin-bridge")
    parser.add_argument("operation", choices=("start", "continue", "status"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--host-session", required=True)
    parser.add_argument("--request")
    parser.add_argument("--run-id")
    parser.add_argument("--mode", choices=("software", "hardware"), default="software")
    parser.add_argument("--answer")
    args = parser.parse_args(argv)
    store = RunStore(Path(args.project))
    coordinator = RunCoordinator(store, OpenCodeWorkflowHost(Path(args.project)))
    if args.operation == "start":
        if not args.request:
            parser.error("start requires --request")
        created = store.create(args.request, mode=args.mode)
        run_id = created["run_id"]
        store.transition(run_id, "ui.session.bound", lambda ledger: None,
                         payload={"host": "opencode-v2", "host_session_id": args.host_session})
        result = coordinator.status(run_id)
    else:
        if not args.run_id:
            parser.error(f"{args.operation} requires --run-id")
        run_id = args.run_id
        if args.operation == "continue" and args.answer:
            state = coordinator.status(run_id)
            if state["status"] == "blocked" and state["stage_id"] == 1:
                def clarify(ledger) -> None:
                    ledger.known_facts.append(args.answer)
                    ledger.user_request += "\n补充说明：" + args.answer
                    ledger.resume_step(1)
                store.transition(run_id, "run.clarified", clarify, stage_id=1,
                                 payload={"answer": args.answer},
                                 expected_seq=state["event_seq"])
        result = coordinator.run_until_blocked(run_id) if args.operation == "continue" else coordinator.status(run_id)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
