"""M4 device-operation broker: approval-bound flash, heartbeat, and rollback.

The broker is the only component allowed to start a destructive device command.
It never retries an operation whose outcome is unknown, and it always attempts
to restore the verified rollback image before returning. Every tool invocation
is recorded with its argv, exit code, UTC time, and output SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .deployment import DeviceTarget, FlashPlan


_APP_START = 0x08002000
_APP_BYTES = 0xDC00
_HEARTBEAT_ADDRESS = 0x20000000
_HEARTBEAT_VALUE = 0xC7B70001


class DeviceRejected(ValueError):
    """A plan, approval, or receipt violates the device contract."""


class ApprovalRejected(DeviceRejected):
    """The human approval does not bind this exact operation or was reused."""


class OutcomeUnknown(DeviceRejected):
    """A destructive command timed out or otherwise lost its result."""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ToolReceipt:
    argv: tuple[str, ...]
    exit: int
    utc: str
    sha256: str
    output: str
    file_path: str | None = None
    file_sha256: str | None = None
    file_bytes: int | None = None
    timed_out: bool = False

    def to_dict(self) -> dict:
        return {
            "argv": list(self.argv), "command": " ".join(self.argv),
            "exit": self.exit, "utc": self.utc, "sha256": self.sha256,
            "output": self.output, "file_path": self.file_path,
            "file_sha256": self.file_sha256, "file_bytes": self.file_bytes,
            "timed_out": self.timed_out, "source": "tool",
        }


@dataclass(frozen=True)
class ApprovalReceipt:
    """A real human/host authorization bound to one immutable flash plan."""

    approval_id: str
    source: str
    approver_id: str
    observed_at_utc: str
    plan_digest: str
    device_id: str
    firmware_sha256: str
    erase_start: int
    erase_end: int
    rollback_sha256: str
    message_sha256: str
    session_id: str

    def validate(self, plan: FlashPlan) -> None:
        if self.source not in {"human", "host"}:
            raise ApprovalRejected("approval source must be human or host")
        for label in ("approval_id", "approver_id", "message_sha256", "session_id"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value.strip():
                raise ApprovalRejected(f"approval {label} is required")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", self.approval_id):
            raise ApprovalRejected("approval_id has an invalid format")
        if not re.fullmatch(r"[0-9a-f]{64}", self.message_sha256):
            raise ApprovalRejected("approval message digest is invalid")
        if not _timestamp(self.observed_at_utc):
            raise ApprovalRejected("approval timestamp is invalid")
        if self.plan_digest != plan.plan_digest:
            raise ApprovalRejected("approval is bound to a different plan")
        if self.device_id != plan.target.device_id:
            raise ApprovalRejected("approval is bound to a different device")
        if self.firmware_sha256 != plan.firmware.sha256:
            raise ApprovalRejected("approval is bound to a different firmware")
        if (self.erase_start, self.erase_end) != (plan.erase_start, plan.erase_end):
            raise ApprovalRejected("approval is bound to a different erase range")
        if self.rollback_sha256 != plan.rollback.sha256:
            raise ApprovalRejected("approval is bound to a different rollback image")

    def to_dict(self) -> dict:
        return {
            "approval_id": self.approval_id, "source": self.source,
            "approver_id": self.approver_id, "observed_at_utc": self.observed_at_utc,
            "plan_digest": self.plan_digest, "device_id": self.device_id,
            "firmware_sha256": self.firmware_sha256,
            "erase_start": self.erase_start, "erase_end": self.erase_end,
            "rollback_sha256": self.rollback_sha256,
            "message_sha256": self.message_sha256, "session_id": self.session_id,
        }


class DeviceBroker:
    """Execute one approved flash/rollback cycle and return typed receipts."""

    def __init__(self, workspace: Path, output_dir: Path, *,
                 runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 sleeper: Callable[[float], None] = time.sleep,
                 timeout: int = 90,
                 clock: Callable[[], str] = _utc) -> None:
        self.workspace = Path(workspace).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.sleeper = sleeper
        self.timeout = timeout
        self.clock = clock

    # -- approval state -------------------------------------------------
    def _approvals_path(self) -> Path:
        return self.output_dir / "device-approvals.json"

    def _used(self) -> dict:
        path = self._approvals_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text())
        except (ValueError, TypeError) as exc:
            raise DeviceRejected("approval ledger is corrupt") from exc
        if not isinstance(data, dict):
            raise DeviceRejected("approval ledger is invalid")
        return data

    def _mark_used(self, approval: ApprovalReceipt, plan: FlashPlan) -> None:
        used = self._used()
        if approval.approval_id in used:
            raise ApprovalRejected("approval was already used")
        used[approval.approval_id] = {
            "plan_digest": plan.plan_digest,
            "used_at_utc": self.clock(),
        }
        temporary = self._approvals_path().with_suffix(".tmp")
        temporary.write_text(json.dumps(used, sort_keys=True, indent=2))
        os.replace(temporary, self._approvals_path())

    # -- tool execution -------------------------------------------------
    def _run(self, argv: list[str], *, read_path: Path | None = None) -> ToolReceipt:
        started = self.clock()
        try:
            completed = self.runner(
                argv, cwd=self.workspace, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=self.timeout, check=False,
            )
            code = int(completed.returncode)
            output = completed.stdout or ""
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            code = 124
            output = str(exc.stdout or "") + "\nst-flash timed out"
            timed_out = True
        data = output.encode()
        file_sha = file_bytes = None
        if read_path is not None and read_path.is_file():
            file_sha = _sha256_file(read_path)
            file_bytes = read_path.stat().st_size
        return ToolReceipt(tuple(argv), code, started, _sha256_bytes(data), output,
                           str(read_path) if read_path else None, file_sha, file_bytes,
                           timed_out)

    @staticmethod
    def _ok(receipt: ToolReceipt, label: str) -> None:
        if receipt.timed_out:
            raise OutcomeUnknown(f"{label} timed out; result is unknown")
        if receipt.exit != 0:
            raise DeviceRejected(f"{label} failed with exit {receipt.exit}")

    def _read(self, path: Path, address: int, size: int) -> ToolReceipt:
        path.parent.mkdir(parents=True, exist_ok=True)
        return self._run(["st-flash", "--hot-plug", "read", str(path),
                          hex(address), hex(size)], read_path=path)

    def _erase(self, address: int, size: int) -> ToolReceipt:
        return self._run(["st-flash", "--hot-plug", "erase", hex(address), hex(size)])

    def _write(self, path: Path, address: int) -> ToolReceipt:
        return self._run(["st-flash", "--hot-plug", "write", str(path), hex(address)])

    def _reset(self) -> ToolReceipt:
        return self._run(["st-flash", "--hot-plug", "reset"])

    # -- snapshots ------------------------------------------------------
    def snapshot(self, target: DeviceTarget, *,
                 app_start: int = _APP_START, app_end: int = _APP_START + _APP_BYTES) -> dict:
        """Read the full flash and the current App slice before any write."""
        target.validate()
        if not (target.flash_start <= app_start < app_end <= target.flash_end):
            raise DeviceRejected("App snapshot range is outside target flash")
        full_path = self.output_dir / "preflight-full.bin"
        receipt = self._read(full_path, target.flash_start,
                             target.flash_end - target.flash_start)
        (self.output_dir / "preflight.log").write_text(receipt.output)
        self._ok(receipt, "preflight read")
        expected = target.flash_end - target.flash_start
        if receipt.file_bytes != expected:
            raise DeviceRejected("preflight read returned the wrong number of bytes")
        full = full_path.read_bytes()
        app = full[app_start - target.flash_start:app_end - target.flash_start]
        app_path = self.output_dir / "preflight-app.bin"
        app_path.write_bytes(app)
        return {
            "receipt": receipt.to_dict(),
            "full_path": str(full_path), "full_bytes": len(full),
            "full_sha256": _sha256_bytes(full),
            "app_path": str(app_path), "app_bytes": len(app),
            "app_sha256": _sha256_bytes(app),
        }

    @staticmethod
    def _heartbeat(plan: FlashPlan) -> tuple[int, int]:
        address = plan.heartbeat_address if plan.heartbeat_address is not None else _HEARTBEAT_ADDRESS
        value = plan.heartbeat_value if plan.heartbeat_value is not None else _HEARTBEAT_VALUE
        if type(address) is not int or address < 0:
            raise DeviceRejected("heartbeat address is invalid")
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            raise DeviceRejected("heartbeat value is invalid")
        return address, value

    def _read_sram(self, name: str, address: int, size: int = 0x10) -> ToolReceipt:
        return self._read(self.output_dir / name, address, size)

    def _check_heartbeat(self, plan: FlashPlan) -> tuple[dict, list[ToolReceipt]]:
        address, value = self._heartbeat(plan)
        reset = self._reset()
        self._ok(reset, "reset")
        receipts = [reset]
        self.sleeper(0.5)
        first = self._read_sram("sram-1.bin", address)
        self._ok(first, "first SRAM read")
        receipts.append(first)
        self.sleeper(0.5)
        second = self._read_sram("sram-2.bin", address)
        self._ok(second, "second SRAM read")
        receipts.append(second)
        data1 = Path(first.file_path).read_bytes() if first.file_path else b""
        data2 = Path(second.file_path).read_bytes() if second.file_path else b""
        if len(data1) < 8 or len(data2) < 8:
            raise DeviceRejected("SRAM read returned too few bytes")
        marker1 = int.from_bytes(data1[:4], "little")
        marker2 = int.from_bytes(data2[:4], "little")
        counter1 = int.from_bytes(data1[4:8], "little")
        counter2 = int.from_bytes(data2[4:8], "little")
        passed = marker1 == marker2 == value and counter2 != counter1
        result = {"address": hex(address), "expected_marker": hex(value),
                  "marker_1": hex(marker1), "marker_2": hex(marker2),
                  "counter_1": counter1, "counter_2": counter2,
                  "passed": passed,
                  "sram_1_sha256": _sha256_bytes(data1),
                  "sram_2_sha256": _sha256_bytes(data2)}
        if not passed:
            raise DeviceRejected("SRAM heartbeat did not match the plan")
        return result, receipts

    def _verify_app(self, plan: FlashPlan, preflight: bytes) -> tuple[dict, list[ToolReceipt]]:
        app_path = self.output_dir / "post-flash-app.bin"
        receipt = self._read(app_path, plan.erase_start, plan.erase_end - plan.erase_start)
        self._ok(receipt, "post-flash App read")
        receipts = [receipt]
        data = app_path.read_bytes()
        firmware = Path(plan.firmware.path).read_bytes()
        expected = firmware + b"\xFF" * (plan.erase_end - plan.erase_start - len(firmware))
        region_ok = data == expected
        bootloader_ok = True
        ota_ok = True
        full_path = self.output_dir / "post-flash-full.bin"
        full_receipt = self._read(full_path, plan.target.flash_start,
                                  plan.target.flash_end - plan.target.flash_start)
        self._ok(full_receipt, "post-flash full read")
        receipts.append(full_receipt)
        full = full_path.read_bytes()
        if len(full) != len(preflight):
            raise DeviceRejected("post-flash full read returned the wrong size")
        bootloader_ok = full[: plan.erase_start - plan.target.flash_start] == preflight[: plan.erase_start - plan.target.flash_start]
        ota_ok = full[plan.erase_end - plan.target.flash_start:] == preflight[plan.erase_end - plan.target.flash_start:]
        result = {
            "app_sha256": _sha256_bytes(data),
            "expected_app_sha256": _sha256_bytes(expected),
            "region_matches_fixture_and_erased_tail": region_ok,
            "bootloader_unchanged": bootloader_ok,
            "ota_flag_page_unchanged": ota_ok,
            "full_sha256": _sha256_bytes(full),
            "full_path": str(full_path),
            "full_bytes": len(full),
        }
        if not (region_ok and bootloader_ok and ota_ok):
            raise DeviceRejected("post-flash verification failed")
        return result, receipts

    def _rollback(self, plan: FlashPlan, preflight_sha256: str) -> tuple[dict, list[ToolReceipt], bool]:
        receipts: list[ToolReceipt] = []
        try:
            erase = self._erase(plan.erase_start, plan.erase_end - plan.erase_start)
            receipts.append(erase)
            self._ok(erase, "rollback erase")
            write = self._write(Path(plan.rollback.path), plan.erase_start)
            receipts.append(write)
            self._ok(write, "rollback write")
            full_path = self.output_dir / "rollback-full.bin"
            read = self._read(full_path, plan.target.flash_start,
                              plan.target.flash_end - plan.target.flash_start)
            receipts.append(read)
            self._ok(read, "rollback read")
            full = full_path.read_bytes()
            matches = _sha256_bytes(full) == preflight_sha256
            reset = self._reset()
            receipts.append(reset)
            self._ok(reset, "rollback reset")
            return {
                "full_path": str(full_path), "full_bytes": len(full),
                "full_sha256": _sha256_bytes(full),
                "matches_preflight": matches,
            }, receipts, matches
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}", "matches_preflight": False,
                    "unknown": True}, receipts, False

    def execute(self, plan: FlashPlan, approval: ApprovalReceipt, *,
                expected_full_sha256: str | None = None) -> dict:
        approval.validate(plan)
        plan.verify()
        used = self._used()
        if approval.approval_id in used:
            raise ApprovalRejected("approval was already used")
        snapshot = self.snapshot(plan.target, app_start=plan.erase_start,
                                 app_end=plan.erase_end)
        if expected_full_sha256 is not None and snapshot["full_sha256"] != expected_full_sha256:
            raise DeviceRejected("device flash changed after the plan was prepared")
        if snapshot["app_sha256"] != plan.rollback.sha256:
            raise DeviceRejected("current App does not match the approved rollback image")
        preflight = Path(snapshot["full_path"]).read_bytes()
        # The approval is single-use and is consumed before the first
        # destructive command. A crash after this point cannot be retried.
        self._mark_used(approval, plan)
        receipts: list[ToolReceipt] = [ToolReceipt(
            tuple(snapshot["receipt"]["argv"]), snapshot["receipt"]["exit"],
            snapshot["receipt"]["utc"], snapshot["receipt"]["sha256"],
            snapshot["receipt"]["output"], snapshot["receipt"]["file_path"],
            snapshot["receipt"]["file_sha256"], snapshot["receipt"]["file_bytes"],
            snapshot["receipt"]["timed_out"])]
        flash_result: dict = {}
        heartbeat: dict = {}
        error = None
        unknown = False
        try:
            erase = self._erase(plan.erase_start, plan.erase_end - plan.erase_start)
            receipts.append(erase)
            self._ok(erase, "erase")
            write = self._write(Path(plan.firmware.path), plan.erase_start)
            receipts.append(write)
            self._ok(write, "fixture write")
            flash_result, extra = self._verify_app(plan, preflight)
            receipts.extend(extra)
            heartbeat, extra = self._check_heartbeat(plan)
            receipts.extend(extra)
        except OutcomeUnknown as exc:
            error, unknown = str(exc), True
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        rollback, rollback_receipts, restored = self._rollback(plan, snapshot["full_sha256"])
        receipts.extend(rollback_receipts)
        if not restored or rollback.get("unknown"):
            unknown = True
        if unknown:
            status = "outcome_unknown"
        elif error or not restored:
            status = "failed"
        else:
            status = "completed"
        artifacts = {path: _sha256_file(Path(path)) for path in (
            snapshot["full_path"], snapshot["app_path"],
            flash_result.get("full_path"), str(self.output_dir / "post-flash-app.bin"),
            rollback.get("full_path"), str(self.output_dir / "sram-1.bin"),
            str(self.output_dir / "sram-2.bin")) if path and Path(path).is_file()}
        result = {
            "status": status, "plan_digest": plan.plan_digest,
            "approval_id": approval.approval_id,
            "preflight": snapshot, "flash": flash_result, "heartbeat": heartbeat,
            "rollback": rollback, "restored": restored, "error": error,
            "receipts": [item.to_dict() for item in receipts],
            "artifacts": artifacts,
            "firmware": {"path": plan.firmware.path, "sha256": plan.firmware.sha256,
                         "bytes": plan.firmware.size_bytes},
            "rollback_image": {"path": plan.rollback.path, "sha256": plan.rollback.sha256,
                               "bytes": plan.rollback.size_bytes},
        }
        (self.output_dir / "device-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return result
