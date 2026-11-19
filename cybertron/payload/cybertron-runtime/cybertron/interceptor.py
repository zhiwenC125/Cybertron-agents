"""Thin execution interceptor for full-access runs.

Full access relaxes path location but never makes irreversible actions silent:
a short, code-reviewed list of dangerous commands and core-config writes must
be confirmed again at the node level.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from typing import Any, Mapping


DANGEROUS_PATTERNS = (
    ("filesystem", re.compile(r"(^|[;&|]\s*)rm\s+-(?:[a-zA-Z]*r[a-zA-Z]*f|f[a-zA-Z]*r)\b", re.I)),
    ("filesystem", re.compile(r"\bmkfs(?:\.|\s|$)", re.I)),
    ("filesystem", re.compile(r"\bdd\b[^\n]*\bof\s*=\s*/dev/", re.I)),
    ("filesystem", re.compile(r"\bshred\b", re.I)),
    ("filesystem", re.compile(r"\btruncate\b[^\n]*-s\s*0\b", re.I)),
    ("database", re.compile(r"\bdrop\s+(?:database|table)\b", re.I)),
    ("database", re.compile(r"\btruncate\s+table\b", re.I)),
    ("database", re.compile(r"\bdelete\s+from\b(?![\s\S]*\bwhere\b)", re.I)),
    ("git", re.compile(r"\bgit\s+push\b[^\n]*--force", re.I)),
    ("git", re.compile(r"\bgit\s+reset\s+--hard\b", re.I)),
    ("system", re.compile(r"\b(?:shutdown|reboot|halt|poweroff)\b", re.I)),
    ("system", re.compile(r"\bkill\s+-9\s+1\b|\bpkill\b", re.I)),
    ("remote", re.compile(r"\b(?:curl|wget)\b[^\n|\n]*\|\s*(?:ba)?sh\b", re.I)),
)

CORE_CONFIG_NAMES = frozenset({
    "opencode.jsonc", ".git/config", "AGENTS.md", ".bashrc", ".zshrc",
    "authorized_keys", "sshd_config",
})


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _command(tool: str, payload: Mapping[str, Any] | str | None) -> str | None:
    if tool in {"bash", "shell"} and isinstance(payload, str):
        return payload
    if not isinstance(payload, Mapping):
        return None
    if tool in {"bash", "shell"}:
        value = payload.get("command") or payload.get("cmd")
        return value if isinstance(value, str) else None
    return None


def _path(tool: str, payload: Mapping[str, Any] | str | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    if tool in {"write", "edit"}:
        for key in ("filePath", "path", "file"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return None


def _structured(command: str) -> tuple[str, str] | None:
    """Token-level checks for the most common dangerous commands."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    if not tokens:
        return None
    name = tokens[0].rsplit("/", 1)[-1]
    args = tokens[1:]
    if name == "rm":
        flags = "".join(arg for arg in args if arg.startswith("-") and not arg.startswith("--"))
        long_flags = {arg for arg in args if arg.startswith("--")}
        if (("r" in flags or "R" in flags) and "f" in flags) or                 ("--recursive" in long_flags and "--force" in long_flags):
            return ("filesystem", "recursive forced delete requires confirmation")
    if name.startswith("mkfs"):
        return ("filesystem", "filesystem format requires confirmation")
    if name == "dd" and any(arg.startswith("of=/dev/") for arg in args):
        return ("filesystem", "raw device write requires confirmation")
    if name in {"shred"}:
        return ("filesystem", "secure erase requires confirmation")
    if name == "truncate" and any(arg == "-s" or arg.startswith("-s0") for arg in args):
        return ("filesystem", "truncating a file requires confirmation")
    if name in {"shutdown", "reboot", "halt", "poweroff"}:
        return ("system", "system power action requires confirmation")
    if name == "pkill" or (name == "kill" and "-9" in args and "1" in args):
        return ("system", "process killing requires confirmation")
    if name == "git" and len(args) >= 1:
        if args[0] == "push" and any(arg in {"--force", "-f"} or arg.startswith("--force=") for arg in args[1:]):
            return ("git", "force push requires confirmation")
        if args[0] == "reset" and "--hard" in args[1:]:
            return ("git", "hard reset requires confirmation")
    if name in {"curl", "wget"} and re.search(r"\|\s*(?:ba)?sh\b", command):
        return ("remote", "piped shell execution requires confirmation")
    return None


def classify(tool: str, payload: Mapping[str, Any] | str | None = None) -> dict[str, Any]:
    command = _command(tool, payload)
    if command is not None:
        structured = _structured(command)
        if structured is not None:
            category, reason = structured
            return {"dangerous": True, "category": category,
                    "command_sha256": _hash(command), "reason": reason}
        for category, pattern in DANGEROUS_PATTERNS:
            if pattern.search(command):
                return {"dangerous": True, "category": category,
                        "command_sha256": _hash(command),
                        "reason": f"{category} command requires confirmation"}
        return {"dangerous": False, "command_sha256": _hash(command)}
    path = _path(tool, payload)
    if path is not None:
        normalized = path.replace("\\", "/")
        base = normalized.rsplit("/", 1)[-1]
        if base in CORE_CONFIG_NAMES or normalized.startswith("/etc/") \
                or "/.ssh/" in f"/{normalized}" or normalized.endswith("/.git/config"):
            return {"dangerous": True, "category": "core-config",
                    "command_sha256": _hash(normalized),
                    "reason": f"overwriting {path} requires confirmation"}
        return {"dangerous": False, "command_sha256": _hash(normalized)}
    return {"dangerous": False, "command_sha256": _hash(json.dumps(payload or {}, sort_keys=True))}
