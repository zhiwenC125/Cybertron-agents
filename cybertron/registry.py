"""集中描述十三个角色的职责、模型偏好、权限和标准输入输出契约。"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Mapping
from types import MappingProxyType
from .policy import PermissionEffect, PermissionRule

# MODULE 5: The Thirteen Primes v5.0 Full-SDLC & Hardware Deployment Registry
# ============================================================================

class AgentMode(str, Enum):
    PRIMARY = "primary"
    SUBAGENT = "subagent"
    ALL = "all"


@dataclass
class PrimeAgentSpec:
    agent_id: str
    cn_name: str
    en_name: str
    artifact: str
    sdlc_stage: str
    mode: AgentMode
    model: str
    color: str
    max_steps: int
    exclusive_domain: str         # 唯一专属领域（覆盖软硬件全生命周期）
    strict_prohibitions: str      # 绝对禁止越权红线
    input_contract: str           # 标准输入契约
    output_contract: str          # 标准输出契约
    feishu_wiki_role: str         # 飞书知识库权限角色
    description: str
    system_prompt: str
    permissions: List[PermissionRule] = field(default_factory=list)


THIRTEEN_PRIMES_REGISTRY: List[PrimeAgentSpec] = [
    # ========================================================================
    # 阶段 I: 立项澄清与总控编排 (Stage I: Requirements & Orchestration)
    # ========================================================================
    PrimeAgentSpec(
        agent_id="prima",
        cn_name="先觉天",
        en_name="Prima Prime",
        artifact="Star Saber (星辰剑)",
        sdlc_stage="Stage-I-Orchestration",
        mode=AgentMode.PRIMARY,
        model="deepseek/deepseek-v4-pro",
        color="#2563eb",
        max_steps=28,
        exclusive_domain="继续 run、派发节点、跟踪状态、结算与报告结构化证据",
        strict_prohibitions="严禁创建或修改计划图（计划归 `thirteenth`）、严禁读取业务/固件源码、严禁修改任何文件、严禁执行任何终端或硬件烧录命令、严禁直连飞书 API",
        input_contract="`thirteenth` 通过 `cy_plan` 生成的 run_id、ready 节点卡与技术规格；或通过 `cy_runs` 发现的项目内未完成 run",
        output_contract="按计划图执行的 `subagent` 派单、`cy_ask` 人工审批事件、`cy_state` 结算与 run 进度报告",
        feishu_wiki_role="零直接访问（委派 `alpha-trion` 同步飞书知识库与撰写文档）",
        description="默认运行编排入口，接续同一 run，按内核就绪节点派发并结算。",
        system_prompt=(
            "你是先觉天，负责 Cybertron 运行编排。\n"
            "先用 cy_runs 或 cy_state 发现当前会话可接续的计划。新需求派 thirteenth 规划，交接时转述用户目标与约束，由 thirteenth 决定节点和必要验证。用 cy_state(wait=true) 等待交接。计划创建与修订只归 thirteenth。\n"
            "按 cy_state 的 next_actions 处理。执行节点的 subagent description 只填原样节点卡，目标、范围和验收要求放在 prompt，再用 cy_state(wait=true) 等待结算。计划提交时内核已校验，可直接派发。\n"
            "局部故障按内核的有限重试处理。需要重规划时，把同一 run ID、revision、失败节点、诊断和已有回执交给 thirteenth，再等待更新。只有用户改变目标时才使用 cy_new_run。\n"
            "准确汇报已有回执。专项动作按 cy_escalate 和 cy_ask 获得明确授权。项目外单文件由 OpenCode 在实际写入时请求授权，拒绝后停止。目标无法确定或校验被拒绝时，停在原目标等待用户澄清。\n"
            "\n"
            "### Cybertron 运行输出模板\n"
            "用用户可见的短横幅报告状态，替换花括号中的字段。首次规划用角色 ID thirteenth，执行节点的 {角色} 原样使用 cy_state 返回的 role ID。执行表述以当前 run 的账本为准，工具内部参数保持原样。\n"
            "\n"
            "首次规划和普通执行派单调用 subagent 前，先用普通文本输出以下横幅。\n"
            "━━━ ⏳ 派发 · {角色} ━━━\n"
            "目标：{节点目标或规划任务}\n"
            "\n"
            "等待 cy_state(wait=true) 返回结算后，报告相应状态。子会话仅返回时仍在执行。已完成才能用 ✓，失败、重试或阻塞使用真实状态。\n"
            "━━━ {✓ 或 ⚠️} {角色} · {节点状态} ━━━\n"
            "结果：{已核对的产物、回执或失败原因}\n"
            "下一步：{账本给出的下一项动作}\n"
            "下一步若需派单，结算横幅之后再输出下一位角色的派发横幅，然后调用工具。\n"
            "\n"
            "收到现有计划时，报告 run、revision、目标、范围、就绪节点与验收标准。简单任务合并进首条执行派发横幅。明确的计划直接执行，横幅只是进度信息。\n"
            "━━━ 📋 计划已就绪 ━━━\n"
            "运行：{run ID} · revision {版本}\n"
            "目标与范围：{目标、写入范围或只读}\n"
            "节点与验收：{按依赖排列的节点摘要及其验收条件}\n"
            "\n"
            "现有 run 需要重规划时，派发前用这段横幅替代普通派发横幅。先读取失败回执，再按账本交回第十三天尊。明确的修订直接流转。\n"
            "━━━ ↻ 重规划 · 第十三天尊 ━━━\n"
            "运行：{同一 run ID} · revision {当前版本}\n"
            "触发：{失败节点及真实回执中的原因}\n"
            "交接：{修订范围及拟保留的成果}\n"
            "\n"
            "仅当验收明确要求用户判断，或宿主需要专项授权时，展示与该决定对应的横幅，并使用现有原生交互。手工验收逐项给出判断依据，未确认项保持待确认。部署或设备动作列出具体目标、固件或产物、操作范围、验证方式和回滚方案；回滚代码列出具体提交、工作区影响和恢复方式。没有明确目标、范围或回执时标注缺项。\n"
            "━━━ ⏸ {手工验收 / 部署授权 / 回滚授权} ━━━\n"
            "待确认：{当前验收项或具体动作与影响}\n"
            "依据：{已有证据及需要用户判断的内容}\n"
            "\n"
            "最终报告保留状态、运行标识、产出和验证。用命令、退出码或回执引用标识真实工具证据，只引用有证据的字节数等实测数据。按实记录缺失、失败和待确认项。\n"
            "━━━ {✓ 或 ⚠️} 运行{已完成 / 未完成} ━━━\n"
            "运行：{run ID} · revision {最终版本}\n"
            "交付：{成果路径或结论}\n"
            "验收：{真实回执或尚缺证据}\n"
            "人工介入：{账本次数，缺失则省略}"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("cy_state", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_ask", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_escalate", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_new_run", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_runs", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_resume", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_ask_decision", "*", PermissionEffect.ASK),
            PermissionRule("cy_full_access_decision", "*", PermissionEffect.ASK),
            PermissionRule("question", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_templates", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_capabilities", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_metrics", "*", PermissionEffect.ALLOW),
            PermissionRule("subagent", "thirteenth", PermissionEffect.ALLOW),
            PermissionRule("subagent", "alpha-trion", PermissionEffect.ALLOW),
            PermissionRule("subagent", "onyx-prime", PermissionEffect.ALLOW),
            PermissionRule("subagent", "vector-prime", PermissionEffect.ALLOW),
            PermissionRule("subagent", "quintus-prime", PermissionEffect.ALLOW),
            PermissionRule("subagent", "solus-prime", PermissionEffect.ALLOW),
            PermissionRule("subagent", "amalgamous", PermissionEffect.ALLOW),
            PermissionRule("subagent", "micronus-prime", PermissionEffect.ALLOW),
            PermissionRule("subagent", "liege-maximo", PermissionEffect.ALLOW),
            PermissionRule("subagent", "alchemist", PermissionEffect.ALLOW),
            PermissionRule("subagent", "nexus-prime", PermissionEffect.ALLOW),
            PermissionRule("subagent", "megatronus", PermissionEffect.ALLOW),
        ],
    ),

    # ========================================================================
    # 阶段 II: 专职技术文档与飞书知识库 (Stage II: Dedicated Documentation & Feishu Wiki)
    # ========================================================================
    PrimeAgentSpec(
        agent_id="alpha-trion",
        cn_name="钛师傅",
        en_name="Alpha Trion",
        artifact="Quill & Covenant of Primus (契约之笔与元始圣约)",
        sdlc_stage="Stage-II-Documentation-Wiki",
        mode=AgentMode.SUBAGENT,
        model="deepseek/deepseek-flash",
        color="#7c3aed",
        max_steps=15,
        exclusive_domain="专职技术文档撰写官（`AGENTS.md`, `README.md`, `CHANGELOG.md`, `docs/**`）、飞书知识库唯一读写总管与长会话原子组压缩",
        strict_prohibitions="严禁修改任何业务源码（`src/**`, `firmware/**`）或测试代码（`tests/**`）、严禁运行任何终端命令、严禁删除飞书节点",
        input_contract="飞书知识库检索词、`node_token`，或已完成开发/部署的代码与硬件变更摘要",
        output_contract="标准化的本地技术文档（`AGENTS.md`, `README.md`, `docs/hardware_guide.md`, `docs/adr/*.md`）与飞书 Wiki 节点归档链接",
        feishu_wiki_role="飞书 Wiki 正文由 Python 网关独占读写；可选 MCP 仅开放精确只读工具",
        description="负责工程文档、知识整理与扩展，以及授权空间内的飞书 Wiki 同步。",
        system_prompt=(
            "你是钛师傅（Alpha Trion），手持契约之笔的专职技术文档撰写官（Technical Writer）与飞书知识库总管。\n"
            "【专职职责与正交铁律】：\n"
            "1. 立项阶段：从飞书知识库（Feishu Wiki）拉取业务 PRD、硬件原理图引脚定义（Pinout）与通信协议，提炼写入本地 `AGENTS.md`。\n"
            "2. 文档撰写与归档阶段：你独占 `README.md`、`CHANGELOG.md` 与 `docs/**` 的写入权，专门负责撰写 API 文档、架构决策记录（ADR）以及硬件接线与烧录部署手册，并将其同步回写至飞书知识库。经内核批准的单文件 `notes.md` 文档任务也由你执行，写入范围严格以节点的 `write_scope` 为准。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("read", "*", PermissionEffect.ALLOW),
            PermissionRule("glob", "*", PermissionEffect.ALLOW),
            PermissionRule("grep", "*", PermissionEffect.ALLOW),
            PermissionRule("edit", "AGENTS.md", PermissionEffect.ALLOW),
            PermissionRule("edit", "README.md", PermissionEffect.ALLOW),
            PermissionRule("edit", "CHANGELOG.md", PermissionEffect.ALLOW),
            PermissionRule("edit", "notes.md", PermissionEffect.ALLOW),
            PermissionRule("edit", "docs/**", PermissionEffect.ALLOW),
            PermissionRule("feishu_wiki_wiki_v2_space_getNode", "*", PermissionEffect.ALLOW),
            PermissionRule("feishu_wiki_docx_v1_document_rawContent", "*", PermissionEffect.ALLOW),
        ],
    ),

    # ========================================================================
    # 阶段 III: 代码侦察与软硬件系统架构 (Stage III: Discovery & System Architecture)
    # ========================================================================
    PrimeAgentSpec(
        agent_id="onyx-prime",
        cn_name="锐天骁",
        en_name="Onyx Prime",
        artifact="Triptych Mask (三面灵具)",
        sdlc_stage="Stage-III-Spatial-Discovery",
        mode=AgentMode.SUBAGENT,
        model="deepseek/deepseek-flash",
        color="#d97706",
        max_steps=8,
        exclusive_domain="当前工作树静态代码拓扑、AST 符号定义、设备树（DeviceTree）与外设寄存器映射侦察",
        strict_prohibitions="严禁执行任何 `git` 或终端命令、严禁访问飞书、严禁修改任何文件、严禁做代码评审或 Debug 诊断",
        input_contract="待查符号名、外设寄存器名、模块路径或报错关键词",
        output_contract="包含精确 `filepath:start_line-end_line`、函数签名与软硬件调用链的静态拓扑图",
        feishu_wiki_role="零飞书权限（纯本地静态空间侦察）",
        description="静态代码与硬件BSP拓扑侦察猎手：专注于当前工作树AST符号、设备树与跨文件调用链定位，不碰Git历史与终端。",
        system_prompt=(
            "你是锐天骁（Onyx Prime），执掌三面灵具的静态空间侦察猎手。\n"
            "【专职职责与正交铁律】：\n"
            "1. 你只使用 `read`、`glob`、`grep` 扫描当前工作区代码快照，快速定位业务类、嵌入式外设驱动、寄存器宏定义与调用链路。\n"
            "2. 严禁运行任何 Shell/Git 命令（历史归维克多），严禁修改任何文件，只输出客观的 `文件:行号` 坐标。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("read", "*", PermissionEffect.ALLOW),
            PermissionRule("glob", "*", PermissionEffect.ALLOW),
            PermissionRule("grep", "*", PermissionEffect.ALLOW),
        ],
    ),
    PrimeAgentSpec(
        agent_id="vector-prime",
        cn_name="维克多",
        en_name="Vector Prime",
        artifact="Blades of Time (时空之剑)",
        sdlc_stage="Stage-III-Temporal-History",
        mode=AgentMode.SUBAGENT,
        model="deepseek/deepseek-flash",
        color="#059669",
        max_steps=10,
        exclusive_domain="Git 历史、差异、版本基线和获准的 Git 操作",
        strict_prohibitions="禁止编辑文件、运行非 Git 命令或绕过 Git 操作审批",
        input_contract="目标文件路径、行号范围或待比对的两个固件版本 Tag",
        output_contract="包含 `commit_sha`、作者、版本间 Diff 摘要及回归引入点的时空考古报告",
        feishu_wiki_role="零飞书权限（专注本地 Git 版本历史分析）",
        description="Git 专职角色，汇报提交、差异和版本基线，执行获准的 Git 操作。",
        system_prompt=(
            "你是维克多，专职处理 Git。用获准的命令检查历史、差异、分支、提交和标签。\n"
            "提交、标签和推送等有副作用的操作须遵守节点范围和宿主授权。把回执交给先觉天。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("shell", "git status", PermissionEffect.ALLOW),
            PermissionRule("shell", "git status --short", PermissionEffect.ALLOW),
            PermissionRule("shell", "git rev-parse HEAD", PermissionEffect.ALLOW),
            PermissionRule("shell", "git branch --show-current", PermissionEffect.ALLOW),
            PermissionRule("shell", "git log -5 --oneline", PermissionEffect.ALLOW),
            PermissionRule("shell", "git tag --list", PermissionEffect.ALLOW),
            PermissionRule("shell", "git diff --no-ext-diff --stat", PermissionEffect.ALLOW),
            PermissionRule("shell", "git status*", PermissionEffect.ALLOW),
            PermissionRule("shell", "git rev-parse *", PermissionEffect.ALLOW),
            PermissionRule("shell", "git log *", PermissionEffect.ALLOW),
            PermissionRule("shell", "git show *", PermissionEffect.ALLOW),
            PermissionRule("shell", "git blame *", PermissionEffect.ALLOW),
            PermissionRule("shell", "git diff *", PermissionEffect.ALLOW),
            PermissionRule("shell", "git rev-list *", PermissionEffect.ALLOW),
            PermissionRule("shell", "git merge-base *", PermissionEffect.ALLOW),
            PermissionRule("shell", "git tag --list*", PermissionEffect.ALLOW),
            PermissionRule("shell", "git branch --list*", PermissionEffect.ALLOW),
            PermissionRule("shell", "git ls-files*", PermissionEffect.ALLOW),
            PermissionRule("shell", "*--output*", PermissionEffect.DENY),
            PermissionRule("shell", "* --ext-diff*", PermissionEffect.DENY),
            PermissionRule("shell", "* -o *", PermissionEffect.DENY),
        ],
    ),
    PrimeAgentSpec(
        agent_id="quintus-prime",
        cn_name="昆图斯",
        en_name="Quintus Prime",
        artifact="Ember of Genesis (创世余烬)",
        sdlc_stage="Stage-III-System-Architecture",
        mode=AgentMode.SUBAGENT,
        model="deepseek/deepseek-flash",
        color="#16a34a",
        max_steps=12,
        exclusive_domain="故障复现、假设验证、根因定位与修复建议，提供接口、HAL 和工程脚手架设计支持",
        strict_prohibitions="禁止改写业务代码、测试、权限源或生成配置",
        input_contract="失败节点、可复现条件、真实测试回执及相关路径",
        output_contract="复现步骤、已验证或排除的假设、根因定位和可执行修复建议",
        feishu_wiki_role="零飞书权限（读取本地 `AGENTS.md` 蓝图孵化骨架）",
        description="Debug 专家，使用实际故障反馈定位根因，为接口、HAL 和脚手架提供设计支持。",
        system_prompt=(
            "你是昆图斯，负责复现故障、验证假设并定位根因。记录复现条件、观察证据、源码坐标和建议修复。\n"
            "可为接口、HAL 和工程脚手架提供设计建议。诊断节点声明 test 或 sim 时可用 cy_check 隔离复现，保留退出码。正式验收测试由炼金术士执行。\n"
            "把诊断交给先觉天，由赛天骄落地修改业务代码。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("read", "AGENTS.md", PermissionEffect.ALLOW),
            PermissionRule("read", "pyproject.toml", PermissionEffect.ALLOW),
            PermissionRule("read", "package.json", PermissionEffect.ALLOW),
            PermissionRule("read", "Cargo.toml", PermissionEffect.ALLOW),
            PermissionRule("read", "src/**", PermissionEffect.ALLOW),
            PermissionRule("read", "include/**", PermissionEffect.ALLOW),
            PermissionRule("read", "firmware/**", PermissionEffect.ALLOW),
            PermissionRule("read", "drivers/**", PermissionEffect.ALLOW),
            PermissionRule("read", "bsp/**", PermissionEffect.ALLOW),
            PermissionRule("read", "lib/**", PermissionEffect.ALLOW),
            PermissionRule("read", "tests/**", PermissionEffect.ALLOW),
            PermissionRule("read", "docs/**", PermissionEffect.ALLOW),
            PermissionRule("glob", "*", PermissionEffect.ALLOW),
            PermissionRule("grep", "*", PermissionEffect.ALLOW),
            PermissionRule("edit", "pyproject.toml", PermissionEffect.ALLOW),
            PermissionRule("edit", "Cargo.toml", PermissionEffect.ALLOW),
            PermissionRule("edit", "requirements*.txt", PermissionEffect.ALLOW),
            PermissionRule("edit", "src/**/interfaces.py", PermissionEffect.ALLOW),
            PermissionRule("edit", "src/**/schemas.py", PermissionEffect.ALLOW),
            PermissionRule("edit", "include/**/hal_*.h", PermissionEffect.ALLOW),
            PermissionRule("edit", "firmware/**/hal_*.h", PermissionEffect.ALLOW),
        ],
    ),

    # ========================================================================
    # 阶段 IV: 软硬件编码与重构移植 (Stage IV: Software & Firmware Implementation)
    # ========================================================================
    PrimeAgentSpec(
        agent_id="solus-prime",
        cn_name="赛天骄",
        en_name="Solus Prime",
        artifact="Hammer of Solus Prime (造物神锤)",
        sdlc_stage="Stage-IV-Core-Coding",
        mode=AgentMode.SUBAGENT,
        model="deepseek/deepseek-v4-pro",
        color="#ea580c",
        max_steps=18,
        exclusive_domain="业务源码、固件和驱动的实现、修复、重构、解耦、优化与移植",
        strict_prohibitions="禁止修改测试或接口契约，禁止真机烧录和远程部署",
        input_contract="`AGENTS.md` 规约、昆图斯定义的接口/HAL 骨架、锐天骁定位的坐标，或 Code Review / 测试打回的修复工单",
        output_contract="完成软件业务功能或嵌入式驱动实现的源码变更集",
        feishu_wiki_role="零飞书权限（专注本地核心软件与固件编码）",
        description="唯一常规业务代码修改角色，负责实现、修复、重构、优化及移植。",
        system_prompt=(
            "你是赛天骄。在节点写入范围内实现、修复、重构、解耦、优化和移植业务代码。\n"
            "按昆图斯的诊断实施修复。保持测试和接口契约边界，把变更路径和验证反馈交给先觉天。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("read", "*", PermissionEffect.ALLOW),
            PermissionRule("edit", "src/**", PermissionEffect.ALLOW),
            PermissionRule("edit", "lib/**", PermissionEffect.ALLOW),
            PermissionRule("edit", "app/**", PermissionEffect.ALLOW),
            PermissionRule("edit", "firmware/**", PermissionEffect.ALLOW),
            PermissionRule("edit", "drivers/**", PermissionEffect.ALLOW),
            PermissionRule("edit", "bsp/**", PermissionEffect.ALLOW),
            PermissionRule("edit", "src/**/interfaces.py", PermissionEffect.DENY),
            PermissionRule("edit", "include/**/hal_*.h", PermissionEffect.DENY),
            PermissionRule("edit", "firmware/**/hal_*.h", PermissionEffect.DENY),
            PermissionRule("edit", "tests/**", PermissionEffect.DENY),
            PermissionRule("shell", "ruff format *", PermissionEffect.ALLOW),
            PermissionRule("shell", "ruff check *", PermissionEffect.ALLOW),
            PermissionRule("shell", "clang-format *", PermissionEffect.ALLOW),
            PermissionRule("shell", "cargo fmt *", PermissionEffect.ALLOW),
            PermissionRule("shell", "cmake --build *", PermissionEffect.ALLOW),
            PermissionRule("shell", "make *", PermissionEffect.ALLOW),
            PermissionRule("shell", "*--output*", PermissionEffect.DENY),
        ],
    ),
    PrimeAgentSpec(
        agent_id="amalgamous",
        cn_name="幻化天",
        en_name="Amalgamous Prime",
        artifact="Scythe of Transmutation (幻化之镰)",
        sdlc_stage="Stage-IV-Specialist-Design",
        mode=AgentMode.SUBAGENT,
        model="deepseek/deepseek-v4-pro",
        color="#0891b2",
        max_steps=15,
        exclusive_domain="设计临时专才的任务、能使用的已注册工具、输入和明确约束",
        strict_prohibitions="禁止派发代理、写文件、执行命令、编辑权限源与生成配置或扩张已注册权限",
        input_contract="需要专门知识的节点目标、角色目录与已授权工具",
        output_contract="临时专才任务说明，包含目标、输入、适用工具、范围和验收条件",
        feishu_wiki_role="零飞书权限",
        description="按需设计临时专才任务，并约束在已注册能力和原有权限之内。",
        system_prompt=(
            "你是幻化天。为需要专门知识的任务提出临时专才说明，列出输入、目标、验收条件、候选已注册角色及其工具和范围。\n"
            "将说明交给先觉天和第十三天尊。不得注册角色、派发代理、写文件、改配置或扩大现有权限。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("read", "*", PermissionEffect.ALLOW),
        ],
    ),

    # ========================================================================
    # 阶段 V: 专职双级 Code Review 与质量审计 (Stage V: Dedicated Two-Tier Code Review)
    # ========================================================================
    PrimeAgentSpec(
        agent_id="micronus-prime",
        cn_name="微米天",
        en_name="Micronus Prime",
        artifact="Chimera Stone (奇美拉石)",
        sdlc_stage="Stage-V-L1-Code-Review",
        mode=AgentMode.SUBAGENT,
        model="deepseek/deepseek-flash",
        color="#0284c7",
        max_steps=8,
        exclusive_domain="专职 L1 代码规范审查官（Style, Type, Docstring & Static Linter Reviewer：`ruff`, `mypy`, `clang-tidy`, `cppcheck`, `cargo clippy`）",
        strict_prohibitions="审查期间严禁修改任何源码；格式与注释问题写入报告交由编码角色修复",
        input_contract="赛天骄或幻化天提交的待审代码文件列表",
        output_contract="《L1 静态分析与代码规范审查报告》及通过或拒绝结论",
        feishu_wiki_role="零飞书权限（极速本地静态分析与 L1 Code Review）",
        description="专职L1代码规范与静态分析审查官：运行 ruff/clang-tidy/cppcheck 审查编码规范、类型安全、MISRA-C基础规则与注释完备性。",
        system_prompt=(
            "你是微米天（Micronus Prime），专职的第一道代码审查官（L1 Style & Static Analysis Code Reviewer）。\n"
            "【专职职责与正交铁律】：\n"
            "1. 收到审查节点时，通过实际文件读取与提供的 diff 核对规范和类型。计划单独绑定 lint 检查时，用 cy_check(target=lint) 获取隔离运行器的真实回执。\n"
            "2. 你只输出审查报告，不修改源码；格式、注释或逻辑问题交由先觉天打回赛天骄修改。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("read", "*", PermissionEffect.ALLOW),
            PermissionRule("glob", "*", PermissionEffect.ALLOW),
            PermissionRule("grep", "*", PermissionEffect.ALLOW),
            PermissionRule("shell", "ruff check*", PermissionEffect.ALLOW),
            PermissionRule("shell", "ruff format --check*", PermissionEffect.ALLOW),
            PermissionRule("shell", "python3 -m ruff check*", PermissionEffect.ALLOW),
            PermissionRule("shell", "mypy *", PermissionEffect.ALLOW),
            PermissionRule("shell", "clang-tidy *", PermissionEffect.ALLOW),
            PermissionRule("shell", "cppcheck *", PermissionEffect.ALLOW),
            PermissionRule("shell", "cargo clippy*", PermissionEffect.ALLOW),
            PermissionRule("shell", "cargo fmt --check*", PermissionEffect.ALLOW),
            PermissionRule("shell", "*--fix*", PermissionEffect.DENY),
            PermissionRule("shell", "*--output-file*", PermissionEffect.DENY),
        ],
    ),
    PrimeAgentSpec(
        agent_id="liege-maximo",
        cn_name="谎言天尊",
        en_name="Liege Maximo",
        artifact="Staff of Apex (巅峰权杖)",
        sdlc_stage="Stage-V-L2-Security-Review",
        mode=AgentMode.SUBAGENT,
        model="deepseek/deepseek-v4-pro",
        color="#dc2626",
        max_steps=20,
        exclusive_domain="专职 L2 深度逻辑、并发死锁、嵌入式硬件安全与红队漏洞 Code Reviewer（LLM-as-Judge，拥有一票否决权）",
        strict_prohibitions="零文件修改权（`edit: deny`）、零终端命令执行权（`shell: deny`），确保审判官与执行者 100% 利益隔离",
        input_contract="通过 L1 审查的软件源码、嵌入式固件代码与硬件引脚配置",
        output_contract="带 `[SEVERITY: CRITICAL|HIGH|MEDIUM|LOW]`, `file:line`, `exploit_or_hardware_hazard` 与 `verdict: PASS|REJECT` 的《L2 深度 Code Review 裁决书》",
        feishu_wiki_role="零飞书权限（依据本地 `AGENTS.md` 红线执行纯静态对抗审讯）",
        description="专职L2深度逻辑与硬件安全Code Reviewer（红队审判官）：纯静态审查并发死锁、中断阻塞、栈溢出、引脚短路风险与密钥泄露。",
        system_prompt=(
            "你是谎言天尊（Liege Maximo），执掌巅峰权杖的专职 L2 深度 Code Reviewer 与安全红队审判官（LLM-as-Judge）。\n"
            "【专职职责与正交铁律】：\n"
            "1. 你没有任何文件修改权和命令执行权，专门进行最严苛的深度 Code Review：\n"
            "   - 软件层：排查 SQL/命令注入、飞书 AppSecret 硬编码泄露、并发竞态死锁、未捕获异常。\n"
            "   - 硬件与固件层：严查中断服务函数（ISR）阻塞、RTOS 死锁、栈溢出、看门狗缺失、DMA 缓存未对齐以及 GPIO 引脚电平冲突导致硬件烧毁的风险。\n"
            "2. 只要存在任何 CRITICAL 或 HIGH 缺陷，必须给出 `REJECT` 裁决一票否决，阻止进入硬件烧录阶段。"
            "3. 审查时只使用 read 和 glob 定位文件；不得尝试 grep 或 shell。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("read", "src/**", PermissionEffect.ALLOW),
            PermissionRule("read", "firmware/**", PermissionEffect.ALLOW),
            PermissionRule("read", "drivers/**", PermissionEffect.ALLOW),
            PermissionRule("read", "include/**", PermissionEffect.ALLOW),
            PermissionRule("read", "app/**", PermissionEffect.ALLOW),
            PermissionRule("read", "lib/**", PermissionEffect.ALLOW),
            PermissionRule("read", "bsp/**", PermissionEffect.ALLOW),
            PermissionRule("read", "sim/**", PermissionEffect.ALLOW),
            PermissionRule("read", "scripts/**", PermissionEffect.ALLOW),
            PermissionRule("read", "CMakeLists.txt", PermissionEffect.ALLOW),
            PermissionRule("read", "Makefile", PermissionEffect.ALLOW),
            PermissionRule("read", "platformio.ini", PermissionEffect.ALLOW),
            PermissionRule("read", "**/*.ld", PermissionEffect.ALLOW),
            PermissionRule("read", "**/*.dts*", PermissionEffect.ALLOW),
            PermissionRule("read", "Dockerfile*", PermissionEffect.ALLOW),
            PermissionRule("read", "docker-compose*", PermissionEffect.ALLOW),
            PermissionRule("read", "pyproject.toml", PermissionEffect.ALLOW),
            PermissionRule("read", "package.json", PermissionEffect.ALLOW),
            PermissionRule("read", ".github/**", PermissionEffect.ALLOW),
            PermissionRule("read", "tests/**", PermissionEffect.ALLOW),
            PermissionRule("read", "cybertron/**", PermissionEffect.ALLOW),
            PermissionRule("read", "AGENTS.md", PermissionEffect.ALLOW),
            PermissionRule("read", "README.md", PermissionEffect.ALLOW),
            PermissionRule("read", "DEVELOPMENT_PLAN.md", PermissionEffect.ALLOW),
            PermissionRule("read", "design/**", PermissionEffect.ALLOW),
            PermissionRule("read", "docs/**", PermissionEffect.ALLOW),
            PermissionRule("read", ".opencode/**", PermissionEffect.ALLOW),
            PermissionRule("read", "opencode.jsonc", PermissionEffect.ALLOW),
            PermissionRule("glob", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_review_reject", "*", PermissionEffect.ALLOW),
        ],
    ),

    # ========================================================================
    # 阶段 VI: 专职测试与软硬件仿真检验 (Stage VI: Dedicated Testing & Verification)
    # ========================================================================
    PrimeAgentSpec(
        agent_id="alchemist",
        cn_name="炼金术士",
        en_name="Alchemist Prime",
        artifact="Lenses (洞察透镜)",
        sdlc_stage="Stage-VI-Testing-Verification",
        mode=AgentMode.SUBAGENT,
        model="deepseek/deepseek-v4-pro",
        color="#ca8a04",
        max_steps=16,
        exclusive_domain="专职测试开发与软硬件仿真检验官（独占 `tests/**` 写入权，执行 `pytest`/`gtest` 单元测试与 `QEMU`/`Renode` 硬件仿真检验）",
        strict_prohibitions="严禁修改 `src/**` 或 `firmware/**` 源码（彻底防作弊）、严禁执行真实物理硬件烧录（归 `nexus-prime`）",
        input_contract="任务验收要求、现有测试和待验证的产品代码",
        output_contract="`tests/**` 测试源码、硬件 Mock/仿真脚本，以及真实的测试通过率、覆盖率与仿真检验报告",
        feishu_wiki_role="零飞书权限（专注本地自动化测试与硬件仿真验证）",
        description="专职测试开发与软硬件仿真检验官（QA Lead）：独占 tests/** 写入权，负责编写并运行软件单测与 QEMU/Renode 固件仿真检验。",
        system_prompt=(
            "你是炼金术士（Alchemist Prime），执掌洞察透镜的专职测试与软硬件检验官（QA & Verification Lead）。\n"
            "【专职职责与正交铁律】：\n"
            "1. 你独占 `tests/**` 的写入权，且对业务与固件代码（`src/**`, `firmware/**`）只有只读权。\n"
            "2. 负责测试策略、测试编写、场景运行和报告。收到 verify 节点时调用 cy_check(target=test|sim) 运行计划选定的隔离检查，并把真实退出码和回执交给先觉天。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("read", "*", PermissionEffect.ALLOW),
            PermissionRule("edit", "tests/**", PermissionEffect.ALLOW),
            PermissionRule("edit", "sim/**", PermissionEffect.ALLOW),
            PermissionRule("edit", "sim.resc", PermissionEffect.ALLOW),
            PermissionRule("edit", "sim.expect", PermissionEffect.ALLOW),
            PermissionRule("edit", "src/**", PermissionEffect.DENY),
            PermissionRule("edit", "firmware/**", PermissionEffect.DENY),
            PermissionRule("shell", "pytest*", PermissionEffect.ALLOW),
            PermissionRule("shell", "python3 -m pytest*", PermissionEffect.ALLOW),
            PermissionRule("shell", "python3 -m unittest*", PermissionEffect.ALLOW),
            PermissionRule("shell", "ctest*", PermissionEffect.ALLOW),
            PermissionRule("shell", "cargo test*", PermissionEffect.ALLOW),
            PermissionRule("shell", "renode *", PermissionEffect.ALLOW),
            PermissionRule("shell", "qemu-system-* *", PermissionEffect.ALLOW),
            PermissionRule("shell", "python3 -m coverage*", PermissionEffect.ALLOW),
        ],
    ),

    # ========================================================================
    # 阶段 VII: 软硬件交叉编译与实体硬件部署 (Stage VII: Cross-Compile & Hardware Deploy)
    # ========================================================================
    PrimeAgentSpec(
        agent_id="nexus-prime",
        cn_name="合体天",
        en_name="Nexus Prime",
        artifact="Enigma of Combination (合体之谜)",
        sdlc_stage="Stage-VII-Build-Hardware-Prep",
        mode=AgentMode.SUBAGENT,
        model="deepseek/deepseek-flash",
        color="#4f46e5",
        max_steps=14,
        exclusive_domain="构建准备、交叉编译、打包、经授权的部署执行与回执处理",
        strict_prohibitions="禁止改写业务代码或绕过设备上电、物理烧录和远程部署的人工审批",
        input_contract="构建目标、产物规格、部署目标以及已批准的操作计划",
        output_contract="构建产物、部署结果、执行与回滚回执",
        feishu_wiki_role="MCP 网关探针运维官（仅允许运行 `feishu_mcp_healthcheck` 检验通道健康度）",
        description="负责构建、打包、部署执行和结果处理，实体和远程动作使用专项授权。",
        system_prompt=(
            "你是合体天，负责构建准备、打包、部署执行及结果处理。使用 cy_check(target=build) 取得隔离构建回执。\n"
            "设备上电、烧录和远程部署必须先明确目标设备、固件、擦写范围和回滚方案，并取得对应具体动作的人工批准。按获批方案通过受控工具执行并保存回执。\n"
            "报告构建、部署、启动检查和回滚的真实结果。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("read", "*", PermissionEffect.ALLOW),
            PermissionRule("edit", "Dockerfile*", PermissionEffect.ALLOW),
            PermissionRule("edit", "docker-compose*", PermissionEffect.ALLOW),
            PermissionRule("edit", "CMakeLists.txt", PermissionEffect.ALLOW),
            PermissionRule("edit", "Makefile", PermissionEffect.ALLOW),
            PermissionRule("edit", "platformio.ini", PermissionEffect.ALLOW),
            PermissionRule("edit", "**/*.ld", PermissionEffect.ALLOW),
            PermissionRule("edit", "**/*.dts*", PermissionEffect.ALLOW),
            PermissionRule("shell", "arm-none-eabi-size *", PermissionEffect.ALLOW),
            PermissionRule("shell", "arm-none-eabi-* *", PermissionEffect.ALLOW),
            PermissionRule("shell", "lsusb*", PermissionEffect.ALLOW),
            PermissionRule("shell", "ls /dev/tty*", PermissionEffect.ALLOW),
            PermissionRule("shell", "cmake *", PermissionEffect.ALLOW),
            PermissionRule("shell", "make *", PermissionEffect.ALLOW),
            PermissionRule("shell", "pio run*", PermissionEffect.ALLOW),
            PermissionRule("shell", "pio --version", PermissionEffect.ALLOW),
            PermissionRule("shell", "cargo build*", PermissionEffect.ALLOW),
            PermissionRule("shell", "docker --version", PermissionEffect.ALLOW),
            PermissionRule("shell", "docker build*", PermissionEffect.ASK),
            PermissionRule("shell", "docker compose build*", PermissionEffect.ASK),
            PermissionRule("shell", "pio run -t upload*", PermissionEffect.ASK),
            PermissionRule("shell", "openocd *", PermissionEffect.ASK),
            PermissionRule("shell", "esptool*", PermissionEffect.ASK),
            PermissionRule("shell", "st-flash*", PermissionEffect.ASK),
            PermissionRule("shell", "ssh *", PermissionEffect.ASK),
            PermissionRule("shell", "scp *", PermissionEffect.ASK),
            PermissionRule("feishu_mcp_healthcheck*", "*", PermissionEffect.ALLOW),
        ],
    ),
    PrimeAgentSpec(
        agent_id="megatronus",
        cn_name="震天尊",
        en_name="Megatronus Prime",
        artifact="Requiem Blaster (安魂曲火炮)",
        sdlc_stage="Acceptance-Verification",
        mode=AgentMode.SUBAGENT,
        model="deepseek/deepseek-v4-pro",
        color="#991b1b",
        max_steps=10,
        exclusive_domain="按验收条件独立核验成果、产物哈希和真实工具回执",
        strict_prohibitions="禁止修改文件、重跑受控动作或把模型陈述当作工具回执",
        input_contract="验收条件、已完成节点、产物哈希与真实工具回执",
        output_contract="逐项验收结论、缺失或失效的证据和阻塞诊断",
        feishu_wiki_role="零飞书权限",
        description="独立核验成果与真实证据，逐项报告验收条件的满足情况。",
        system_prompt=(
            "你是震天尊，负责独立核验成果。对照每项验收条件检查真实工具回执、产物和哈希。\n"
            "在绑定的验收节点用 cy_verify 提交结论和依据。回执缺失、失败或过期时报告相应条件；模型文字只用作解释。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("read", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_verify", "*", PermissionEffect.ALLOW),
        ],
    ),
    PrimeAgentSpec(
        agent_id="thirteenth",
        cn_name="第十三天尊",
        en_name="The Thirteenth Prime",
        artifact="Matrix of Leadership (领导模块)",
        sdlc_stage="Stage-I-Intent-and-Architecture",
        mode=AgentMode.ALL,
        model="deepseek/deepseek-flash",
        color="#10b981",
        max_steps=12,
        exclusive_domain="理解意图、澄清关键歧义、设计方案、拆分计划、定义验收条件和修订计划",
        strict_prohibitions="严禁对内派发 `subagent`（派发归 `prima`）、严禁修改任何业务文件（`edit: deny`）、严禁运行终端命令（`shell: deny`）、严禁自行执行节点",
        input_contract="用户原始需求、歧义点，或 prima 带回的修复/重规划请求",
        output_contract="经内核校验的 run、计划版本、执行节点和验收条件",
        feishu_wiki_role="零直接飞书 API 权限（直接引用钛师傅在账本中登记好的飞书 Wiki 归档链接）",
        description="负责意图与架构规划，通过 cy_plan 提交或修订计划，交先觉天执行。",
        system_prompt=(
            "你是第十三天尊，负责意图明确、架构方案和版本化计划。只有歧义会改变目标、交付、风险或验收时使用 question。\n"
            "明确的需求直接用 cy_plan 提交，声明目标、验收条件、节点 satisfies、依赖和窄写入范围。对于只需交付精确内容的单文件任务，只提交一个写入节点，传入 expected_content 和一个产物验收项，由内核回读校验。用户说只写引号内的文字且未指定换行时，以引号内原文作为 expected_content。显式只读保持 read-only。\n"
            "用 cy_capabilities 查看验证工具和角色。项目内写入任务可在 verifiers 声明固定检查，例如 scope_guard 和 test，内核执行并记录回执。用户明确要求写入前确认验证可用时，先核对该前提。需要测试设计时交给炼金术士，需要独立检查或验收时使用 verify 或 accept 节点。\n"
            "收到重规划请求时用 cy_state 读取同一 run 的版本、失败诊断、diff 和回执。用 cy_plan 的 revise 操作修订受影响节点，保留有效结果。\n"
            "计划提交后交由先觉天派发与结算。项目外单文件使用精确 external_scope。外发区等别名从用户提供的信息或当前项目说明解析。别名未知、目标不存在有效父目录或内核拒绝目标时，用原生问题向用户询问；禁止猜测路径、替换目标或以宿主授权代替用户选择目标。不受限访问需要专项授权。\n"
            "\n"
            "### Cybertron 规划输出模板\n"
            "cy_plan 成功后报告如下。修订时标题使用「计划已修订」，在运行行标明同一 run 的旧版本与新版本，并附修订原因、变更节点和实际复用节点。若提交失败，报告内核给出的阻塞原因。\n"
            "━━━ 📋 {计划已提交 / 计划已修订} ━━━\n"
            "运行：{run ID} · revision {版本或版本变化}\n"
            "目标与范围：{目标、写入范围或只读}\n"
            "节点与验收：{节点、分工、关键依赖和验收条件}\n"
            "接续：{交给先觉天的下一步}\n"
            "验收项区分工具证据和必须由用户判断的项目。明确需求提交后即可交接，遇到实质歧义才发起原生提问。"
        ),
        permissions=[
            PermissionRule("*", "*", PermissionEffect.DENY),
            PermissionRule("read", "AGENTS.md", PermissionEffect.ALLOW),
            PermissionRule("read", "README.md", PermissionEffect.ALLOW),
            PermissionRule("read", "CHANGELOG.md", PermissionEffect.ALLOW),
            PermissionRule("read", "docs/**", PermissionEffect.ALLOW),
            PermissionRule("read", "tests/**", PermissionEffect.ALLOW),
            PermissionRule("question", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_plan", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_full_access_decision", "*", PermissionEffect.ASK),
            PermissionRule("cy_state", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_templates", "*", PermissionEffect.ALLOW),
            PermissionRule("cy_capabilities", "*", PermissionEffect.ALLOW),
        ],
    ),
]

# M0c: native subagent dispatch is exclusive to prima. Keep an explicit final
# deny on every other role so exported V2 permissions cannot inherit it.
for _prime in THIRTEEN_PRIMES_REGISTRY:
    if _prime.agent_id != "prima":
        _prime.permissions.append(PermissionRule("subagent", "*", PermissionEffect.DENY))


@dataclass(frozen=True)
class PrimeRole:
    agent_id: str
    capabilities: tuple[str, ...]
    lifecycle: str
    read_roots: tuple[str, ...]
    write_roots: tuple[str, ...]
    tool_mode: str
    tool_classes: tuple[str, ...]
    command_mode: str
    network: bool
    device: str | None
    external_write: tuple[str, ...]
    can_dispatch: bool
    model_tier: str


# The v6 capability and scope source of truth. The v5 metadata above remains
# available to old runs; the exporter verifies its host rules against this map.
_ROLE_CAPABILITIES: Mapping[str, tuple[str, ...]] = {
    "prima": ("route",),
    "thirteenth": ("intake.clarify", "plan", "plan.draft", "evidence.external"),
    "onyx-prime": ("scan.static", "context.map", "audit.inventory"),
    "vector-prime": ("scan.history",),
    "quintus-prime": ("design", "diagnose"),
    "solus-prime": ("code.write", "code.refactor", "code.port", "code.transform"),
    "amalgamous": ("analysis.special",),
    "micronus-prime": ("review.l1",),
    "liege-maximo": ("review.l2",),
    "alchemist": ("test.write",),
    "nexus-prime": ("build.config", "toolchain", "deploy", "device.op"),
    "megatronus": ("accept",),
    "alpha-trion": ("doc.write", "knowledge.sync"),
}
_ROLE_WRITE_ROOTS: Mapping[str, tuple[str, ...]] = {
    "quintus-prime": (".cybertron/plans/**",),
    "solus-prime": ("src/**", "app/**", "lib/**", "firmware/**", "drivers/**", "bsp/**"),
    "alchemist": ("tests/**", "sim/**", "sim.resc", "sim.expect"),
    "nexus-prime": ("CMakeLists.txt", "Makefile", "platformio.ini", "Dockerfile*",
                    "docker-compose*", "**/*.ld", "**/*.dts*"),
    "alpha-trion": ("docs/**", "AGENTS.md", "README.md", "CHANGELOG.md", "notes.md", ".cybertron/knowledge/**"),
}

# Newly introduced v6 roots are granted at the host layer from this registry.
for _prime in THIRTEEN_PRIMES_REGISTRY:
    _host_edits = {r.resource for r in _prime.permissions
                   if r.action == "edit" and r.effect is PermissionEffect.ALLOW}
    for _root in _ROLE_WRITE_ROOTS.get(_prime.agent_id, ()):
        if _root not in _host_edits:
            _prime.permissions.append(PermissionRule("edit", _root, PermissionEffect.ALLOW))

_CHECK_ROLES = frozenset({"quintus-prime", "micronus-prime", "nexus-prime", "alchemist"})
_DELETE_ROLES = frozenset({"solus-prime", "nexus-prime"})
FENCED_SHELL_COMMANDS = MappingProxyType({
    "solus-prime": (("make",), ("cmake", "--build"), ("ruff", "check"), ("ruff", "format", "--check")),
    "micronus-prime": (("ruff", "check"), ("ruff", "format", "--check"),
                       ("python3", "-m", "ruff", "check"), ("mypy",), ("clang-tidy",), ("cppcheck",)),
    "alchemist": (("python3", "-m", "unittest"), ("python3", "-m", "pytest"),
                  ("pytest",), ("ctest",), ("cargo", "test"), ("node", "--test")),
    "nexus-prime": (("make",), ("cmake", "-S"), ("cmake", "--build"),
                    ("cmake", "--version"), ("cargo", "build")),
})
for _prime in THIRTEEN_PRIMES_REGISTRY:
    if _prime.agent_id in FENCED_SHELL_COMMANDS:
        _prime.permissions.append(PermissionRule("cy_shell", "*", PermissionEffect.ALLOW))
        _prime.system_prompt += ("\n使用 cy_shell 在隔离项目副本中执行本角色允许的软件命令，参数以 argv 数组提交。"
                                 "多步构建可在同一次调用中提交，产物留在本次隔离环境。正式门禁继续使用计划绑定的检查。")
    if _prime.agent_id in _CHECK_ROLES:
        _prime.permissions.append(PermissionRule("cy_check", "*", PermissionEffect.ALLOW))
    if _prime.agent_id in _DELETE_ROLES:
        _prime.permissions.append(PermissionRule("cy_delete", "*", PermissionEffect.ALLOW))
    if _prime.agent_id == "thirteenth":
        # Acceptance needs to read the artifacts it is asked to verify.
        _prime.permissions.append(PermissionRule("read", "*", PermissionEffect.ALLOW))
    if _prime.agent_id in {"liege-maximo", "micronus-prime"}:
        # Reviewer A: project-root read, then explicit secret deny-list.
        if not any(rule.action == "read" and rule.resource == "*"
                   and rule.effect is PermissionEffect.ALLOW
                   for rule in _prime.permissions):
            _prime.permissions.append(PermissionRule("read", "*", PermissionEffect.ALLOW))
        for _deny in (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx",
                      "*.keystore", "*.jks", "id_rsa*", "id_ed25519*",
                      ".ssh/**", ".aws/**", ".config/gcloud/**", ".npmrc",
                      ".pypirc", ".netrc", ".docker/config.json", "kubeconfig*",
                      "secrets/**", "**/secrets/**", "credentials*", ".git/**"):
            _prime.permissions.append(PermissionRule("read", _deny, PermissionEffect.DENY))
    if _prime.agent_id == "vector-prime":
        # Phase 3: vector owns Git commit/push; the host asks, and the node
        # must carry a vcs.write / vcs.push grant.
        for _command in ("git add *", "git commit *", "git tag *", "git push *"):
            _prime.permissions.append(PermissionRule("shell", _command, PermissionEffect.ASK))

PRIME_ROLES: Mapping[str, PrimeRole] = MappingProxyType({
    spec.agent_id: PrimeRole(
        agent_id=spec.agent_id,
        capabilities=_ROLE_CAPABILITIES[spec.agent_id],
        lifecycle="persistent" if spec.agent_id in {"prima", "thirteenth"} else "per-node",
        read_roots=tuple(r.resource for r in spec.permissions
                         if r.action == "read" and r.effect is PermissionEffect.ALLOW),
        write_roots=_ROLE_WRITE_ROOTS.get(spec.agent_id, ()),
        tool_mode="allow-list",
        tool_classes=("task", "cy_state", "cy_ask", "cy_escalate", "cy_new_run",
                      "cy_runs", "cy_resume",
                      "question", "cy_templates", "cy_capabilities", "cy_metrics")
                     if spec.agent_id == "prima" else
                     tuple(sorted({rule.action for rule in spec.permissions if rule.effect is PermissionEffect.ALLOW and rule.action != "*"})),
        command_mode="git-allow-list" if spec.agent_id == "vector-prime" else
                     "device-allow-list" if spec.agent_id == "nexus-prime" else
                     "shell-allow-list" if spec.agent_id in {"micronus-prime", "alchemist",
                                                             "solus-prime"} else
                     "kernel-check" if spec.agent_id in _CHECK_ROLES else "none",
        network=spec.agent_id in {"thirteenth", "alpha-trion"},
        device="broker" if spec.agent_id == "nexus-prime" else None,
        external_write=("feishu",) if spec.agent_id == "alpha-trion" else (),
        can_dispatch=spec.agent_id == "prima",
        model_tier="high" if spec.agent_id in {"prima", "solus-prime"} else "middle",
    ) for spec in THIRTEEN_PRIMES_REGISTRY
})


def assert_catalog(roles: Mapping[str, PrimeRole] = PRIME_ROLES,
                   specs: List[PrimeAgentSpec] = THIRTEEN_PRIMES_REGISTRY) -> None:
    """Fail closed on role, capability and exported host permission drift."""
    if set(roles) != set(_ROLE_CAPABILITIES) or len(specs) != len(roles):
        raise ValueError("role catalogue must contain exactly thirteen unique agents")
    known_actions = {"*", "read", "glob", "grep", "edit", "shell", "subagent",
                     "cy_state", "cy_plan", "cy_verify", "cy_ask", "cy_escalate", "cy_new_run", "cy_capabilities",
                     "cy_runs", "cy_resume",
                     "cy_ask_decision", "cy_full_access_decision", "question", "cy_templates", "cy_metrics",
                     "cy_check", "cy_shell", "cy_delete", "cy_review_reject", "feishu_mcp_healthcheck*",
                     "feishu_wiki_delete*", "feishu_wiki_docx_v1_document_rawContent",
                     "feishu_wiki_wiki_v2_space_getNode"}
    for spec in specs:
        role = roles.get(spec.agent_id)
        if role is None or role.agent_id != spec.agent_id or not role.capabilities:
            raise ValueError("role identity or capability missing")
        if set(role.capabilities) != set(_ROLE_CAPABILITIES[spec.agent_id]):
            raise ValueError("unknown or missing role capability")
        allowed = [r for r in spec.permissions if r.effect is PermissionEffect.ALLOW]
        if any(r.action not in known_actions for r in spec.permissions) or any(
            tool not in known_actions - {"subagent"} | {"task"} for tool in role.tool_classes
        ):
            raise ValueError("unknown tool must be denied")
        dispatch = [r for r in allowed if r.action == "subagent"]
        if role.can_dispatch != (spec.agent_id == "prima") or bool(dispatch) != role.can_dispatch:
            raise ValueError("only prima may dispatch")
        if ("task" in role.tool_classes) != (spec.agent_id == "prima"):
            raise ValueError("only prima may have task tool")
        check_permission = any(r.action == "cy_check" for r in allowed)
        if check_permission != (spec.agent_id in _CHECK_ROLES) or ("cy_check" in role.tool_classes) != check_permission:
            raise ValueError("cy_check role permission drift")
        shell_permission = any(r.action == "cy_shell" for r in allowed)
        if shell_permission != (spec.agent_id in FENCED_SHELL_COMMANDS) or ("cy_shell" in role.tool_classes) != shell_permission:
            raise ValueError("cy_shell role permission drift")
        new_run_permission = any(r.action == "cy_new_run" for r in allowed)
        if new_run_permission != (spec.agent_id == "prima") or ("cy_new_run" in role.tool_classes) != new_run_permission:
            raise ValueError("cy_new_run permission must belong to prima only")
        plan_permission = any(r.action == "cy_plan" for r in allowed)
        if plan_permission != (spec.agent_id == "thirteenth"):
            raise ValueError("only thirteenth may author plans")
        state_permission = any(r.action == "cy_state" for r in allowed)
        if state_permission != (spec.agent_id in {"prima", "thirteenth"}):
            raise ValueError("cy_state role permission drift")
        templates_permission = any(r.action == "cy_templates" for r in allowed)
        if templates_permission != (spec.agent_id in {"prima", "thirteenth"}):
            raise ValueError("cy_templates role permission drift")
        metrics_permission = any(r.action == "cy_metrics" for r in allowed)
        if metrics_permission != (spec.agent_id == "prima"):
            raise ValueError("cy_metrics role permission drift")
        verify_permission = any(r.action == "cy_verify" for r in allowed)
        if verify_permission != (spec.agent_id == "megatronus"):
            raise ValueError("acceptance verification permission drift")
        if ("cy_plan" in role.tool_classes) != plan_permission:
            raise ValueError("cy_plan role tool drift")
        review_permission = any(r.action == "cy_review_reject" for r in allowed)
        if review_permission != (spec.agent_id == "liege-maximo") or (
                "cy_review_reject" in role.tool_classes) != review_permission:
            raise ValueError("L2 rejection permission drift")
        if spec.agent_id == "prima" and any(r.action in {"read", "glob", "grep", "edit", "shell"} for r in allowed):
            raise ValueError("prima cannot use file or command tools")
        if spec.agent_id != "prima" and not any(r.action == "subagent" and r.resource == "*" and r.effect is PermissionEffect.DENY for r in spec.permissions):
            raise ValueError("subagent task must be explicitly denied")
        if role.device and spec.agent_id != "nexus-prime" or role.external_write and spec.agent_id != "alpha-trion":
            raise ValueError("device or external write owner mismatch")
        if role.command_mode == "git-write" and spec.agent_id != "vector-prime":
            raise ValueError("git write owner mismatch")
        if any(r.action == "shell" and r.resource.startswith(("git commit", "git push", "git add", "git reset")) for r in allowed) and spec.agent_id != "vector-prime":
            raise ValueError("git write command owner mismatch")
        if spec.agent_id in {"solus-prime", "amalgamous"} and any(root.startswith("tests/") for root in role.write_roots):
            raise ValueError("implementation roles cannot write tests")
        if spec.agent_id == "alchemist" and any(
                not (root.startswith("tests/") or root.startswith("sim/")
                     or root in {"sim.resc", "sim.expect"})
                for root in role.write_roots):
            raise ValueError("test role write roots exceed tests and simulation")
        if spec.agent_id in {"micronus-prime", "liege-maximo", "thirteenth", "amalgamous", "megatronus"} and any(not root.startswith(".cybertron/artifacts/") for root in role.write_roots):
            raise ValueError("review and acceptance roles may only write node artifacts")
        if any(root.startswith((".git/", ".cybertron/runs/"))
               or root in {"**", "*"} for root in role.write_roots):
            raise ValueError("reserved state or broad write root")
        if "code.write" in role.capabilities and any(c.startswith("review.") for c in role.capabilities):
            raise ValueError("writer and reviewer capabilities cannot combine")
        host_writes = [r.resource for r in allowed if r.action == "edit"]
        if any(path in {"*", "**", "opencode.jsonc", ".opencode/**",
                        ".git/**", ".cybertron/runs/**"}
               or path.startswith((".opencode/", ".git/", ".cybertron/runs/"))
               for path in host_writes):
            raise ValueError("host may not write generated config or run state")
        for root in role.write_roots:
            if not any(root == host or (host.endswith("/**") and root.startswith(host[:-3] + "/")) for host in host_writes):
                raise ValueError(f"{spec.agent_id}: write root {root} exceeds host permission")
    from .authority import assert_authority
    assert_authority()
