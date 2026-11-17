"""Access modes and human-readable run folder names.

Three modes mirror the host permission model:

* ``read-only``: no writes at all.
* ``workspace``: writes stay inside the project and inside the node scope.
* ``full``: the user explicitly authorized writes anywhere, including paths
  outside the project.  Hard-denied configuration and run-state paths still
  remain off limits.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

ACCESS_MODES = ("read-only", "workspace", "full")
DEFAULT_ACCESS_MODE = "workspace"

_HARD_PARTS = {".git", ".cybertron/runs", ".opencode", "opencode.jsonc"}
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$")


def normalize_access_mode(value: str | None) -> str:
    if value is None:
        return DEFAULT_ACCESS_MODE
    if value not in ACCESS_MODES:
        raise ValueError("access_mode must be read-only, workspace, or full")
    return value


def is_external_scope(scope: str) -> bool:
    return scope.startswith(("/", "~")) or scope == ".." or scope.startswith("../")


def hard_denied(scope: str) -> bool:
    """Reject generated config, VCS metadata, and run state in every mode."""
    parts = [part for part in scope.replace("\\", "/").split("/") if part]
    if any(part in {".git", ".opencode", "opencode.jsonc"} for part in parts):
        return True
    return any(parts[index] == ".cybertron" and parts[index + 1] == "runs"
               for index in range(len(parts) - 1))


def resolve_scope(scope: str, workspace: Path) -> Path:
    if scope.startswith("~"):
        return Path(scope).expanduser().resolve()
    path = Path(scope)
    if not path.is_absolute():
        path = workspace / path
    return path.resolve()


def slugify_title(title: str | None, *, fallback: str = "run") -> str:
    """Turn an OpenCode session title into a safe on-disk folder prefix."""
    raw = unicodedata.normalize("NFKC", (title or "")).strip().lower()
    ascii_only = "".join(char if char.isascii() and (char.isalnum() or char in "-_ ") else "-"
                         for char in raw)
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    slug = re.sub(r"-+", "-", slug)[:40].strip("-")
    if not slug or not _SLUG_RE.fullmatch(slug):
        slug = fallback
    return slug
