# Cybertron v6：账本治理的动态任务图多智能体架构方案

> 日期：2026-11-15 范围：本地项目 `forge` 与 `Cybertron-agents` 的架构对比、Cybertron 被压成 pipeline 的成因、简单任务失败诊断，以及 v6 动态多智能体架构与迁移路线。 依据：两个仓库的源码、`opencode2 debug agents` 实际生效权限、沙箱复现结果。
>
> 本文是 v6 设计提案，描述目标架构；已交付阶段与历史验收状态见根目录 [`DEVELOPMENT_PLAN.md`](../DEVELOPMENT_PLAN.md)。

## 一、结论摘要

1. 两个项目的根本差别在于对"计划"的定位。forge 的计划是运行时产物，由 `forge-architect` 现场生成 `PLAN.md`；Cybertron 的计划是代码常量，9 个 `LedgerStep` 写死在构造函数里，编排器只能推进"当前未完成的那一步"。
2. Cybertron 的动态性丢失，起点是"把计划当成 schema"。之后的权限、存储、宿主插件、验收标准都在这个前提上层层固化。
3. 现状下 Cybertron 无法完成简单任务。根目录写一个 md 文件，全系统没有角色有写权限；即使写到 `docs/`，也会在第 6 步因为 "Ran 0 tests" 被阻塞。
4. v6 的方向是 **LLM 提议计划变更，代码裁决合法性**：保留 forge 式的编排判断力，保留 Cybertron 的事件溯源和证据内核，两者之间只通过带类型的接口通信。

## 二、forge 与 Cybertron 的差异

| 维度     | forge                                                        | Cybertron-agents（现状）                                     |
| -------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 编排主体 | LLM（`forge-orchestrator`，没有文件工具，只有 `task` 和 `forge_state`） | 确定性 Python（`RunCoordinator` + `PrimaDispatcher`）        |
| 计划来源 | 运行时由 architect 生成 `PLAN.md`，unit 数量可变             | `create_full_sdlc_hardware_ledger()` 里写死 9 步             |
| 路由     | 7 类意图路由，`forge-factory` 兜底                           | 只有 `next_step()` 一种动作                                  |
| 角色定义 | 按职责                                                       | 按 SDLC 阶段一对一绑定（`registry.py` 的 `sdlc_stage`）      |
| 状态     | PLAN.md（人读，LLM 写回）+ STATE.json（纯 Python 工具写，状态值由编排者给出） | `events.jsonl` + 快照，审计更强，但 schema 锁死 9 步         |
| 门禁     | S1–S5、U1–U5，质量深度可按变更范围调整，有 N/A 条件          | 强类型证据、硬件审批、`outcome_unknown` 不自动重试           |
| 返工     | 失败路由表 + `back_to_architect` 重规划                      | 只有一条硬编码：L2 拒绝后回退第 4、5 步                      |
| 派单     | 宿主原生 `task` 工具派 subagent                              | 插件删掉 subagent 工具，Python 为每个角色起一次 `opencode2 run` 子进程 |

forge 也有自己的短板：

- 状态双轨：STATE.json 由编排者调用确定性的 `forge_state` 写入，但状态值由编排者给出，`write` 只校验步骤名、不校验状态值；PLAN.md 的 Pipeline 节由 LLM（forge-knowledge Scene 0）写回。
- quality、review 的 PASS 来自模型摘要，没有工具回执。
- 实现完成之后，deploy → quality → review → oracle → verification → knowledge 仍是一条固定管道。
- `forge-factory` 只输出临时 agent 的规格，OpenCode 不能在运行时注册新 agent，所以规格实际无法执行。

## 三、Cybertron 为什么被压成了 pipeline

### 3.1 代码证据

| 位置                                             | 内容                                                         | 影响                         |
| ------------------------------------------------ | ------------------------------------------------------------ | ---------------------------- |
| `cybertron/ledger.py:152`                        | `create_full_sdlc_hardware_ledger()` 直接返回 9 个 `LedgerStep` | 计划是常量                   |
| `cybertron/ledger.py:221`                        | `create_software_ledger()` 通过改写 9 步的目标文案得到软件计划 | 用任务去适配管线，步数不变   |
| `cybertron/ledger.py:52`                         | `next_step()` 取第一个未完成步                               | 只能线性推进                 |
| `cybertron/ledger.py:117` / `:128`               | 写死 `step_id != 5`、`self.plan[3]`                          | 返工路径硬编码               |
| `cybertron/runstore.py:64`                       | `if len(steps) != 9: raise RunCorrupt(...)`                  | 存储层锁死 9 步              |
| `cybertron/hosts.py:18` / `:90`                  | 权限按 `(step_id, agent_id)` 判断                            | 角色权限焊死在阶段号上       |
| `.opencode/plugins/cybertron.js:126`             | `delete event.tools.subagent`                                | prima 失去派单能力           |
| `cybertron/orchestrator.py:173`                  | `run_until_blocked()` 一次循环最多 40 轮                     | 编排者退化为触发器           |
| `design/cybertron_13_primes_architecture.md:308` | "动态派单…仍待实现"                                          | 白皮书自己承认动态部分未实现 |

### 3.2 成因链

```undefined
角色 = 阶段（设计）
  → 计划只能写死（实现）
    → 状态机只能线性（治理）
      → 宿主删掉派单工具（运行）
        → 验收只测九步（工程）
          → 编排者变成触发器，系统成为 pipeline
```

每一步单独看都有道理。可恢复、可审计的诉求天然偏好可预测的状态转移，于是 `next_step()` 成了最省事的实现。问题在于这个取舍被固化成了数据契约（`len(steps) != 9`），并且阶段 E 的验收只覆盖"九步能跑通"，没有一条验收要求"不同需求产出不同的计划"。

## 四、现状诊断：简单任务无法完成

### 4.1 两个硬阻断

**阻断 1：****根目录****的** **md** **文件无人可写。** 根据 `opencode2 debug agents` 解析出的实际生效权限：

| 角色                          | 可写路径                                              |
| ----------------------------- | ----------------------------------------------------- |
| solus-prime                   | `src/**` `app/**` `firmware/**` `drivers/**` `bsp/**` |
| alpha-trion                   | `AGENTS.md` `README.md` `CHANGELOG.md` `docs/**`      |
| quintus-prime                 | 脚手架文件（`pyproject.toml` 等）                     |
| alchemist                     | `tests/**`                                            |
| micronus-prime / liege-maximo | 无写权限                                              |
| prima                         | 无写权限，subagent 工具被插件删除                     |

**阻断 2：零****测试****被判为失败。** 在没有测试的临时项目里直接运行 `AlchemistTestExecutor`，结果是：

```undefined
status: blocked
summary: Sandboxed tests failed or ran zero tests:
         Ran 0 tests in 0.000s
         NO TESTS RAN
```

