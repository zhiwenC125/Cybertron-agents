"""Offline CLI for creating, inspecting, verifying, and resuming a run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runstore import RunStore, RunStoreError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cybertron run")
    parser.add_argument("operation", choices=("create", "show", "verify", "resume"))
    parser.add_argument("value", help="request for create; run ID for other operations")
    parser.add_argument("--project", default=".")
    args = parser.parse_args(argv)
    store = RunStore(Path(args.project))
    try:
        result = getattr(store, args.operation)(args.value)
    except (RunStoreError, ValueError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
