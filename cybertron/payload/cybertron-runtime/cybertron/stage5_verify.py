"""Offline stage 5 checks: OS isolation and real QA evidence in the ledger."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .dispatch import PrimaDispatcher
from .isolated_runner import AlchemistTestExecutor, MacOSSandboxRunner
from .ledger import PrimaPlanOrchestrator


def main() -> None:
    workspace = Path(__file__).resolve().parent.parent
    runner = MacOSSandboxRunner(workspace)
    probe = r'''
import json, os, socket
from pathlib import Path
scratch = Path(os.environ["TMPDIR"])
root = Path.cwd()
checks = {}
scratch.joinpath("allowed.txt").write_text("ok")
checks["scratch_write"] = "allowed"
def connect_loopback():
    with socket.socket() as client:
        client.settimeout(1)
        client.connect(("127.0.0.1", 9))
for name, action in (
    ("project_write", lambda: root.joinpath("sandbox-escape.txt").write_text("bad")),
    ("device_read", lambda: open("/dev/null", "rb")),
    ("network_connect", connect_loopback),
):
    try:
        value = action()
        if hasattr(value, "close"):
            value.close()
        checks[name] = "ALLOWED"
    except OSError as exc:
        checks[name] = "blocked" if exc.errno in (1, 13) else f"unexpected:{exc.errno}"
print(json.dumps(checks))
'''
    report = runner.run([sys.executable, "-c", probe])
    if report.exit_code != 0 or report.timed_out:
        raise RuntimeError(f"Sandbox probe failed to start: {report.stderr[-500:]}")
    checks = json.loads(report.stdout.strip())
    print(f"Isolation: {checks}")
    if checks != {"scratch_write": "allowed", "project_write": "blocked",
                  "device_read": "blocked", "network_connect": "blocked"}:
        raise RuntimeError("Sandbox isolation checks did not pass")

    ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger("离线质量门禁验证")
    for step_id in range(1, 6):
        ledger.start_step(step_id)
        ledger.complete_step(step_id, "Synthetic prerequisite for isolated QA check",
                             ["probe://synthetic-prerequisite"])
    executor = AlchemistTestExecutor(runner, sys.executable)
    result = PrimaDispatcher(executor).run_next(ledger)
    assert result is not None
    print(f"QA: {result.status.value}; ledger step 6: {ledger.plan[5].status}")
    print(f"QA evidence: {result.quality_evidence}")
    if ledger.plan[5].status != "completed" or ledger.plan[5].quality_evidence != list(result.quality_evidence):
        raise RuntimeError(result.summary)


if __name__ == "__main__":
    main()
