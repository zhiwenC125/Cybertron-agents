"""Move the ledger one step after validating an executor result."""

from __future__ import annotations

from .execution import AgentExecutor, AgentResult, AgentTask, ResultStatus
from .ledger import CybertronTaskLedger
from .registry import THIRTEEN_PRIMES_REGISTRY


class PrimaDispatcher:
    def __init__(self, executor: AgentExecutor) -> None:
        self.executor = executor
        self.agent_ids = {agent.agent_id for agent in THIRTEEN_PRIMES_REGISTRY}

    def run_next(self, ledger: CybertronTaskLedger) -> AgentResult | None:
        step = ledger.next_step()
        if step is None:
            return None
        agent_id = step.next_agent()
        if agent_id is None:
            raise ValueError(f"Step {step.step_id} has no remaining agent")
        if agent_id not in self.agent_ids:
            raise ValueError(f"Unknown agent: {agent_id}")
        if ledger.turn_count >= ledger.max_turns:
            raise RuntimeError("Ledger turn limit reached")
        if step.status == "blocked":
            raise ValueError(f"Step {step.step_id} is blocked; resume it first")
        if step.status == "pending":
            ledger.start_step(step.step_id)

        task = AgentTask(
            step_id=step.step_id,
            agent_id=agent_id,
            user_request=ledger.user_request,
            objective=step.participant_objectives.get(agent_id, step.objective),
            input_artifact=step.input_artifact,
            expected_output=step.expected_output,
            feedback=step.feedback,
            prior_evidence=tuple(
                item for completed in ledger.plan if completed.status == "completed"
                for item in completed.evidence
            ) + tuple(step.evidence),
        )
        ledger.turn_count += 1
        try:
            result = self.executor.execute(task)
        except Exception as exc:
            ledger.block_step(step.step_id, f"Executor error: {exc}")
            raise

        if result.step_id != task.step_id or result.agent_id != task.agent_id:
            ledger.block_step(step.step_id, "Executor returned a result for a different task")
            raise ValueError("Executor returned a result for a different task")
        if not result.summary.strip():
            ledger.block_step(step.step_id, "Executor returned an empty summary")
            raise ValueError("Executor returned an empty summary")
        if result.status == ResultStatus.COMPLETED:
            if not result.evidence or not all(item.strip() for item in result.evidence):
                ledger.block_step(step.step_id, "Completion has no evidence")
                raise ValueError("Completion requires nonempty evidence")
            ledger.record_agent_completion(step.step_id, agent_id, result.summary,
                                           list(result.evidence), list(result.artifacts))
        elif result.status in (ResultStatus.BLOCKED, ResultStatus.NEEDS_APPROVAL):
            ledger.block_step(step.step_id, result.summary)
        elif result.status == ResultStatus.REJECTED:
            ledger.reject_review(agent_id, result.summary)
        else:
            ledger.block_step(step.step_id, "Unknown executor status")
            raise ValueError("Unknown executor status")
        return result

    def run_until_blocked(self, ledger: CybertronTaskLedger) -> list[AgentResult]:
        results: list[AgentResult] = []
        while ledger.next_step() is not None:
            result = self.run_next(ledger)
            assert result is not None
            results.append(result)
            if result.status != ResultStatus.COMPLETED:
                break
        return results
