"""Optional v6 plan seeds; prima may change them through validated graph ops."""

from __future__ import annotations

from .graph import PlanGraph, PlanNode


def read_only_scan_template(objective: str) -> PlanGraph:
    """Seed one onyx-prime inspection node without a project write scope."""
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError("read-only objective is required")
    return PlanGraph([PlanNode(
        "scan", "task", "scan.static", "onyx-prime", objective.strip(),
        write_scope=(),
        acceptance=("Report the requested inspection findings without changing project files",),
        verifiers=("scope_guard",),
    )], access_mode="read-only")


def bug_fix_template(objective: str, write_scope: tuple[str, ...], *, lightweight: bool = False) -> PlanGraph:
    """Seed a scoped bug fix for the selected verification mode.

    This is a planning hint, not a gate decision or an execution receipt.
    The caller still submits every change through the graph validator.
    """
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError("bug objective is required")
    if lightweight and len(write_scope) == 1 and not any(char in write_scope[0] for char in "*?["):
        return PlanGraph([PlanNode(
            "fix", "task", "code.write", "solus-prime", objective.strip(),
            write_scope=write_scope, acceptance=("Correct the regression and pass the existing test",),
            verifiers=("scope_guard", "test"),
        )])
    nodes = [
        PlanNode("scan-static", "task", "scan.static", "onyx-prime",
                 f"Locate the cause of: {objective}",
                 acceptance=("Source coordinates and call path [review]",),
                 verifiers=("scope_guard",)),
        PlanNode("scan-history", "task", "scan.history", "vector-prime",
                 f"Identify the introducing change for: {objective}",
                 acceptance=("Relevant commit and diff coordinates [review]",),
                 verifiers=("scope_guard",)),
        PlanNode("fix", "task", "code.write", "solus-prime",
                 f"Fix the root cause of: {objective}",
                 depends_on=("scan-static", "scan-history"),
                 write_scope=write_scope,
                 acceptance=("Regression corrected [auto]",),
                 verifiers=("scope_guard",)),
        PlanNode("review", "review", "review.l2", "liege-maximo",
                 f"Review the fix for: {objective}",
                 depends_on=("fix",),
                 acceptance=("Independent review verdict [review]",),
                 verifiers=("scope_guard",)),
    ]
    return PlanGraph(nodes)
