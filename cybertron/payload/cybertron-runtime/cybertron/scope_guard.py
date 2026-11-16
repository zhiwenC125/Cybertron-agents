"""Workspace snapshot, diff, and rollback for a single v6 node dispatch."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple


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


@dataclass(frozen=True)
class Snapshot:
    entries: Dict[str, FileState]


@dataclass(frozen=True)
class ScopeReport:
    changed_paths: Tuple[str, ...]
    rejected_paths: Tuple[str, ...]
    rolled_back: bool


class ScopeGuard:
    """Check a node's actual workspace diff; never follow workspace symlinks."""

    def __init__(self, workspace: Path, write_scope: Iterable[str]) -> None:
        self.workspace = Path(workspace).absolute()
        if not self.workspace.is_dir() or self.workspace.is_symlink():
            raise ScopeGuardError("workspace must be a real directory")
        self.write_scope = tuple(write_scope)
        for scope in self.write_scope:
            if not isinstance(scope, str) or not scope or scope.startswith("/") or ".." in scope.split("/"):
                raise ScopeGuardError("invalid write_scope")

    @staticmethod
    def _hard_denied(path: str) -> bool:
        return (path == ".git" or path.startswith(".git/")
                or path == ".cybertron/runs" or path.startswith(".cybertron/runs/")
                or path == ".opencode" or path.startswith(".opencode/")
                or path == "opencode.jsonc")

    def _allowed(self, path: str, *, is_dir: bool) -> bool:
        if self._hard_denied(path):
            return False
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
                else:
                    raise ScopeGuardError(f"unsupported entry: {rel}")
            for name in files:
                path = base / name
                rel = path.relative_to(self.workspace).as_posix()
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    entries[rel] = FileState("symlink", os.readlink(path).encode(), info.st_mode)
                elif stat.S_ISREG(info.st_mode):
                    entries[rel] = FileState("file", path.read_bytes(), stat.S_IMODE(info.st_mode))
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
            else:
                path.write_bytes(state.content)
                path.chmod(state.mode)
        return ScopeReport(changed, rejected, True)
