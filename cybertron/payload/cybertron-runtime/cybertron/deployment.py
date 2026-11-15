"""Offline stage 7 deployment contracts; no device or shell operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


_FIRMWARE_SUFFIXES = {".bin", ".elf", ".hex", ".uf2"}


def _required(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


@dataclass(frozen=True)
class FirmwareArtifact:
    path: str
    sha256: str
    size_bytes: int

    @classmethod
    def inspect(cls, path: Path) -> FirmwareArtifact:
        if path.is_symlink() or path.suffix.lower() not in _FIRMWARE_SUFFIXES:
            raise ValueError("Firmware must be a regular .bin/.elf/.hex/.uf2 file")
        if not path.is_file():
            raise FileNotFoundError("Firmware file is missing")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        if size == 0:
            raise ValueError("Firmware file is empty")
        return cls(str(path.resolve()), digest.hexdigest(), size)

    def verify(self) -> None:
        current = type(self).inspect(Path(self.path))
        if current.sha256 != self.sha256 or current.size_bytes != self.size_bytes:
            raise ValueError("Firmware changed after inspection")


@dataclass(frozen=True)
class DeviceTarget:
    device_id: str
    board: str
    connection: str
    flash_start: int
    flash_end: int  # exclusive

    def validate(self) -> None:
        for label in ("device_id", "board", "connection"):
            _required(getattr(self, label), label)
        if not (isinstance(self.flash_start, int) and isinstance(self.flash_end, int)
                and 0 <= self.flash_start < self.flash_end):
            raise ValueError("Target flash range must be a nonempty address interval")


@dataclass(frozen=True)
class FlashPlan:
    target: DeviceTarget
    firmware: FirmwareArtifact
    rollback: FirmwareArtifact
    erase_start: int
    erase_end: int  # exclusive
    rollback_procedure: str
    heartbeat_marker: str
    plan_digest: str

    @classmethod
    def prepare(cls, target: DeviceTarget, firmware: FirmwareArtifact,
                rollback: FirmwareArtifact, *, erase_start: int, erase_end: int,
                rollback_procedure: str, heartbeat_marker: str) -> FlashPlan:
        target.validate()
        firmware.verify()
        rollback.verify()
        if not (isinstance(erase_start, int) and isinstance(erase_end, int)
                and target.flash_start <= erase_start < erase_end <= target.flash_end):
            raise ValueError("Erase range is outside the target flash region")
        if Path(firmware.path).suffix.lower() == ".bin" and firmware.size_bytes > erase_end - erase_start:
            raise ValueError("Raw firmware does not fit the erase range")
        if Path(rollback.path).suffix.lower() == ".bin" and rollback.size_bytes > target.flash_end - target.flash_start:
            raise ValueError("Rollback firmware does not fit target flash")
        procedure = _required(rollback_procedure, "rollback_procedure")
        marker = _required(heartbeat_marker, "heartbeat_marker")
        if firmware.path == rollback.path or firmware.sha256 == rollback.sha256:
            raise ValueError("Rollback firmware must be a distinct verified image")
        values = {
            "target": asdict(target), "firmware": asdict(firmware),
            "rollback": asdict(rollback), "erase_start": erase_start,
            "erase_end": erase_end, "rollback_procedure": procedure,
            "heartbeat_marker": marker,
        }
        digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        return cls(target, firmware, rollback, erase_start, erase_end,
                   procedure, marker, digest)

    def verify(self) -> None:
        rebuilt = type(self).prepare(
            self.target, self.firmware, self.rollback,
            erase_start=self.erase_start, erase_end=self.erase_end,
            rollback_procedure=self.rollback_procedure,
            heartbeat_marker=self.heartbeat_marker,
        )
        if rebuilt.plan_digest != self.plan_digest:
            raise ValueError("Flash plan changed after preparation")

    def assessment(self) -> dict:
        """Reviewable blast-radius data; contains no command or approval claim."""
        self.verify()
        return {
            "plan_digest": self.plan_digest,
            "target": asdict(self.target),
            "firmware": asdict(self.firmware),
            "erase_range": {"start": self.erase_start, "end_exclusive": self.erase_end},
            "rollback": asdict(self.rollback),
            "rollback_procedure": self.rollback_procedure,
            "heartbeat_marker": self.heartbeat_marker,
            "requires_human_approval": True,
        }


@dataclass(frozen=True)
class SimulationReceipt:
    plan_digest: str
    device_id: str
    heartbeat_observed: bool
    simulated: bool = True


def simulate_flash(plan: FlashPlan, boot_log: str) -> SimulationReceipt:
    """Check a supplied fake boot log without opening ports or writing hardware."""
    plan.verify()
    if not isinstance(boot_log, str) or plan.heartbeat_marker not in boot_log:
        raise ValueError("Simulated boot log does not contain the required heartbeat")
    return SimulationReceipt(plan.plan_digest, plan.target.device_id, True)
