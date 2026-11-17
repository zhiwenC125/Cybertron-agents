"""Stable session IDs with human-readable slugs and retained aliases."""

from __future__ import annotations

import fcntl
import json
import re
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .runstore import RunCorrupt, RunStore, RunStoreError, SCHEMA_VERSION, _utc_now


RESERVED = {"new", "list", "show", "rename", "run", "runs", "session", "sessions",
            "archive", "unarchive", "export", "delete"}
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$")


def normalize_slug(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Slug must be text")
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"[\s_]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    if not SLUG.fullmatch(normalized) or normalized in RESERVED:
        raise ValueError("Slug must use 1–48 ASCII letters, digits, or hyphens and avoid reserved words")
    return normalized


class SessionStore:
    def __init__(self, workspace: Path) -> None:
        self.runs = RunStore(workspace)
        self.root = self.runs.root

    @contextmanager
    def _index_lock(self) -> Iterator[None]:
        if self.root.is_symlink():
            raise RunCorrupt("Unsafe sessions directory")
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".index.lock"
        if lock_path.is_symlink():
            raise RunCorrupt("Unsafe session index lock")
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _all(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        result = []
        for directory in sorted(self.root.iterdir()):
            if directory.name.startswith("."):
                continue
            if directory.is_symlink() or not directory.is_dir():
                raise RunCorrupt("Unsafe session directory")
            path = self.runs._safe_file(directory / "session.json")
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RunCorrupt("Session metadata is unreadable") from exc
            if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("session_id"), str):
                raise RunCorrupt("Session metadata identity or schema is invalid")
            self.runs._id(data["session_id"])
            data.setdefault("directory", directory.name)
            if data["directory"] != directory.name:
                raise RunCorrupt("Session directory metadata differs from the folder name")
            data.setdefault("slug", None)  # Sessions created before stage C.
            data.setdefault("title", None)
            data.setdefault("aliases", [])
            data.setdefault("archived", False)
            if data["slug"] is not None and (normalize_slug(data["slug"]) != data["slug"]):
                raise RunCorrupt("Session slug is invalid")
            if not isinstance(data["aliases"], list) or any(
                not isinstance(alias, str) or normalize_slug(alias) != alias for alias in data["aliases"]
            ):
                raise RunCorrupt("Session aliases are invalid")
            result.append(data)
        return result

    def _session_path(self, session: dict) -> Path:
        return self.root / session.get("directory", session["session_id"])

    def _resolve(self, reference: str) -> dict:
        sessions = self._all()
        try:
            canonical_id = self.runs._id(reference)
        except RunStoreError:
            canonical_id = None
        if canonical_id is not None:
            matches = [session for session in sessions if session["session_id"] == canonical_id]
        else:
            slug = normalize_slug(reference)
            matches = [session for session in sessions if slug == session["slug"] or slug in session["aliases"]]
        if len(matches) != 1:
            raise RunStoreError("Session not found or ambiguous")
        return matches[0]

    def create(self, slug: str, title: str = "") -> dict:
        slug = normalize_slug(slug)
        title = title.strip() or slug
        if len(title) > 200:
            raise ValueError("Session title is too long")
        with self._index_lock():
            if any(slug == session["slug"] or slug in session["aliases"] for session in self._all()):
                raise RunStoreError("Session slug already exists")
            session_id = str(uuid.uuid4())
            directory = self.root / slug
            suffix = 2
            while directory.exists() or directory.is_symlink():
                directory = self.root / f"{slug}-{suffix}"
                suffix += 1
            directory.mkdir(exist_ok=False)
            data = {
                "schema_version": SCHEMA_VERSION,
                "session_id": session_id,
                "directory": directory.name,
                "slug": slug,
                "title": title,
                "aliases": [],
                "archived": False,
                "created_at_utc": _utc_now(),
                "workspace": str(self.runs.workspace),
            }
            self.runs._atomic_json(directory / "session.json", data)
            return data

    def list(self) -> list[dict]:
        return [self.show(session["session_id"]) for session in self._all()]

    def show(self, reference: str) -> dict:
        session = self._resolve(reference)
        runs = self._session_path(session) / "runs"
        if runs.is_symlink():
            raise RunCorrupt("Unsafe runs directory")
        children = list(runs.iterdir()) if runs.is_dir() else []
        if any(child.is_symlink() or not child.is_dir() for child in children):
            raise RunCorrupt("Unsafe run entry")
        count = len(children)
        return {**session, "run_count": count}

    def rename(self, reference: str, slug: str, title: str | None = None) -> dict:
        slug = normalize_slug(slug)
        if title is not None:
            title = title.strip()
            if not title or len(title) > 200:
                raise ValueError("Session title must contain 1–200 characters")
        with self._index_lock():
            session = self._resolve(reference)
            for other in self._all():
                if other["session_id"] != session["session_id"] and (
                    slug == other["slug"] or slug in other["aliases"]
                ):
                    raise RunStoreError("Session slug already exists")
            previous = session["slug"]
            if previous and previous != slug and previous not in session["aliases"]:
                session["aliases"].append(previous)
            session["aliases"] = [alias for alias in session["aliases"] if alias != slug]
            session["slug"] = slug
            if title is not None:
                session["title"] = title
            current = self._session_path(session)
            target = self.root / slug
            if current.name != session["session_id"] and current != target:
                if target.exists() or target.is_symlink():
                    raise RunStoreError("Session directory already exists")
                current.rename(target)
                session["directory"] = target.name
                current = target
            self.runs._atomic_json(current / "session.json", session)
        return self.show(session["session_id"])

    def archive(self, reference: str, archived: bool = True) -> dict:
        with self._index_lock():
            session = self._resolve(reference)
            session["archived"] = archived
            self.runs._atomic_json(self._session_path(session) / "session.json", session)
        return self.show(session["session_id"])

    def create_run(self, reference: str, request: str) -> dict:
        with self._index_lock():
            session = self._resolve(reference)
            return self.runs.create(request, session_id=session["session_id"])

    def list_runs(self, reference: str) -> list[dict]:
        session = self._resolve(reference)
        directory = self._session_path(session) / "runs"
        if directory.is_symlink():
            raise RunCorrupt("Unsafe runs directory")
        if not directory.is_dir():
            return []
        children = sorted(directory.iterdir())
        if any(child.is_symlink() or not child.is_dir() for child in children):
            raise RunCorrupt("Unsafe run entry")
        return [self.runs.show(child.name) for child in children]