文档只能由 alpha-trion 在第 9 步写，而第 9 步之前必须先通过第 6 步的测试门。只写文档的项目永远没有测试，所以永远到不了第 9 步。

### 4.2 能完成的任务范围

现状下能完成的任务需要同时满足：Python 项目、有 `tests/test*.py`、unittest 全部通过、任务能表达成完整 SDLC、不需要写根目录 md、不涉及硬件。任务越简单（写文档、改单个文件、项目没有测试），越容易落在这个范围之外。

### 4.3 测试为什么没发现

- `SimulationExecutor` 对每一步都无条件返回 completed，并附带 `source_type=SIMULATION` 的通过证据；`FakeHost` 下 `allow_simulated_evidence=True`。模拟环境里不会出现"零测试"或"无写权限"。
- `micronus-prime` 定义为 L1 静态分析官，但权限中没有 shell，实际从未执行过 ruff 或 clang-tidy。

## 五、v6 目标架构

### 5.1 定位

- 前半段保留 forge 式的判断力：prima 负责规划和路由。
- 后半段保留 Cybertron 的内核：状态、证据、权限、副作用全部由确定性代码掌握。
- 两者之间只通过带类型的接口通信：图操作（GraphOp）、上下文包、结构化结果。

### 5.2 分层结构

```text
┌──────────────────────────────────────────────────────────────┐
│ 宿主层（OpenCode / DSH）                                      │
│  交互：消息流、Thought、原生 subagent 卡片、后台/取消、审批弹窗 │
│  执行：模型调用、工具调用、会话与流式输出                       │
├──────────────────────────────────────────────────────────────┤
│ 适配层（cybertron.js 插件 + host adapter）                     │
│  cy_* 工具、task 前后钩子、节点↔会话绑定、宿主回执采集           │
├──────────────────────────────────────────────────────────────┤
│ 内核层（确定性 Python）                                        │
│  图操作裁决 │ 就绪调度 │ 写范围守卫 │ 门禁策略 │ 配置文件执行    │
│  事件账本（唯一权威）│ 预算与失败指纹 │ 审批与回滚 │ 重放       │
├──────────────────────────────────────────────────────────────┤
│ 角色层（13 天尊 = 能力身份）                                   │
│  每个节点一个 context 包，只读上游摘要与路径，不读写 run 状态    │
└──────────────────────────────────────────────────────────────┘
```

分层原则：**会话归宿主，事实归内核。** 两层之间只通过带类型的接口通信——图操作（GraphOp）、上下文包、结构化结果、宿主回执。宿主负责用户看见什么，内核负责什么算数；任何一层都不能替另一层做决定。

### 5.3 三层 harness loop

> 命名约定：**Loop-0/1/2 指三个 harness 循环**；**L1/L2 仍指 micronus/liege 的审查级别**（§7.2、§8、§9 中的 L2 均指审查）。上一版两套编号都写成 L1/L2，"轻量 L2"与"L2 编排循环"无法区分。

| 循环             | 所有者               | 做什么                                                       | 何时终止                                                     |
| ---------------- | -------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| Loop-0 工具循环  | 宿主（OpenCode/DSH） | 单个角色内部的 模型 ↔ 工具 交互                              | 角色的 `steps` 预算用完或返回结果                            |
| Loop-1 节点修复  | 内核                 | 角色返回后运行该节点的验证器（diff 范围、lint、测试、构建）；失败时把诊断附加到同一节点重新派发 | `max_attempts`（默认 2）；或连续两次失败指纹相同，此时交给 Loop-2 |
| Loop-2 编排循环  | prima                | 读全局状态，提交图操作（插入、拆分、换角色、请求用户），派发就绪节点，直到验收标准全部满足 | 验收标准全部有证据；或 `max_replans`（默认 3）/ `max_dispatches` 用完，升级给用户 |

forge 的"连续两轮 concern 指纹无变化就 escalate"保留到 Loop-1。区别在于由内核比较验证器输出的哈希，而不是让编排者自己判断有没有进展。

循环预算的默认值写在内核配置里，不交给模型决定：

| 预算 | 默认值 | 耗尽后 |
| --- | --- | --- |
| 单节点 `max_attempts` | 2 | 交给 Loop-2 决定换角色或拆节点 |
| 单 run `max_replans` | 3 | 升级用户，附当前缺口清单 |
| 单 run `max_dispatches` | 20 | 升级用户，不再自动重规划 |
| 单次派发墙钟 | 10 分钟 | 记 `dispatch_timeout`，按失败处理 |
| 单节点 token | 按模型档位配置 | 中止并记 `budget_exhausted` |
| 并行写节点 | 默认 1，写范围不重叠时最多 4 | 其余排队，不并发写同一路径 |

### 5.4 交互层：子代理必须是宿主原生的

派单的界面不由内核绘制。prima 调用宿主原生 `task` 工具，子代理以一张内联卡片出现在同一会话里：名字、目标、一行职责说明，自己的 Thought 与工具流，可以 `Ctrl+B` 转入后台，也可以取消；父级的思考与 `cy_*` 调用保持可见。forge 的这张卡片就是参照。

内核不重写这层 UI，只通过插件钩子做三件事：派发前校验、派发后记账、结束后验产物。

| 关注点 | 归谁 | 做法 |
| --- | --- | --- |
| 会话、流式输出、Thought、后台、取消、并行展示 | 宿主 | 原生 `task` 与会话 UI，内核不介入 |
| 派给哪个节点、哪个角色、是否合法 | 内核 | `tool.execute.before` 校验 node 状态、role↔capability、`write_scope`；不合法直接拒绝 |
| 子代理实际做了什么 | 宿主 + 内核 | `tool.execute.after` 记录 task session ID、工具事件、耗时；文件 diff 由内核的 `scope_guard` 统一计算 |
| 是否通过 | 内核 | 只认验证器回执，不读角色自报的 `claims` |
| 预算、重试、换角色 | 内核 | Loop-1/2 的预算与失败指纹，见 5.3 |

卡片上至少显示 `node_id`、能力 ID 和 `write_scope`。用户要审计的是范围，不是代号。

三条交互规则：

1. **后台不等于完成。** `Ctrl+B` 只改变展示位置，节点状态仍是 `running`；完成以宿主 `task` 返回为准。
2. **取消是终态。** 用户取消后节点记 `cancelled` 而不是 `failed`，不自动重试；需要重跑由 prima 提交 `retry_node`。
3. **拒绝也要有卡片。** 钩子拒绝一次派发时，界面显示被拒绝的派发及原因（例如"n5 正在执行，不能重派"），而不是静默失败。

宿主没有原生 subagent 或钩子能力不足时（CI、headless），才使用 `cy_dispatch` 适配器；两者的图操作、事件和证据语义完全一致，只是没有卡片。

## 六、核心数据契约

### 6.1 计划节点（替代 LedgerStep）

