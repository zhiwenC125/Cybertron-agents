"""Exercise the real L2 reviewer against a read-only config review task."""

from __future__ import annotations

import argparse
from pathlib import Path

from .dispatch import PrimaDispatcher
from .execution import QualityEvidence, QualityKind
from .ledger import PrimaPlanOrchestrator
from .opencode_executor import OpenCodeV2Executor


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe the read-only OpenCode V2 L2 reviewer")
    parser.add_argument("request", help="Review question about the exported configuration")
    parser.add_argument("--bundle", default=".",
                        help="Project root containing opencode.jsonc and cybertron/ source")
    parser.add_argument("--model", help="Use another configured model for this probe")
    args = parser.parse_args()

    ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger(args.request)
    for step_id in (1, 2, 3, 4):
        ledger.start_step(step_id)
        ledger.complete_step(step_id, "Probe prerequisite only", ["probe://synthetic-prerequisite"])
    ledger.start_step(5)
    ledger.record_agent_completion(5, "micronus-prime", "Simulated L1 pass",
                                   ["probe://simulated-l1"], [],
                                   [QualityEvidence(QualityKind.REVIEW_L1, True,
                                                    "simulation-only")])
    dispatcher = PrimaDispatcher(OpenCodeV2Executor(
        Path(args.bundle).resolve(), model_override=args.model,
    ))
    result = dispatcher.run_next(ledger)
    assert result is not None
    print(f"liege-maximo: {result.status.value}: {result.summary}")
    print(f"Ledger step 5: {ledger.plan[4].status}")
    print("Earlier steps and L1 were simulated for this isolated L2 probe")


if __name__ == "__main__":
    main()
