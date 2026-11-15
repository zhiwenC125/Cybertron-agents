"""Host-neutral task and result contracts for one agent dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from typing import Protocol, Tuple


class ResultStatus(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    NEEDS_APPROVAL = "needs_approval"
    REJECTED = "rejected"


class QualityKind(str, Enum):
    REVIEW_L1 = "review_l1"
    REVIEW_L2 = "review_l2"
    TEST = "test"


class EvidenceSource(str, Enum):
    UNVERIFIED = "unverified"
    MODEL = "model"
    TOOL = "tool"
    SANDBOX = "sandbox"
    HOST = "host"
    HUMAN = "human"
    SIMULATION = "simulation"


@dataclass(frozen=True)
class QualityEvidence:
    """A typed gate result; source identifies the report or run that produced it."""
    kind: QualityKind
    passed: bool
    source: str
    source_type: EvidenceSource = EvidenceSource.UNVERIFIED
    command_or_tool: str = ""
    exit_code: int | None = None
    observed_at_utc: str = ""
    output_sha256: str = ""
    verified_by: str = ""
    reference: str = ""

    def verified(self) -> bool:
        if not self.passed or not self.source.strip() or self.source_type not in (
            EvidenceSource.TOOL, EvidenceSource.SANDBOX, EvidenceSource.HOST
        ):
            return False
        if not self.command_or_tool or not self.verified_by or not re.fullmatch(r"[a-f0-9]{64}", self.output_sha256):
            return False
        try:
            timestamp = datetime.fromisoformat(self.observed_at_utc.replace("Z", "+00:00"))
        except ValueError:
            return False
        return timestamp.tzinfo is not None and (self.exit_code == 0 if self.source_type != EvidenceSource.HOST else True)


@dataclass(frozen=True)
class AgentTask:
    step_id: int
    agent_id: str
    user_request: str
    objective: str
    input_artifact: str
    expected_output: str
    prior_evidence: Tuple[str, ...] = ()
    feedback: str = ""


@dataclass(frozen=True)
class AgentResult:
    step_id: int
    agent_id: str
    status: ResultStatus
    summary: str
    evidence: Tuple[str, ...] = ()
    artifacts: Tuple[str, ...] = ()
    quality_evidence: Tuple[QualityEvidence, ...] = ()


class AgentExecutor(Protocol):
    """An adapter for a model host or deterministic local simulation."""

    def execute(self, task: AgentTask) -> AgentResult:
        ...
