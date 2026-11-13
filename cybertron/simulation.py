"""Side-effect-free local exercise of the dispatch contract."""

from __future__ import annotations

import argparse

from .dispatch import PrimaDispatcher
from .execution import AgentResult, AgentTask, ResultStatus
from .ledger import PrimaPlanOrchestrator


class SimulationExecutor:
    def __init__(self, *, simulate_hardware_approval: bool = False,
                 reject_review_once: bool = False) -> None:
        self.simulate_hardware_approval = simulate_hardware_approval
        self.reject_review_once = reject_review_once
        self._review_rejected = False

    def execute(self, task: AgentTask) -> AgentResult:
        if task.agent_id == "liege-maximo" and self.reject_review_once and not self._review_rejected:
            self._review_rejected = True
            return AgentResult(task.step_id, task.agent_id, ResultStatus.REJECTED,
                               "模拟发现并发访问缺少同步；请修复后重新审查")
        if task.step_id == 8 and not self.simulate_hardware_approval:
            return AgentResult(
                task.step_id, task.agent_id, ResultStatus.NEEDS_APPROVAL,
                "模拟硬件步骤等待批准；未执行任何烧录命令",
            )
        return AgentResult(
            task.step_id, task.agent_id, ResultStatus.COMPLETED,
            f"模拟完成：{task.objective}" + (f"；已处理反馈：{task.feedback}" if task.feedback else ""),
            evidence=(f"simulation://step/{task.step_id}/{task.agent_id}",),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a side-effect-free Cybertron workflow simulation")
    parser.add_argument("request", nargs="?", default="模拟研发任务")
    parser.add_argument("--simulate-hardware-approval", action="store_true")
    parser.add_argument("--reject-review-once", action="store_true",
                        help="Inject one L2 rejection and exercise the repair loop")
    args = parser.parse_args()
    ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger(args.request)
    dispatcher = PrimaDispatcher(SimulationExecutor(
        simulate_hardware_approval=args.simulate_hardware_approval,
        reject_review_once=args.reject_review_once,
    ))
    results = dispatcher.run_until_blocked(ledger)
    while results and results[-1].status == ResultStatus.REJECTED and ledger.next_step().status == "pending":
        results.extend(dispatcher.run_until_blocked(ledger))
    for result in results:
        print(f"Step {result.step_id}: {result.agent_id} → {result.status.value}: {result.summary}")
    print(f"Completed {sum(step.status == 'completed' for step in ledger.plan)}/{len(ledger.plan)} steps")


if __name__ == "__main__":
    main()