```JSON
{
  "node_id": "n3",
  "kind": "task | review | verify | human | device_op",
  "capability": "code.write",
  "role": "solus-prime",
  "objective": "实现 UART DMA 接收环形缓冲",
  "depends_on": ["n1", "n2"],
  "read_scope": ["src/**", "include/**"],
  "write_scope": ["src/uart/**"],
  "acceptance": ["AC1: 连续 1 MB 输入无丢字节 [auto]"],
  "verifiers": ["scope_guard", "profile.lint", "profile.test"],
  "budget": {"max_attempts": 2}
}
```

### 6.2 图操作（prima 唯一能改计划的方式）

| 操作                                    | 内核会拒绝的情况                                             |
| --------------------------------------- | ------------------------------------------------------------ |
| `add_node` / `add_edge`                 | 产生环；能力映射不到任何角色（内核登记为能力缺口）；`write_scope` 超出角色权限上限 |
| `split_node` / `reassign_role`          | 节点正在执行中                                               |
| `retry_node(feedback)`                  | 超出 `max_attempts`                                          |
| `insert_gate`                           | 不会拒绝，门禁只能加                                         |
| `mark_not_applicable(reason, evidence)` | 该门禁属于风险下限（必须执行，只能走用户豁免）；没有证据 |
| `request_human(question)`               | 不会拒绝                                                     |
| `complete_run`                          | 还有验收标准没有对应证据                                     |

每个图操作都写成事件（`plan.op.proposed` / `plan.op.applied` / `plan.op.rejected`），计划本身的演变过程也可以审计和重放。

`mark_not_applicable` 只覆盖风险下限之上的门禁。下限内的门禁只有一种豁免方式：用户在审批界面确认后，宿主把 `user_waiver` 回执直接写入账本，不由 prima 提议；没有审批回执的豁免一律拒绝。

每个图操作携带 `op_id` 与 `plan_revision`，内核按 `op_id` 幂等，同一操作重放不会二次生效。

`runstore` 的 schema 升到 v2，保留 `schema_version` 字段：旧版九步 run 只读，仍可 `verify` 和导出报告，但不参与 v2 调度；新 run 使用 v2 图 schema。插件与内核以 `task session ID` 对账：钩子写入 `dispatch.started` 后崩溃的派发，恢复时按 session 查宿主记录，找不到就记 `outcome_unknown`，不自动重试。

### 6.3 角色结果

```JSON
{
  "status": "completed | failed | blocked | needs_input",
  "summary": "…",
  "artifacts": [{"path": "src/uart/ring.c"}],
  "claims": ["已处理溢出回绕"],
  "suggested_ops": [{"op": "add_node", "capability": "test.write"}],
  "questions": []
}
```

`claims` 和 `suggested_ops` 只作参考。产物 sha256 由内核计算，不信任角色填写的值。质量结论只认验证器回执。

## 七、五个内核机制

### 7.1 写范围守卫

写权限分三层，外层是内层的上限，运行时只认最内层：

| 层 | 由谁定义 | 例子 |
| --- | --- | --- |
| 宿主静态权限 | 导出器按角色目录生成（`opencode.jsonc`） | solus-prime 可写 `src/**`、`app/**`，不能写 `tests/**` |
| 角色上限 `write_roots` | `registry.py` 的角色目录 | alchemist 只能写 `tests/**` 和仿真目录 |
| 节点 `write_scope` | 计划图节点，必须是角色上限的子集 | `src/uart/**` |

不变量：`write_scope ⊆ write_roots ⊆ 宿主静态权限`。违反任一层都由内核在派发前拒绝，并记 `plan.op.rejected`。

宿主静态权限由导出器生成，默认按角色目录写成细粒度规则（上表例子）。为了减少导出器维护成本，也可以统一放宽到 `edit **`，但必须同时保留两条硬拒绝：`.git/**` 和 `.cybertron/runs/**`（状态只由内核写）。`.cybertron/plans/**` 与 `.cybertron/knowledge/**` 属于角色上限，由节点 `write_scope` 进一步收窄，不在静态层拒绝。`opencode.jsonc` 与 `.opencode/**` 只由导出器维护，任何角色都不能写。

运行时：内核在派发前记录文件哈希快照，派发后计算 diff；任何文件在 `write_scope` 之外被改动，该节点判定失败并自动回滚。这一机制解决"写个 md 都不行"。

### 7.2 门禁策略引擎

内核根据实际 diff 计算风险等级，按等级确定门禁下限。prima 可以在下限之上加门禁，不能降到下限以下。

| 变更事实                           | 门禁下限                                                 |
| ---------------------------------- | -------------------------------------------------------- |
| 只改了 `*.md`                      | 写范围守卫                                               |
| 代码改动，规模小，不涉及公共接口   | 守卫 + lint + 测试（或带证据的 N/A）+ 轻量 L2（只审本次 diff） |
| 公共接口、跨模块、改动行数超过阈值 | 上一行全部 + 完整 L2（审接口与跨模块影响）+ 构建 + 用户确认计划 |
| 固件/驱动                          | 上一行全部 + 交叉编译 + 体积预算 +（有仿真配置档时）仿真 |
| 设备操作                           | 上一行全部 + 单次审批 + 回滚镜像 + 心跳核验              |

### 7.3 测试门的四种结论

- `pass` / `fail`：正常结论。
- `not_applicable`：工具链配置档探测到项目没有测试框架。
- `waived`：用户显式豁免，并留下记录；只能由 `user_waiver` 回执产生，prima 不能自行宣布豁免。

项目没有测试但风险等级要求测试时，prima 必须插入 `test.write` 节点或请求用户豁免。

### 7.4 工具链配置档

内核先探测项目类型，再加载对应命令集，在沙箱中执行：

```YAML
# .cybertron/profiles/stm32-cmake.yaml
detect: ["CMakeLists.txt", "*.ioc"]
lint:   ["clang-tidy -p build {changed_c_files}"]
build:  ["cmake --build build"]
size:   ["arm-none-eabi-size build/app.elf"]
test:   ["ctest --test-dir build"]
sim:    ["renode --console -e 'include @tests/sim.resc'"]
flash:  {broker: true, tool: openocd}
```

内置配置档覆盖 python、node、go、rust、cmake-arm、esp-idf、platformio，项目也可以自定义。lint 由内核实际执行，micronus 只负责解读输出。

### 7.5 并行调度与写范围锁

只读节点总是可以并行。写类节点只有在 `write_scope` 互不重叠时才并行；重叠时排队，或在独立的 git worktree 中执行。

## 八、角色：从阶段身份改为能力身份

13 个名字保留，`sdlc_stage` 字段换成 `capabilities` 加上权限上限。

