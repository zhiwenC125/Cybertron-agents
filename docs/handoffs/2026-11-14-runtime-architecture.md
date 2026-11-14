# Cybertron 后续开发 Handoff：从配置包到可恢复的多智能体编排

日期：2026-11-14

状态：规划文件；以下阶段除已注明的现状外均**尚未实现或验收**。

适用范围：Cybertron 核心运行态、OpenCode V2 接入、安装发布、后续 DeepSeek Harness 接入与硬件交付。
协作基线：以仓库根目录 [`AGENTS.md`](../../AGENTS.md) 为准；七阶段既有验收状态以 [`DEVELOPMENT_PLAN.md`](../../DEVELOPMENT_PLAN.md) 和 [`docs/stages/`](../stages/) 为准。

## 1. 对前两轮讨论的裁定

**核心判断正确，但不能把整个系统称为“只有静态配置”。** 当前架构更准确地描述为：**静态配置生成与分发 + 内存中的九步编排器 + 宿主提供的单角色模型/工具循环；Cybertron 自身尚无可恢复、可审计的运行态存储。**

| 讨论中的说法 | 裁定 | 当前代码证据与修正 |
| --- | --- | --- |
| 角色、权限和宿主配置已落盘 | 正确 | `cybertron/registry.py` 是权限事实源；`cybertron/exporters.py` 生成 `opencode.jsonc` 与 `.opencode/agents/*.md`。安装包分发这些文件。 |
| 多智能体账本只在内存里 | 对 **CybertronTaskLedger** 正确 | `cybertron/ledger.py` 维护状态，`cybertron/dispatch.py` 推进状态；没有运行态 `save/load`、事件日志或恢复入口。阶段验收 JSON 与宿主会话文件并非这个账本的持久化。 |
| “静态配置编译型，而不是运行时环境型” | 需要修正 | Cybertron 已有运行时派单逻辑，只是未持久化；OpenCode 承担角色内部的模型和工具循环。因此二者不是互斥分类。 |
| 已有完整九步 OpenCode 自动接力 | 错误 | `cybertron/opencode_run.py` 只执行第 1 步；`cybertron/opencode_executor.py` 仅允许选定只读角色；`.opencode/commands/cybertron.md` 是提示词入口，未把宿主对话自动接到 Python 账本。离线模拟的九步状态机不等于真实宿主接力。 |
| DSH session 文件意味着 Cybertron 可恢复 | 错误 | 附件中的 `~/.dsh/sessions/.../session.v4.jsonl.zstd` 属于 DSH 宿主会话；当前 Cybertron 只导出 DSH preset JSON，没有已接入的 DSH 插件或 Cybertron run 映射。 |
| session 包含多个 run，run 是一次任务审计单位 | 作为目标设计正确 | `run_id` 不等于进程 ID。一次 run 可以跨进程恢复；一次 session 可以包含多次 run。当前代码尚没有这两层对象。 |
| slug 用于人类寻址，ID 用于内部关联 | 作为目标设计正确 | 用户可以主要看到 slug；`session_id`、`run_id` 必须不可变。仅凭 slug 不能安全关联审批和证据。 |
| 账本落盘后自然拥有 Harness loop | 错误 | 持久化解决恢复和审计；模型调用、工具调度、权限/审批、流式事件仍由宿主或未来的独立 AgentLoop 承担。 |

附件是历史讨论记录，不能当作当前仓库快照。其中“`installer.py` / `pyproject.toml` 未提交”“`.gitignore` 没有构建条目”已过时；这些文件现在已提交。文中关于根目录导出物缺少防漂移测试、DSH 只有 preset、安装入口可能出现行为差异的提醒仍值得处理。任何新增事实应重新以代码和测试验证。

## 2. 已有基线与不能混淆的范围

- 原七阶段的**最小闭环基线**已达到；第 7 阶段完整目标仍在进行中。STM32F103C8T6 最小测试 App 经单次人工批准完成烧录、读回、SRAM 心跳和原 App 恢复；这不代表完整 OTA App 或 ESP32-S3 已验收。详见 [`07-deployment.md`](../stages/07-deployment.md)。
- npm、pipx、GitHub Shell 三条安装路径已发布；`curl | sh` 路径仍可保留，但必须保持可审阅、固定版本和校验能力。安装资产是 13 个角色与 `/cybertron` 命令，不等于安装完整 Python 运行时。
- 飞书自建应用走 `tenant_access_token`；只有指定测试空间和 `alpha-trion` 网关能读写 Wiki。App ID/Secret 仅取自本机环境变量。自建应用须在知识空间成员设置获得管理员权限，相关闭环见 [`06-feishu.md`](../stages/06-feishu.md)。
- 本地 `policy.py` 是自检，不是 OpenCode 工具调用的拦截器；真实权限须以宿主判定为准。
- 用户此前决定不授权向外部模型发送项目文件。后续开发和验收默认使用离线测试、假宿主和脱敏回执；不要把真实 L2 外部模型探针当作必跑门禁。
- **七个开发阶段**、账本中的**九个 SDLC 步骤**、本文件的**后续实施阶段**是三套不同的编号，不相互替代。

