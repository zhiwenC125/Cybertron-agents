"""Independently verify the M4 acceptance receipts, event chain, and restored device."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ACCEPTANCE = ROOT / "docs" / "stages" / "v6-m4-acceptance.json"
EVENTS = ROOT / "docs" / "stages" / "v6-m4-device-events.jsonl"
AUTHORIZATION = ROOT / "docs" / "stages" / "v6-m4-user-authorization.txt"
STAGE7_BACKUP = ROOT / "local_backups" / "stm32f1_2026-11-14_before-stage7.bin"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    checks: list[dict] = []

    def check(name: str, condition: bool, detail: object = None) -> None:
        checks.append({"name": name, "passed": bool(condition), "detail": detail})

    data = json.loads(ACCEPTANCE.read_text())
    events = [json.loads(line) for line in EVENTS.read_text().splitlines() if line]
    authorization = AUTHORIZATION.read_text()
    auth_sha = sha_bytes(authorization.encode())
    device = data.get("device") or {}
    result = (device.get("node") or {}).get("result") or {}
    plan = device.get("plan_digest")
    approval = device.get("approval") or {}
    preflight = device.get("preflight") or {}
    flash = result.get("flash") or {}
    heartbeat = result.get("heartbeat") or {}
    rollback = result.get("rollback") or {}
    firmware = device.get("firmware") or {}
    rollback_image = device.get("rollback") or {}

    check("status passed", data.get("status") == "passed", data.get("status"))
    check("offline false", data.get("offline") is False, data.get("offline"))
    check("authorization hash", data.get("authorization_sha256") == auth_sha,
          data.get("authorization_sha256"))
    check("approval message hash", approval.get("message_sha256") == auth_sha,
          approval.get("message_sha256"))
    check("approval plan", approval.get("plan_digest") == plan and len(plan or "") == 64)
    check("approval device", approval.get("device_id") == "ST-LINK:local/STM32F1xx_MD:0x410",
          approval.get("device_id"))
    check("approval firmware", approval.get("firmware_sha256") == firmware.get("sha256"))
    check("approval rollback", approval.get("rollback_sha256") == rollback_image.get("sha256"))
    check("approval erase", (approval.get("erase_start"), approval.get("erase_end")) ==
          (device.get("erase", {}).get("start"), device.get("erase", {}).get("end")))
    check("preflight hash", preflight.get("full_sha256") ==
          "58e2a250b260adb75b3194142bc636e82adf5a27b2958dc8ce8b00368520c252",
          preflight.get("full_sha256"))
    check("preflight bytes", preflight.get("full_bytes") == 65536, preflight.get("full_bytes"))
    check("rollback app hash", rollback_image.get("sha256") ==
          "bfa1af7bac39eb065979b8c05cb8f79ffae7260751ad3f06a019b309eebcd852",
          rollback_image.get("sha256"))
    check("rollback app bytes", rollback_image.get("bytes") == 56320, rollback_image.get("bytes"))
    check("firmware hash", firmware.get("sha256") ==
          "62554f5a0043bc92d2cfc6456e0ab116348324a1b699af62891532559e00476d",
          firmware.get("sha256"))
    check("firmware bytes", firmware.get("bytes") == 100, firmware.get("bytes"))
    check("flash region", flash.get("region_matches_fixture_and_erased_tail") is True)
    check("flash bootloader", flash.get("bootloader_unchanged") is True)
    check("flash ota flag", flash.get("ota_flag_page_unchanged") is True)
    check("flash changed", flash.get("full_sha256") != preflight.get("full_sha256"),
          flash.get("full_sha256"))
    check("heartbeat passed", heartbeat.get("passed") is True)
    check("heartbeat marker", heartbeat.get("marker_1") == heartbeat.get("marker_2") == "0xc7b70001")
    check("heartbeat counter", heartbeat.get("counter_2", 0) > heartbeat.get("counter_1", 0),
          [heartbeat.get("counter_1"), heartbeat.get("counter_2")])
    check("rollback restored", rollback.get("matches_preflight") is True)
    check("rollback full hash", rollback.get("full_sha256") == preflight.get("full_sha256"))
    check("result restored", result.get("restored") is True)
    check("node completed", (device.get("node") or {}).get("status") == "completed")

    receipts = result.get("receipts") or []
    check("receipt count", len(receipts) == 12, len(receipts))
    check("receipts are tools", all(item.get("source") == "tool" for item in receipts))
    check("receipt exits", all(item.get("exit") == 0 for item in receipts))
    check("receipt times", all(item.get("utc") for item in receipts))
    check("receipt hashes", all(sha_bytes((item.get("output") or "").encode()) == item.get("sha256")
                                for item in receipts))
    commands = " ".join(item.get("command", "") for item in receipts)
    for verb in ("erase", "write", "reset", "read"):
        check(f"receipt uses {verb}", f" {verb} " in commands)

    check("event count", len(events) == 24, len(events))
    types = [event["type"] for event in events]
    check("event order", types[:7] == ["plan.created", "gate.check", "gate.check",
                                       "gate.check", "device.planned", "approval.granted",
                                       "dispatch.started"], types[:7])
    check("one node completed", types.count("node.completed") == 1)
    check("no retry", "node.retry" not in types and "loop2.escalated" not in types)
    completed = next(event for event in events if event["type"] == "node.completed")
    evidence = completed.get("evidence") or {}
    check("evidence source", evidence.get("source") == "tool", evidence.get("source"))
    check("evidence exit", evidence.get("exit") == 0)
    check("evidence hash", len(evidence.get("sha256") or "") == 64)
    gates = {event["gate"]: event["status"] for event in events if event["type"] == "gate.check"}
    for gate in ("cross_compile", "size", "sim", "device.approval", "rollback.image", "heartbeat"):
        check(f"gate {gate}", gates.get(gate) == "pass", gates.get(gate))

    artifacts = result.get("artifacts") or {}
    check("artifacts present", len(artifacts) >= 5, len(artifacts))
    for path, digest in artifacts.items():
        check(f"artifact {Path(path).name}", Path(path).is_file() and sha_file(Path(path)) == digest)

    if not STAGE7_BACKUP.is_file():
        check("stage7 backup exists", False)
    else:
        check("stage7 backup hash", sha_file(STAGE7_BACKUP) == preflight.get("full_sha256"),
              sha_file(STAGE7_BACKUP))

    with tempfile.TemporaryDirectory(prefix="cybertron-m4-verify-") as directory:
        path = Path(directory) / "full.bin"
        completed_read = subprocess.run(
            ["st-flash", "--hot-plug", "read", str(path), "0x08000000", "0x10000"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=60, check=False)
        current = sha_file(path) if path.is_file() else None
        check("independent device read exit", completed_read.returncode == 0, completed_read.returncode)
        check("independent device read hash", current == preflight.get("full_sha256"), current)

    failures = [item for item in checks if not item["passed"]]
    report = {
        "checked_at_utc": utc(), "checks": len(checks),
        "passed": len(checks) - len(failures), "all_passed": not failures,
        "failures": failures, "checks_detail": checks,
    }
    output = ROOT / "docs" / "stages" / "v6-m4-verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"checks": report["checks"], "passed": report["passed"],
                      "all_passed": report["all_passed"],
                      "failures": [item["name"] for item in failures]}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
