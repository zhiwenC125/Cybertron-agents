"""Host-neutral task and result contracts for one agent dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
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


@dataclass(frozen=True)
class QualityEvidence:
    """A typed gate result; source identifies the report or run that produced it."""
    kind: QualityKind
    passed: bool
    source: str


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