本次交接的本机基线复核：`python3 -m unittest discover -s tests -q` 为 **58 tests / OK**；`python3 cybertron_primes_engine.py` 自检通过；`python3 -m cybertron.stage5_verify` **失败**。后者的隔离检查正确阻止项目目录写入，但 `tests/test_installer.py:setUp()` 仍用 `tempfile.mkdtemp(dir=ROOT)` 在项目根目录建测试目录，导致 4 个安装器测试在沙箱内 `PermissionError`，QA 账本阻塞。它是目前真实存在的回归门禁，不应被旧的阶段 5 验收记录覆盖。修复时将测试临时目录放到隔离运行器允许的 scratch 目录，并确认子进程可访问该路径；再重跑三个基线命令。

## 3. 目标边界与数据模型

目标是 **Cybertron 管跨宿主的任务状态和证据；OpenCode / DSH 管各自的模型与工具循环**。先实现宿主适配器，不在本轮重写 LLM 客户端或自研完整 Harness loop。

```text
Cybertron Session（持续上下文；session_id 不变，slug 可显示/改名）
  └─ Run（一次任务闭环；run_id 不变，可跨进程）
       └─ Stage（现有九步 SDLC 中的 1..9；当前代码名 LedgerStep）
            └─ Dispatch / Turn（某角色的一次派单）
                 └─ Attempt（一次调用或重试；记录宿主关联和结果）

HostSession（OpenCode / DSH 自己的会话）通过 host + host_session_id
关联 Dispatch / Turn；不能直接充当 Cybertron session_id。
```

建议以项目级 `.cybertron/` 作为本地默认存储，并加入 `.gitignore`；敏感输入、模型原始对话、固件备份和凭证不进入 Git 或安装包。可通过配置选择其他存储根，但所有路径均需限制在明确允许的目录内。

```text
.cybertron/
└── sessions/
    └── <稳定的 session_id>/
        ├── session.json             # schema、ID、slug、title、workspace
        └── runs/
            └── <run_id>/
                ├── run.json         # 任务、状态、配置/代码版本、宿主映射
                ├── events.jsonl     # Cybertron 域事件；权威状态来源
                ├── ledger.json      # 可重建的快照，含 snapshot_seq
                ├── evidence/        # 脱敏回执和内容哈希/外部引用
                └── approvals/       # 绑定具体操作的审批回执
```

目录建议先用稳定 ID，CLI/UI 对外主要使用 slug；这样改名只改元数据与索引，不必原子移动整棵运行目录。若以后选 `<slug>--<短 ID>`，短 ID **不是数学上的唯一保证**，仍需冲突检查和完整 ID。`title` 是可自由修改的展示名，`slug` 是受约束的寻址名，二者不要混用。

事件只记录 Cybertron 需要的事实，如 `run.created`、`stage.started`、`dispatch.started`、`dispatch.completed`、`review.rejected`、`approval.granted`、`run.blocked`；宿主完整对话只保存引用，不复制整份 transcript。每条事件至少含 `schema_version`、`event_id`、`seq`、UTC 时间、`session_id`、`run_id`、关联阶段/派单 ID、来源和必要载荷。快照仅是事件投影；事件写入成功而快照未完成时，恢复必须仍能重放。首次实现不强制哈希链或内容寻址大文件，但 schema 中要预留版本、摘要和外部引用字段。

## 4. 实施阶段与验收门槛

按顺序交付，每阶段单独提交、测试和记录结果。以下 CLI 名称是**拟实现接口**，不是当前可运行命令。

### 阶段 A：锁定配置与安装发布基线

**目标**：每个发布版本安装同一份、可核验的角色配置；修改注册表后不会把旧权限留在根目录或包里。

**实施**：

