"""Run one read-only OpenCode V2 role and print its structured result."""

from __future__ import annotations

import argparse
from pathlib import Path

from .dispatch import PrimaDispatcher
from .ledger import PrimaPlanOrchestrator
from .opencode_executor import OpenCodeV2Executor


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the first OpenCode V2 agent task")
    parser.add_argument("request", help="Requirement for thirteenth to clarify")
    default_bundle = "." if Path("opencode.jsonc").is_file() else "opencode_v2_smoke"
    parser.add_argument("--bundle", default=default_bundle)
    args = parser.parse_args()
    ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger(args.request)
    result = PrimaDispatcher(OpenCodeV2Executor(Path(args.bundle).resolve())).run_next(ledger)
    assert result is not None
    print(f"{result.agent_id}: {result.status.value}: {result.summary}")
    print(f"Ledger step 1: {ledger.plan[0].status}")


if __name__ == "__main__":
    main()