| 角色           | 能力                                                         | 权限上限                            |
| -------------- | ------------------------------------------------------------ | ----------------------------------- |
| prima          | plan、route                                                  | 只有 cy_* 工具与原生 `task`，没有文件工具 |
| thirteenth     | intake.clarify、evidence.external（飞书/Coding/知识库只读）、accept | 只读 + 向用户提问                   |
| onyx-prime     | scan.static、context.map、audit.inventory（全仓只读清单）    | 只读                                |
| vector-prime   | scan.history、diagnose、analysis.special（经 `cy_check`）    | 固定的只读 git 命令                 |
| quintus-prime  | design、plan.draft                                           | 写 `.cybertron/plans/**`            |
| solus-prime    | code.write                                                   | 由节点 write_scope 决定             |
| amalgamous     | code.refactor、code.port、code.transform（批量迁移与格式转换） | 由节点 write_scope 决定             |
| micronus-prime | review.l1（解读内核执行的 lint 结果）                        | 只读                                |
| liege-maximo   | review.l2（高风险变更可配置另一家模型）                      | 只读                                |
| alchemist      | test.write                                                   | 由节点 write_scope 决定             |
| nexus-prime    | build.config、toolchain                                      | 构建文件，由节点 write_scope 决定   |
| megatronus     | device.op                                                    | 只通过副作用代理执行                |
| alpha-trion    | doc.write、knowledge.sync                                    | 由节点 write_scope 决定；飞书走网关 |

不设临时专才。表外任务按职责类型由现有天尊承接，领域知识用 skill 注入；能力映射不到任何角色时，内核拒绝该节点并登记缺口，交由用户决定是否扩展，详见 13.8。

### prima 的派单方式

**恢复宿主原生 `task` 工具。** 上一版写的是"不恢复原生 subagent，改由内核起子进程派发"，这与 §2 的诊断矛盾：现状之所以被压成 pipeline，正是因为插件删掉了 subagent 工具、Python 为每个角色起一次子进程；换一个 `cy_dispatch` 的名字并不能改变这一点，只会同时丢掉子代理卡片、流式输出、后台和取消。

正确做法是把"进程由谁起"和"事实由谁记账"分开：

- **交互层归宿主。** prima 调用原生 `task`，子代理以卡片形式出现在同一会话里，见 5.4。
- **治理层归内核。** 插件在 `tool.execute.before` 里要求这次 `task` 绑定一个就绪节点，校验角色、能力和 `write_scope`，不合法直接拒绝；在 `tool.execute.after` 里记录 task session ID、工具事件和耗时。产物由内核在节点结束时用 `scope_guard` 计算 diff 并跑验证器。
- **回执不依赖 spawn。** 会话 ID、工具事件来自钩子，文件 diff 来自快照对比，证据来源标为 `host`；子代理自报的 `claims` 不入账。

这样原生 subagent 并没有"绕过内核"：它可以绕过内核的进程，但绕不过派发前的拒绝和结束后的验证。

配置约束：

- `task` 只对 prima 开放，目标限定为其余 12 个角色；所有 subagent 一律 `task: deny`，禁止递归派发。
- `cy_plan` / `cy_state` / `cy_ask` 保留；`cy_dispatch` 只作为没有原生 subagent 的宿主的适配器。
- 同一轮并行多个 `task` 时，插件逐个校验对应节点，`write_scope` 重叠的派发直接拒绝并要求排队。

和现状的区别在于决策权的位置：

- 现状：`cybertron_run` 一次调用跑完整条九步直到阻塞，prima 只是触发器，且没有子代理卡片。
- v6：prima 每一轮自己决定派哪个节点、要不要重规划，内核只判断合不合法；派发仍以原生卡片呈现。

## 九、同一套系统的三种计划形状

```undefined
"根目录写 notes.md"
  n1 doc.write(write_scope=notes.md) → 守卫 → 完成
  1 次派单，不需要确认计划

"修复解析空指针"
  n1 scan.static ─┐
  n2 scan.history ┴→ n3 code.write → [lint+test] → n4 review.l2 → 完成
  约 4 次派单

"STM32 新增 DMA 驱动"
  n1 clarify → n2 scan ‖ n3 history → n4 design →（用户确认计划）
  → n5 code.write ‖ n6 test.write → [lint/build/size/test/sim]
  → n7 review.l2 → n8 device_op（审批+回滚）→ [心跳] → n9 doc.write
```

修 bug 时如果 L2 拒绝，只把 n3 标记为过期并带着反馈重跑，n1 和 n2 的结果保留。现状会把第 4、5 步整体清空。

## 十、与 forge 的对比

| 维度         | forge                                                        | Cybertron v6                                                 |
| ------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 计划         | PLAN.md 的 checkbox                                          | 经过校验的图 + 可重放的操作日志                              |
| 实现完成之后 | 固定 6 步管道 + N/A 条件                                     | 按风险计算门禁下限，只能加不能减                             |
| 状态写回     | STATE.json 由编排者经 `forge_state` 写，值不校验；PLAN.md 由 LLM（forge-knowledge）写 | 只由内核写，LLM 不碰状态                                     |
| 门禁证据     | 模型摘要                                                     | 带类型的回执（sandbox/host/tool/human）                      |
| 写权限       | 角色静态配置                                                 | 按节点范围 + diff 守卫 + 自动回滚                            |
| 并行         | 各 unit 串行                                                 | 按写范围上锁的并行                                           |
| 表外任务     | forge-factory 只输出规格，没有执行者                         | 按职责类型覆盖 + skill 注入；缺口登记后由用户决定（见 13.8） |
| 硬件         | 首次部署时确认一次                                           | 每次操作都审批，绑定设备和固件哈希，带回滚                   |
| 恢复         | 读 PLAN.md                                                   | 事件重放 + `outcome_unknown`                                 |
| 宿主         | 只支持 OpenCode                                              | 宿主适配器，可接 OpenCode、DSH                               |

从 forge 直接沿用：编排者没有文件工具、意图路由、派单时传路径不传内容、只在少数节点打断用户、PROJECT_CONTEXT/RULES/LEARNINGS 知识层、派发前后的中文状态横幅、原生 subagent 卡片与后台/取消。

## 十一、迁移路线

### 11.1 模块处理

| 模块                                                         | 处理方式                                                     |
| ------------------------------------------------------------ | ------------------------------------------------------------ |
| `runstore.py`、`sessions.py`、`side_effects.py`、`deployment.py`、`model_config.py`、`installer.py`、`feishu.py` | 保留；runstore 的 schema 升到 v2，去掉"必须 9 步"的校验      |
| `ledger.py` → `graph.py`                                     | PlanGraph + 校验器；现有九步改为"硬件全流程"模板             |
| `dispatch.py` + `orchestrator.py` → `kernel.py`              | 就绪节点调度、Loop-1 节点修复循环、图操作的应用              |
| `registry.py`                                                | 增加 capabilities 和权限上限                                 |
| `isolated_runner.py` → `profiles.py`                         | 从只跑 Python unittest 泛化为配置档执行器                    |
| 新增                                                         | `gates.py`（风险策略）、`scope_guard.py`、`templates.py`     |
| `.opencode/plugins/cybertron.js`                             | `cybertron_run` 拆成 cy_state / cy_plan / cy_ask；恢复原生 `task` 并加 before/after 钩子；`cy_dispatch` 仅作适配器；重写 prima 提示词 |

