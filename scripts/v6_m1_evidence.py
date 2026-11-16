"""Capture M1 command receipts from actual local tools, never model claims."""

import hashlib
import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STAGE = ROOT / "docs/stages"
COMMANDS = [
    ("unittest", ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"], None),
    ("plugin", ["node", "--test", "tests/v6_plugin_hook.test.mjs",
                "tests/v6_plugin_runtime.test.mjs"], None),
    ("bundle-check", ["python3", "-c",
                      "from pathlib import Path; from cybertron.opencode_v2 import validate_bundle; "
                      "errors=validate_bundle(Path('.')); print('bundle errors:', errors); "
                      "raise SystemExit(bool(errors))"], None),
    ("plan-shapes", ["python3", "tests/v6_m1_probe.py"], {"PYTHONPATH": "."}),
    ("stage5", ["python3", "-m", "cybertron.stage5_verify"], None),
    ("engine", ["python3", "cybertron_primes_engine.py"], None),
    ("host-config", ["opencode2", "debug", "config"], None),
    ("diff-check", ["git", "diff", "--check"], None),
]


def main() -> int:
    receipts = []
    for name, argv, extra_env in COMMANDS:
        env = {**os.environ, **(extra_env or {})}
        completed = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True)
        output = completed.stdout + completed.stderr
        path = STAGE / f"v6-m1-{name}.log"
        # Host configuration may include machine-specific settings or secrets.
        # Keep its hash and exit code without copying that output into the repo.
        if name != "host-config":
            path.write_bytes(output)
        receipt = {
            "cmd": ("PYTHONPATH=. " if extra_env else "") + shlex.join(argv),
            "cwd": str(ROOT), "exit": completed.returncode,
            "utc": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(output).hexdigest(), "source": "tool",
            "output_path": str(path.relative_to(ROOT)) if name != "host-config" else None,
        }
        receipts.append(receipt)
        print(f"{name}: exit={completed.returncode} sha256={receipt['sha256']}")
        if completed.returncode:
            break
    evidence = {
        "milestone": "M1", "status": "blocked", "commit": None,
        "required_gates": ["unit_tests_all_green", "plugin_hooks", "catalog_invariants",
                           "graph_ops", "plan_shapes", "export_permission_consistency"],
        "commands": receipts, "host": None,
        "plan_shapes_path": "docs/stages/v6-m1-plan-shapes.json",
        "negative_cases": ["seven catalog invariants reject violations",
                           "invalid graph operations preserve revision and nodes",
                           "M2 gate conclusions fail closed",
                           "native dispatch mismatch is rejected visibly"],
        "open_issues": [] if len(receipts) == len(COMMANDS) and all(r["exit"] == 0 for r in receipts)
                       else ["M1 command gate failed; inspect the corresponding log"],
    }
    (STAGE / "v6-m1.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    return 0 if not evidence["open_issues"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
