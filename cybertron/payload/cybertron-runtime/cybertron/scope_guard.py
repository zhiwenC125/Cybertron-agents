"""Workspace snapshot, diff, and rollback for a single v6 node dispatch."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

from .access import DEFAULT_ACCESS_MODE, hard_denied, normalize_access_mode


class ScopeGuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileState:
    kind: str
    content: bytes = b""
    mode: int = 0

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def _opaque_state(info: os.stat_result) -> FileState:
    """Fingerprint an entry the process may not read without treating it as fatal."""
    fingerprint = f"{info.st_size}:{info.st_mtime_ns}:{info.st_ino}".encode()
    return FileState("opaque", fingerprint, stat.S_IMODE(info.st_mode))


@dataclass(frozen=True)
class Snapshot:
    entries: Dict[str, FileState]


@dataclass(frozen=True)
class ScopeReport:
    changed_paths: Tuple[str, ...]
    rejected_paths: Tuple[str, ...]
    rolled_back: bool


PRUNED_DIRS = frozenset({"node_modules", ".venv", "venv", "__pycache__",
                         ".mypy_cache", ".pytest_cache", ".ruff_cache", ".cache",
                         ".gradle", ".idea"})


class ScopeGuard:
    """Check a node's actual workspace diff; never follow workspace symlinks."""

    def __init__(self, workspace: Path, write_scope: Iterable[str],
                 access_mode: str = DEFAULT_ACCESS_MODE) -> None:
        self.workspace = Path(workspace).absolute()
        if not self.workspace.is_dir() or self.workspace.is_symlink():
            raise ScopeGuardError("workspace must be a real directory")
        self.access_mode = normalize_access_mode(access_mode)
        self.write_scope = tuple(write_scope)
        for scope in self.write_scope:
            if not isinstance(scope, str) or not scope:
                raise ScopeGuardError("invalid write_scope")
            if self.access_mode == "workspace-write" and (
                    scope.startswith("/") or scope.startswith("~") or ".." in scope.split("/")):
                raise ScopeGuardError("workspace-write access mode requires project-relative write_scope")
            if hard_denied(scope):
                raise ScopeGuardError("write_scope targets generated config, VCS, or run state")

    @staticmethod
    def _hard_denied(path: str) -> bool:
        return hard_denied(path)

    def _allowed(self, path: str, *, is_dir: bool) -> bool:
        if self._hard_denied(path):
            return False
        if self.access_mode == "read-only":
            return False
        if self.access_mode == "danger-full-access":
            return True
        for scope in self.write_scope:
            if scope == "**":
                return True
            if scope.endswith("/**"):
                prefix = scope[:-3]
                if path.startswith(prefix + "/") or (is_dir and (path == prefix or prefix.startswith(path + "/"))):
                    return True
            elif scope.startswith("*.") and "/" not in path and path.endswith(scope[1:]):
                return True
            elif path == scope or (is_dir and scope.startswith(path + "/")):
                return True
        return False

    def snapshot(self) -> Snapshot:
        # Read-only has no writes to verify, and full access is explicitly
        # user-authorized; do not walk an unbounded home directory or pretend
        # to constrain it. Declared artifacts are hashed by the host instead.
        if self.access_mode in {"read-only", "danger-full-access"}:
            return Snapshot({})
        entries: Dict[str, FileState] = {}
        for current, dirs, files in os.walk(self.workspace, topdown=True, followlinks=False):
            base = Path(current)
            for name in list(dirs):
                path = base / name
                rel = path.relative_to(self.workspace).as_posix()
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    entries[rel] = FileState("symlink", os.readlink(path).encode(), info.st_mode)
                    dirs.remove(name)
                elif stat.S_ISDIR(info.st_mode):
                    entries[rel] = FileState("directory", mode=stat.S_IMODE(info.st_mode))
                    if name in PRUNED_DIRS:
                        # Dependency and cache trees dominate large repositories.
                        # Keep the directory entry (deletion is still detected)
                        # without reading every vendored file.
                        dirs.remove(name)
                else:
                    if stat.S_ISSOCK(info.st_mode) or stat.S_ISFIFO(info.st_mode):
                        dirs.remove(name)
                        continue
                    raise ScopeGuardError(f"unsupported entry: {rel}")
            for name in files:
                path = base / name
                rel = path.relative_to(self.workspace).as_posix()
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    entries[rel] = FileState("symlink", os.readlink(path).encode(), info.st_mode)
                elif stat.S_ISREG(info.st_mode):
                    try:
                        content = path.read_bytes()
                    except OSError:
                        # A snapshot must never make an unrelated unreadable file
                        # fatal for every dispatch. Keep an opaque stat fingerprint
                        # so an out-of-scope change is still detected and rejected;
                        # such an entry cannot be restored byte-for-byte.
                        entries[rel] = _opaque_state(info)
                    else:
                        entries[rel] = FileState("file", content, stat.S_IMODE(info.st_mode))
                elif stat.S_ISSOCK(info.st_mode) or stat.S_ISFIFO(info.st_mode) \
                        or stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode):
                    # Runtime endpoints and device nodes have no file contents to
                    # snapshot. Replaced regular files still appear as deleted.
                    continue
                else:
                    raise ScopeGuardError(f"unsupported entry: {rel}")
        return Snapshot(entries)

    def diff(self, before: Snapshot) -> ScopeReport:
        after = self.snapshot()
        changed = tuple(sorted(path for path in before.entries.keys() | after.entries.keys()
                               if before.entries.get(path) != after.entries.get(path)))
        rejected = tuple(path for path in changed if (
            (after.entries.get(path) is not None and after.entries[path].kind == "symlink")
            or not self._allowed(path, is_dir=(before.entries.get(path) or after.entries.get(path)).kind == "directory")))
        return ScopeReport(changed, rejected, False)

    def assert_safe_before_dispatch(self, before: Snapshot) -> None:
        for path, state in before.entries.items():
            if state.kind == "symlink":
                raise ScopeGuardError(f"workspace contains symlink: {path}")

    def verify_and_rollback(self, before: Snapshot) -> ScopeReport:
        after = self.snapshot()
        changed = tuple(sorted(path for path in before.entries.keys() | after.entries.keys()
                               if before.entries.get(path) != after.entries.get(path)))
        rejected = tuple(path for path in changed if (
            (after.entries.get(path) is not None and after.entries[path].kind == "symlink")
            or not self._allowed(path, is_dir=(before.entries.get(path) or after.entries.get(path)).kind == "directory")))
        if not rejected:
            return ScopeReport(changed, (), False)
        # Remove changed entries first, deepest to shallowest. Symlinked
        # directories are opaque; removing them cannot touch their targets.
        for rel in sorted(rejected, key=lambda value: value.count("/"), reverse=True):
            path = self.workspace / rel
            parent = path.parent
            unsafe_parent = False
            while parent != self.workspace:
                if parent.is_symlink():
                    unsafe_parent = True
                    break
                parent = parent.parent
            if unsafe_parent:
                # The symlink itself is in the diff and will be removed next.
                continue
            if not path.is_symlink() and not path.exists():
                continue
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        # Recreate old directories before files. Never write through a symlink.
        for rel in sorted(rejected, key=lambda value: value.count("/")):
            state = before.entries.get(rel)
            if state is None:
                continue
            path = self.workspace / rel
            parent = path.parent
            while parent != self.workspace:
                if parent.is_symlink():
                    raise ScopeGuardError(f"unsafe rollback parent for {rel}")
                parent = parent.parent
            path.parent.mkdir(parents=True, exist_ok=True)
            if state.kind == "directory":
                path.mkdir(exist_ok=True)
                path.chmod(state.mode)
            elif state.kind == "symlink":
                path.symlink_to(state.content.decode())
            elif state.kind == "opaque":
                # The baseline bytes were unreadable, so they cannot be restored;
                # the rejection is still reported to the host.
                continue
            else:
                path.write_bytes(state.content)
                path.chmod(state.mode)
        return ScopeReport(changed, rejected, True)
