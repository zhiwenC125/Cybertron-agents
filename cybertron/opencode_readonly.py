"""Probe two real read-only discovery roles without running the coding workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from .dispatch import PrimaDispatcher
from .execution import AgentTask
from .ledger import PrimaPlanOrchestrator
from .opencode_executor import OpenCodeV2Executor


def main() -> None:
    parser = argparse.ArgumentParser(description="Run two OpenCode V2 read-only roles")
    parser.add_argument("request", help="Question about the generated OpenCode bundle")
    parser.add_argument("--bundle", default=".",
                        help="Project root containing opencode.jsonc and source files")
    parser.add_argument("--model", help="Override the role's configured model for this probe")
    parser.add_argument("--only-vector", action="store_true",
                        help="Retry only vector-prime without rerunning onyx-prime")
    args = parser.parse_args()
    executor = OpenCodeV2Executor(Path(args.bundle).resolve(), model_override=args.model)
    if args.only_vector:
        task = AgentTask(3, "vector-prime", args.request,
                         "只读追溯 Git 历史和固件基线，输出相关提交与差异",
                         "Git repository", "Git baseline report")
        result = executor.execute(task)
        print(f"vector-prime: {result.status.value}: {result.summary}")
        print("Single-role retry; the prior onyx-prime result is not replayed into a ledger")
        return
    ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger(args.request)
    for step_id in (1, 2):
        ledger.start_step(step_id)
        ledger.complete_step(step_id, "Probe prerequisite only", ["probe://synthetic-prerequisite"])
    dispatcher = PrimaDispatcher(executor)
    for _ in range(2):
        result = dispatcher.run_next(ledger)
        assert result is not None
        print(f"{result.agent_id}: {result.status.value}: {result.summary}")
        if result.status.value != "completed":
            break
    print(f"Ledger step 3: {ledger.plan[2].status}; completed roles: {ledger.plan[2].completed_agents}")


if __name__ == "__main__":
    main()
