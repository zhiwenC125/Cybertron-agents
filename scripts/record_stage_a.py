"""Record reproducible, redacted local acceptance receipts for stage A."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs/stages/A-installation-baseline-acceptance.json"


def run(argv: list[str]) -> dict:
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
    stdout, stderr = result.stdout, result.stderr
    receipt = {
        "argv": argv,
        "exit_code": result.returncode,
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        "summary": (stderr or stdout).strip()[-500:],
    }
    match = re.search(r"Ran (\d+) tests", stderr)
    if match:
        receipt["test_count"] = int(match.group(1))
    return receipt


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/record_stage_a.py <built-wheel>")
    wheel = Path(sys.argv[1]).resolve()
    receipts = [
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]),
        run([sys.executable, "-m", "cybertron.stage5_verify"]),
        run([sys.executable, "cybertron_primes_engine.py"]),
        run(["bash", "-n", "install.sh"]),
        run(["node", "--check", "bin/cybertron.mjs"]),
        run(["node", "--check", "lib/install.mjs"]),
        run(["git", "diff", "--check"]),
    ]
    receipts.append(run(["node", "scripts/build-payload.mjs"]))
    npm_result = subprocess.run(["npm", "pack", "--dry-run", "--ignore-scripts", "--json"],
                                cwd=ROOT, capture_output=True, text=True)
    npm_files = {item["path"] for item in json.loads(npm_result.stdout)[0]["files"]}
    with ZipFile(wheel) as archive:
        wheel_files = set(archive.namelist())
    agents = {path.name for path in (ROOT / ".opencode/agents").glob("*.md")}
    package_match = (len(agents) == 13 and
                     all(f"payload/agents/{name}" in npm_files and
                         f"cybertron/payload/agents/{name}" in wheel_files for name in agents) and
                     "payload/commands/cybertron.md" in npm_files and
                     "cybertron/payload/commands/cybertron.md" in wheel_files)
    report = {
        "schema_version": 1,
        "stage": "A",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tests": receipts,
        "packages": {
            "npm_pack_exit_code": npm_result.returncode,
            "npm_payload_count": len([name for name in npm_files if name.startswith("payload/agents/")]),
            "wheel_name": wheel.name,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "wheel_payload_count": len([name for name in wheel_files if name.startswith("cybertron/payload/agents/")]),
            "matching_payload_names": package_match,
        },
        "external_model_called": False,
        "hardware_operation": False,
        "publication": "not_published",
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if any(item["exit_code"] != 0 for item in receipts) or npm_result.returncode != 0 or not package_match:
        raise SystemExit("Stage A acceptance failed; see the structured receipt")
    print(f"Stage A acceptance passed: {OUTPUT}")


if __name__ == "__main__":
    main()
