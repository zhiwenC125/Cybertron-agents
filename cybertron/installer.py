"""pipx/Python 安装入口：``cybertron init`` 与 ``cybertron doctor``。

与 npm CLI、install.sh 共享同一份 payload（``.opencode/agents`` +
``.opencode/commands``）。默认只预览，``--apply`` 才写盘。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO = "zhiwenC125/Cybertron-agents"
DEFAULT_REF = "main"
KNOWN_AGENT_COUNT = 13
MINIMAL_CONFIG = (
    '{\n'
    '  "$schema": "https://opencode.ai/config.json",\n'
    '  "default_agent": "prima"\n'
    '}\n'
)

CONFIG_LABELS = {
    "would-create": "将写入最小配置",
    "filled-empty": "将补全 default_agent",
    "has-default": "已有 default_agent",
    "set-default": "将补 default_agent",
    "parse-failed": "无法解析，跳过",
    "not-object": "不是对象，跳过",
}


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("cybertron-agents")
    except Exception:
        return "0.1.0"


def default_base(global_install: bool, project: str) -> Path:
    if global_install:
        config_home = os.environ.get("XDG_CONFIG_HOME")
        root = Path(config_home) if config_home else Path.home() / ".config"
        return root / "opencode"
    return Path(project or ".") / ".opencode"


def find_payload_dir(base: Path) -> Path:
    """返回同时含 ``agents/`` 与 ``commands/`` 的目录。"""
    for candidate in (base, base / "payload", base / ".opencode"):
        if (candidate / "agents").is_dir():
            return candidate
    raise SystemExit(f"找不到 payload（缺少 agents/）: {base}")


def resolve_payload(
    explicit: str, ref: str, expected_sha256: str, allow_download: bool = True
):
    if explicit:
        return find_payload_dir(Path(explicit).resolve())

    here = Path(__file__).resolve().parent
    repo = here.parent
    if (repo / ".opencode" / "agents").is_dir():
        return repo / ".opencode"

    bundled = here / "payload"
    if (bundled / "agents").is_dir():
        return bundled

    if allow_download:
        return download_payload(ref, expected_sha256)
    return None


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    dest = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if target != dest and dest not in target.parents:
            raise SystemExit(f"拒绝不安全的归档路径: {member.name}")
    tar.extractall(dest)


def download_payload(ref: str, expected_sha256: str = "") -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="cybertron-install-"))
    if ref.startswith("v"):
        url = f"https://github.com/{REPO}/archive/refs/tags/{ref}.tar.gz"
    else:
        url = f"https://github.com/{REPO}/archive/refs/heads/{ref}.tar.gz"
    archive = tmp / "src.tar.gz"
    print(f"下载: {url}")
    with urllib.request.urlopen(url) as response, open(archive, "wb") as handle:
        shutil.copyfileobj(response, handle)

    if expected_sha256:
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != expected_sha256:
            raise SystemExit(f"SHA-256 校验失败：期望 {expected_sha256}，实际 {actual}")
        print("SHA-256 校验通过")

    with tarfile.open(archive) as tar:
        _safe_extract(tar, tmp)
    for child in tmp.iterdir():
        if child.is_dir() and (child / ".opencode" / "agents").is_dir():
            return child / ".opencode"
    raise SystemExit("归档中未找到 .opencode/agents")


def list_markdown(directory: Path) -> list:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.suffix == ".md")


def plan(payload: Path, base: Path) -> list:
    items = []
    for kind in ("agents", "commands"):
        for src in list_markdown(payload / kind):
            target = base / kind / src.name
            if target.exists():
                state = "same" if src.read_bytes() == target.read_bytes() else "update"
            else:
                state = "new"
            items.append((kind, src, target, state))
    return items


def strip_jsonc(text: str) -> str:
    out = []
    i = 0
    size = len(text)
    in_string = False
    quote = ""
    while i < size:
        char = text[i]
        nxt = text[i + 1] if i + 1 < size else ""
        if in_string:
            out.append(char)
            if char == "\\":
                if i + 1 < size:
                    out.append(nxt)
                i += 2
                continue
            if char == quote:
                in_string = False
            i += 1
            continue
        if char in "\"'":
            in_string = True
            quote = char
            out.append(char)
            i += 1
            continue
        if char == "/" and nxt == "/":
            while i < size and text[i] != "\n":
                i += 1
            continue
        if char == "/" and nxt == "*":
            i += 2
            while i < size and not (text[i] == "*" and i + 1 < size and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def ensure_config(base: Path, dry_run: bool) -> tuple:
    path = base / "opencode.jsonc"
    if not path.exists():
        if not dry_run:
            base.mkdir(parents=True, exist_ok=True)
            path.write_text(MINIMAL_CONFIG, encoding="utf-8")
        return "would-create", path

    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        if not dry_run:
            path.write_text(MINIMAL_CONFIG, encoding="utf-8")
        return "filled-empty", path

    try:
        data = json.loads(strip_jsonc(raw))
    except json.JSONDecodeError:
        return "parse-failed", path
    if not isinstance(data, dict):
        return "not-object", path
    if "default_agent" in data:
        return "has-default", path

    data["default_agent"] = "prima"
    if not dry_run:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return "set-default", path


def apply_install(items: list) -> tuple:
    created = updated = same = 0
    for _kind, src, target, state in items:
        if state == "new":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            created += 1
        elif state == "update":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target, target.with_suffix(target.suffix + ".bak"))
            shutil.copyfile(src, target)
            updated += 1
        else:
            same += 1
    return created, updated, same


def run_init(args) -> int:
    payload = resolve_payload(args.payload, args.ref, args.sha256)
    base = default_base(args.global_, args.project)
    dry_run = not args.apply
    items = plan(payload, base)
    if not items:
        raise SystemExit("payload 为空，未找到可安装的 Markdown")

    print(f"安装目标: {base}")
    print(f"payload: {payload}")
    print(f"模式: {'预览（dry-run，加 --apply 写入）' if dry_run else '写入（--apply）'}")
    marks = {"new": "+", "update": "~", "same": "="}
    for _kind, _src, target, state in items:
        note = " (备份为 .bak 后覆盖)" if state == "update" else ""
        print(f"  {marks[state]} {target}{note}")

    action, config_path = ensure_config(base, dry_run)
    print(f"配置: {config_path} -> {CONFIG_LABELS.get(action, action)}")

    if dry_run:
        print("\n这是预览。确认后加 --apply 执行。")
        return 0

    created, updated, same = apply_install(items)
    print(f"\n新增 {created}，更新 {updated}，未变 {same}")
    print("安装完成。运行: opencode2 debug agents")
    return 0


def run_doctor(args) -> int:
    base = default_base(args.global_, args.project)
    payload = resolve_payload(
        args.payload, args.ref, args.sha256, allow_download=False
    )
    agents = list_markdown(base / "agents")
    commands = list_markdown(base / "commands")
    if payload is None:
        expected = KNOWN_AGENT_COUNT
        source = "内置期望值（未联网下载）"
    else:
        expected = len(list_markdown(payload / "agents"))
        source = f"本地 payload: {payload}"
    config = base / "opencode.jsonc"

    print(f"目标: {base}")
    print(f"角色来源: {source}")
    print(f"已安装角色: {len(agents)}（期望 {expected}）")
    print(f"已安装命令: {len(commands)}")
    print(f"配置: {'存在' if config.exists() else '缺失'}")
    print(f"python: {sys.version.split()[0]}")
    if len(agents) != expected:
        print("提示: 角色数量不符，运行 cybertron init --apply 重新安装。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cybertron",
        description="把塞伯坦十三天尊安装到 OpenCode 配置目录。",
    )
    parser.add_argument(
        "--version", action="version", version=f"cybertron-agents {_version()}"
    )
    sub = parser.add_subparsers(dest="command")

    init_parser = sub.add_parser("init", help="安装角色与 /cybertron 命令")
    init_parser.add_argument("--global", dest="global_", action="store_true")
    init_parser.add_argument("--project", default=".")
    init_parser.add_argument("--payload", default="")
    init_parser.add_argument("--ref", default=DEFAULT_REF)
    init_parser.add_argument("--sha256", default="")
    init_parser.add_argument("--apply", action="store_true")
    init_parser.add_argument("--dry-run", dest="apply", action="store_false")

    doctor_parser = sub.add_parser("doctor", help="检查安装状态")
    doctor_parser.add_argument("--global", dest="global_", action="store_true")
    doctor_parser.add_argument("--project", default=".")
    doctor_parser.add_argument("--payload", default="")
    doctor_parser.add_argument("--ref", default=DEFAULT_REF)
    doctor_parser.add_argument("--sha256", default="")

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return run_init(args)
    if args.command == "doctor":
        return run_doctor(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
