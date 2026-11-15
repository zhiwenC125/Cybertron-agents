"""Offline-first entry point for the persistent outer workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .hosts import FakeHost, OpenCodeReadOnlyHost
from .opencode_v2 import validate_bundle
from .orchestrator import RunCoordinator
from .runstore import RunStore, RunStoreError
from .sessions import SessionStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cybertron workflow")
    parser.add_argument("operation", choices=("create", "step", "run", "status", "resume", "doctor"))
    parser.add_argument("value", nargs="?", help="request for create; run ID for other operations")
    parser.add_argument("--project", default=".")
    parser.add_argument("--session", help="existing session slug for create")
    parser.add_argument("--host", choices=("fake", "opencode-readonly"), default="fake")
    parser.add_argument("--allow-external-model", action="store_true",
                        help="explicitly permit real read-only OpenCode model calls")
    parser.add_argument("--simulate-hardware-approval", action="store_true")
    parser.add_argument("--reject-review-once", action="store_true")
    args = parser.parse_args(argv)
    workspace = Path(args.project).resolve()
    store = RunStore(workspace)
    try:
        if args.operation == "doctor":
            errors = validate_bundle(workspace)
            result = {"config_valid": not errors, "errors": errors,
                      "external_model_called": False}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if not errors else 1
        if not args.value:
            parser.error(f"workflow {args.operation} requires a request or run ID")
        if args.operation == "create":
            result = SessionStore(workspace).create_run(args.session, args.value) if args.session else store.create(args.value)
        else:
            if args.host == "opencode-readonly":
                if args.operation in ("step", "run") and not args.allow_external_model:
                    parser.error("Real OpenCode calls require --allow-external-model")
                host = OpenCodeReadOnlyHost(workspace)
            else:
                host = FakeHost(reject_review_once=args.reject_review_once,
                                simulate_hardware_approval=args.simulate_hardware_approval)
            coordinator = RunCoordinator(store, host)
            if args.operation == "step":
                result = coordinator.step(args.value)
            elif args.operation == "run":
                result = coordinator.run_until_blocked(args.value)
            elif args.operation == "resume":
                store.resume(args.value)
                result = coordinator.status(args.value)
            else:
                result = coordinator.status(args.value)
    except (RunStoreError, ValueError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
