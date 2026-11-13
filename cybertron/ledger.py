"""记录九步 SDLC 的状态、角色接力、证据和审查返工次数。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List
from .execution import QualityEvidence
from .compaction import AlphaTrionHeadTailCompaction
from .feishu import FeishuWikiKnowledgeClient
from .registry import PrimeAgentSpec, THIRTEEN_PRIMES_REGISTRY

# ============================================================================

@dataclass
class LedgerStep:
    step_id: int
    sdlc_stage: str
    assigned_prime: str
    objective: str
    input_artifact: str
    expected_output: str
    status: str = "pending"  # "pending", "in_progress", "completed", "blocked"
    evidence_summary: str = ""
    evidence: List[str] = field(default_factory=list)
    quality_evidence: List[QualityEvidence] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    participants: List[str] = field(default_factory=list)
    participant_objectives: Dict[str, str] = field(default_factory=dict)
    completed_agents: List[str] = field(default_factory=list)
    feedback: str = ""

    def next_agent(self) -> str | None:
        agents = self.participants or [self.assigned_prime]
        return agents[len(self.completed_agents)] if len(self.completed_agents) < len(agents) else None


@dataclass
class CybertronTaskLedger:
    """
    Full-Lifecycle Software + Hardware Task Ledger with Explicit Quality & Flash Gates.
    """
    user_request: str
    feishu_wiki_refs: List[str] = field(default_factory=list)
    known_facts: List[str] = field(default_factory=list)
    open_risks: List[str] = field(default_factory=list)
    plan: List[LedgerStep] = field(default_factory=list)
    turn_count: int = 0
    max_turns: int = 20
    review_retry_count: int = 0
    max_review_retries: int = 2
    review_rejections: List[str] = field(default_factory=list)

    def next_step(self) -> LedgerStep | None:
        """Return the current unfinished step in the documented SDLC order."""
        return next((step for step in self.plan if step.status != "completed"), None)

    def start_step(self, step_id: int) -> LedgerStep:
        step = self.next_step()
        if step is None or step.step_id != step_id or step.status != "pending":
            raise ValueError(f"Step {step_id} cannot start in the current ledger state")
        step.status = "in_progress"
        return step

    def complete_step(self, step_id: int, evidence_summary: str,
                      evidence: List[str] | None = None,
                      artifacts: List[str] | None = None) -> LedgerStep:
        step = self.next_step()
        if step is None or step.step_id != step_id or step.status != "in_progress":
            raise ValueError(f"Step {step_id} is not in progress")
        if not evidence_summary.strip():
            raise ValueError("Completion requires evidence")
        step.evidence_summary = evidence_summary.strip()
        step.evidence = list(evidence or [])
        step.artifacts = list(artifacts or [])
        step.status = "completed"
        return step

    def record_agent_completion(self, step_id: int, agent_id: str,
                                summary: str, evidence: List[str],
                                artifacts: List[str],
                                quality_evidence: List[QualityEvidence] | None = None) -> LedgerStep:
        step = self.next_step()
        if step is None or step.step_id != step_id or step.status != "in_progress":
            raise ValueError(f"Step {step_id} is not in progress")
        if step.next_agent() != agent_id:
            raise ValueError(f"Agent {agent_id} is not next for step {step_id}")
        if not summary.strip() or not evidence or not all(item.strip() for item in evidence):
            raise ValueError("Agent completion requires a summary and evidence")
        step.completed_agents.append(agent_id)
        step.evidence.extend(evidence)
        step.quality_evidence.extend(quality_evidence or [])
        step.artifacts.extend(artifacts)
        if step.next_agent() is None:
            step.evidence_summary = summary.strip()
            step.status = "completed"
        return step

    def block_step(self, step_id: int, reason: str) -> LedgerStep:
        step = self.next_step()
        if step is None or step.step_id != step_id or step.status != "in_progress":
            raise ValueError(f"Step {step_id} is not in progress")
        if not reason.strip():
            raise ValueError("A blocked step requires a reason")
        step.evidence_summary = reason.strip()
        step.status = "blocked"
        return step

    def resume_step(self, step_id: int) -> LedgerStep:
        step = self.next_step()
        if step is None or step.step_id != step_id or step.status != "blocked":
            raise ValueError(f"Step {step_id} is not blocked")
        step.status = "in_progress"
        return step

    def reject_review(self, reviewer_id: str, reason: str) -> bool:
        """Return coding and review to pending; false means retry limit reached."""
        review = self.next_step()
        if review is None or review.step_id != 5 or review.status != "in_progress":
            raise ValueError("Only an active review step can be rejected")
        if reviewer_id not in ("micronus-prime", "liege-maximo") or review.next_agent() != reviewer_id:
            raise ValueError("Rejection must come from the active reviewer")
        if not reason.strip():
            raise ValueError("Review rejection requires a reason")
        self.review_rejections.append(f"{reviewer_id}: {reason.strip()}")
        if self.review_retry_count >= self.max_review_retries:
            self.block_step(5, f"Review retry limit reached: {reason.strip()}")
            return False
        self.review_retry_count += 1
        coding = self.plan[3]
        if coding.step_id != 4 or coding.status != "completed":
            raise ValueError("Completed coding step is required before review rework")
        for step in (coding, review):
            step.status = "pending"
            step.evidence_summary = ""
            step.evidence.clear()
            step.quality_evidence.clear()
            step.artifacts.clear()
            step.completed_agents.clear()
        coding.feedback = f"{reviewer_id}: {reason.strip()}"
        return True


class PrimaPlanOrchestrator:
    """
    Prima Prime Orchestrator driving the 9-Step Software + Hardware Full Lifecycle.
    """

    def __init__(self) -> None:
        self.primes: Dict[str, PrimeAgentSpec] = {p.agent_id: p for p in THIRTEEN_PRIMES_REGISTRY}
        self.compactor = AlphaTrionHeadTailCompaction(token_budget=64_000, head_ratio=0.25)
        self.feishu_client = FeishuWikiKnowledgeClient()

    def create_full_sdlc_hardware_ledger(self, user_request: str) -> CybertronTaskLedger:
        """Initializes the 9-step end-to-end Software + Hardware SDLC workflow ledger."""
        return CybertronTaskLedger(
            user_request=user_request,
            plan=[
                LedgerStep(
                    1, "Stage-I-Clarification", "thirteenth",
                    "核查软硬件需求规格（目标芯片型号、外设引脚、通信协议与性能指标）是否完备",
                    "Raw User Request", "Clarified Hardware/Software Spec"
                ),
                LedgerStep(
                    2, "Stage-II-Feishu-Doc-Sync", "alpha-trion",
                    "从飞书知识库拉取 PRD、硬件引脚定义表与历史 ADR，提炼写入本地 AGENTS.md",
                    "Clarified Spec + Feishu Space ID", "Updated Local AGENTS.md & docs/spec/"
                ),
                LedgerStep(
                    3, "Stage-III-Discovery-Arch", "onyx-prime",
                    "扫描本地工作树 AST、设备树与驱动拓扑（配合 vector-prime 基线排查与 quintus-prime HAL 骨架孵化）",
                    "AGENTS.md", "File:Line Coordinates & HAL Interface Skeletons",
                    participants=["onyx-prime", "vector-prime", "quintus-prime"],
                    participant_objectives={
                        "onyx-prime": "只读扫描当前代码树、设备树和驱动拓扑，输出文件与行号",
                        "vector-prime": "只读追溯 Git 历史和固件基线，输出相关提交与差异",
                        "quintus-prime": "根据侦察结果创建工程骨架与 HAL 接口契约",
                    }
                ),
                LedgerStep(
                    4, "Stage-IV-Coding-Firmware", "solus-prime",
                    "编写核心业务源码 (src/**) 与嵌入式外设驱动/固件逻辑 (firmware/**, drivers/**)",
                    "HAL Skeletons + AGENTS.md", "Implemented Software & Firmware Source Files"
                ),
                LedgerStep(
                    5, "Stage-V-Dual-Code-Review", "micronus-prime",
                    "执行 L1 静态分析审查 (ruff/clang-tidy/cppcheck)，随后交由 liege-maximo 执行 L2 深度逻辑、死锁与硬件引脚安全审计",
                    "Modified src/** & firmware/**", "L1 Static Report + L2 Liege Maximo PASS Verdict",
                    participants=["micronus-prime", "liege-maximo"],
                    participant_objectives={
                        "micronus-prime": "执行 L1 静态规范检查并给出通过或拒绝结论",
                        "liege-maximo": "在 L1 通过后执行 L2 逻辑与安全审查并给出通过或拒绝结论",
                    }
                ),
                LedgerStep(
                    6, "Stage-VI-Test-Simulation", "alchemist",
                    "在 tests/** 编写独立单元测试与 QEMU/Renode 硬件仿真检验脚本并运行验证",
                    "Reviewed Code + AGENTS.md", "tests/** + Pytest/Emulator Pass Report"
                ),
                LedgerStep(
                    7, "Stage-VII-Cross-Compile", "nexus-prime",
                    "更新 CMake/Dockerfile，执行交叉编译生成固件镜像 (.bin/.elf)，核算 Flash/RAM 占用并探测目标开发板端口",
                    "Verified Source Tree", "Compiled Firmware Binary + Target Port Manifest"
                ),
                LedgerStep(
                    8, "Stage-VII-Hardware-Flash", "megatronus",
                    "生成《硬件烧录爆炸半径评估单》，触发 ask 人工审批后执行 openocd/esptool 物理烧录并核验串口启动心跳",
                    "Firmware Binary + Port Manifest", "Hardware Flash Receipt & Serial Heartbeat Log"
                ),
                LedgerStep(
                    9, "Stage-II-and-VII-Doc-Delivery", "alpha-trion",
                    "撰写更新 README.md 与硬件部署指南，将 ADR 与烧录台账回写至飞书知识库，再由 thirteenth 向用户交付",
                    "Flash Receipt + Completed Ledger", "Updated Docs + Feishu Wiki URL + Final User Report",
                    participants=["alpha-trion", "thirteenth"],
                    participant_objectives={
                        "alpha-trion": "整理本次研发文档与知识库归档结果",
                        "thirteenth": "根据账本和文档结果进行最终验收与交付汇报",
                    }
                ),
            ],
        )
