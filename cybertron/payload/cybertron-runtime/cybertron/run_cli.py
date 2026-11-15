"""Offline CLI for creating, inspecting, verifying, and resuming a run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runstore import RunStore, RunStoreError
from .sessions import SessionStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cybertron run")
    parser.add_argument("operation", choices=("create", "show", "verify", "resume", "list"))
    parser.add_argument("value", nargs="?", help="request for create; run ID for other operations")
    parser.add_argument("--project", default=".")
    parser.add_argument("--session", help="session slug or ID for create/list")
    args = parser.parse_args(argv)
    store = RunStore(Path(args.project))
    try:
        if args.operation == "list":
            if not args.session:
                parser.error("run list requires --session")
            result = SessionStore(Path(args.project)).list_runs(args.session)
        elif args.operation == "create" and args.session:
            if not args.value:
                parser.error("run create requires a request")
            result = SessionStore(Path(args.project)).create_run(args.session, args.value)
        else:
            if not args.value:
                parser.error(f"run {args.operation} requires a value")
            result = getattr(store, args.operation)(args.value)
    except (RunStoreError, ValueError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
