"""Host adapters for offline contract tests and permitted OpenCode reads."""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from .execution import AgentResult, AgentTask, EvidenceSource, QualityEvidence, QualityKind, ResultStatus
from .isolated_runner import AlchemistTestExecutor, MacOSSandboxRunner
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


class OpenCodeWorkflowHost(OpenCodeReadOnlyHost):
    """Host-enforced role access for normal software work; hardware remains gated."""

    host_name = "opencode-v2-workflow"

    def __init__(self, workspace: Path, *, binary: str = "opencode2",
                 model_override: str | None = None) -> None:
        super().__init__(workspace, binary=binary, model_override=model_override)
        self._verified_reviews: dict[str, str] = {}
        self._qa: AlchemistTestExecutor | None = None

    def can_execute(self, task: AgentTask) -> bool:
        return (task.step_id, task.agent_id) != (8, "megatronus")

    def execute(self, task: AgentTask, *, host_session_id: str,
                dispatch_id: str, attempt_id: str) -> HostTurnResult:
        if not self.can_execute(task):
            raise ValueError("Physical flash requires a bound plan and human approval")
        executor = OpenCodeV2Executor(self.workspace, binary=self.binary,
                                      model_override=self.model_override,
                                      host_session_id=host_session_id,
                                      workflow_mode=True)
        result = executor.execute(task)
        if result.status == ResultStatus.COMPLETED and task.agent_id in ("micronus-prime", "liege-maximo"):
            raw = executor.last_raw_response
            turn_id = executor.last_host_turn_id
            observed_reads = [part for part in executor.last_tool_events
                              if part.get("tool") in ("read", "glob", "grep")]
            if not raw or not turn_id or not observed_reads:
                result = AgentResult(task.step_id, task.agent_id, ResultStatus.BLOCKED,
                                     "Review lacks a host-attested message or project read")
            else:
                kind = (QualityKind.REVIEW_L1 if task.agent_id == "micronus-prime"
                        else QualityKind.REVIEW_L2)
                digest = hashlib.sha256(raw.encode()).hexdigest()
                source = f"opencode://{host_session_id}/{turn_id}"
                self._verified_reviews[source] = digest
                receipt = QualityEvidence(
                    kind, True, source, source_type=EvidenceSource.HOST,
                    command_or_tool=f"opencode2:review:{task.agent_id}", exit_code=0,
                    observed_at_utc=datetime.now(timezone.utc).isoformat(),
                    output_sha256=digest, verified_by="OpenCodeWorkflowHost",
                    reference=source)
                result = AgentResult(task.step_id, task.agent_id, result.status,
                                     result.summary, evidence=result.evidence,
                                     artifacts=result.artifacts,
                                     quality_evidence=result.quality_evidence + (receipt,))
        if result.status == ResultStatus.COMPLETED and task.agent_id == "alchemist":
            try:
                self._qa = AlchemistTestExecutor(MacOSSandboxRunner(self.workspace), sys.executable)
                qa_result = self._qa.execute(task)
            except RuntimeError as exc:
                qa_result = AgentResult(task.step_id, task.agent_id, ResultStatus.BLOCKED,
                                        f"Isolated QA unavailable: {exc}")
            if qa_result.status == ResultStatus.COMPLETED:
                result = AgentResult(task.step_id, task.agent_id, ResultStatus.COMPLETED,
                                     result.summary + "; isolated unittest passed",
                                     evidence=result.evidence + qa_result.evidence,
                                     artifacts=result.artifacts,
                                     quality_evidence=qa_result.quality_evidence)
            else:
                result = qa_result
        return HostTurnResult(result, host_session_id, executor.last_host_turn_id or "")

    def verify_evidence(self, evidence: QualityEvidence) -> bool:
        if (evidence.source_type == EvidenceSource.HOST and
                evidence.verified_by == "OpenCodeWorkflowHost"):
            return self._verified_reviews.get(evidence.source) == evidence.output_sha256
        return self._qa.verify_evidence(evidence) if self._qa is not None else False
