#!/usr/bin/env python3
"""Compatibility entry point for the Cybertron multi-agent engine."""
from pathlib import Path

from cybertron import (
    AgentMode, AlphaTrionHeadTailCompaction, CompactionStrategy,
    CybertronTaskLedger, FeishuWikiGovernanceConfig, FeishuWikiKnowledgeClient,
    LedgerStep, MegatronusCircuitBreaker, Message, PermissionEffect,
    PermissionRule, PrimaPlanOrchestrator, PrimeAgentSpec,
    THIRTEEN_PRIMES_REGISTRY, ToolCallRequest,
    compile_deepseek_harness_assets, compile_opencode_v2_assets,
    function_to_json_schema, run_self_verification,
)

if __name__ == "__main__":
    run_self_verification(Path("./cybertron_workspace_dist"))
