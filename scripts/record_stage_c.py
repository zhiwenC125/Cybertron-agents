"""Record stage C's offline acceptance commands and their hashes."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone

from record_stage_b import ROOT, run


def main() -> None:
    receipts = [
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]),
        run([sys.executable, "-m", "cybertron.stage5_verify"]),
        run([sys.executable, "cybertron_primes_engine.py"]),
        run(["git", "diff", "--check"]),
    ]
    path = ROOT / "docs/stages/C-session-acceptance.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "stage": "C",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tests": receipts,
        "external_model_called": False,
        "hardware_operation": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if any(receipt["exit_code"] != 0 for receipt in receipts):
        raise SystemExit("Stage C acceptance failed")
    print(f"Stage C acceptance passed: {path}")


if __name__ == "__main__":
    main()
