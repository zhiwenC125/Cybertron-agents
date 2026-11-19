"""Human-facing CLI for v6 runs, intent coverage, and grants."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .host_v6 import HostBridgeError, V6HostBridge


def _runs(project: Path) -> list[dict]:
    bridge = V6HostBridge(project)
    root = project / ".cybertron" / "runs"
    if not root.is_dir():
        return []
    runs = []
    for directory in sorted(root.iterdir()):
        if directory.is_symlink() or not directory.is_dir():
            continue
        run_file = directory / "run.json"
        if not run_file.is_file() or run_file.is_symlink():
            continue
        try:
            data = json.loads(run_file.read_text())
        except (OSError, ValueError):
            continue
        run_id = data.get("run_id")
        if not isinstance(run_id, str):
            continue
        try:
            state = bridge.state(run_id)
        except HostBridgeError:
            continue
        runs.append({"meta": data, "state": state})
    runs.sort(key=lambda item: item["meta"].get("created_utc") or "")
    return runs


def _coverage(state: dict) -> str:
    items = state.get("intent_coverage") or []
    if not items:
        return "-"
    done = sum(1 for item in items if item.get("satisfied"))
    return f"{done}/{len(items)}"


def cmd_runs(args) -> int:
    runs = _runs(Path(args.project).resolve())
    if not runs:
        print("没有 v6 run。")
        return 0
    print("| run | slug | status | intent | parent | superseded_by |")
    print("| --- | --- | --- | --- | --- | --- |")
    for item in runs:
        meta, state = item["meta"], item["state"]
        print(f"| {meta.get('run_id', '')[:8]} | {meta.get('slug', '-')} | "
              f"{state.get('status', '-')} | {_coverage(state)} | "
              f"{(meta.get('parent_run_id') or '-')[:8]} | "
              f"{(meta.get('superseded_by') or '-')[:8]} |")
    return 0


def cmd_show(args) -> int:
    bridge = V6HostBridge(Path(args.project).resolve())
    try:
        state = bridge.state(args.run)
    except HostBridgeError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    meta = {}
    run_file = Path(state["run_dir"]) / "run.json"
    if run_file.is_file():
        try:
            meta = json.loads(run_file.read_text())
        except (OSError, ValueError):
            meta = {}
    print(f"run: {state['run_id']}")
    print(f"slug: {meta.get('slug', '-')}")
    print(f"status: {state['status']}")
    print(f"access_mode: {state['access_mode']}")
    print(f"parent: {meta.get('parent_run_id') or '-'}")
    print(f"superseded_by: {meta.get('superseded_by') or '-'}")
    print(f"intent: {state.get('intent', {}).get('goal') if state.get('intent') else '-'}")
    print(f"coverage: {_coverage(state)}")
    for item in state.get("intent_coverage") or []:
        mark = "OK" if item.get("satisfied") else "MISS"
        print(f"  [{mark}] {item['id']}: {item['criterion']}")
    print("nodes:")
    for node in state.get("nodes") or []:
        print(f"  {node['node_id']:<12} {node['status']:<10} {node['role']}")
    grants = state.get("grants") or []
    print(f"grants: {len(grants)}")
    for grant in grants:
        print(f"  {grant.get('kind')} {grant.get('node_id')} {grant.get('status')}")
    return 0


def cmd_grants(args) -> int:
    bridge = V6HostBridge(Path(args.project).resolve())
    try:
        grants = bridge.grants(args.run)
    except HostBridgeError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    if not grants:
        print("没有 Grant。")
        return 0
    print("| kind | node | status | mode | uses | expires |")
    print("| --- | --- | --- | --- | --- | --- |")
    for grant in grants:
        print(f"| {grant.get('kind')} | {grant.get('node_id')} | "
              f"{grant.get('status')} | {grant.get('mode', '-')} | "
              f"{grant.get('uses', 0)}/{grant.get('max_uses', '-')} | "
              f"{grant.get('expires_utc', '-')} |")
    return 0


def cmd_lineage(args) -> int:
    bridge = V6HostBridge(Path(args.project).resolve())
    run_id = args.run
    seen = set()
    chain = []
    while run_id and run_id not in seen:
        seen.add(run_id)
        try:
            state = bridge.state(run_id)
        except HostBridgeError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 2
        run_file = Path(state["run_dir"]) / "run.json"
        meta = {}
        if run_file.is_file():
            try:
                meta = json.loads(run_file.read_text())
            except (OSError, ValueError):
                meta = {}
        chain.append((run_id, meta.get("slug", "-"), state.get("status", "-")))
        run_id = meta.get("parent_run_id")
    for index, (run_id, slug, status) in enumerate(reversed(chain)):
        print(f"{'  ' * index}{run_id[:8]} {slug} [{status}]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cybertron v6",
                                     description="查看 v6 run、Intent 覆盖与 Grant。")
    parser.add_argument("--project", default=".")
    sub = parser.add_subparsers(dest="operation")

    runs = sub.add_parser("runs", help="列出所有 v6 run")
    runs.add_argument("--project", default=None)
    runs.set_defaults(func=cmd_runs)
    show = sub.add_parser("show", help="查看一个 run")
    show.add_argument("run")
    show.add_argument("--project", default=None)
    show.set_defaults(func=cmd_show)
    grants = sub.add_parser("grants", help="列出一个 run 的 Grant")
    grants.add_argument("run")
    grants.add_argument("--project", default=None)
    grants.set_defaults(func=cmd_grants)
    lineage = sub.add_parser("lineage", help="查看 run 的父链")
    lineage.add_argument("run")
    lineage.add_argument("--project", default=None)
    lineage.set_defaults(func=cmd_lineage)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    if getattr(args, "project", None) is None:
        args.project = "."
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