1. 加入对仓库根目录 `opencode.jsonc`、`.opencode/agents/*.md` 与当前 `registry.py` 重新导出结果的逐文件一致性检查；保留 Markdown/JSON 权限相互核验。
2. 先修复上述安装器测试的隔离路径，并让阶段 5 验收重新通过；测试不得为获得通过而放宽沙箱对项目写入、设备读取或网络的阻断。
3. 构建 npm/pipx/Shell 三路安装矩阵：干净临时项目中的 dry-run、apply、重复安装、升级、备份、doctor、失败回滚；检查 13 角色和命令。
4. 修复版本一致性：pipx 的版本号不能默认取得 GitHub `main` 的 payload；Shell 默认 `main` 与可选 SHA-256 的行为须在发布路径上改为固定 tag/不可变摘要，或明确要求用户显式选择浮动开发版。
5. 明确已有 JSONC 配置、注释和未知字段的保留语义；拒绝无法安全合并的文件，避免静默改写；统一 `.bak` 策略，避免升级时覆盖唯一回滚副本。
6. 加 CI 检查单元测试、导出漂移、打包内容和安装矩阵；发布文档写明版本、哈希、兼容范围。

**验收**：阶段 5 隔离验收重新通过，且原有沙箱阻断仍有效；三条安装路径对同一版本生成相同角色/命令内容；根目录漂移使 CI 失败；临时项目内无凭证泄漏；失败不留下半安装状态。此阶段不调用外部模型或硬件。

### 阶段 B：实现离线 RunStore 与可恢复账本

**目标**：进程退出后，单个 run 的九步状态、返工次数和证据引用能够完整恢复。

**实施**：

1. 引入 `session_id`、`run_id`、`dispatch_id`、`attempt_id`，提供版本化序列化；先保持现有 `LedgerStep` Python API，磁盘 schema 可用 `stage_id`，避免一次性大重构。
2. 将状态转换封装在存储服务中：先提交事件，再生成/替换快照；采用原子快照写入、单写者锁和连续序号，拒绝未知必需 schema。
3. 增加 `cybertron run create/show/verify/resume` 的离线入口；`resume` 先重建账本，绝不直接重放上次未确认的副作用。
4. 用假执行器测试事件已写而快照未写、截断尾部、重复事件、并发恢复、旧 schema、配置版本变化；定义每种情况是修复、只读还是阻塞。

**验收**：测试进程重启后恢复的阶段、参与者、返工次数与事件完全一致；损坏或未知事件不能悄悄跳过；同一 run 不能被两个写进程同时推进；旧测试继续通过。

### 阶段 C：加入 session / slug 管理与审计查询

**目标**：用户通过可读名称找回任务，系统仍以不可变 ID 追踪多次 run。

**实施**：

1. 增加 `session create/list/show/rename` 与 `run list --session <slug>`；建立 slug → `session_id` 的索引或 alias。
2. slug 规范化、唯一性、保留字、路径穿越和符号链接检查；改名保留旧 slug alias，内部事件与 run 永远引用 ID。
3. 定义归档、导出、保留期与本地删除策略；默认不自动上传会话、证据或固件镜像。

**验收**：同一 session 可含多个 run；改名后旧入口仍能解析且审计关联不变；冲突、大小写差异、非法路径输入均有明确结果。

### 阶段 D：证据来源、审批和副作用围栏

**目标**：模型陈述、工具回执、人工批准分别可识别；崩溃恢复不会重复写入或烧录。

**实施**：

1. 扩展 `QualityEvidence` 或增加兼容的新证据对象：`source_type`（model/tool/sandbox/host/human）、命令/工具、退出码、时间、输出/产物 SHA-256、验证者与脱敏引用。现有字符串证据迁移为“来源未验证”，不能冒充工具 PASS。
2. 给每次派单和副作用分配幂等键；记录“计划 → 宿主批准 → 执行 → 回执”的状态。调用已发出但回执缺失时标为 **outcome_unknown**，先查询宿主或核对设备/文件，再由人工决定，不自动重试。
3. 硬件审批对象绑定目标设备、固件摘要、擦写范围、回滚镜像、计划摘要和一次有效范围；审批改变任一绑定条件即失效。飞书写入同样需要目标空间和操作范围约束。
4. 为 `docs/stages/` 的公开验收摘要建立可选 manifest，记录提交、命令、回执摘要和本地原件引用。公开摘要只能证明已记录的结论与哈希；没有原始字节时不能声称第三方能完整复验。

**验收**：仅有模型文字时 L1/L2/测试门禁不能当成真实工具通过；回执来源可追溯；同一审批不能用于不同设备或固件；在写操作前后注入崩溃均不会自动重复副作用。

### 阶段 E：接入 OpenCode 的真实九步外层编排

**目标**：Cybertron 在 OpenCode 宿主之上按九步派单、持久化结果、在权限或证据不足时停止；宿主继续负责角色内部 Harness loop。

**实施**：

