"""CLI for stable session IDs and human-readable slugs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runstore import RunStoreError
from .sessions import SessionStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cybertron session")
    parser.add_argument("operation", choices=("create", "list", "show", "rename", "archive", "unarchive"))
    parser.add_argument("reference", nargs="?", help="slug or session ID")
    parser.add_argument("new_slug", nargs="?", help="new slug for rename")
    parser.add_argument("--title", default=None)
    parser.add_argument("--project", default=".")
    args = parser.parse_args(argv)
    store = SessionStore(Path(args.project))
    try:
        if args.operation == "list":
            result = store.list()
        elif args.operation == "create":
            if not args.reference:
                parser.error("session create requires a slug")
            result = store.create(args.reference, args.title or "")
        elif args.operation == "rename":
            if not args.reference or not args.new_slug:
                parser.error("session rename requires old and new slugs")
            result = store.rename(args.reference, args.new_slug, args.title)
        else:
            if not args.reference:
                parser.error(f"session {args.operation} requires a slug or ID")
            if args.operation == "show":
                result = store.show(args.reference)
            else:
                result = store.archive(args.reference, args.operation == "archive")
    except (RunStoreError, ValueError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
