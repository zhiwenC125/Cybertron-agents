"""Cybertron multi-agent configuration and orchestration primitives."""
from .schema import Message, ToolCallRequest, function_to_json_schema
from .compaction import AlphaTrionHeadTailCompaction, CompactionStrategy
from .policy import MegatronusCircuitBreaker, PermissionEffect, PermissionRule
from .feishu import FeishuWikiGovernanceConfig, FeishuWikiKnowledgeClient
from .registry import AgentMode, PrimeAgentSpec, THIRTEEN_PRIMES_REGISTRY
from .ledger import CybertronTaskLedger, LedgerStep, PrimaPlanOrchestrator
from .exporters import compile_deepseek_harness_assets, compile_opencode_v2_assets
from .selfcheck import run_self_verification
from .execution import AgentExecutor, AgentResult, AgentTask, QualityEvidence, QualityKind, ResultStatus
from .dispatch import PrimaDispatcher
