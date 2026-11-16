"""M4 acceptance: build the STM32 fixture, run Renode, and execute one approved
device operation through the device broker and the v6 device-node ledger.

The script never asks for a new approval. It reads the exact user-authorization
text and binds its SHA-256 into the approval receipt and the flash plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cybertron.deployment import DeviceTarget, FirmwareArtifact, FlashPlan
from cybertron.device_broker import (ApprovalReceipt, ApprovalRejected,
                                     DeviceBroker, DeviceRejected)
from cybertron.device_node import DeviceNodeKernel
from cybertron.profiles import run_check


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "stage7_fixture" / "stm32_minimal"
EXPECTED_FIXTURE_SHA = "62554f5a0043bc92d2cfc6456e0ab116348324a1b699af62891532559e00476d"
APP_START = 0x08002000
APP_END = 0x0800FC00
FLASH_START = 0x08000000
FLASH_END = 0x08010000
HEARTBEAT_ADDRESS = 0x20000000
HEARTBEAT_VALUE = 0xC7B70001
AUTHORIZATION = ROOT / "docs" / "stages" / "v6-m4-user-authorization.txt"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(argv: list[str], cwd: Path, log: Path) -> dict:
    log.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=180, check=False)
    log.write_text(completed.stdout or "")
    return {
        "cmd": " ".join(argv), "cwd": str(cwd), "exit": completed.returncode,
        "utc": utc(), "sha256": sha_file(log), "source": "tool",
        "output_path": str(log.relative_to(ROOT)) if log.is_relative_to(ROOT) else str(log),
    }


def build_fixture(output: Path) -> dict:
    build = output / "build"
    build.mkdir(parents=True, exist_ok=True)
    gcc = run([
        "arm-none-eabi-gcc", "-mcpu=cortex-m3", "-mthumb", "-nostdlib",
        "-Wl,-T,stage7_fixture/stm32_minimal/app.ld", "-Wl,--gc-sections",
        "-o", str(build / "heartbeat.elf"), "stage7_fixture/stm32_minimal/heartbeat.s",
    ], ROOT, output / "build-gcc.log")
    if gcc["exit"] != 0:
        raise DeviceRejected("fixture cross-compile failed")
    objcopy = run([
        "arm-none-eabi-objcopy", "-O", "binary", str(build / "heartbeat.elf"),
        str(build / "heartbeat.bin"),
    ], ROOT, output / "build-objcopy.log")
    if objcopy["exit"] != 0:
        raise DeviceRejected("fixture objcopy failed")
    size = run(["arm-none-eabi-size", str(build / "heartbeat.elf")],
               ROOT, output / "build-size.log")
    if size["exit"] != 0:
        raise DeviceRejected("fixture size check failed")
    firmware = build / "heartbeat.bin"
    if sha_file(firmware) != EXPECTED_FIXTURE_SHA:
        raise DeviceRejected("rebuilt fixture hash differs from the accepted fixture")
    return {"firmware": str(firmware), "sha256": sha_file(firmware),
            "bytes": firmware.stat().st_size,
            "gcc": gcc, "objcopy": objcopy, "size": size}


def simulation_receipt() -> dict:
    result = run_check(FIXTURE, "sim")
    receipt = result["receipts"][-1]
    if result["status"] != "pass" or "CYBERTRON_SIM_PASS marker=C7B70001" not in receipt["output"]:
        raise DeviceRejected("Renode simulation did not report the expected heartbeat")
    return {**receipt, "target": "sim", "status": result["status"],
            "profile": result["profile"]}


def authorization_text() -> str:
    if not AUTHORIZATION.is_file():
        raise DeviceRejected("user authorization text is missing")
    return AUTHORIZATION.read_text()


def make_approval(plan: FlashPlan, message: str) -> ApprovalReceipt:
    message_sha = hashlib.sha256(message.encode()).hexdigest()
    return ApprovalReceipt(
        approval_id="m4-chat-" + message_sha[:16], source="human",
        approver_id="developer", observed_at_utc=utc(),
        plan_digest=plan.plan_digest, device_id=plan.target.device_id,
        firmware_sha256=plan.firmware.sha256,
        erase_start=plan.erase_start, erase_end=plan.erase_end,
        rollback_sha256=plan.rollback.sha256,
        message_sha256=message_sha, session_id="dsh:cybertron-v6-m4",
    )


def write_summary(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v6-m4-acceptance")
    parser.add_argument("--offline", action="store_true",
                        help="build and simulate only; do not touch the device")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", type=Path,
                        default=ROOT / "docs" / "stages" / "v6-m4-acceptance.json")
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (args.output or ROOT / "local_backups" / f"v6-m4-run-{stamp}").resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary: dict = {
        "milestone": "M4", "checked_at_utc": utc(),
        "offline": args.offline, "output_dir": str(output),
        "authorization_path": str(AUTHORIZATION.relative_to(ROOT)),
        "authorization_sha256": sha_file(AUTHORIZATION) if AUTHORIZATION.is_file() else None,
        "status": "blocked", "commands": [], "offline_receipts": {},
        "device": None, "events_path": None, "open_issues": [],
    }
    try:
        fixture = build_fixture(output)
        summary["offline_receipts"]["fixture"] = fixture
        summary["commands"].extend([fixture["gcc"], fixture["objcopy"], fixture["size"]])
        sim = simulation_receipt()
        summary["offline_receipts"]["sim"] = sim
        summary["commands"].append({"cmd": sim["command"], "exit": sim["exit"],
                                    "utc": sim["utc"], "sha256": sim["sha256"],
                                    "source": sim["source"]})
        if args.offline:
            summary["open_issues"].append("Device operation intentionally skipped in offline mode.")
            write_summary(args.summary, summary)
            print(json.dumps(summary, ensure_ascii=False))
            return 2

        target = DeviceTarget(
            "ST-LINK:local/STM32F1xx_MD:0x410", "STM32F103C8T6",
            "ST-LINK V2 SWD", FLASH_START, FLASH_END)
        broker = DeviceBroker(ROOT, output / "device")
        snapshot = broker.snapshot(target, app_start=APP_START, app_end=APP_END)
        summary["device"] = {"preflight": snapshot}
        rollback = Path(snapshot["app_path"])
        if rollback.stat().st_size != APP_END - APP_START:
            raise DeviceRejected("preflight App slice has the wrong size")
        plan = FlashPlan.prepare(
            target, FirmwareArtifact.inspect(Path(fixture["firmware"])),
            FirmwareArtifact.inspect(rollback),
            erase_start=APP_START, erase_end=APP_END,
            rollback_procedure=("Erase only 0x08002000..0x0800FBFF, write the "
                                "preflight App slice, read back full 64 KiB flash, "
                                "compare SHA-256 with the preflight digest, then reset."),
            heartbeat_marker="SRAM[0x20000000] == 0xC7B70001 and counter advances",
            heartbeat_address=HEARTBEAT_ADDRESS, heartbeat_value=HEARTBEAT_VALUE)
        message = authorization_text()
        approval = make_approval(plan, message)
        summary["device"].update({
            "plan_digest": plan.plan_digest,
            "firmware": {"path": plan.firmware.path, "sha256": plan.firmware.sha256,
                         "bytes": plan.firmware.size_bytes},
            "rollback": {"path": plan.rollback.path, "sha256": plan.rollback.sha256,
                         "bytes": plan.rollback.size_bytes},
            "erase": {"start": plan.erase_start, "end": plan.erase_end},
            "approval": approval.to_dict(),
        })
        workspace = output / "workspace"
        run_id = f"m4-{stamp.lower()}"
        kernel = DeviceNodeKernel(workspace, run_id, "device")
        result = kernel.run(
            plan, approval, broker,
            expected_full_sha256=snapshot["full_sha256"],
            sim_receipt=sim, build_receipt=fixture["gcc"],
            size_receipt=fixture["size"])
        summary["device"]["node"] = result
        summary["device"]["run_id"] = run_id
        summary["events_path"] = result["events_path"]
        summary["status"] = "passed" if result["status"] == "completed" else "blocked"
        if result["status"] != "completed":
            summary["open_issues"].append(result.get("error") or result["status"])
        events_copy = ROOT / "docs" / "stages" / "v6-m4-device-events.jsonl"
        events_copy.write_text(Path(result["events_path"]).read_text())
        summary["events_sha256"] = sha_file(events_copy)
        summary["events_copy"] = str(events_copy.relative_to(ROOT))
        write_summary(args.summary, summary)
        print(json.dumps({"status": summary["status"], "run_id": run_id,
                          "events": summary["events_copy"],
                          "device_result": result["status"]}, ensure_ascii=False))
        return 0 if summary["status"] == "passed" else 2
    except (DeviceRejected, ApprovalRejected, OSError, subprocess.SubprocessError) as exc:
        summary["open_issues"].append(f"{type(exc).__name__}: {exc}")
        preflight = output / "device" / "preflight.log"
        if preflight.is_file():
            summary["device"] = {"preflight_log": str(preflight.relative_to(ROOT)),
                                 "preflight_log_sha256": sha_file(preflight)}
        write_summary(args.summary, summary)
        print(json.dumps({"status": "blocked", "error": str(exc),
                          "summary": str(args.summary)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