1. 定义宿主适配器事件协议：派单、`host_session_id` / turn ID、工具结果、权限请求、取消、超时和最终结构化结果；保留当前同步 `AgentExecutor` 作为兼容适配层。
2. 先用假宿主完成九步、拒绝返工和恢复测试，再逐个开放真实只读角色；随后接入隔离运行器与可验证的 QA 回执。不得因 Python `policy.py` 返回允许就绕过 OpenCode V2 权限。
3. 让 `/cybertron` 与 Python 编排器有真实、可测试的连接；若仍仅是提示词入口，界面和文档必须明确标示。
4. 写角色只在目标路径、宿主权限与审计回执可核验后启用。保持“不向外部模型发送项目文件”的既有用户边界，不能以本阶段验收为由运行真实 L2 项目文件探针。

**验收**：假宿主端到端九步与拒绝返工通过；真实宿主仅在用户允许的只读范围内验收；中断恢复能关联原 run 和宿主会话；没有质量证据、宿主拒绝或审批缺失时账本阻塞。

### 阶段 F：DeepSeek Harness 适配与双宿主一致性

**目标**：在不复制角色权限事实源的前提下，让 DSH 成为可用的第二个宿主。

**实施**：先核对目标 DSH 版本的插件 API 和会话事件契约；从 `registry.py` 生成实际可加载的插件/预设；映射 DSH 会话 ID、事件序号和审批/工具回执到 Cybertron run。用同一组离线契约测试覆盖 OpenCode 与 DSH；宿主差异在适配器内显式表达。不要直接编辑或依赖 DSH 私有 `session.v4.jsonl.zstd` 文件格式作为 Cybertron 存储接口。

**验收**：DSH 插件真实加载；相同角色权限与状态事件可验证；任一宿主中断后能定位对应 run；两宿主均无法绕过 Cybertron 的证据与审批门禁。此阶段未完成前，对外称“DSH preset 草案”，不要称“双宿主完整运行”。

### 阶段 G：完整硬件交付（独立审批轨道）

**目标**：在前述存储、审批和证据机制上，完成完整 OTA App 与 ESP32-S3 的真机验收。

**实施**：先确认 STM32 外部 W25Q32 数据处置/备份、可观察的 App 心跳及恢复镜像；再分别准备 STM32 完整 OTA 和 ESP32-S3-N16R8 的设备清单、固件哈希、分区/擦写范围、构建回执、回滚步骤与评估单。每次真实烧录、设备上电或远程部署都需针对**该次具体操作**重新取得人工批准。树莓派 5 暂不列入当前验收范围。

**验收**：每块设备分别具有构建、审批、写入、读回/心跳和回滚的结构化真实回执；任何缺失都只可报告为未验收，不能用既有最小 App 回执替代。

## 5. 阶段依赖与建议下一步

```text
A 配置/发布基线 ──┐
                 ├─→ B RunStore → C session/slug → D 证据/审批 → E OpenCode 接力
现有离线编排 ──────┘                                       ├─→ F DSH 适配
                                                        └─→ G 硬件完整闭环
```

**下一次开发建议只启动阶段 A**：它有清晰、低风险的验收范围，也能保护同事和其他电脑的安装体验。阶段 A 完成后再开始阶段 B；若优先级转向长任务恢复，可先完成 A 中的根目录防漂移检查和版本固定，再推进 B。每阶段结束时更新 `DEVELOPMENT_PLAN.md` 与相应 `docs/stages/` 记录，不提前把计划标为已完成。

### 交接给下一位开发者的起步清单

1. 读 `AGENTS.md`、本文件、`DEVELOPMENT_PLAN.md`，确认当前分支和工作树；不要把历史附件中的仓库列表当作最新事实。
2. 跑现有基线：`python3 -m unittest discover -s tests -v`、`python3 -m cybertron.stage5_verify`、`python3 cybertron_primes_engine.py`。这些命令可能生成文件，按项目隔离边界运行；不要运行真实模型探针。
3. 阶段 A 先写一个“从 registry 临时导出并与根目录逐文件比较”的测试，再处理三入口的版本固定与安装矩阵。配置权限变更必须重新导出、审查并由开发者核对 `opencode2 debug config`。
4. 每个改动保留明确的失败/回滚路径和结构化验收回执；涉及真机、飞书写入或外部模型发送项目文件时，分别遵守已有用户边界与专项授权。

## 6. 本 Handoff 的非目标

- 不宣称已经实现持久化、完整九步真实接力、DSH 插件或完整 OTA。
- 不把 DSH/OpenCode 宿主会话文件直接当作 Cybertron 账本，或把模型生成的文字当作工具运行回执。
- 不在本次文档提交中烧录设备、改写飞书知识库、部署服务或调用外部模型处理项目文件。