### 11.2 里程碑

| 里程碑            | 交付内容                                          | 验收                                                         |
| ----------------- | ------------------------------------------------- | ------------------------------------------------------------ |
| M0 解封           | 图 schema、单节点计划、写范围守卫、测试门四种结论 | 真实宿主上"根目录写 notes.md"派单 1 次即完成并出现原生子代理卡片；四类反例测试通过（成环、越界 diff、伪造证据、零测试）；现有测试全绿 |
| M1 规划权回归     | prima 工具集、图校验、重规划、修 bug 模板         | 三种规模的需求分别得到约 1 / 4 / 8 个节点的计划；被拒绝的派发在界面可见原因 |
| M2 门禁与配置档   | 风险策略、python/node/cmake-arm 配置档            | C 项目产出真实的 lint/build 回执；prima 无法把门禁降到下限以下 |
| M3 并行与修复     | 调度器、写范围锁、Loop-1 修复循环、局部返工       | 注入一次 L2 拒绝，只有受影响的子图重跑                       |
| M4 硬件           | 接入第 7 阶段已有的审批和回滚、renode 仿真配置档  | STM32 节点产出完整回执链                                     |
| M5 学习与第二宿主 | 图模板沉淀、指标面板、DSH 适配                    | 同类需求第二次运行时节点数和人工干预次数下降                 |

验收规则（M0–M5 通用）：

- 必须在真实宿主上跑通；`SimulationExecutor` 和 `FakeHost` 只能用于单元测试，不能作为里程碑证据。
- 每个里程碑至少包含一个反例：非法图操作被拒绝、越界写入被回滚、模型自述证据过不了门禁。
- 结论以事件账本为准；截图和模型摘要只作辅助材料。

### 11.3 衡量指标

- 一次通过率
- 每种任务规模的平均派单次数
- 简单任务端到端耗时
- 人工干预次数
- 门禁拦截中真实问题的占比

建议在 M0 之前先跑一次基线：用现状系统分别执行"改一行 bug""加一个小功能""加一个跨模块功能"，记录参与角色数、形式化通过的步骤数、派单次数。

## 十二、硬性约束

1. LLM 不写状态，也不自报证据。
2. 门禁只能加，不能降到风险下限以下。
3. 每次副作用操作都要单独审批，审批绑定具体对象，不能复用。
4. 每个循环都有预算，判断"没有进展"的是内核，不是模型。
5. 知识和模板可以影响规划，但不能绕过校验器。
6. 派单界面归宿主：内核不自建子代理 UI，只在宿主没有原生 subagent 时降级到 `cy_dispatch`。

## 十三、向 forge 与 nexus-matrix 学习：13 天尊的能力分配

> 依据：`forge/opencode/agents/` 下 19 个 agent 定义；`Nexus/plugins/nexus-matrix`（0.1.1）的 `roles/catalog.js` 与 `prompts/*.md`。

### 13.1 两个参照系各自的取舍

**原则：向 forge 学"需要哪些职能"，向 matrix 学"怎么约束一个角色"。**

- forge 的 19 个 agent 职能齐全，但约束主要写在提示词里，状态也由 LLM 写回。
- matrix 的约束写成了代码（角色目录、读写根、工具类别、fail-closed 守卫），但删掉了知识层、调试、独立测试和多道审查。
- 13 天尊的数量处在两者之间：比 matrix 多出几个角色，可以把 matrix 合并掉的职责重新拆开；又比 forge 少一半，不会过于分散。

matrix 相对 forge 精简掉的内容：

| 精简项             | forge 中的形态                                               | matrix 中的形态                                              |
| ------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 跨 run 知识层      | forge-knowledge、forge-knowledge-expander 维护 MODULE_CONTEXT / LEARNINGS / BUG_PATTERNS | 无；事实只存在当前 run 目录，多数角色禁止访问 `$FORGE`       |
| 独立验收链         | quality → review → oracle → verification 四道                | 只有一个 code-review；verification 由 gate + orchestrator 承担；oracle 删除 |
| 调试专家           | forge-debug：先查根因、三击规则、blast radius、必附回归测试  | 无；code-analysis 没有 bash，无法复现                        |
| 写测试与写代码分离 | forge-test 独立编写测试                                      | code-implementation 默认可写 `tests/**`，自写自测            |
| 动态造角色         | forge-factory 输出临时 agent 规格                            | `assertCatalog()` 写死 10 个角色                             |
| 编排者流程规则     | S1–S5、U1–U5、O1–O12、C1–C18 与固定后半段管道                | 只保留计划确认门，交人收窄为五类情形                         |
| 组织规范           | forge-git 的 Issue-ID 红线（R1/R2）；forge-deploy 完整部署链 | git 只要求 `type(scope): summary`；device-test 只做验证      |

matrix 同时把很多约束从提示词搬进了代码：按角色的读写根、命令模式、工具能力类别、executor-guard 运行时拦截、结构化结果、runtime 写状态、幂等、心跳超时、崩溃恢复、gate 事实落盘。

### 13.2 13 天尊职能分配表

