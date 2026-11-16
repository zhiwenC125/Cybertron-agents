"""M2 risk floors and evidence-backed gate conclusions.

The model may request additional gates. Only the kernel computes a floor from
workspace snapshots and records tool, sandbox, or host receipts.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import PurePosixPath
from typing import Mapping

from .scope_guard import Snapshot
from .profiles import CheckReceipt


class GateRejected(ValueError):
    pass


class Risk(IntEnum):
    DOCUMENT = 0
    CODE = 1
    INTERFACE = 2
    FIRMWARE = 3
    DEVICE = 4


_FLOORS = {
    Risk.DOCUMENT: frozenset({"scope_guard"}),
    Risk.CODE: frozenset({"scope_guard", "lint", "test", "review.l2.light"}),
    Risk.INTERFACE: frozenset({"scope_guard", "lint", "test", "review.l2.full", "build", "plan.confirm"}),
    Risk.FIRMWARE: frozenset({"scope_guard", "lint", "test", "review.l2.full", "build", "plan.confirm",
                            "cross_compile", "size"}),
    Risk.DEVICE: frozenset({"scope_guard", "lint", "test", "review.l2.full", "build", "plan.confirm",
                          "cross_compile", "size", "device.approval", "rollback.image", "heartbeat"}),
}


@dataclass(frozen=True)
class DiffFacts:
    paths: tuple[str, ...]
    changed_lines: int
    modules: tuple[str, ...]
    public_interface: bool
    firmware: bool
    device_operation: bool = False


def diff_facts(before: Snapshot, after: Snapshot, *, device_operation: bool = False) -> DiffFacts:
    """Derive risk inputs from actual workspace bytes, never model arguments."""
    paths = tuple(sorted(path for path in before.entries.keys() | after.entries.keys()
                         if before.entries.get(path) != after.entries.get(path)
                         and not path.startswith(".cybertron/runs/")
                         and (before.entries.get(path) or after.entries.get(path)).kind != "directory"))
    lines = 0
    for path in paths:
        old = before.entries.get(path)
        new = after.entries.get(path)
        if not (old and old.kind == "file" or new and new.kind == "file"):
            continue
        old_lines = old.content.decode("utf-8", errors="replace").splitlines() if old and old.kind == "file" else []
        new_lines = new.content.decode("utf-8", errors="replace").splitlines() if new and new.kind == "file" else []
        lines += sum(1 for line in difflib.ndiff(old_lines, new_lines) if line[:1] in {"+", "-"})
    modules = tuple(sorted({PurePosixPath(path).parts[0] for path in paths if "/" in path}))
    public = any(path.startswith(("include/", "api/")) or path.endswith((".h", "interfaces.py", "schemas.py"))
                 for path in paths)
    firmware = any(path.startswith(("firmware/", "drivers/", "bsp/")) or path.endswith(".ioc") for path in paths)
    return DiffFacts(paths, lines, modules, public, firmware, device_operation)


def risk_floor(facts: DiffFacts, *, simulation_available: bool = False) -> tuple[Risk, frozenset[str]]:
    if facts.device_operation:
        risk = Risk.DEVICE
    elif facts.firmware:
        risk = Risk.FIRMWARE
    elif facts.public_interface or len(facts.modules) > 1 or facts.changed_lines > 200:
        risk = Risk.INTERFACE
    elif facts.paths and all(path.endswith(".md") for path in facts.paths):
        risk = Risk.DOCUMENT
    else:
        risk = Risk.CODE
    floor = _FLOORS[risk]
    if risk >= Risk.FIRMWARE and simulation_available:
        floor |= {"sim"}
    return risk, frozenset(floor)


def _receipt_valid(receipt: Mapping[str, object]) -> bool:
    return (receipt.get("source") in {"tool", "sandbox", "host"}
            and isinstance(receipt.get("command"), str) and bool(receipt["command"])
            and type(receipt.get("exit")) is int
            and isinstance(receipt.get("utc"), str) and bool(receipt["utc"])
            and isinstance(receipt.get("sha256"), str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"])))


def _fingerprint(receipt: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(dict(receipt), sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class GateLedger:
    floor: frozenset[str]
    added: set[str] = field(default_factory=set)
    conclusions: dict[str, dict] = field(default_factory=dict)
    _trusted: set[str] = field(default_factory=set, repr=False)

    @property
    def required(self) -> frozenset[str]:
        return self.floor | self.added

    def add(self, gate: str) -> None:
        if not isinstance(gate, str) or not gate:
            raise GateRejected("gate name is required")
        self.added.add(gate)

    def trust_check(self, gate: str, receipt: CheckReceipt) -> None:
        """Kernel-only entry point for a receipt returned by the check runner."""
        if gate not in {"lint", "build", "test"} or not isinstance(receipt, CheckReceipt):
            raise GateRejected("unsupported check receipt")
        data = receipt.to_dict()
        expected = {"lint": "clang-tidy", "build": "cmake --build", "test": "unittest"}[gate]
        if (not _receipt_valid(data) or data["source"] != "sandbox"
                or expected not in data["command"]
                or hashlib.sha256(data["output"].encode()).hexdigest() != data["sha256"]):
            raise GateRejected("check receipt is not authentic")
        self._trusted.add(_fingerprint(data))

    def record(self, gate: str, outcome: str, receipt: Mapping[str, object]) -> None:
        if gate not in self.required or not _receipt_valid(receipt):
            raise GateRejected("gate or trusted receipt is missing")
        if _fingerprint(receipt) not in self._trusted:
            raise GateRejected("receipt was not registered by the kernel")
        if outcome == "pass" and receipt["exit"] != 0:
            raise GateRejected("pass requires successful tool receipt")
        if outcome == "fail" and receipt["exit"] == 0:
            raise GateRejected("fail requires failing tool receipt")
        if outcome == "not_applicable":
            if gate != "test" or gate in self.floor or receipt.get("profile_probe") != "test_framework_absent":
                raise GateRejected("only an optional test gate with a real profile probe can be not applicable")
        elif outcome == "waived":
            if gate != "test" or receipt.get("source") != "host" or receipt.get("kind") != "user_waiver" or not receipt.get("approval_id"):
                raise GateRejected("waiver requires an actual host approval receipt")
        elif outcome not in {"pass", "fail"}:
            raise GateRejected("unknown gate outcome")
        self.conclusions[gate] = {"outcome": outcome, "receipt": dict(receipt)}

    def complete(self) -> bool:
        return all(self.conclusions.get(gate, {}).get("outcome") in {"pass", "waived", "not_applicable"}
                   for gate in self.required)
