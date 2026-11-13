"""Read-only USB and toolchain inventory for the stage 7 MCU MVP."""

from __future__ import annotations

import json
import plistlib
import shutil
import subprocess
from typing import Any


def summarize_usb_registry(data: bytes) -> dict[str, list[dict[str, Any]]]:
    """Report only USB descriptors; never claim a target MCU was identified."""
    entries = plistlib.loads(data)
    result: dict[str, list[dict[str, Any]]] = {
        "stlink_probes": [], "esp32_native_usb_candidates": [],
        "other_usb_serial_candidates": [],
    }

    def visit(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return
        product = str(item.get("USB Product Name") or item.get("kUSBProductString") or "")
        vendor = item.get("idVendor")
        device = item.get("idProduct")
        if isinstance(vendor, int) and isinstance(device, int):
            descriptor = {"product": product, "vendor_id": vendor, "product_id": device}
            if vendor == 0x0483 and "stlink" in product.lower().replace("-", ""):
                result["stlink_probes"].append(descriptor)
            elif vendor == 0x303A:
                result["esp32_native_usb_candidates"].append(descriptor)
            elif "serial" in product.lower() or "uart" in product.lower():
                result["other_usb_serial_candidates"].append(descriptor)
        for child in item.get("IORegistryEntryChildren", []):
            visit(child)

    visit(entries)
    return result


def main() -> None:
    binary = shutil.which("ioreg")
    if binary is None:
        raise SystemExit("macOS ioreg is required for read-only USB inventory")
    completed = subprocess.run(
        [binary, "-p", "IOUSB", "-a", "-l", "-w", "0"],
        capture_output=True, timeout=15, check=False,
    )
    if completed.returncode:
        raise SystemExit("USB registry inventory failed")
    report = summarize_usb_registry(completed.stdout)
    report["tools_on_path"] = {
        name: bool(shutil.which(name))
        for name in ("arm-none-eabi-gcc", "STM32_Programmer_CLI", "openocd",
                     "idf.py", "esptool", "pio")
    }
    report["target_mcu_identified"] = False
    report["device_opened"] = False
    report["firmware_written"] = False
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