| 天尊           | 职能                                                         | 来自 forge                                 | 来自 matrix                | 写根上限                                     | 执行能力                            |
| -------------- | ------------------------------------------------------------ | ------------------------------------------ | -------------------------- | -------------------------------------------- | ----------------------------------- |
| prima          | 规划、路由、派发、决策                                       | forge-orchestrator、emb-forge-orchestrator | orchestrator               | 无文件与命令工具；cy_* + 原生 task           | 无                                  |
| thirteenth     | 前端：意图澄清、对外只读取证；后端：逐条核对 AC、交付        | intent-analyst、verification               | intent                     | 本节点产物                                   | 只读                                |
| onyx-prime     | 代码制图、影响面分析、节点展开、全仓只读审计清单             | codebase-cartographer、knowledge-expander  | code-analysis              | 本节点产物                                   | 只读                                |
| vector-prime   | git 考古、根因诊断（只诊断不修复）、专项分析（性能、抓包等） | debug 的调查部分                           | 无                         | 本节点产物                                   | 固定只读 git 命令 + `cy_check` 复现 |
| quintus-prime  | 计划图草案、接口/HAL 契约骨架                                | architect                                  | planner                    | `.cybertron/plans/**` + 节点声明的接口文件   | 无                                  |
| solus-prime    | 功能实现、最小修复                                           | implementation、debug 的修复部分           | code-implementation        | 节点 write_scope，不含 `tests/**`            | `cy_check`                          |
| amalgamous     | 重构、移植、批量迁移与格式转换                               | 无                                         | 无                         | 节点 write_scope                             | `cy_check`                          |
| micronus-prime | L1：RULES 合规、禁用模式、解读 lint 结果、找测试缺口         | quality                                    | code-review 的规则部分     | 本节点产物                                   | 无，lint 由内核执行                 |
| liege-maximo   | L2 深度审查；高风险变更换一家模型再审一次，充当 oracle       | review、oracle                             | code-review                | 本节点产物                                   | 无                                  |
| alchemist      | 测试策略、编写测试和仿真脚本、解读失败原因                   | test                                       | build-test 的结果解读      | `tests/**`、仿真脚本                         | `cy_check`                          |
| nexus-prime    | 构建与工具链配置、打包、提交集成，负责 Issue-ID 红线         | git、deploy 的打包部分                     | git、build-test 的构建部分 | 构建文件                                     | 固定 git 命令；push 需审批          |
| megatronus     | 设备操作：烧录、上电、设备测试、设备部署                     | deploy                                     | device-test                | 设备证据目录                                 | 只经副作用代理，每次单独审批        |
| alpha-trion    | 文档、跨 run 知识层、飞书/Coding 写入                        | writer、knowledge（不含状态写回）          | doc-writing                | `docs/**`、`*.md`、`.cybertron/knowledge/**` | 无 shell，外部写入走网关            |

有几个映射能直接沿用角色名的本义：

- 幻化天（amalgamous）是变形者，对应重构、移植和批量格式转换。
- 合体天（nexus-prime）负责合体，对应把变更集成进仓库，也就是构建加提交。
- 维克多（vector-prime）守护时间线，对应回归定位和根因调查。

以下工作由内核承担，不分配给任何天尊：

- **状态写回**：forge 里由 forge-knowledge 的 Scene 0 写，这是 forge 最大的缺陷，不继承。
- **执行 lint/构建/测试**：matrix 让 build-test 用 deny-only shell 直接执行，它自己的文档也承认这不是沙箱。Cybertron 已有 `sandbox-exec` 隔离运行器，比 matrix 更强。
- **汇总 gate 事实**：沿用 matrix 的做法，gate 只给事实，不做决策。

### 13.3 为什么 13 个角色比 matrix 的 10 个更合适

多出的角色可以把四条职责分离链重新拆开：

| 分离链                        | forge                       | matrix                                         | 13 天尊                                         |
| ----------------------------- | --------------------------- | ---------------------------------------------- | ----------------------------------------------- |
| 写实现 ≠ 写测试 ≠ 审查 ≠ 验收 | 有                          | 实现角色同时写测试，审查只有一道，没有独立验收 | solus ≠ alchemist ≠ micronus/liege ≠ thirteenth |
| 诊断 ≠ 修复                   | 由 forge-debug 一个角色包办 | 没有诊断角色                                   | vector ≠ solus                                  |
| 集成 ≠ 物理执行               | git 与 deploy 分开          | git 与 device-test 分开                        | nexus ≠ megatronus                              |
| 知识沉淀 ≠ 运行状态           | 都由 forge-knowledge 负责   | 没有知识层                                     | alpha-trion ≠ 内核                              |

这四条链就是 Cybertron 做这套设计的理由。如果最后又像 matrix 那样合并回去，13 个角色只剩名字上的区别。

### 13.4 从 matrix 学：把约束写进代码

**把** **`registry.py`** **改造成角色目录**，参照 matrix 的 `roles/catalog.js`，用 `capabilities` 替代 `sdlc_stage`：

```Python
@dataclass(frozen=True)
class PrimeRole:
    agent_id: str
    capabilities: tuple[str, ...]     # 替代 sdlc_stage，例如 ("code.write",)
    lifecycle: str                    # persistent | per-node
    read_roots: tuple[str, ...]
    write_roots: tuple[str, ...]      # 上限；节点 write_scope 必须是它的子集
    tool_mode: str                    # allow-list | deny-only
    tool_classes: tuple[str, ...]
    command_mode: str                 # none | git-allow-list | kernel-check
    network: bool
    device: str | None
    external_write: tuple[str, ...]   # feishu / coding
    can_dispatch: bool
    model_tier: str                   # high | middle | low | heterogeneous
```

**用** **`assert_catalog()`** **校验不变量**，参照 matrix 的 `assertCatalog()`，违反一条就拒绝启动：

1. 只有 prima 的 `can_dispatch` 为真；也只有 prima 拥有 `task` 工具，其他角色一律 `task: deny`。
2. 只有 nexus-prime 有 git 写命令，只有 megatronus 有 device 权限，只有 alpha-trion 有 external_write。
3. solus 和 amalgamous 不能写 `tests/**`，alchemist 只能写 `tests/**` 和仿真目录。
4. micronus、liege、thirteenth 的写根只包含本节点产物目录。
5. 任何角色都不能写 `.cybertron/runs/**`，状态只由内核写。
6. 同一个角色不能同时拥有 `code.write` 和 `review.*` 能力。
7. 未知工具一律拒绝。

**其他值得照搬的做法：**

- 结构化结果：成功只认产物 hash 加 gate 事实，不解析自然语言摘要。
- 上下文包：内核为每个节点生成一份 `context.md`，只放上游摘要和文件路径。角色读不到其他节点的产物，也读不到 run 状态。
- 编排者不读代码：prima 只通过 cy_* 工具读取运行事实，派发走原生 `task`。

**不照搬的做法：**

- deny-only bash：实现类角色改用内核提供的 `cy_check(target)`，在沙箱里按工具链配置档执行，结果返回给角色。Loop-0 工具循环照样能拿到反馈，执行过程也可信。
- 去掉设备的逐次审批：matrix 为了便利去掉了 DevLink 的逐次审批。Cybertron 的硬件定位决定了必须保留。

### 13.5 从 forge 学：补回 matrix 删掉的职能

**1. 跨 run 知识层，由 alpha-trion 负责**

```undefined
onyx 制图 ─────────┐
vector 根因报告 ───┼─→ alpha-trion 在 run 结束时整理沉淀
liege 审查结论 ────┘     .cybertron/knowledge/
                        ├── PROJECT_CONTEXT.md
                        ├── RULES.md
                        ├── LEARNINGS.md
                        └── BUG_PATTERNS.md
                               │
                               ▼
              内核把相关条目注入下一个 run 的每个节点 context.md
```

知识写回在 run 结束时作为一个节点执行。不要像 forge 那样每一步都写回，状态更不能交给它写。

**2. 调试流程拆给三个角色**

失败后，prima 依次插入三个节点：

1. vector 诊断：读历史，用 `cy_check` 复现，产出根因和回归测试规格。
2. alchemist 编写回归测试。
3. solus 做最小修复。

