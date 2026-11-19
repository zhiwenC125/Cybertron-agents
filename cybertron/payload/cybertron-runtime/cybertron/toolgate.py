"""Infer the Grant kinds a concrete tool call needs.

Node ``requires`` is the explicit contract.  This module is the safety net for
concrete commands: a ``git push`` or ``openocd`` call cannot bypass a Grant just
because the planner forgot to declare it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping


_RULES = (
    (re.compile(r"\bgit\s+push\b", re.I), "vcs.push"),
    (re.compile(r"\bgit\s+(?:add|commit|tag)\b", re.I), "vcs.write"),
    (re.compile(r"\b(?:openocd|esptool|st-flash)\b|\bpio\s+run\b[^\n]*-t\s*upload", re.I), "device"),
    (re.compile(r"\b(?:docker\s+push|kubectl\s+(?:apply|delete)|ssh|scp|rsync)\b", re.I), "deploy"),
    (re.compile(r"\b(?:pip3?|pipx|npm|pnpm|yarn|cargo)\s+(?:install|add)\b", re.I), "pkg.install"),
    (re.compile(r"\b(?:curl|wget)\b", re.I), "network.read"),
)


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


def infer(tool: str, payload: Mapping[str, Any] | str | None,
          project: Path) -> list[str]:
    command = _command(tool, payload)
    if command is not None:
        kinds = [kind for pattern, kind in _RULES if pattern.search(command)]
        return list(dict.fromkeys(kinds))
    path = _path(tool, payload)
    if path is not None:
        target = Path(path)
        if target.is_absolute():
            resolved = target.resolve()
        else:
            resolved = (Path(project) / target).resolve()
        try:
            resolved.relative_to(Path(project).resolve())
        except ValueError:
            return ["write.expand"]
    return []
