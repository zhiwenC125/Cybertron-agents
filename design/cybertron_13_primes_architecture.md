# 塞伯坦十三天尊（The Thirteen Primes）软硬一体全生命周期多智能体 Code Agent 架构设计白皮书（v5.0 Markdown 终审版）

> **版本信息**：v5.0（软硬一体全生命周期 SDLC + 硬件交叉编译烧录部署 + 独立 Code Review / 测试 / 飞书文档专职化重构版）
> **架构与产品视角**：首席产品经理 (PM) & 首席软件/嵌入式系统架构师 (Principal Systems Architect)
> **核心理论参考**：[Victor Dibia — Designing Multi-Agent Systems (PicoAgents Framework)](https://github.com/victordibia/designing-multiagent-systems)
> **双栖目标宿主**：[OpenCode V2](https://opencode.ai/docs/agents/)（`.opencode/agents/*.md` + `opencode.jsonc`）与 [DeepSeek Harness (dsh)](https://github.com/deepseek-ai/deepseek-harness)（`.dsh/cordis-cybertron-plugin.mjs`）
> **知识库底座**：[飞书开放平台知识库（Feishu Wiki v2）](https://open.feishu.cn/document/server-docs/docs/wiki-v2/wiki-overview?lang=zh-CN) & [飞书官方 OpenAPI MCP (`@larksuiteoapi/lark-mcp`)](https://github.com/larksuite/lark-openapi-mcp)

## 1. 产品经理与首席架构师重构洞察：从「纯软件代码生成」升级为「软硬一体全生命周期工程军团」

在 v4.0 的审视中，你敏锐地指出了两个决定系统工程上限的关键问题：
1. **质量与文档角色必须显性专职化**：工程研发中，**代码审查（Code Review）**、**动静态测试与硬件在环验证（Testing & Verification）**以及**技术文档与飞书知识库沉淀（Documentation & Feishu Wiki）**绝不能沦为编码角色的附庸，必须拥有独立、专职、具备一票否决权的天尊角色。
2. **打破纯软件边界，覆盖「硬件交叉编译、固件烧录与边缘设备部署（Hardware/Edge Deployment）」**：真正的全栈 Code Agent 不仅要能写 Python/Rust/C++ 业务代码，还要能生成 CMake/DeviceTree（设备树）、调用交叉编译工具链（`arm-none-eabi-gcc` / `aarch64-linux-gnu-gcc` / `cargo-embed` / `esptool` / `openocd` / `PlatformIO` / `ROS2`），并将编译产物安全部署烧录到真实开发板、MCU、FPGA 或边缘计算节点（如 Jetson / 树莓派 / RDK / STM32 / ESP32）上采集串口日志完成端到端闭环。

结合 [victordibia/designing-multiagent-systems](https://github.com/victordibia/designing-multiagent-systems/blob/main/README.md) 中关于 **软件工程智能体（Ch.17 SWE-Agent）**、**自主计划账本编排（Ch.7 Plan-Based Orchestration）** 与 **多评审员质量门禁（Ch.10 Evaluation & Judges）** 的设计范式，我们在 **v5.0** 中将 **[塞伯坦十三天尊（The Thirteen Primes）](https://transformers.fandom.com/wiki/Thirteen)** 严格映射到 **软硬一体软件开发全生命周期（7 大 SDLC 阶段）**，做到 **「一尊一专职、零权限重叠、软硬全闭环」**。

```svg
<svg viewBox="0 0 680 340" xmlns="http://www.w3.org/2000/svg">
  <style>
    :root {
      --lumi-ink: light-dark(#000000, #e0e0e0);
      --lumi-muted: light-dark(#5f6368, #9aa0a6);
      --lumi-dim: light-dark(#f2f0f0, #242528);
      --lumi-container: light-dark(#e8e6e6, #2d2f33);
      --lumi-outline: light-dark(#727676, #9a9b9c);
      --lumi-accent-bg: light-dark(#dcf1ff, #192967);
      --lumi-primary: light-dark(#3186ff, #9dd2ff);
      --lumi-sans: 'Google Sans Flex', var(--font-family, 'Google Sans', sans-serif);
      --lumi-mono: 'Google Sans Code', ui-monospace, monospace;
    }
    text { font-weight: 400; stroke: none; }
    .t-l1 { font-family: var(--lumi-sans); font-size: 15px; fill: var(--lumi-ink); }
    .t-l2 { font-family: var(--lumi-mono); font-size: 13px; font-style: italic; fill: var(--lumi-ink); }
    .t-l4 { font-family: var(--lumi-sans); font-size: 13px; fill: var(--lumi-muted); }
    .node-step { fill: var(--lumi-dim); stroke: none; }
    .node-focal { fill: var(--lumi-accent-bg); stroke: var(--lumi-primary); stroke-width: 1.25; }
    .node-store { fill: var(--lumi-container); stroke: var(--lumi-outline); stroke-width: 1; }
    .edge-arrow { fill: none; stroke: var(--lumi-ink); stroke-width: 1.3; stroke-linecap: round; stroke-dasharray: 0 4; marker-end: url(#lumi-caret-sdlc); }
  </style>
  <defs>
    <marker id="lumi-caret-sdlc" viewBox="0 0 10 10" refX="7.5" refY="5" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" orient="auto">
      <path d="M 3 1.2 L 7.5 5 L 3 8.8" fill="none" stroke="var(--lumi-ink)" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  <rect class="node-focal" x="20" y="24" width="184" height="80" rx="40"/>
  <text class="t-l1" x="112" y="55" text-anchor="middle" dominant-baseline="central">1. 指挥与立项</text>
  <text class="t-l2" x="112" y="77" text-anchor="middle" dominant-baseline="central">Prima / Thirteenth</text>
  <line class="edge-arrow" x1="212" y1="64" x2="240" y2="64"/>
  <rect class="node-store" x="248" y="24" width="184" height="80" rx="40"/>
  <text class="t-l1" x="340" y="55" text-anchor="middle" dominant-baseline="central">2. 飞书文档与知识</text>
  <text class="t-l2" x="340" y="77" text-anchor="middle" dominant-baseline="central">Alpha Trion (专职文档)</text>
  <line class="edge-arrow" x1="440" y1="64" x2="468" y2="64"/>
  <rect class="node-step" x="476" y="24" width="184" height="80" rx="40"/>
  <text class="t-l1" x="568" y="55" text-anchor="middle" dominant-baseline="central">3. 架构与代码侦察</text>
  <text class="t-l2" x="568" y="77" text-anchor="middle" dominant-baseline="central">Onyx / Vector / Quintus</text>
  <path class="edge-arrow" d="M 568 112 L 568 156 Q 568 172 552 172 L 128 172 Q 112 172 112 188 L 112 212"/>
  <rect class="node-step" x="20" y="220" width="184" height="80" rx="40"/>
  <text class="t-l1" x="112" y="251" text-anchor="middle" dominant-baseline="central">4. 软硬件编码实现</text>
  <text class="t-l2" x="112" y="273" text-anchor="middle" dominant-baseline="central">Solus / Amalgamous</text>
  <line class="edge-arrow" x1="212" y1="260" x2="240" y2="260"/>
  <rect class="node-focal" x="248" y="220" width="184" height="80" rx="40"/>
  <text class="t-l1" x="340" y="251" text-anchor="middle" dominant-baseline="central">5. Review与测试检验</text>
  <text class="t-l2" x="340" y="273" text-anchor="middle" dominant-baseline="central">Micronus/Alchem/Liege</text
  <line class="edge-arrow" x1="440" y1="260" x2="468" y2="260"/>
  <rect class="node-store" x="476" y="220" width="184" height="80" rx="40"/>
  <text class="t-l1" x="568" y="251" text-anchor="middle" dominant-baseline="central">6. 硬件烧录与部署</text>
  <text class="t-l2" x="568" y="273" text-anchor="middle" dominant-baseline="central">Nexus / Megatronus</text>
</svg>
```

## 2. 软件+硬件全生命周期（SDLC）与塞伯坦十三天尊全景映射总表

我们将软硬一体研发全生命周期划分为 **7 大标准工程阶段**，13 位天尊各司其职，专门强化了 **专职技术文档撰写（02 钛师傅）**、**专职代码审查 Code Review（08 微米天 + 10 谎言天尊双级审查）**、**专职测试与软硬件检验（09 炼金术士）** 以及 **专职硬件交叉编译、固件烧录与容器部署（11 合体天 + 12 震天尊）**：

| SDLC 生命周期阶段 | 编号与天尊代号 | 塞伯坦神器 | 工程专职角色定位 | 核心职能一句话总结（MECE 零重叠） |
| :--- | :--- | :--- | :--- | :--- |
| **阶段 I：立项澄清与总控编排**<br>*(Requirements & Orchestration)* | **01. 先觉天** (`prima`) | 星辰剑 ([Star Saber](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)) | **首席研发编排官**<br>*(Primary Orchestrator)* | 唯一主控入口，维护全局 `TaskLedger` 状态机，按 SDLC 阶段点名调度其余 12 位天尊，不亲自读写业务代码。 |
| **阶段 I：立项澄清与总控编排**<br>*(Requirements & Orchestration)* | **13. 第十三天尊** (`thirteenth`) | 领导模块 ([Matrix](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)) | **产品需求澄清与验收交付官**<br>*(PM & Acceptance Lead)* | 对外连接人类开发者：立项前澄清软硬件指标（MCU型号/算力/接口），结项时执行端到端预览并输出交付报告。 |
| **阶段 II：技术文档与飞书知识库**<br>*(Documentation & Feishu Wiki)* | **02. 钛师傅** (`alpha-trion`) | 契约之笔 ([Quill](https://zh.wikipedia.org/zh-cn/%E5%89%B5%E4%B8%96%E5%8D%81%E4%B8%89%E7%A5%96)) | **专职技术文档撰写官 & 飞书知识库总管**<br>*(Tech Writer & Wiki Steward)* | **专职写文档**：唯一读写飞书知识库（PRD/ADR/硬件引脚手册），撰写并同步本地 `AGENTS.md`、`README.md` 与 `docs/**`。 |
| **阶段 III：代码侦察与系统架构**<br>*(Discovery & System Architecture)* | **03. 锐天骁** (`onyx-prime`) | 三面灵具 ([Triptych Mask](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)) | **静态代码库与硬件驱动拓扑侦察官**<br>*(Static Code & BSP Scout)* | 负责**空间维度**只读扫描：用 `read/glob/grep` 探查存量源码结构、AST 符号定义、外设寄存器映射与跨文件调用链。 |
| **阶段 III：代码侦察与系统架构**<br>*(Discovery & System Architecture)* | **04. 维克多** (`vector-prime`) | 时空之剑 ([Blades of Time](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)) | **Git 版本演进与固件基线考古官**<br>*(Version & Baseline Historian)* | 负责**时间维度**只读考古：用 `git log/blame/diff/tag` 追溯历史提交、固件版本基线差异并定位引入回归 Bug 的 Commit。 |
| **阶段 III：代码侦察与系统架构**<br>*(Discovery & System Architecture)* | **05. 昆图斯** (`quintus-prime`) | 创世余烬 ([Ember of Genesis](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)) | **软硬件系统架构师 & 脚手架孵化器**<br>*(System Architect & Scaffolder)* | 负责 **0 到 1 工程骨架与硬件抽象层（HAL）契约定义**：创建目录、依赖清单（`pyproject.toml`/`CMakeLists.txt`）与空接口头文件。 |
| **阶段 IV：软硬件编码与重构**<br>*(Software & Firmware Coding)* | **06. 赛天骄** (`solus-prime`) | 造物神锤 ([Forge of Solus](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)) | **核心业务代码与嵌入式固件锻造师**<br>*(Core Software & Firmware Coder)* | **专职写核心代码**：实现后端业务逻辑、算法以及嵌入式驱动/BSP/RTOS 任务代码（`src/**`, `firmware/**`），修复功能 Bug。 |
| **阶段 IV：软硬件编码与重构**<br>*(Software & Firmware Coding)* | **07. 幻化天** (`amalgamous`) | 幻化之镰 ([Scythe](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)) | **代码重构与跨硬件平台移植专家**<br>*(Refactoring & Hardware Porting)* | **专职结构重构与硬件平台迁移**：在不改变外部业务语义的前提下，完成代码解耦、内存布局优化及跨芯片/跨操作系统移植。 |
| **阶段 V：专职 Code Review 与质量审计**<br>*(Dedicated Code Review & Audit)* | **08. 微米天** (`micronus-prime`) | 奇美拉石 ([Chimera Stone](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)) | **专职代码规范审查官（L1 静态 Code Reviewer）**<br>*(Style, Lint & Static Reviewer)* | **专职第一道 Code Review**：执行 `ruff/clang-tidy/clippy` 静态规范检查、类型安全校验、内存对齐检查与 Docstring 完备性审查。 |
| **阶段 V：专职 Code Review 与质量审计**<br>*(Dedicated Code Review & Audit)* | **10. 谎言天尊** (`liege-maximo`) | 巅峰权杖 ([Staff of Apex](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)) | **专职深度逻辑与安全 Code Reviewer（L2 红队审判官）**<br>*(Deep Logic & Security Reviewer)* | **专职第二道深度 Code Review**：纯静态对抗审查，挑刺并发死锁、中断重入、内存溢出、密钥硬编码与架构违规，拥有一票否决权。 |
| **阶段 VI：专职测试与软硬件检验**<br>*(Testing & SIL/HIL Verification)* | **09. 炼金术士** (`alchemist`) | 洞察透镜 ([Lenses](https://www.quora.com/What-are-the-names-and-abilities-of-the-13-Primes)) | **专职测试开发与软硬件仿真检验官（QA & Verification）**<br>*(Test Engineer & SIL/HIL Verifier)* | **专职写测试与跑检验**：独占 `tests/**` 写入权，编写单元测试、集成测试与 QEMU/Renode 硬件仿真测试脚本，输出覆盖率与检验报告。 |
| **阶段 VII：软硬件构建与实体硬件部署**<br>*(Cross-Compile & Hardware Deploy)* | **11. 合体天** (`nexus-prime`) | 合体之谜 ([Enigma](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)) | **软硬件交叉编译、容器打包与硬件部署工程师**<br>*(Build, Cross-Compile & HW Deployer)* | **专职构建与硬件部署**：维护 Docker/CI、交叉编译工具链，构建固件镜像（`.bin/.elf/.uf2`），探测串口/JTAG/SSH 目标板并生成烧录部署管线。 |
| **阶段 VII：软硬件构建与实体硬件部署**<br>*(Cross-Compile & Hardware Deploy)* | **12. 震天尊** (`megatronus`) | 安魂曲火炮 ([Requiem Blaster](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)) | **物理硬件烧录安全闸门、高危熔断与回滚执法官**<br>*(Hardware Flash Gate & Circuit Breaker)* | **专职物理烧录审批与安全熔断**：管控真实硬件擦写烧录（`openocd/esptool`）、高压外设上电、文件删除与固件回滚，100% 强制人工确认。 |

## 3. 塞伯坦十三天尊（01–13）逐一职责宪章全景详解（Role Charter）

为了让你在审核时对每一位天尊的职责一目了然，以下按 **软硬一体软件开发全生命周期（7 大阶段）** 逐一列出 13 位天尊的完整职责说明书：

### 阶段 I：需求立项、人机澄清与全局编排（Requirements & Orchestration）

#### 01. 先觉天（Prima Prime · Agent ID: `prima`）—— 首席研发编排官（Primary Orchestrator）
- **塞伯坦设定与模型**：十三天尊之首，持星辰剑（[Star Saber](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)） | 绑定模型：`deepseek/deepseek-reasoner`（`mode: primary`）
- **核心专职职责**：作为整个多智能体系统的唯一主控入口，先觉天复刻 [PicoAgents](https://github.com/victordibia/designing-multiagent-systems) 的 `PlanBasedOrchestrator`。收到用户任务后，他负责建立并动态维护全局研发账本（`CybertronTaskLedger`），严格按照 **「立项澄清 → 飞书文档拉取 → 侦察与架构 → 软硬件编码 → 双级 Code Review → 自动化测试与仿真检验 → 交叉编译与硬件烧录部署 → 飞书文档归档」** 的生命周期调度其余 12 位天尊。当测试失败或 Code Review 被拒时，负责将缺陷工单精准打回给编码天尊修复。
- **标准输入与输出**：输入为用户需求或 `thirteenth` 澄清后的技术规格单；输出为 `TaskLedger` 状态更新与下一步唯一子天尊派单指令。
- **绝对禁止红线**：严禁亲自读取 `src/**` 或 `firmware/**` 源码、严禁修改任何文件（`edit: deny`）、严禁执行任何终端命令（`shell: deny`）、严禁直接调用飞书 API。

#### 13. 第十三天尊（The Thirteenth Prime · Agent ID: `thirteenth`）—— 产品需求澄清与最终验收交付官
- **塞伯坦设定与模型**：领导模块传递者（[Matrix of Leadership](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)） | 绑定模型：`deepseek/deepseek-chat`（`mode: all`）
- **核心专职职责**：负责对外连接人类开发者，把守研发的**「最前端（立项澄清）」**与**「最后端（验收交付）」**：
  1. **立项前软硬件需求澄清**：当需求未指明关键参数（如目标硬件芯片型号 STM32F4/ESP32-S3/Jetson Orin、通信协议 UART/CAN/MQTT、性能时延指标或接口格式）时，向用户发起结构化澄清问卷。
  2. **结项时端到端验收与交付汇报**：利用全系统唯一的 `webfetch` 权限预览已启动的 Web/上位机服务，汇总代码变更清单、Code Review 结论、测试通过率、硬件烧录回执以及钛师傅归档的飞书知识库链接，向用户输出完整交付简报。
- **标准输入与输出**：输入为歧义点或已完工的 `TaskLedger`；输出为澄清问卷或最终研发交付报告。
- **绝对禁止红线**：严禁对内派发 `subagent`（调度归先觉天）、严禁修改任何代码或文档文件（`edit: deny`）、严禁运行终端命令（`shell: deny`）。

### 阶段 II：专职技术文档撰写与飞书知识库治理（Documentation & Feishu Wiki）

#### 02. 钛师傅（Alpha Trion · Agent ID: `alpha-trion`）—— 专职技术文档撰写官 & 飞书知识库总管
- **塞伯坦设定与模型**：博学者与记录官，持契约之笔与《元始圣约》（[Quill & Covenant of Primus](https://zh.wikipedia.org/zh-cn/%E5%89%B5%E4%B8%96%E5%8D%81%E4%B8%89%E7%A5%96)） | 绑定模型：`deepseek/deepseek-chat`（`mode: subagent`）
- **核心专职职责**：**全系统唯一的专职文档工程师（Technical Writer）与飞书知识库（[Feishu Wiki](https://open.feishu.cn/document/server-docs/docs/wiki-v2/wiki-overview?lang=zh-CN)）唯一读写总管**：
  1. **开发前知识拉取与本地契约撰写**：立项后从飞书知识库拉取需求 PRD、硬件原理图引脚定义表（Pinout）、寄存器手册与历史架构决策（ADR），提炼后撰写/更新本地工作区的 `AGENTS.md` 与 `docs/spec/*.md`，让后续天尊无需重复联网即可离线读取清晰规范。
  2. **专职撰写项目文档**：负责编写和更新项目的 `README.md`、API 接口文档、硬件接线与烧录说明指南（`docs/hardware_guide.md`）、架构决策记录（`docs/adr/*.md`）及变更日志（`CHANGELOG.md`）。
  3. **飞书双阶段知识库归档与上下文压缩**：在功能开发或硬件部署完成后，将最新架构文档、接口手册与复盘记录同步回写至飞书知识库节点；同时内置 [PicoAgents `compaction.py`](https://github.com/victordibia/designing-multiagent-systems/blob/main/picoagents/src/picoagents/compaction.py) 原子组首尾压缩器，防止长文档撑爆上下文。
- **标准输入与输出**：输入为飞书检索词、`node_token` 或待编写文档的代码/硬件变更摘要；输出为本地 `AGENTS.md`、`README.md`、`docs/**` 文档及飞书 Wiki 节点 URL。
- **绝对禁止红线**：严禁修改任何业务源码（`src/**`, `firmware/**`）或测试代码（`tests/**`）、严禁执行任何 Shell 命令、严禁删除飞书节点（删除归震天尊）。

### 阶段 III：代码库侦察与软硬件系统架构设计（Discovery & System Architecture）

#### 03. 锐天骁（Onyx Prime · Agent ID: `onyx-prime`）—— 静态代码拓扑与硬件 BSP 依赖侦察官
- **塞伯坦设定与模型**：猛兽之祖，持三面灵具（[Triptych Mask](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)） | 绑定模型：`deepseek/deepseek-chat`（`mode: subagent`）
- **核心专职职责**：负责**「空间维度（当前工作区静态快照）」**的纯只读侦察。通过 `glob`、`grep`、`read` 高速扫描本地代码树、CMake/Makefile 依赖关系、设备树（`.dts/.dtsi`）、引脚宏定义以及函数调用链（Call Graph），输出精确的文件路径与行号坐标。
- **标准输入与输出**：输入为待查符号名、外设名或报错关键词；输出为包含精确 `filepath:start_line-end_line` 与上下游依赖图的侦察报告。
- **绝对禁止红线**：严禁执行任何 `git` 或终端命令、严禁直连飞书、严禁修改任何文件、严禁做主观代码质量评判。

#### 04. 维克多（Vector Prime · Agent ID: `vector-prime`）—— Git 版本时间线与固件基线考古官
- **塞伯坦设定与模型**：时空守护者，持时空之剑（[Blades of Time](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)） | 绑定模型：`deepseek/deepseek-chat`（`mode: subagent`）
- **核心专职职责**：负责**「时间维度（Git 版本演进史）」**的纯只读考古。使用只读 Git 命令（`git log`, `git blame`, `git diff`, `git tag`, `git show`）分析代码与固件版本的历史演进，比对不同硬件批次/固件 Tag 之间的差异，定位引入 Bug 的精确 Commit。
- **标准输入与输出**：输入为目标文件路径、版本 Tag 或故障时间范围；输出为包含 `commit_sha`、提交者、历史差异对比与回归根因的考古报告。
- **绝对禁止红线**：严禁用 `glob/grep` 扫全库静态拓扑（归锐天骁）、严禁修改任何文件、严禁执行 `git reset/push` 等写操作。

#### 05. 昆图斯（Quintus Prime · Agent ID: `quintus-prime`）—— 软硬件系统架构师 & 脚手架孵化器
- **塞伯坦设定与模型**：生命缔造者，持创世余烬（[Ember of Genesis](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)） | 绑定模型：`deepseek/deepseek-chat`（`mode: subagent`）
- **核心专职职责**：负责**「从 0 到 1 的软硬件工程骨架创建与接口契约定义」**：
  1. 创建标准工程目录结构（`mkdir -p`），编写软件依赖清单（`pyproject.toml`, `package.json`, `Cargo.toml`）。
  2. 定义软件模块的数据模型（`schemas.py`）、抽象接口契约（`interfaces.py`）以及硬件抽象层头文件骨架（`hal_*.h` / `bsp_interface.hpp`，函数体留空），确保软硬件模块之间通过标准接口解耦。
- **标准输入与输出**：输入为 `AGENTS.md` 中的系统架构蓝图；输出为工程目录树、包管理清单及空接口/头文件契约骨架。
- **绝对禁止红线**：严禁在函数体内编写具体业务逻辑或寄存器操作实现（归赛天骄）、严禁编写测试或部署脚本。

### 阶段 IV：软件业务与嵌入式固件编码实现（Software & Firmware Implementation）

#### 06. 赛天骄（Solus Prime · Agent ID: `solus-prime`）—— 核心业务代码与嵌入式固件锻造师
- **塞伯坦设定与模型**：传奇锻造大师，持造物神锤（[Forge of Solus Prime](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)） | 绑定模型：`deepseek/deepseek-coder`（`mode: subagent`）
- **核心专职职责**：**全系统唯一负责编写新增业务功能与嵌入式底层驱动实现的主力程序员**：
  1. **软件层**：在 `src/**`、`app/**` 中实现后端服务、核心算法、API 路由与状态机逻辑。
  2. **硬件/固件层**：在 `firmware/**`、`drivers/**`、`bsp/**` 中编写 MCU/SoC 外设驱动（GPIO/UART/SPI/I2C/CAN/PWM）、RTOS 任务调度、传感器数据采集与边缘推理代码，并根据测试或 Code Review 意见修复代码 Bug。
- **标准输入与输出**：输入为 `AGENTS.md` 规范、昆图斯定义的接口骨架及锐天骁提供的行号坐标；输出为完成功能实现的 `src/**`, `app/**`, `firmware/**`, `drivers/**` 源码。
- **绝对禁止红线**：严禁修改 `tests/**` 测试用例、严禁擅自篡改 `interfaces.py`/`hal_*.h` 契约签名、严禁运行任何编译或烧录 Shell 命令。

#### 07. 幻化天（Amalgamous Prime · Agent ID: `amalgamous`）—— 代码解耦重构与跨硬件平台移植专家
- **塞伯坦设定与模型**：变形之祖，持幻化之镰（[Scythe of Transmutation](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)） | 绑定模型：`deepseek/deepseek-coder`（`mode: subagent`）
- **核心专职职责**：负责**「不改变外部功能语义的深度结构重构（Refactoring）与跨硬件平台移植（Hardware Porting）」**：
  1. **代码解耦与性能重构**：拆分高圈复杂度函数、消除重复代码、优化嵌入式端静态内存分配（消除动态 `malloc` 碎片）与 DMA 缓冲区对齐。
  2. **跨硬件芯片/架构移植**：将已有算法或驱动从一种硬件平台迁移适配到另一种平台（例如从 STM32 HAL 移植到 ESP-IDF，或从 x86 迁移到 ARM64/RISC-V 算子）。
- **标准输入与输出**：输入为待重构源码或跨平台移植需求；输出为功能语义 100% 等价、完成解耦或跨架构适配的 `src/**`, `lib/**`, `firmware/**` 源码。
- **绝对禁止红线**：严禁夹带未经要求的业务功能新增、严禁修改 `tests/**`、严禁执行任何 Shell 命令。

### 阶段 V：专职双级代码审查（Dedicated Two-Tier Code Review & Static Audit）

为了彻底解决「缺乏专职 Code Review 与静态检验角色」的问题，我们在进入测试与硬件烧录前设立了 **「08 微米天（L1 规范与静态分析审查）+ 10 谎言天尊（L2 深度逻辑、并发与硬件安全审查）」** 双级专职 Code Review 门禁：

#### 08. 微米天（Micronus Prime · Agent ID: `micronus-prime`）—— 专职 L1 代码规范审查与静态分析官（Style & Static Analyzer）
- **塞伯坦设定与模型**：迷你金刚之祖，持奇美拉石（[Chimera Stone](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)） | 绑定模型：`deepseek/deepseek-chat`（`mode: subagent`, `steps: 8`）
- **核心专职职责**：**专职第一道自动化静态检验与代码规范审查（L1 Code Review & Static Linting）**：
  1. 运行静态分析与格式化工具链（Python: `ruff check`, `mypy`; C/C++ 固件: `clang-tidy`, `cppcheck`; Rust: `cargo clippy`），检验语法规范、类型完整性、未使用变量、未初始化指针与 MISRA-C 基础规范。
  2. 审查所有公开函数与硬件驱动接口是否具备完整的类型签名与 Docstring/Doxygen 注释，并可执行零控制流变动的注释/格式自动补全。
- **标准输入与输出**：输入为赛天骄或幻化天提交的变更代码列表；输出为静态分析检验报告（`L1_Static_Review_Report`）及规范化后的代码。
- **绝对禁止红线**：严禁修改任何可执行控制流或业务逻辑语句！若发现逻辑级 Bug，必须在审查报告中标记并交由先觉天打回赛天骄修改。

#### 10. 谎言天尊（Liege Maximo · Agent ID: `liege-maximo`）—— 专职 L2 深度逻辑与安全 Code Reviewer（Adversarial Red-Team Critic）
- **塞伯坦设定与模型**：博弈与诡计大师，持巅峰权杖（[Staff of Apex](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)） | 绑定模型：`deepseek/deepseek-reasoner`（`mode: subagent`）
- **核心专职职责**：**专职第二道深度人工级 Code Review 与红队安全审判（L2 Deep Code Reviewer，对应 [PicoAgents `eval/judges/`](https://github.com/victordibia/designing-multiagent-systems)）**。他不写任何代码、不跑任何命令，纯粹以最严苛的资深架构师与安全红队视角逐行审视代码：
  1. **软件层审查**：排查 SQL/命令注入、硬编码飞书 `AppSecret`/API 密钥、并发竞态条件、内存泄漏与接口契约违背。
  2. **嵌入式与硬件层审查**：专门审查中断服务函数（ISR）中是否违规调用了阻塞操作/浮点运算、多线程/RTOS 死锁风险、看门狗（Watchdog）喂狗逻辑缺失、栈溢出风险、DMA 缓存一致性以及引脚电平冲突（如把输入引脚配置为强推挽输出导致硬件短路风险）。
- **标准输入与输出**：输入为待审讯的软件与固件代码；输出为带 `[SEVERITY: CRITICAL|HIGH|MEDIUM|LOW]`、精确 `file:line` 证据与修复建议的《深度 Code Review 裁决书》（含 `PASS` 或 `REJECT` 印章，拥有一票否决权）。
- **绝对禁止红线**：零文件写入权（`edit: deny`）、零终端执行权（`shell: deny`），确保 Code Reviewer 绝对中立。

### 阶段 VI：专职测试开发与软硬件仿真检验（Dedicated Testing & SIL/HIL Verification）

#### 09. 炼金术士（Alchemist Prime · Agent ID: `alchemist`）—— 专职测试开发与软硬件仿真检验官（QA & Verification Lead）
- **塞伯坦设定与模型**：元素法则洞察者，持洞察透镜（[Lenses](https://www.quora.com/What-are-the-names-and-abilities-of-the-13-Primes)） | 绑定模型：`deepseek/deepseek-coder`（`mode: subagent`）
- **核心专职职责**：**全系统唯一的专职测试与检验工程师（独占 `tests/**` 写入权与测试执行权）**：
  1. **软件单元与集成测试**：针对业务代码独立编写正向、反向、异常注入与边界值测试用例（`pytest` / `unittest` / `gtest` / `cargo test`），统计测试覆盖率。
  2. **硬件在环前仿真检验（SIL / Emulator Verification）**：在烧录真实硬件前，编写硬件 Mock 桩代码或调用 `QEMU` / `Renode` / `Verilator` 仿真器对嵌入式固件逻辑进行软件在环仿真检验，验证状态机、通信协议帧解析（CRC 校验/粘包处理）与寄存器配置序列是否正确。
- **标准输入与输出**：输入为通过静态审查的 `src/**` / `firmware/**` 代码及 `AGENTS.md` 验收标准；输出为 `tests/**` 测试套件源码及真实的测试运行通过率、覆盖率与失败 Traceback 检验报告。
- **绝对禁止红线**：严禁修改 `src/**` 或 `firmware/**` 业务源码（彻底杜绝通过删改业务代码或弱化断言来伪造测试通过）。

### 阶段 VII：软硬件交叉编译、容器打包与实体硬件烧录部署（Build & Hardware Deployment）

为了全面支持你提出的**「包含硬件部署的 Code Multi-Agents」**需求，我们将阶段 VII 拆分为**「11 合体天（构建、交叉编译与硬件部署管线工程）」**与**「12 震天尊（物理硬件烧录上电安全闸门与熔断回滚）」**的双保险闭环：

#### 11. 合体天（Nexus Prime · Agent ID: `nexus-prime`）—— 软硬件交叉编译、容器打包与硬件部署工程师（Build & Hardware Deployer）
- **塞伯坦设定与模型**：合体金刚之祖，持合体之谜（[Enigma of Combination](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)） | 绑定模型：`deepseek/deepseek-chat`（`mode: subagent`）
- **核心专职职责**：**全系统专职的构建与软硬件部署集成官（DevOps & Embedded Build/Deploy Engineer）**：
  1. **软件容器化与 MCP 网关运维**：编写和维护 `Dockerfile*`、`docker-compose*`、`.github/workflows/**`、`opencode.jsonc` 与 `.dsh/**`，并执行飞书 MCP 网关连通性探针。
  2. **嵌入式与边缘硬件构建配置**：编写和维护 `CMakeLists.txt`、`Makefile`、`platformio.ini`、链接脚本（`*.ld`）、设备树（`*.dts`）与交叉编译配置。
  3. **交叉编译与非破坏性硬件连接探测**：运行交叉编译工具链（`cmake --build`, `make`, `pio run --without-upload`, `cargo build --target thumbv7em-none-eabihf`）生成固件二进制包（`.bin/.hex/.elf/.uf2`），核算出固件 Flash/RAM 占用率；并执行只读硬件外设探测（`lsusb`, `ls /dev/ttyUSB* /dev/ttyACM*`, `openocd -c "init; targets; exit"`, `ros2 node list`），准备就绪的硬件烧录与边缘设备部署清单。
- **标准输入与输出**：输入为通过测试的代码库与目标硬件平台参数；输出为编译生成的固件二进制产物、Flash/RAM 内存占用报告、Docker 镜像配置及就绪的硬件烧录命令单。
- **绝对禁止红线**：严禁修改 `src/**` 业务逻辑或 `tests/**` 测试用例、严禁读写飞书文档正文、严禁绕过震天尊直接执行物理硬件擦写烧录（`flash/upload`）动作。

#### 12. 震天尊（Megatronus Prime · Agent ID: `megatronus`）—— 物理硬件烧录安全闸门、高危熔断与固件回滚执法官
- **塞伯坦设定与模型**：熵与终结之力化身，持安魂曲火炮（[Requiem Blaster](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)） | 绑定模型：`deepseek/deepseek-reasoner`（`mode: subagent`）
- **核心专职职责**：**全系统唯一掌管「物理世界副作用（Physical Hardware Flash & Actuation）」与「高危破坏/回滚」的安全执法官**：
  1. **实体硬件烧录与边缘部署行刑（Hardware Flashing & Edge Rollout）**：在合体天完成交叉编译与设备探测、且谎言天尊确认无引脚短路风险后，由震天尊接管执行真正的物理烧录与远程部署命令（如 `openocd -c "program firmware.elf verify reset exit"`、`esptool.py write_flash`、`pio run -t upload`、`scp/ssh` 边缘节点服务重启、ROS2 实体机器人节点启动）。所有物理烧录与硬件控制动作在底层 100% 绑定 `effect: ask`，必须先向人类开发者展示**《硬件烧录爆炸半径评估单》（目标端口、固件大小、Flash 擦写区间、供电/外设安全检查、黄金固件回滚镜像路径）**，经人类点击确认后方可执行，并在烧录后读取串口（Serial Monitor）启动心跳日志确认硬件成功点亮。
  2. **失控死循环熔断与紧急回滚（Circuit Breaker & Rollback）**：当任何子天尊连续 3 次重复调用同一工具陷入死循环，或新固件烧录后硬件串口无心跳/触发 HardFault 时，立即熔断并执行黄金备份固件重刷或 `git reset` 回滚。
- **标准输入与输出**：输入为合体天提交的待烧录固件包与端口信息，或超限熔断工单；输出为硬件烧录爆炸半径评估单、人类授权后的烧录日志、串口启动自检回执或回滚报告。
- **绝对禁止红线**：严禁绕过 `ask` 人工确认静默擦写硬件或删除文件、严禁编写任何常规业务或测试代码。

## 4. 软硬一体全生命周期 6 组核心相邻天尊「一刀切」MECE 正交边界表

为确保在软硬一体开发、Code Review、测试检验与文档编写过程中绝不出现职责模糊，以下为 6 组核心角色的物理级正交切分判据：

| 易混淆角色组合 | 正交切分维度（Orthogonal Axis） | 前者唯一职责边界（只做什么） | 后者唯一职责边界（只做什么） |
| :--- | :--- | :--- | :--- |
| **1. 微米天 (`micronus`)<br>vs 谎言天尊 (`liege-maximo`)**<br>*(双级专职 Code Review)* | **L1 自动化语法规范与格式审查**<br>vs **L2 深度逻辑、并发与硬件安全审查** | **微米天**：跑 `ruff/clang-tidy/cppcheck` 静态工具，查编码规范、类型签名与注释缺失，可做零逻辑变动的格式修复。 | **谎言天尊**：零写入、零命令执行，纯靠深度推理审查死锁、中断阻塞、栈溢出、引脚冲突与密钥泄露，出一票否决裁决书。 |
| **2. 谎言天尊 (`liege-maximo`)<br>vs 炼金术士 (`alchemist`)**<br>*(Code Review vs 测试检验)* | **纯静态代码审讯（Static Review）**<br>vs **动态运行测试与仿真检验（Dynamic Test）** | **谎言天尊**：不写测试、不跑程序，只通过静态阅读代码做对抗性挑刺与安全审查。 | **炼金术士**：唯一可写 `tests/**` 并实际运行 `pytest/gtest/QEMU` 仿真测试的 QA 检验官，凭真实运行结果与覆盖率说话。 |
| **3. 合体天 (`nexus-prime`)<br>vs 震天尊 (`megatronus`)**<br>*(硬件编译打包 vs 物理烧录上电)* | **无副作用的交叉编译与设备探测**<br>vs **有物理副作用的真机烧录与回滚** | **合体天**：写 `CMakeLists.txt/Dockerfile`，跑交叉编译生成 `.bin/.elf` 并探测串口是否存在（不改变目标板 Flash 状态）。 | **震天尊**：唯一可执行 `openocd/esptool/upload` 擦写物理硬件 Flash、重启边缘设备及执行回滚的行刑官（强制触发 `ask` 审批）。 |
| **4. 钛师傅 (`alpha-trion`)<br>vs 全部编码/测试天尊**<br>*(专职文档与飞书知识库隔离)* | **自然语言文档与飞书 Wiki 读写**<br>vs **编程语言代码与配置文件读写** | **钛师傅**：唯一可读写飞书知识库（Feishu Wiki）及本地 `AGENTS.md`、`README.md`、`docs/**` 的专职文档官。 | **其余 12 天尊**：100% 物理阻断飞书内容 API 与 `docs/**` 写入权，一律只读钛师傅同步好的本地 `AGENTS.md` 契约。 |
| **5. 昆图斯 (`quintus`)<br>vs 赛天骄 (`solus-prime`)<br>vs 幻化天 (`amalgamous`)** | **0→1 接口与 HAL 头文件骨架**<br>vs **新增软硬件功能与驱动实现**<br>vs **保功能不变的重构与跨芯片移植** | **昆图斯**：只建目录、写依赖清单与空接口/HAL 头文件（函数体留空）。<br>**赛天骄**：填充具体业务逻辑、外设寄存器驱动与修 Bug。 | **幻化天**：外部功能语义 100% 不变，专门做代码解耦、静态内存优化或跨芯片架构（如 STM32 迁 ESP32）移植。 |
| **6. 锐天骁 (`onyx-prime`)<br>vs 维克多 (`vector-prime`)**<br>*(空间侦察 vs 时间侦察)* | **当前代码树静态空间拓扑**<br>vs **Git 历史提交与固件版本时间线** | **锐天骁**：只用 `read/glob/grep` 扫描当前代码快照的 AST 结构、设备树与调用链（禁跑任何 Git 命令）。 | **维克多**：只用 `git log/blame/diff/tag` 追溯历史提交与固件基线差异（禁用 `glob/grep` 扫全库）。 |

## 5. 塞伯坦十三天尊 v5.0 软硬一体零重叠 RBAC 权限矩阵（Action × Resource Matrix）

下表直接映射为 [OpenCode V2](https://opencode.ai/docs/agents/) 的 `permissions` 规则与 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 的 Tool Policy，确保 13 位天尊在本地文件、交叉编译终端、硬件烧录接口与飞书知识库上**100% 权限正交**：

| 编号与天尊代号 | 本地读取范围 (`read / glob / grep`) | 本地唯一可写域 (`edit` 互斥分区) | 终端与硬件工具白名单 (`shell`) | 飞书知识库权限 (`feishu_*`) | 特殊独占权 & 绑定模型 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **01. 先觉天**<br>`prima` | `ALLOW`: `AGENTS.md`, `docs/**`<br>`DENY`: `src/**`, `firmware/**` | `DENY`: `*` (零文件写入权) | `DENY`: `*` (零终端执行权) | `DENY`: `*` (委派钛师傅读写) | **唯一 `subagent: *` 派发权**<br>`deepseek-reasoner` |
| **02. 钛师傅**<br>`alpha-trion` | `ALLOW`: `*` (可读全库以撰写文档) | **唯一 `ALLOW`: `AGENTS.md`, `README.md`, `CHANGELOG.md`, `docs/**`** | `DENY`: `*` (纯文档与知识治理) | **唯一 `ALLOW`: `feishu_wiki_*`, `feishu_docx_*` 读写** | 专职文档与飞书总管<br>`deepseek-chat` |
| **03. 锐天骁**<br>`onyx-prime` | **唯一全库静态侦察 `ALLOW`: `read/glob/grep *`** | `DENY`: `*` (纯只读侦察) | `DENY`: `*` (禁跑 Git 与任何脚本) | `DENY`: `*` | 静态空间与 BSP 侦察<br>`deepseek-chat` |
| **04. 维克多**<br>`vector-prime` | `DENY`: `glob/grep` (禁做静态全库扫描) | `DENY`: `*` (纯只读考古) | **唯一 `ALLOW`: `git log/blame/diff/show/tag/status*`** | `DENY`: `*` | Git 与固件基线考古<br>`deepseek-chat` |
| **05. 昆图斯**<br>`quintus-prime` | `ALLOW`: `AGENTS.md`, 配置文件 | **唯一 `ALLOW`: `pyproject.toml`, `package.json`, `Cargo.toml`, `**/interfaces.py`, `**/schemas.py`, `**/hal_*.h`** | `ALLOW`: 仅 `mkdir -p *` | `DENY`: `*` | 软硬件架构与骨架孵化<br>`deepseek-chat` |
| **06. 赛天骄**<br>`solus-prime` | `ALLOW`: `*` | **唯一业务与固件实现 `ALLOW`: `src/**`, `app/**`, `firmware/**`, `drivers/**`, `bsp/**`** (禁改 `tests/**` 与接口头文件) | `DENY`: `*` (编译归合体天，测试归炼金术士) | `DENY`: `*` | 核心软件与嵌入式编码<br>`deepseek-coder` |
| **07. 幻化天**<br>`amalgamous` | `ALLOW`: `*` | **唯一重构与移植 `ALLOW`: `src/**`, `lib/**`, `firmware/**`** (严格保外部语义不变) | `DENY`: `*` | `DENY`: `*` | AST 重构与跨芯片移植<br>`deepseek-coder` |
| **08. 微米天**<br>`micronus-prime` | `ALLOW`: `src/**`, `firmware/**` | `ALLOW`: `src/**`, `firmware/**` (仅限格式化与补全类型/注释，零逻辑改动) | **唯一 L1 静态检查 `ALLOW`: `ruff *`, `black *`, `mypy *`, `clang-tidy *`, `cppcheck *`, `cargo clippy*`** | `DENY`: `*` | L1 规范与静态分析审查<br>`deepseek-chat` |
| **09. 炼金术士**<br>`alchemist` | `ALLOW`: `AGENTS.md`, `src/**`, `firmware/**`, `tests/**` | **唯一测试写入权 `ALLOW`: `tests/**`** (对业务与固件代码严格 `DENY`) | **唯一测试与仿真执行 `ALLOW`: `pytest*`, `ctest*`, `cargo test*`, `qemu-system-*`, `renode*`** | `DENY`: `*` | 专职测试与 SIL 仿真检验<br>`deepseek-coder` |
| **10. 谎言天尊**<br>`liege-maximo` | `ALLOW`: `read / grep *` | `DENY`: `*` (零写入权，防利益冲突) | `DENY`: `*` (零执行权，纯静态深度审讯) | `DENY`: `*` | L2 深度逻辑与安全 Review<br>`deepseek-reasoner` |
| **11. 合体天**<br>`nexus-prime` | `ALLOW`: 构建、容器与硬件配置文件 | **唯一构建与部署配置 `ALLOW`: `Dockerfile*`, `docker-compose*`, `.github/**`, `CMakeLists.txt`, `Makefile`, `platformio.ini`, `*.ld`, `*.dts`, `opencode.jsonc`, `.dsh/**`** | **唯一交叉编译与硬件探测 `ALLOW`: `cmake *`, `make *`, `arm-none-eabi-*`, `pio run --without-upload*`, `lsusb*`, `ls /dev/tty*`, `docker build*`** | `ALLOW`: 仅 `feishu_mcp_healthcheck*` 网关探针 | 交叉编译、容器与硬件部署管线<br>`deepseek-chat` |
| **12. 震天尊**<br>`megatronus` | `ALLOW`: `read *` | `DENY`: `*` | **唯一物理硬件烧录与高危回滚 `ASK` (强制弹窗确认): `openocd *`, `esptool*`, `pio run -t upload*`, `st-flash*`, `ssh/scp *`, `rm *`, `git reset/push*`** | **唯一 `ASK`: `feishu_wiki_delete*` 节点删除审批** | 物理硬件烧录闸门与熔断行刑官<br>`deepseek-reasoner` |
| **13. 第十三天尊**<br>`thirteenth` | `ALLOW`: `AGENTS.md`, `README.md`, `docs/**` | `DENY`: `*` | `DENY`: `*` | `DENY`: `*` | **唯一 `webfetch: *` 端到端预览与人机交付**<br>`deepseek-chat` |

## 6. 飞书知识库（Feishu Wiki）双阶段治理与软硬件文档闭环

在 v5.0 架构中，飞书知识库不仅存储软件文档，还完整承载**硬件引脚分配表（Pinout）、外设通信协议帧定义、交叉编译环境手册与烧录验收记录**，并由 **02 钛师傅（`alpha-trion`）** 作为唯一读写漏斗统一治理：

1. **阶段 A：多智能体自身开发期知识库（Build-Time Wiki）**
   - `/01-塞伯坦架构ADR`：记录 13 天尊职责边界变更、状态机流转协议与 PicoAgents 组件选型。
   - `/02-软硬件工具链与MCP规范`：记录 OpenCode V2、DeepSeek Harness Cordis 插件、交叉编译工具链及飞书 MCP 网关配置。
   - `/03-Code-Review与红队基线`：沉淀微米天（L1 静态规则）与谎言天尊（L2 嵌入式中断/内存/安全审查清单）的评审标准。
2. **阶段 B：目标项目运行期知识库（Run-Time Wiki）**
   - `/10-产品需求PRD与软硬件指标`：存储业务功能需求、目标 MCU/边缘计算板型号、传感器型号及实时性指标。
   - `/20-硬件原理图引脚与通信协议字典`：存储 GPIO 引脚映射、UART/CAN/Modbus 报文协议格式与寄存器表（编码前由钛师傅拉取并同步到本地 `AGENTS.md`）。
   - `/30-测试检验与硬件烧录台账`：存储炼金术士的测试覆盖率报告、合体天的固件 Flash/RAM 占用率报告以及震天尊每次实体硬件烧录的版本号与串口心跳回执。
3. **双宿主 Token 鉴权与自动续期机制**
   - **OpenCode V2 接入**：在 `opencode.jsonc` 的 `mcp.servers.feishu_wiki` 中通过 `@larksuiteoapi/lark-mcp` 挂载，使用 `{env:FEISHU_APP_ID}` 与 `{env:FEISHU_APP_SECRET}` 注入环境变量。
   - **DeepSeek Harness (dsh) 接入**：在 `.dsh/cordis-cybertron-plugin.mjs` 中内置 `FeishuTokenVault`，自动请求 `POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal` 获取 [7200 秒有效期的 `tenant_access_token`](https://open.feishu.cn/document/server-docs/api-call-guide/calling-process/get-access-token?lang=zh-CN)，并在到期前 300 秒自动静默刷新；同时在插件代码层锁死 `caller_prime_id === 'alpha-trion'` 方可读写文档正文。

## 7. 软硬一体全生命周期（SDLC）13 天尊标准接力工作流

当一个包含「软件后端 + 嵌入式固件开发 + 真实硬件烧录部署」的研发任务进入系统时，13 位天尊严格按照以下 9 步单向状态机闭环运转：

```
[用户发起软硬件开发/部署需求]
   │
   ├─► Step 1 [需求澄清]: 13.第十三天尊 (thirteenth)
   │     └──► 核查目标芯片型号(如STM32/ESP32/Jetson)、外设引脚与业务指标是否清晰；若有缺失向用户发澄清问卷
   ▼
01.先觉天 (prima) ──► 初始化 CybertronTaskLedger 全生命周期状态账本
   │
   ├─► Step 2 [飞书知识拉取与文档立项]: 02.钛师傅 (alpha-trion)
   │     └──► 从飞书 Wiki 拉取 PRD、硬件引脚表与通信协议 ──► 撰写/更新本地 AGENTS.md 与 docs/spec/
   │
   ├─► Step 3 [时空双维侦察与架构骨架]:
   │     ├──► 03.锐天骁 (onyx-prime)   ──► 扫描当前代码树 AST、设备树与驱动调用链 (输出 file:line 坐标)
   │     ├──► 04.维克多 (vector-prime) ──► 追溯 Git 提交历史与上一版稳定固件 Tag 基线
   │     └──► 05.昆图斯 (quintus-prime)──► 创建目录树、依赖清单及接口/HAL头文件空骨架 (interfaces.py / hal_*.h)
   │
   ├─► Step 4 [软硬件编码与平台移植]:
   │     ├──► 06.赛天骄 (solus-prime)  ──► 编写业务源码 (src/**) 与嵌入式外设驱动/固件逻辑 (firmware/**, drivers/**)
   │     └──► 07.幻化天 (amalgamous)   ──► (按需) 执行 AST 结构解耦、静态内存优化或跨芯片平台移植
   │
   ├─► Step 5 [双级专职 Code Review 门禁]:
   │     ├──► 08.微米天 (micronus-prime) ──► [L1 规范审查] 运行 ruff/clang-tidy/cppcheck，补全类型签名与注释
   │     └──► 10.谎言天尊 (liege-maximo) ──► [L2 深度审查] 静态审讯死锁、中断阻塞、栈溢出、引脚冲突与密钥泄露
   │           └──► (若任一 Review 给出 REJECT) ──► 先觉天将缺陷行号打回 06.赛天骄修复，禁止进入测试与编译！
   │
   ├─► Step 6 [专职自动化测试与仿真检验]: 09.炼金术士 (alchemist)
   │     └──► 在 tests/** 编写单元测试与 QEMU/Renode 硬件仿真脚本并执行 ──► 验证通过率与覆盖率
   │
   ├─► Step 7 [交叉编译、容器打包与硬件探测]: 11.合体天 (nexus-prime)
   │     └──► 维护 CMake/Dockerfile，执行交叉编译生成固件 (.bin/.elf)，核算 Flash/RAM 占用并探测 /dev/ttyUSB* 端口
   │
   ├─► Step 8 [物理硬件烧录审批与上电验证]: 12.震天尊 (megatronus)
   │     └──► 生成《硬件烧录爆炸半径评估单》──► 触发 ask 弹窗由人类确认 ──► 执行 openocd/esptool 烧录并读取串口心跳日志
   │           └──► (若烧录后串口无心跳或报错) ──► 震天尊立即自动重刷黄金备份固件回滚，并上报先觉天！
   │
   └─► Step 9 [专职文档撰写、飞书归档与最终交付]:
         ├──► 02.钛师傅 (alpha-trion) ──► 更新 README.md / 硬件部署手册，并将本次 ADR 与烧录台账回写至飞书知识库
         └─► 13.第十三天尊 (thirteenth) ──► webfetch 端到端预览 + 向用户输出含飞书 Wiki 链接的完整交付报告
```

## 8. 代码优先（Code-First）快速启动命令与参考来源

当前 `cybertron_primes_engine.py` 是兼容命令入口，核心代码位于 `cybertron/`。它已将 13 位天尊的静态职责和权限、9 步计划及配置导出编码落地；动态派单、真实审查与测试门禁、飞书 Wiki 内容操作、DeepSeek Harness 插件和实体硬件审批执行仍待实现。在终端运行以下命令可完成本地自检并导出静态配置：

```bash
# 1. 导出飞书开放平台应用凭证与目标知识空间 ID
export FEISHU_APP_ID="cli_a6xxxxxxxxxxxx"
export FEISHU_APP_SECRET="xxxxxxxxxxxxxxxxxxxxxxxx"
export FEISHU_WIKI_SPACE_ID="735xxxxxxxxxxxxxxxx"

# 2. 运行塞伯坦 v5.0 引擎自检（验证 7 大 SDLC 阶段、双级 Code Review、软硬件部署权限隔离并生成双端配置）
python3 cybertron_primes_engine.py

# 3. 检查生成的配置，确认目标宿主兼容后再同步至项目根目录
cp -r cybertron_workspace_dist/.opencode cybertron_workspace_dist/opencode.jsonc cybertron_workspace_dist/.dsh ./
```

### 参考架构与技术规范来源（Verified References）
- **Designing Multi-Agent Systems & PicoAgents Framework (Victor Dibia)**：[https://github.com/victordibia/designing-multiagent-systems](https://github.com/victordibia/designing-multiagent-systems) 及 [compaction.py 源码](https://github.com/victordibia/designing-multiagent-systems/blob/main/picoagents/src/picoagents/compaction.py)
- **OpenCode V2 智能体定义、权限与 MCP Servers 规范**：[https://opencode.ai/docs/agents/](https://opencode.ai/docs/agents/) 与 [https://opencode.ai/docs/mcp-servers/](https://opencode.ai/docs/mcp-servers/)
- **DeepSeek Harness (dsh) 开源仓库与 Cordis 插件机制**：[https://github.com/deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 与 [DeepSeek Harness Explained](https://www.datacamp.com/blog/what-is-deepseek-harness)
- **飞书开放平台知识库 API 与官方 OpenAPI MCP**：[飞书知识库 API 概述](https://open.feishu.cn/document/server-docs/docs/wiki-v2/wiki-overview?lang=zh-CN)、[飞书访问凭证规范](https://open.feishu.cn/document/server-docs/api-call-guide/calling-process/get-access-token?lang=zh-CN) 与 [larksuite/lark-openapi-mcp](https://github.com/larksuite/lark-openapi-mcp)
- **塞伯坦十三天尊（The Thirteen Primes）正典设定**：[Teletraan I: Thirteen Primes Wiki](https://transformers.fandom.com/wiki/Thirteen) 与 [All 13 Prime Transformers Domains & Artifacts Guide](https://eva.ulanzi.com/summary/article/all-13-prime-transformers-order-complete-w72aol)
