"""Offline, event-backed storage for one recoverable Cybertron run.

The event log is authoritative. A snapshot is only a projection and can be
regenerated after an interrupted write. This module never invokes an agent.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from .execution import EvidenceSource, QualityEvidence, QualityKind
from .ledger import CybertronTaskLedger, LedgerStep, PrimaPlanOrchestrator


SCHEMA_VERSION = 1


class RunStoreError(RuntimeError):
    pass


class RunCorrupt(RunStoreError):
    pass


class RunLocked(RunStoreError):
    pass


class ConfigChanged(RunStoreError):
    pass


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ledger_data(ledger: CybertronTaskLedger) -> dict:
    return asdict(ledger)


def _decode_ledger(data: object) -> CybertronTaskLedger:
    if not isinstance(data, dict) or set(data) != {field.name for field in fields(CybertronTaskLedger)}:
        raise RunCorrupt("Ledger fields do not match schema 1")
    steps = data.get("plan")
    if not isinstance(steps, list) or len(steps) != 9:
        raise RunCorrupt("Run must contain nine ledger stages")
    decoded = []
    for index, raw in enumerate(steps, 1):
        if not isinstance(raw, dict) or set(raw) != {field.name for field in fields(LedgerStep)}:
            raise RunCorrupt(f"Stage {index} fields do not match schema 1")
        if raw.get("step_id") != index or raw.get("status") not in (
            "pending", "in_progress", "completed", "blocked"
        ):
            raise RunCorrupt(f"Stage {index} has invalid identity or status")
        evidence = raw.get("quality_evidence")
        if not isinstance(evidence, list):
            raise RunCorrupt(f"Stage {index} has invalid quality evidence")
        try:
            decoded.append(LedgerStep(**{
                **raw,
                "quality_evidence": [QualityEvidence(**{
                    **item,
                    "kind": QualityKind(item["kind"]),
                    "source_type": EvidenceSource(item.get("source_type", "unverified")),
                })
                                     for item in evidence],
            }))
        except (KeyError, TypeError, ValueError) as exc:
            raise RunCorrupt(f"Stage {index} has invalid quality evidence") from exc
    result = CybertronTaskLedger(**{**data, "plan": decoded})
    if not isinstance(result.turn_count, int) or result.turn_count < 0 or not isinstance(result.review_retry_count, int):
        raise RunCorrupt("Ledger counters are invalid")
    return result


class RunStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".cybertron" / "sessions"
        if (self.workspace / ".cybertron").is_symlink():
            raise RunStoreError("Storage root may not be a symlink")

    @staticmethod
    def _safe_file(path: Path) -> Path:
        if path.is_symlink():
            raise RunCorrupt(f"Unsafe symlink in run storage: {path.name}")
        return path

    @staticmethod
    def _id(value: str) -> str:
        try:
            parsed = uuid.UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise RunStoreError("A canonical UUID is required") from exc
        if str(parsed) != value:
            raise RunStoreError("A canonical UUID is required")
        return value

    def _config_digest(self) -> str:
        config = self.workspace / "opencode.jsonc"
        return hashlib.sha256(config.read_bytes()).hexdigest() if config.is_file() else "missing"

    @staticmethod
    def _runtime_digest() -> str:
        package = Path(__file__).resolve().parent
        digest = hashlib.sha256()
        for name in ("dispatch.py", "ledger.py", "registry.py", "runstore.py"):
            digest.update(name.encode() + b"\0" + (package / name).read_bytes())
        return digest.hexdigest()

    def _locate(self, run_id: str) -> tuple[Path, dict]:
        self._id(run_id)
        if self.root.is_symlink():
            raise RunCorrupt("Unsafe sessions directory")
        if not self.root.is_dir():
            raise RunStoreError("No runs exist in this workspace")
        found = []
        for session in self.root.iterdir():
            if session.name.startswith("."):
                continue
            if session.is_symlink() or not session.is_dir():
                raise RunCorrupt("Unsafe session directory")
            self._id(session.name)
            if (session / "runs").is_symlink():
                raise RunCorrupt("Unsafe runs directory")
            run_dir = session / "runs" / run_id
            if run_dir.is_symlink():
                raise RunCorrupt("Unsafe run directory")
            if run_dir.is_dir():
                found.append(run_dir)
        if len(found) != 1:
            raise RunStoreError("Run not found or ambiguous")
        directory = found[0]
        try:
            metadata = json.loads(self._safe_file(directory / "run.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunCorrupt("Run metadata is unreadable") from exc
        if metadata.get("schema_version") != SCHEMA_VERSION or metadata.get("run_id") != run_id \
                or metadata.get("session_id") != directory.parent.parent.name:
            raise RunCorrupt("Run metadata identity or schema is invalid")
        for name in ("workspace", "config_sha256", "runtime_sha256"):
            if not isinstance(metadata.get(name), str):
                raise RunCorrupt(f"Run metadata lacks {name}")
        return directory, metadata

    @contextmanager
    def _writer(self, directory: Path) -> Iterator[None]:
        lock_path = self._safe_file(directory / ".lock")
        with lock_path.open("a+b") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RunLocked("Run already has a writer") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".snapshot-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_json_bytes(value) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _append(self, directory: Path, event: dict) -> None:
        with self._safe_file(directory / "events.jsonl").open("ab") as handle:
            handle.write(_json_bytes(event) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _write_snapshot(self, directory: Path, seq: int, ledger: CybertronTaskLedger) -> None:
        data = _ledger_data(ledger)
        self._atomic_json(self._safe_file(directory / "ledger.json"), {
            "schema_version": SCHEMA_VERSION,
            "snapshot_seq": seq,
            "ledger_sha256": _digest(data),
            "ledger": data,
        })

    def _event(self, metadata: dict, seq: int, event_type: str,
               ledger: CybertronTaskLedger, *, stage_id: int | None = None,
               dispatch_id: str | None = None, attempt_id: str | None = None,
               payload: dict | None = None) -> dict:
        data = _ledger_data(ledger)
        return {
            "schema_version": SCHEMA_VERSION,
            "event_id": str(uuid.uuid4()),
            "seq": seq,
            "recorded_at_utc": _utc_now(),
            "session_id": metadata["session_id"],
            "run_id": metadata["run_id"],
            "stage_id": stage_id,
            "dispatch_id": dispatch_id,
            "attempt_id": attempt_id,
            "source": "cybertron",
            "type": event_type,
            "payload": payload or {},
            "payload_sha256": _digest(payload or {}),
            "ledger_sha256": _digest(data),
            "ledger": data,
        }

    def create(self, request: str, session_id: str | None = None) -> dict:
        if not request.strip():
            raise ValueError("A nonempty request is required")
        if self.root.is_symlink():
            raise RunCorrupt("Unsafe sessions directory")
        existing_session = session_id is not None
        if existing_session:
            self._id(session_id)
            session_dir = self.root / session_id
            if session_dir.is_symlink() or not session_dir.is_dir():
                raise RunStoreError("Session not found or unsafe")
            session_file = self._safe_file(session_dir / "session.json")
            try:
                session_data = json.loads(session_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RunCorrupt("Session metadata is unreadable") from exc
            if session_data.get("session_id") != session_id or session_data.get("schema_version") != SCHEMA_VERSION:
                raise RunCorrupt("Session metadata identity or schema is invalid")
            if session_data.get("archived"):
                raise RunStoreError("Archived session cannot receive new runs")
        else:
            session_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        directory = self.root / session_id / "runs" / run_id
        directory.mkdir(parents=True, exist_ok=False)
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "session_id": session_id,
            "run_id": run_id,
            "created_at_utc": _utc_now(),
            "workspace": str(self.workspace),
            "config_sha256": self._config_digest(),
            "runtime_sha256": self._runtime_digest(),
        }
        if not existing_session:
            self._atomic_json(directory.parent.parent / "session.json", {
                "schema_version": SCHEMA_VERSION,
                "session_id": session_id,
                "created_at_utc": metadata["created_at_utc"],
                "workspace": str(self.workspace),
            })
        self._atomic_json(directory / "run.json", metadata)
        ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger(request)
        event = self._event(metadata, 1, "run.created", ledger)
        with self._writer(directory):
            self._append(directory, event)
            self._write_snapshot(directory, 1, ledger)
        return {"session_id": session_id, "run_id": run_id, "status": "pending", "stage_id": 1}

    def _replay(self, directory: Path, metadata: dict) -> tuple[int, CybertronTaskLedger]:
        path = self._safe_file(directory / "events.jsonl")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise RunCorrupt("Event log is unreadable") from exc
        if not raw or not raw.endswith(b"\n"):
            raise RunCorrupt("Event log is empty or has a truncated tail")
        seen = set()
        ledger = None
        for seq, line in enumerate(raw.splitlines(), 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RunCorrupt(f"Event {seq} is invalid JSON") from exc
            if event.get("schema_version") != SCHEMA_VERSION:
                raise RunCorrupt(f"Event {seq} has unsupported schema")
            try:
                self._id(event.get("event_id"))
            except RunStoreError as exc:
                raise RunCorrupt(f"Event {seq} has invalid ID") from exc
            if not isinstance(event.get("type"), str) or not event["type"]:
                raise RunCorrupt(f"Event {seq} has invalid type")
            if event.get("seq") != seq or event.get("event_id") in seen:
                raise RunCorrupt(f"Event {seq} has duplicate or noncontiguous identity")
            if event.get("session_id") != metadata["session_id"] or event.get("run_id") != metadata["run_id"]:
                raise RunCorrupt(f"Event {seq} belongs to another run")
            if "payload_sha256" in event:
                if event["payload_sha256"] != _digest(event.get("payload")):
                    raise RunCorrupt(f"Event {seq} payload digest differs")
            elif event["type"].startswith(("operation.", "approval.")):
                raise RunCorrupt(f"Event {seq} side effect payload lacks a digest")
            seen.add(event["event_id"])
            if event.get("ledger_sha256") != _digest(event.get("ledger")):
                raise RunCorrupt(f"Event {seq} ledger digest differs")
            ledger = _decode_ledger(event["ledger"])
        assert ledger is not None
        return seq, ledger

    def _snapshot_state(self, directory: Path, seq: int, ledger: CybertronTaskLedger) -> str:
        path = self._safe_file(directory / "ledger.json")
        if not path.exists():
            return "missing"
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "invalid"
        if snapshot.get("schema_version") != SCHEMA_VERSION:
            return "unsupported"
        if snapshot.get("snapshot_seq") > seq:
            return "ahead"
        if snapshot.get("snapshot_seq") < seq:
            return "stale"
        return "current" if snapshot.get("ledger_sha256") == _digest(_ledger_data(ledger)) \
            and snapshot.get("ledger") == _ledger_data(ledger) else "invalid"

    def show(self, run_id: str) -> dict:
        directory, metadata = self._locate(run_id)
        seq, ledger = self._replay(directory, metadata)
        step = ledger.next_step()
        return {
            "session_id": metadata["session_id"],
            "run_id": run_id,
            "event_seq": seq,
            "status": "completed" if step is None else step.status,
            "stage_id": None if step is None else step.step_id,
            "next_agent": None if step is None else step.next_agent(),
            "turn_count": ledger.turn_count,
            "review_retry_count": ledger.review_retry_count,
            "snapshot": self._snapshot_state(directory, seq, ledger),
            "config": "current" if metadata["config_sha256"] == self._config_digest() else "changed",
            "runtime": "current" if metadata["runtime_sha256"] == self._runtime_digest() else "changed",
            "workspace": "current" if metadata["workspace"] == str(self.workspace) else "changed",
        }

    def load_ledger(self, run_id: str) -> CybertronTaskLedger:
        """Return a detached ledger reconstructed from the authoritative events."""
        directory, metadata = self._locate(run_id)
        _, ledger = self._replay(directory, metadata)
        return ledger

    def events(self, run_id: str) -> list[dict]:
        """Return validated Cybertron events without host transcript contents."""
        directory, metadata = self._locate(run_id)
        self._replay(directory, metadata)
        return [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]

    def verify(self, run_id: str) -> dict:
        result = self.show(run_id)
        if result["snapshot"] in ("ahead", "unsupported"):
            raise RunCorrupt(f"Snapshot is {result['snapshot']}")
        result["verified"] = all(result[key] == "current" for key in
                                 ("snapshot", "config", "runtime", "workspace"))
        return result

    def resume(self, run_id: str) -> dict:
        directory, metadata = self._locate(run_id)
        with self._writer(directory):
            if metadata["config_sha256"] != self._config_digest():
                raise ConfigChanged("OpenCode config changed since this run was created")
            if metadata["runtime_sha256"] != self._runtime_digest() or metadata["workspace"] != str(self.workspace):
                raise ConfigChanged("Runtime or workspace changed since this run was created")
            seq, ledger = self._replay(directory, metadata)
            snapshot = self._snapshot_state(directory, seq, ledger)
            if snapshot in ("ahead", "unsupported"):
                raise RunCorrupt(f"Snapshot is {snapshot}")
            if snapshot != "current":
                self._write_snapshot(directory, seq, ledger)
        result = self.show(run_id)
        result["resumed_offline"] = True
        result["dispatch_started"] = False
        return result

    def transition(self, run_id: str, event_type: str,
                   mutate: Callable[[CybertronTaskLedger], None], *, stage_id: int | None = None,
                   dispatch_id: str | None = None, attempt_id: str | None = None,
                   payload: dict | None = None, expected_seq: int | None = None) -> dict:
        directory, metadata = self._locate(run_id)
        with self._writer(directory):
            if metadata["config_sha256"] != self._config_digest():
                raise ConfigChanged("OpenCode config changed since this run was created")
            if metadata["runtime_sha256"] != self._runtime_digest() or metadata["workspace"] != str(self.workspace):
                raise ConfigChanged("Runtime or workspace changed since this run was created")
            seq, ledger = self._replay(directory, metadata)
            if expected_seq is not None and seq != expected_seq:
                raise RunLocked("Run advanced before this transition")
            mutate(ledger)
            event = self._event(metadata, seq + 1, event_type, ledger,
                                stage_id=stage_id, dispatch_id=dispatch_id,
                                attempt_id=attempt_id, payload=payload)
            self._append(directory, event)
            self._write_snapshot(directory, seq + 1, ledger)
        return self.show(run_id)
