"""Host adapters for offline contract tests and permitted OpenCode reads."""

from __future__ import annotations

from pathlib import Path

from .execution import AgentTask, QualityEvidence
from .opencode_executor import OpenCodeV2Executor
from .orchestrator import HostTurnResult
from .simulation import SimulationExecutor


READ_ONLY_TASKS = {(1, "thirteenth"), (3, "onyx-prime"),
                   (3, "vector-prime"), (5, "liege-maximo")}


class FakeHost:
    """Deterministic host for tests; its evidence is never real acceptance."""

    host_name = "fake"
    simulated = True

    def __init__(self, *, reject_review_once: bool = False,
                 simulate_hardware_approval: bool = False) -> None:
        self.executor = SimulationExecutor(reject_review_once=reject_review_once,
                                           simulate_hardware_approval=simulate_hardware_approval)
        self.turns = 0

    def can_execute(self, task: AgentTask) -> bool:
        return True

    def execute(self, task: AgentTask, *, host_session_id: str,
                dispatch_id: str, attempt_id: str) -> HostTurnResult:
        self.turns += 1
        return HostTurnResult(self.executor.execute(task), host_session_id,
                              f"fake-turn-{self.turns}")

    def verify_evidence(self, evidence: QualityEvidence) -> bool:
        return False


class OpenCodeReadOnlyHost:
    """Use OpenCode V2 only for the existing explicitly permitted read-only roles."""

    host_name = "opencode-v2"
    simulated = False

    def __init__(self, workspace: Path, *, binary: str = "opencode2",
                 model_override: str | None = None) -> None:
        self.workspace = workspace.resolve()
        self.binary = binary
        self.model_override = model_override

    def can_execute(self, task: AgentTask) -> bool:
        return (task.step_id, task.agent_id) in READ_ONLY_TASKS

    def execute(self, task: AgentTask, *, host_session_id: str,
                dispatch_id: str, attempt_id: str) -> HostTurnResult:
        if not self.can_execute(task):
            raise ValueError("OpenCode host role is outside the read-only allowlist")
        executor = OpenCodeV2Executor(self.workspace, binary=self.binary,
                                      model_override=self.model_override,
                                      host_session_id=host_session_id)
        result = executor.execute(task)
        return HostTurnResult(result, host_session_id,
                              executor.last_host_turn_id or "")

    def verify_evidence(self, evidence: QualityEvidence) -> bool:
        # Model-produced review text is never a host tool receipt.
        return False
