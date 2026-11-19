"""Intent contract: what the user asked for and what counts as done.

The intent is authored by ``thirteenth`` during clarification and stored with
the plan.  Nodes reference done criteria through ``satisfies``.  The kernel
uses the contract in two places only:

* plan review: every done criterion must be covered by at least one node, and
  explicit constraints must not be violated;
* completion: every done criterion must have real evidence from a completed
  node (or a test gate), not model text.

This module deliberately has no dependency on ``graph`` to keep validation
pure and importable from the bridge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


EVIDENCE_KINDS = ("artifact", "test", "review", "receipt")
_DONE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class IntentRejected(ValueError):
    """The intent payload is malformed or internally inconsistent."""


def _strings(value: Any, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if value is None and allow_empty:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise IntentRejected(f"{field} must be a list of strings")
    items = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise IntentRejected(f"{field} must contain nonempty strings")
        items.append(item.strip())
    return tuple(items)


@dataclass(frozen=True)
class DoneCriterion:
    id: str
    criterion: str
    evidence: str = "receipt"

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _DONE_ID.fullmatch(self.id):
            raise IntentRejected("done id must match [a-z][a-z0-9_-]{0,31}")
        if not isinstance(self.criterion, str) or not self.criterion.strip():
            raise IntentRejected("done criterion is required")
        if self.evidence not in EVIDENCE_KINDS:
            raise IntentRejected(f"done evidence must be one of {', '.join(EVIDENCE_KINDS)}")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "criterion": self.criterion.strip(),
                "evidence": self.evidence}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DoneCriterion":
        if not isinstance(data, Mapping) or set(data) - {"id", "criterion", "evidence"}:
            raise IntentRejected("invalid done criterion fields")
        if "id" not in data or "criterion" not in data:
            raise IntentRejected("done criterion requires id and criterion")
        return cls(id=data["id"], criterion=data["criterion"],
                   evidence=data.get("evidence", "receipt"))


@dataclass(frozen=True)
class Intent:
    goal: str
    done: tuple[DoneCriterion, ...]
    source: str = "chat"
    non_goals: tuple[str, ...] = ()
    forbidden_capabilities: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    confirmed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.goal, str) or not self.goal.strip():
            raise IntentRejected("intent goal is required")
        if not self.done:
            raise IntentRejected("intent requires at least one done criterion")
        if len({item.id for item in self.done}) != len(self.done):
            raise IntentRejected("done ids must be unique")
        if not isinstance(self.source, str) or not self.source.strip():
            raise IntentRejected("intent source is required")
        if not isinstance(self.confirmed, bool):
            raise IntentRejected("intent confirmed must be a boolean")

    @property
    def done_ids(self) -> frozenset[str]:
        return frozenset(item.id for item in self.done)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal.strip(),
            "source": self.source.strip(),
            "done": [item.to_dict() for item in self.done],
            "non_goals": list(self.non_goals),
            "forbidden_capabilities": list(self.forbidden_capabilities),
            "forbidden_paths": list(self.forbidden_paths),
            "confirmed": self.confirmed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Intent":
        if not isinstance(data, Mapping):
            raise IntentRejected("intent must be an object")
        allowed = {"goal", "source", "done", "non_goals", "forbidden_capabilities",
                   "forbidden_paths", "confirmed"}
        if set(data) - allowed:
            raise IntentRejected("unknown intent field")
        if "goal" not in data or "done" not in data:
            raise IntentRejected("intent requires goal and done")
        raw_done = data["done"]
        if isinstance(raw_done, (str, bytes)) or not isinstance(raw_done, (list, tuple)):
            raise IntentRejected("done must be a list")
        done = tuple(DoneCriterion.from_dict(item) for item in raw_done)
        return cls(
            goal=data["goal"],
            done=done,
            source=data.get("source", "chat"),
            non_goals=_strings(data.get("non_goals"), "non_goals"),
            forbidden_capabilities=_strings(
                data.get("forbidden_capabilities"), "forbidden_capabilities"),
            forbidden_paths=_strings(data.get("forbidden_paths"), "forbidden_paths"),
            confirmed=data.get("confirmed", False),
        )


def coverage(intent: Intent | None, nodes: Mapping[str, Any],
             node_status: Mapping[str, str], events: Iterable[Mapping[str, Any]],
             passed_gates: Iterable[str],
             gate_nodes: Mapping[str, Iterable[str | None]] | None = None) -> list[dict[str, Any]]:
    """Return per-done coverage.  ``satisfied`` only when evidence exists.

    Evidence rules are intentionally small for Phase 1:

    * ``artifact``: a covering node completed with at least one artifact;
    * ``test``: a covering node completed and a test or sim gate bound to that
      node (through ``gate_nodes``) passed;
    * ``review``: a covering review node completed;
    * ``receipt``: a covering node completed (host receipt exists).
    """
    if intent is None:
        return []
    events = list(events)
    artifacts = {event.get("node_id") for event in events
                 if event.get("type") == "node.completed" and event.get("artifacts")}
    completed = {node_id for node_id, value in node_status.items() if value == "completed"}
    test_nodes: set[str] = set()
    if gate_nodes is not None:
        for gate in ("test", "sim"):
            test_nodes.update(node_id for node_id in gate_nodes.get(gate, ())
                              if isinstance(node_id, str) and node_id)
    else:
        # Legacy callers that only pass a gate set cannot prove which node the
        # gate belongs to.  Treat them as run-level facts, not node evidence.
        test_nodes = set()
    result: list[dict[str, Any]] = []
    for done in intent.done:
        covering = [node_id for node_id, node in nodes.items()
                    if done.id in getattr(node, "satisfies", ())]
        satisfied_by: list[str] = []
        for node_id in covering:
            if node_id not in completed:
                continue
            if done.evidence == "artifact" and node_id not in artifacts:
                continue
            if done.evidence == "test" and node_id not in test_nodes:
                continue
            if done.evidence == "review" and getattr(nodes[node_id], "kind", "") != "review":
                continue
            satisfied_by.append(node_id)
        if not covering:
            reason = "no node satisfies this criterion"
        elif not satisfied_by and not any(node_id in completed for node_id in covering):
            reason = "covering nodes have not completed"
        elif done.evidence == "artifact":
            reason = "no completed artifact for this criterion"
        elif done.evidence == "test":
            reason = "no passing test/sim gate bound to a covering node"
        elif done.evidence == "review":
            reason = "no completed review node"
        else:
            reason = "no host receipt for this criterion"
        result.append({
            "id": done.id,
            "criterion": done.criterion,
            "evidence": done.evidence,
            "covered_by": covering,
            "satisfied_by": satisfied_by,
            "satisfied": bool(satisfied_by),
            "reason": None if satisfied_by else reason,
        })
    return result