forge-debug 的纪律保留下来，但改为由内核检查：

- 同一假设的指纹连续失败 3 次（三击规则），内核拒绝再次派发同一假设。
- 修复节点必须关联一条回归测试证据，否则无法完成。

**3. 两道审查，再加一道异构审查**

- micronus 负责 forge-quality 那一层：规则、禁用模式、TODO、测试缺口。
- liege 负责 forge-review 那一层：逻辑、架构、接口兼容。
- 门禁策略判定为高风险时，额外插入一次 liege 审查，换另一家模型执行。这就是 oracle，不需要新增角色。

**4. 不设临时专才**

forge 用 forge-factory 兜底，但它只输出规格，没有执行者。Cybertron 不设专才：任务按职责类型由现有天尊承接，领域知识用 skill 注入，能力映射不到任何角色时登记缺口、交给用户决定。详见 13.8。

**5. 组织规范**

- nexus-prime 提交前，内核校验两件事：暂存文件都在本 run 的 write_scope 内；feat/perf 类型的提交带有 Issue-ID（forge 的 R1/R2）。
- push 和首次部署走审批（forge 的 U2）。

### 13.6 需要避开的问题：用代号路由

forge 和 matrix 的角色名本身就说明职能（`forge-test`、`code-review`），LLM 路由时不容易出错。"liege-maximo""alchemist"这类代号要靠记忆映射，prima 容易派错角色。

prima 在 `cy_plan` 里只写能力 ID，例如 `capability: "test.write"`，由内核解析出对应的天尊。天尊名字只用于展示和日志。

### 13.7 落地顺序

| 步骤 | 内容                                                         | 验收                                                         |
| ---- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 1    | `registry.py` 改为角色目录，加入 `assert_catalog()` 和不变量测试 | 七条不变量各有一个反例测试，违反时 fail-closed               |
| 2    | 导出器根据角色目录生成 OpenCode 权限；内核增加按节点 write_scope 的守卫 | solus 改动 `tests/**` 被拒绝并自动回滚                       |
| 3    | 实现 `cy_check`；micronus 改为解读内核执行的 lint 结果       | C 项目的 L1 证据来自真实 clang-tidy 输出                     |
| 4    | 增加知识目录和 context 包注入；alpha-trion 承担 run 结束时的沉淀节点 | 同一仓库第二次运行时，onyx 节点的读取量下降                  |
| 5    | 实现 vector 诊断 → alchemist 写回归测试 → solus 修复的流程，以及三击规则 | 注入一个 bug，三个节点依次产出根因、测试、修复               |
| 6    | 实现 skill 注入、能力缺口登记与 liege 的异构审查             | 能力映射不到角色时节点被拒绝并登记缺口；高风险变更自动出现第二次审查 |

步骤 1 和 2 可以和第十一章的 M0 合并做。角色目录确定之后，后面的图校验、门禁和调度才有可以依赖的权限上限。

### 13.8 不设临时专才：按职责类型覆盖任务

**专才的需求来自角色按"工具"切得太细。** v5 白皮书的原则是"一尊一专职、零权限重叠"，例如 onyx 只能用 read/glob/grep、禁止碰 git，vector 只能用 git、禁止扫库。任务稍微跨一点就没人能接。matrix 的角色按职责划分：code-analysis 负责"读全仓、产出报告"，读什么、分析什么都不限，所以 10 个角色就不需要专才。

forge 与 matrix 的现状：

|        | 谁设计专才                             | 谁执行                                                       | 权限能否按任务定制 |
| ------ | -------------------------------------- | ------------------------------------------------------------ | ------------------ |
| forge  | forge-factory 输出临时 agent 规格      | 没有专门执行者；OpenCode 运行中不能注册新 agent，只能借用现有 agent | 否                 |
| matrix | 无（`assertCatalog()` 固定 10 个角色） | ad-hoc 节点：给现有角色派一个不属于计划阶段的短任务          | 否                 |

**按职责类型重新划分 13 天尊。** 任何任务都能归到下面五类之一，只要每类都有角色能接任意目标，就不存在"没人能做"的任务。

| 职责类型                 | 天尊                                                      | 能接的任务                                                   |
| ------------------------ | --------------------------------------------------------- | ------------------------------------------------------------ |
| 只读分析，产出报告或清单 | onyx、vector                                              | onyx：仓库内任意只读分析，包括代码、日志、依赖、许可证。vector：需要复现或查历史的分析 |
| 对外只读取证             | thirteenth                                                | 飞书、Coding、知识库只读，参照 matrix 的 intent              |
| 写产物                   | solus、amalgamous、alchemist、alpha-trion、nexus、quintus | solus：功能和生成代码。amalgamous：重构、移植、批量迁移与格式转换。alchemist：测试。alpha-trion：文档。nexus：构建文件。quintus：计划和接口 |
| 判定                     | micronus、liege、thirteenth                               | liege 的审查范围按节点定，可以是本次 diff，也可以是全仓      |
| 有副作用的执行           | nexus、megatronus、alpha-trion                            | 分别负责 git、设备操作、外部系统写入                         |

**从 forge 和 matrix 借的四个机制：**

1. **领域知识用 skill 注入，不新增角色。** matrix 的 planner 靠 `matrix-plan-contract` skill 拿到计划契约；forge-plugin 支持用 `extends` 继承提示词。Cybertron 的节点声明 `skills: [...]`，内核把 skill 内容放进该节点的 context.md。skill 只提供知识，不附带任何权限。
2. **统一的产物契约。** 结果结构统一（参照 `matrix.result/v1`），产物按 kind 区分：report、inventory、patch、test、doc、plan、verdict。角色目录写明每个角色能产出哪些 kind。
3. **按节点授予能力类别。** 参照 matrix 的 deny-only + toolClasses：角色目录定上限，节点在上限内申请，内核校验。
4. **计划外的临时节点。** 对应 matrix 的 ad-hoc 节点，在 v6 里就是 prima 用 `add_node` 插入一个节点，写明能力和目标。

原先归给专才的几类缺口，现在的承接方式：

| 缺口                         | 由谁接                                                       |
| ---------------------------- | ------------------------------------------------------------ |
| 外部资料                     | thirteenth 只读飞书、Coding、知识库。公网访问默认关闭（matrix 对所有角色硬拒绝 `web_fetch` / `web_search`）；确实需要时作为 thirteenth 的一个能力类别，按节点申请 |
| 全仓审计                     | onyx 产出 inventory；需要判定是否合规时，再派 liege 审查，范围设为全仓 |
| 数据或资产转换               | amalgamous 加对应 skill，产出 patch                          |
| 专项分析（性能、抓包、功耗） | vector：在工具链配置档里加上 profile、抓包解码等目标，通过 `cy_check` 调用，再配合相应 skill |

