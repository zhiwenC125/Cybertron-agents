"""Run project checks under a macOS sandbox with no host writes or device access."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .execution import AgentResult, AgentTask, EvidenceSource, QualityEvidence, QualityKind, ResultStatus


@dataclass(frozen=True)
class SandboxReport:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    digest: str


class MacOSSandboxRunner:
    """Fail closed when sandbox-exec is unavailable; never run a bare command."""

    def __init__(self, workspace: Path, *, timeout_seconds: int = 120) -> None:
        self.workspace = workspace.resolve()
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _profile(scratch: Path) -> str:
        # The inherited process sandbox denies network and all writes by default.
        # Read access excludes /dev so a child process cannot open serial/JTAG nodes.
        return (
            "(version 1)\n"
            "(deny default)\n"
            "(deny network*)\n"
            "(allow process*)\n"
            "(allow file-read*)\n"
            '(deny file-read* (subpath "/dev"))\n'
            '(deny file-read* (subpath "/private/dev"))\n'
            f'(allow file-write* (subpath "{scratch}"))\n'
        )

    def run(self, command: Sequence[str]) -> SandboxReport:
        binary = shutil.which("sandbox-exec")
        if binary is None:
            raise RuntimeError("sandbox-exec is unavailable; isolated execution is required")
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("A nonempty argv command is required")
        with tempfile.TemporaryDirectory(prefix="cybertron-sandbox-") as directory:
            scratch = Path(directory).resolve()
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(scratch),
                "TMPDIR": str(scratch),
                "TMP": str(scratch),
                "TEMP": str(scratch),
                "XDG_CACHE_HOME": str(scratch),
                "PYTHONDONTWRITEBYTECODE": "1",
                # Python can start without opening /dev/urandom, which is denied below.
                "PYTHONHASHSEED": "0",
                "CYBERTRON_SANDBOX": "1",
                "LANG": os.environ.get("LANG", "C.UTF-8"),
            }
            argv = [binary, "-p", self._profile(scratch), *command]
            try:
                completed = subprocess.run(
                    argv, cwd=self.workspace, env=env, text=True,
                    capture_output=True, timeout=self.timeout_seconds, check=False,
                )
                code, stdout, stderr, timed_out = (
                    completed.returncode, completed.stdout, completed.stderr, False,
                )
            except subprocess.TimeoutExpired as exc:
                code, stdout, stderr, timed_out = (
                    None, str(exc.stdout or ""), str(exc.stderr or ""), True,
                )
            digest = hashlib.sha256(
                (repr(tuple(command)) + "\n" + stdout + "\n" + stderr).encode()
            ).hexdigest()
            return SandboxReport(code, stdout, stderr, timed_out, digest)


class AlchemistTestExecutor:
    """Turn a real sandboxed unittest run into typed QA evidence."""

    def __init__(self, runner: MacOSSandboxRunner, python_binary: str) -> None:
        self.runner = runner
        self.python_binary = python_binary
        self._last_report: SandboxReport | None = None

    def verify_evidence(self, evidence: QualityEvidence) -> bool:
        report = self._last_report
        return (report is not None and report.exit_code == 0 and not report.timed_out
                and evidence.source_type == EvidenceSource.SANDBOX
                and evidence.output_sha256 == report.digest
                and evidence.source == f"sandbox://sha256/{report.digest}")

    def execute(self, task: AgentTask) -> AgentResult:
        if task.step_id != 6 or task.agent_id != "alchemist":
            raise ValueError("This executor only handles step 6 / alchemist")
        report = self.runner.run([
            self.python_binary, "-m", "unittest", "discover", "-s", "tests", "-q",
        ])
        self._last_report = report
        source = f"sandbox://sha256/{report.digest}"
        output = report.stderr or report.stdout
        count = re.search(r"Ran (\d+) tests?", output)
        if report.timed_out or report.exit_code != 0 or not count or int(count.group(1)) == 0:
            detail = (report.stderr or report.stdout).strip()[-500:]
            return AgentResult(task.step_id, task.agent_id, ResultStatus.BLOCKED,
                               f"Sandboxed tests failed or ran zero tests: {detail}", evidence=(source,))
        return AgentResult(
            task.step_id, task.agent_id, ResultStatus.COMPLETED,
            "Sandboxed unittest suite passed", evidence=(source,),
            quality_evidence=(QualityEvidence(
                QualityKind.TEST, True, source, source_type=EvidenceSource.SANDBOX,
                command_or_tool="python -m unittest discover -s tests -q",
                exit_code=report.exit_code,
                observed_at_utc=datetime.now(timezone.utc).isoformat(),
                output_sha256=report.digest,
                verified_by="MacOSSandboxRunner",
                reference=source,
            ),),
        )
