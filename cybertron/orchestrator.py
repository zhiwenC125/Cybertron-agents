"""Persistent outer dispatch loop above a model host.

The host owns each role's model/tool loop. Cybertron records intent before a
host call, applies validated results afterward, and never retries an unknown
turn automatically.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from .dispatch import PrimaDispatcher
from .execution import AgentResult, AgentTask, QualityEvidence, ResultStatus
from .runstore import RunStore, RunStoreError


@dataclass(frozen=True)
class HostTurnResult:
    result: AgentResult
    host_session_id: str
    host_turn_id: str


class HostAdapter(Protocol):
    host_name: str
    simulated: bool

    def can_execute(self, task: AgentTask) -> bool:
        ...

    def execute(self, task: AgentTask, *, host_session_id: str,
                dispatch_id: str, attempt_id: str) -> HostTurnResult:
        ...

    def verify_evidence(self, evidence: QualityEvidence) -> bool:
        ...


class RunCoordinator:
    def __init__(self, store: RunStore, host: HostAdapter) -> None:
        self.store = store
        self.host = host
        self.dispatcher = PrimaDispatcher(host, allow_simulated_evidence=host.simulated)

    def _open_dispatch(self, run_id: str) -> dict | None:
        started = {}
        closed = set()
        for event in self.store.events(run_id):
            if event["type"] == "dispatch.started":
                started[event["dispatch_id"]] = event
            elif event["type"] in ("dispatch.completed", "dispatch.blocked"):
                closed.add(event["dispatch_id"])
        remaining = [event for dispatch_id, event in started.items() if dispatch_id not in closed]
        if len(remaining) > 1:
            raise RunStoreError("Run has multiple unresolved dispatches")
        return remaining[0] if remaining else None

    def status(self, run_id: str) -> dict:
        state = self.store.show(run_id)
        unresolved = self._open_dispatch(run_id)
        if unresolved:
            state["dispatch_status"] = "outcome_unknown"
            state["dispatch_id"] = unresolved["dispatch_id"]
            state["host_session_id"] = unresolved["payload"]["host_session_id"]
        else:
            state["dispatch_status"] = "idle"
        return state

    def step(self, run_id: str) -> dict:
        self.store.resume(run_id)  # Rebuild snapshots; never invokes a host.
        unresolved = self._open_dispatch(run_id)
        if unresolved:
            return self.status(run_id)
        ledger = self.store.load_ledger(run_id)
        step = ledger.next_step()
        if step is None or step.status == "blocked":
            return self.status(run_id)
        if step.step_id == 8 and step.objective.startswith("软件任务无需物理烧录"):
            expected_seq = self.store.show(run_id)["event_seq"]
            def skip_hardware(current) -> None:
                current.start_step(8)
                current.complete_step(8, "软件任务不涉及设备或物理烧录", ["scope://software-only"])
            self.store.transition(run_id, "stage.skipped", skip_hardware, stage_id=8,
                                  payload={"reason": "software_only_no_device"},
                                  expected_seq=expected_seq)
            return self.status(run_id)
        agent_id = step.next_agent()
        if agent_id is None:
            raise RunStoreError("Active stage has no remaining role")
        expected_seq = self.store.show(run_id)["event_seq"]
        preview = AgentTask(step.step_id, agent_id, ledger.user_request,
                            step.participant_objectives.get(agent_id, step.objective),
                            step.input_artifact, step.expected_output)
        if not self.host.can_execute(preview):
            def block(current) -> None:
                active = current.next_step()
                if active.status == "pending":
                    current.start_step(active.step_id)
                current.block_step(active.step_id, f"Host {self.host.host_name} does not support {agent_id}")

            self.store.transition(run_id, "run.blocked", block, stage_id=step.step_id,
                                  payload={"reason": "unsupported_role", "agent_id": agent_id},
                                  expected_seq=expected_seq)
            return self.status(run_id)

        dispatch_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        host_session_id = f"ses_{uuid.uuid4().hex}"
        prepared = []

        def start(current) -> None:
            task = self.dispatcher.prepare_task(current)
            if task is None or task.step_id != step.step_id or task.agent_id != agent_id:
                raise RunStoreError("Run changed while preparing dispatch")
            prepared.append(task)

        started = self.store.transition(run_id, "dispatch.started", start, stage_id=step.step_id,
                                        dispatch_id=dispatch_id, attempt_id=attempt_id,
                                        payload={"agent_id": agent_id, "host": self.host.host_name,
                                                 "host_session_id": host_session_id},
                                        expected_seq=expected_seq)
        task = prepared[0]
        try:
            turn = self.host.execute(task, host_session_id=host_session_id,
                                     dispatch_id=dispatch_id, attempt_id=attempt_id)
        except Exception as exc:
            self.store.transition(run_id, "dispatch.outcome_unknown", lambda current: None,
                                  stage_id=step.step_id, dispatch_id=dispatch_id,
                                  attempt_id=attempt_id,
                                  payload={"host_session_id": host_session_id,
                                           "reason": type(exc).__name__},
                                  expected_seq=started["event_seq"])
            return self.status(run_id)

        if turn.host_session_id != host_session_id or not turn.host_turn_id:
            self.store.transition(run_id, "dispatch.outcome_unknown", lambda current: None,
                                  stage_id=step.step_id, dispatch_id=dispatch_id,
                                  attempt_id=attempt_id,
                                  payload={"host_session_id": host_session_id,
                                           "reason": "host_identity_mismatch"},
                                  expected_seq=started["event_seq"])
            return self.status(run_id)
        result = turn.result
        try:
            self.store.transition(run_id, "dispatch.completed",
                                  lambda current: self.dispatcher.apply_result(current, task, result),
                                  stage_id=step.step_id, dispatch_id=dispatch_id,
                                  attempt_id=attempt_id,
                                  payload={"host_session_id": host_session_id,
                                           "host_turn_id": turn.host_turn_id,
                                           "agent_id": agent_id,
                                           "result_status": result.status.value},
                                  expected_seq=started["event_seq"])
        except ValueError as exc:
            def block_invalid(current) -> None:
                active = current.next_step()
                if active is not None and active.step_id == step.step_id and active.status == "in_progress":
                    current.block_step(step.step_id, f"Invalid host result: {exc}")

            self.store.transition(run_id, "dispatch.blocked", block_invalid,
                                  stage_id=step.step_id, dispatch_id=dispatch_id,
                                  attempt_id=attempt_id,
                                  payload={"host_session_id": host_session_id,
                                           "host_turn_id": turn.host_turn_id,
                                           "reason": str(exc)[:200]},
                                  expected_seq=started["event_seq"])
        return self.status(run_id)

    def run_until_blocked(self, run_id: str) -> dict:
        for _ in range(40):
            state = self.step(run_id)
            if state["dispatch_status"] == "outcome_unknown" or state["status"] in ("blocked", "completed"):
                return state
        raise RunStoreError("Dispatch safety limit reached")