**兜底：** `assert_catalog()` 加一条完整性检查，每个"职责类型 × 产物 kind"组合至少有一个角色能承接。prima 请求的能力映射不到任何角色时，内核拒绝该节点并在账本里登记缺口，prima 转为 `request_human`，由你决定是给某个天尊加能力类别或 skill，还是明确记为范围之外。

**代价：** 角色变宽后静态权限上限也变大，要靠 M0 的按节点 write_scope 守卫收窄，所以这项调整要等 M0 完成后再做。

## 十四、治理方式对比：Cybertron 账本、forge 与 matrix

> 依据：`forge/opencode/tools/state_tool.py`；`Nexus/plugins/nexus-matrix/src/tools/gate.js` 与 `prompts/orchestrator.md`；`Cybertron-agents/cybertron/runstore.py`、`execution.py`、`dispatch.py`。

### 14.1 结论

三者的底线一样：编排者都不直接碰文件。差别在于由谁宣布"事实"和"通过"：

- **forge**：事实和结论都可以由 LLM 宣布。
- **matrix**：节点结算事实由代码保管；AC 的 pass/fail 由编排者提交，代码只做形式校验。
- **Cybertron 账本**：事实由代码保管；哪些证据能让门禁通过、预算何时耗尽，也由代码决定。

### 14.2 逐项对比

| 维度            | forge                                                        | matrix                                                       | Cybertron 账本                                               |
| --------------- | ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 状态由谁写      | 双轨：STATE.json 由编排者调用 `forge_state`（纯 Python）写，值由编排者给出；PLAN.md 的 Pipeline 节由 forge-knowledge（LLM）写 | runtime 写，节点结算后按固定顺序落盘：result → artifacts → gate → events → state → decisions；编排者没有写文件的工具 | RunStore 写。`events.jsonl` 是权威来源，快照是它的投影，可以重放 |
| 状态值是否校验  | `write` 只校验步骤名存在，状态值不校验；`set` 可写任意点分路径 | 节点生命周期由代码管：拒绝重复派发与重复结算；计划未确认不能派发计划阶段 | 代码校验转换合法性                                           |
| 计划治理        | architect 生成 PLAN.md，用户确认后按 checkbox 三态推进       | planner 产出 `plan.json`，schema 校验禁止多余字段；确认门记录 revision，revision 变化时 runner fail-closed | 现状：9 步写死在代码里。v6：每个 GraphOp 逐条校验，提议、应用、拒绝都记入账本 |
| 下一步由谁定    | orchestrator 按提示词规则（S1–S5、O1–O12）和固定后半段管道   | orchestrator 自行判断；配置明确拒绝 `states`、`transitions`、`stageMaxRetries` 等字段，只有 watchdog 当安全阀 | 现状：代码的 `next_step()`。v6：prima 提议，内核按预算和门禁下限裁决 |
| AC 通过由谁宣布 | specialist 的自然语言摘要 + 专用信号                         | 编排者通过 `matrix_gate(record)` 提交每条 check 的 status 和证据路径；代码校验枚举、计算 sha256，没有证据的 auto+pass 会被降为 blocked，但证据内容是否真的支持 pass 不做判定 | 只认带类型的证据：来源必须是 tool、sandbox 或 host，且带命令、退出码、UTC 时间、sha256、核验者，宿主还要二次核验。模型自述过不了门 |
| 失败与重试      | 写死在提示词里：quality 连续失败 2 次交给用户；修复后从 quality 重跑；三击规则 | 编排者判断，没有固定次数                                     | 现状：review 最多重试 2 次。v6：内核管理 `max_attempts`、`max_replans`，失败指纹重复即判定没有进展 |
| 副作用          | 首次部署确认一次                                             | DevLink 已取消逐次审批，操作范围靠模型遵守任务文字           | 每次操作单独审批，审批绑定设备、固件哈希、擦写范围和回滚方案，不可复用；结果不明时标为 `outcome_unknown`，不自动重试 |
| 权限执行        | agent frontmatter 里的工具开关 + 提示词禁令                  | `catalog.js` + executor-guard 在运行时 fail-closed，覆盖路径 ACL、命令模式、工具类别 | registry 导出成 OpenCode 权限；v6 再加按节点的 write_scope 和 diff 守卫，越界自动回滚 |

### 14.3 状态写回与状态机是两件事

- **状态写回**：状态最后由谁落盘。
- **状态机**：哪些状态转换是合法的，由谁校验。

|                | 下一步由谁决定        | 状态由谁落盘                                                 | 状态转换由谁校验                                             |
| -------------- | --------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| forge          | orchestrator（LLM）   | `forge_state` 工具写入，值由 orchestrator 给出；PLAN.md 由 forge-knowledge 写 | 只靠提示词                                                   |
| matrix         | orchestrator（LLM）   | runtime                                                      | 代码只管节点生命周期和不变量，流程顺序不管                   |
| Cybertron 现状 | 代码（`next_step()`） | RunStore                                                     | 代码：整条九步流程都是状态机，这也是它变成 pipeline 的原因   |
| Cybertron v6   | prima 提议，内核裁决  | 内核                                                         | 代码管节点生命周期（pending、running、completed、failed、cancelled、stale）和图的合法性；流程顺序由计划图决定 |

v6 借鉴的是 matrix 的做法：保留节点级状态机，去掉流程级状态机。

### 14.4 三个本质区别

1. **谁保管事实。** forge 只算半个账本：PLAN.md 由 LLM 写回，所以文档专门规定"没收到 `PIPELINE_WRITE_OK` 就视为未持久化"。matrix 和 Cybertron 都把节点事实交给代码。
2. **谁有判定权。** 这是 matrix 和 Cybertron 最大的分歧。matrix 的原则是"不得按固定流程、固定次数或阈值决策"，AC 结论也由编排者提交。Cybertron 把一部分判断收回代码：哪类证据能过门、门禁下限在哪、预算何时耗尽、是否在空转。v6 的说法是"判断归 LLM，合法性和预算归代码"。
3. **证据有没有来源类型。** matrix 也区分宿主证据和模型报告（例如 build-test 的 `prepare_result` 里的退出码"仍是模型报告"），但这些区分散在各个角色的规则里。Cybertron 的 `QualityEvidence` 把来源做成枚举字段，门禁直接按类型拒绝。

### 14.5 各自的代价

- **forge**：最灵活，但状态和质量结论都可能被模型"说成真的"。
- **matrix**：灵活，节点事实可信。风险在于编排者基于真实事实做出糟糕的判断，或在 gate 里把证据不足的 AC 记成 pass；代码不拦这些，只有超时兜底。设备侧对模型的信任也更多。
- **Cybertron**：最难被模型骗。但治理用过头就是现状：连计划本身都被管成了常量，写一个 md 都过不了。v6 的修正是把治理对象从"计划长什么样"改成"计划的变更是否合法、证据是否可信"。