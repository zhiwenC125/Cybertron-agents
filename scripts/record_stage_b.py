"""Record local stage B test receipts without copying raw tool logs into Git."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs/stages/B-runstore-acceptance.json"


def run(argv: list[str]) -> dict:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
    receipt = {
        "argv": argv,
        "exit_code": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        "summary": (result.stderr or result.stdout).strip()[-500:],
    }
    tests = re.search(r"Ran (\d+) tests", result.stderr)
    if tests:
        receipt["test_count"] = int(tests.group(1))
    return receipt


def main() -> None:
    receipts = [
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]),
        run([sys.executable, "-m", "cybertron.stage5_verify"]),
        run([sys.executable, "cybertron_primes_engine.py"]),
        run(["git", "diff", "--check"]),
    ]
    OUTPUT.write_text(json.dumps({
        "schema_version": 1,
        "stage": "B",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tests": receipts,
        "external_model_called": False,
        "hardware_operation": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if any(receipt["exit_code"] != 0 for receipt in receipts):
        raise SystemExit("Stage B acceptance failed")
    print(f"Stage B acceptance passed: {OUTPUT}")


if __name__ == "__main__":
    main()
