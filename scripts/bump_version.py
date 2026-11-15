"""Keep the npm, Python, Shell and fallback versions in sync."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCES = (
    "package.json",
    "pyproject.toml",
    "install.sh",
    "cybertron/installer.py",
)
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def current_versions(files: dict[str, str]) -> dict[str, str]:
    package = json.loads(files["package.json"])["version"]
    patterns = {
        "pyproject.toml": r'(?m)^version = "([0-9]+\.[0-9]+\.[0-9]+)"$',
        "install.sh": r'(?m)^VERSION="v([0-9]+\.[0-9]+\.[0-9]+)"$',
        "cybertron/installer.py": r'(?m)^DEFAULT_REF = "v([0-9]+\.[0-9]+\.[0-9]+)"$',
    }
    versions = {"package.json": package}
    for name, pattern in patterns.items():
        matches = re.findall(pattern, files[name])
        if len(matches) != 1:
            raise ValueError(f"Cannot identify one version in {name}")
        versions[name] = matches[0]
    fallback = re.findall(r'(?m)^        return "([0-9]+\.[0-9]+\.[0-9]+)"$',
                          files["cybertron/installer.py"])
    if len(fallback) != 1 or fallback[0] != versions["cybertron/installer.py"]:
        raise ValueError("Python fallback version differs from DEFAULT_REF")
    if not all(VERSION.fullmatch(value) for value in versions.values()):
        raise ValueError("Versions must use X.Y.Z")
    if len(set(versions.values())) != 1:
        raise ValueError(f"Version mismatch: {versions}")
    return versions


def render(files: dict[str, str], target: str) -> dict[str, str]:
    old = next(iter(current_versions(files).values()))
    if not VERSION.fullmatch(target):
        raise ValueError("Target version must use X.Y.Z")
    if tuple(map(int, target.split("."))) <= tuple(map(int, old.split("."))):
        raise ValueError(f"Target {target} must be newer than {old}")
    replacements = {
        "package.json": [(f'"version": "{old}"', f'"version": "{target}"')],
        "pyproject.toml": [(f'version = "{old}"', f'version = "{target}"')],
        "install.sh": [(f'VERSION="v{old}"', f'VERSION="v{target}"'),
                       (f'默认 v{old}', f'默认 v{target}')],
        "cybertron/installer.py": [(f'DEFAULT_REF = "v{old}"',
                                    f'DEFAULT_REF = "v{target}"'),
                                   (f'        return "{old}"',
                                    f'        return "{target}"')],
    }
    result = {}
    for name, changes in replacements.items():
        content = files[name]
        for before, after in changes:
            if content.count(before) != 1:
                raise ValueError(f"Expected exactly one {before!r} in {name}")
            content = content.replace(before, after, 1)
        result[name] = content
    current_versions(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", help="next X.Y.Z version")
    parser.add_argument("--check", action="store_true", help="verify synchronized versions")
    parser.add_argument("--dry-run", action="store_true", help="preview changes only")
    args = parser.parse_args(argv)
    try:
        files = {name: (ROOT / name).read_text(encoding="utf-8") for name in SOURCES}
        versions = current_versions(files)
        old = next(iter(versions.values()))
        if args.check:
            if args.version and args.version != old:
                raise ValueError(f"Expected {args.version}, found {old}")
            print(f"Versions aligned: {old}")
            return 0
        if not args.version:
            parser.error("a target version or --check is required")
        updated = render(files, args.version)
        for name in SOURCES:
            print(f"{name}: {old} -> {args.version}")
        if args.dry_run:
            return 0
        written = []
        try:
            for name in SOURCES:
                target = ROOT / name
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                                                 prefix=".cybertron-version-", delete=False) as stream:
                    stream.write(updated[name])
                    temporary = Path(stream.name)
                temporary.chmod(target.stat().st_mode & 0o777)
                temporary.replace(target)
                written.append(name)
        except Exception:
            for name in reversed(written):
                (ROOT / name).write_text(files[name], encoding="utf-8")
            raise
        print("Run node scripts/build-payload.mjs, then update release notes and tests.")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Version error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
