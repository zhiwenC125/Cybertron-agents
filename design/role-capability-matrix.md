# Cybertron 角色能力矩阵与 10 / 13 分工归类

> 日期：2026-11-16
> 目的：回答「为什么别人 10 个 agent 够用，Cybertron 13 个反而不行」，并给出完整的角色分类、能力/权限/缺口矩阵、可选的 10-agent 归并方案。

## 一、为什么 13 个反而不如 10 个

**角色数量不是能力指标。** 当前 13 天尊是「按 SDLC 阶段切分」的身份，不是「按能力切分」的工人：

- 每个角色只覆盖一段，且多数是只读或受限编辑；
- 阶段之间 handoff 多，每换一个角色就多一次上下文重建；
- 构建、测试、lint、运行、Git 交付、联网这些**执行能力没有归属**，13 个角色都做不了；
- 编排是固定九步，不会按任务选择「这次只需要 3 个角色」。

别人 10 个 agent 之所以够用，通常是因为：

1. 每个 agent 的能力更宽（planner / coder / reviewer / ops 各自带工具）；
2. 执行能力由**共享 runner** 提供，而不是每个 agent 自己带 shell；
3. 编排者按任务动态选择 2–4 个角色，而不是每次全员上场。

所以真正的差距是：**共享执行服务 + 动态编排 + 交互层**，不是「少 3 个角色」。

## 二、七族分类（13 角色）

| 族 | 角色 | 职责 |
| --- | --- | --- |
| 指挥与交付 | `prima`、`thirteenth` | 规划、路由、澄清、验收 |
| 知识与文档 | `alpha-trion` | 本地文档、飞书知识库 |
| 侦察与架构 | `onyx-prime`、`quintus-prime` | 静态拓扑、接口骨架 |
| 版本控制与交付 | `vector-prime` | Git 历史、commit / push / PR |
| 实现 | `solus-prime`、`amalgamous` | 新功能/驱动、重构/移植 |
| 验证 | `micronus-prime`、`liege-maximo`、`alchemist` | L1 静态、L2 深度、测试与仿真 |
| 构建与运维 | `nexus-prime`、`megatronus` | 交叉编译、物理烧录与回滚 |

## 三、逐角色能力 / 权限 / 缺口

| 角色 | 族 | 可写 | 可执行 | 主要缺口 |
| --- | --- | --- | --- | --- |
| `prima` | 指挥 | 无 | 无 | 动态规划、预算、直接工具 |
| `thirteenth` | 指挥/交付 | 无 | 无 | 结构化澄清卡、webfetch、验收证据 |
| `alpha-trion` | 知识 | `AGENTS/README/CHANGELOG/docs/**` | 无（飞书走 Python 网关） | 原生飞书工具、检索、记忆层 |
| `onyx-prime` | 侦察 | 无 | `read/glob/grep` | 基本够用；可补 AST/依赖图 |
| `vector-prime` | 版本控制 | 通过 `vcs_broker` 提交 | git 读 + commit / push / PR | 破坏性 git 仍 deny；push/PR 需审批 |
| `quintus-prime` | 架构 | 配置/接口/`mkdir` | 无 | 依赖安装、真实脚手架 |
| `solus-prime` | 实现 | `src/app/firmware/drivers/bsp` | 无 | 构建/测试/运行 |
| `amalgamous` | 实现 | `src/lib/firmware/drivers` | 无 | 同 solus；可合并 |
| `micronus-prime` | 验证 | 无 | 无 | lint 执行（应由 runner 提供） |
| `liege-maximo` | 验证 | 无 | 无 | 无（只读是设计） |
| `alchemist` | 验证 | `tests/**` | 无 | 测试执行、覆盖率 |
| `nexus-prime` | 构建 | 构建配置 | `size/lsusb/tty` | `cmake/make/pio`、docker、CI |
| `megatronus` | 运维 | 无 | 烧录 `ask` | 宿主真实派单、审批代理、ssh/scp |

## 四、10-agent 归并方案（备选，暂不采用）

> 决策：**保留 13 个角色，不归并**。以下仅作为未来若需要进一步减少 handoff 的备选，不进入当前路线。

| 新角色 | 由谁合并 | 能力 | 代价 |
| --- | --- | --- | --- |
| `recon` | `onyx-prime` + `quintus-prime` | 静态拓扑 + 接口骨架 | 侦察与架构的边界变模糊 |
| `implementer` | `solus-prime` + `amalgamous` | 新功能 + 重构/移植 | 重构与新增的边界变模糊 |
| `reviewer` | `micronus-prime` + `liege-maximo` | L1 + L2（两种模式，可换模型） | L2 的独立对抗性下降 |
| `git` | `vector-prime` | Git 历史 + commit / push / PR | 只读考古属性让位于交付职责 |
| 保留 | `prima`、`thirteenth`、`alpha-trion`、`alchemist`、`nexus-prime`、`megatronus` | — | — |

归并后 10 个：`prima`、`thirteenth`、`alpha-trion`、`recon`、`implementer`、`reviewer`、`alchemist`、`nexus`、`git`、`megatronus`。

**建议**：如果目标是「减少 handoff」，这是合理路径；如果目标是「保持质量门禁的独立性」，建议保留 13 个名字，但用动态编排让每次只激活 2–4 个。两个目标可以并存：名字保留，激活收缩。

## 五、共享能力服务（关键补位）

不要给每个角色加 shell，而是由内核提供共享执行服务：

| 服务 | 能力 | 使用角色 |
| --- | --- | --- |
| `lint_runner` | `ruff/clang-tidy/cppcheck/clippy` | `micronus-prime` |
| `test_runner` | `pytest/ctest/cargo test/QEMU/Renode` | `alchemist` |
| `build_runner` | `cmake/make/pio/cargo build` | `nexus-prime` |
| `runtime_runner` | 启动应用、读日志、复现 | 调试类任务 |
| `pkg_broker` | 受控依赖安装 | `quintus/nexus` |
| `web_broker` | 受控检索/文档 | `thirteenth/onyx` |
| `vcs_broker` | commit/push/PR | `vector-prime` |
| `device_broker` | 烧录/回滚/串口 | `megatronus` |

每个服务都在沙箱中执行，返回结构化证据；角色只负责「请求 + 解读」，不直接持有 shell。

## 六、按任务实际激活的角色

| 任务 | 激活角色 | 数量 |
| --- | --- | --- |
| 写 `notes.md` | `alpha-trion`（或 quick lane） | 1 |
| 修一个 bug | `onyx` → `solus` → `reviewer` → `alchemist` → `git` | 4–6 |
| 新功能 | `thirteenth` → `alpha` → `onyx` → `quintus` → `solus` → `reviewer` → `alchemist` → `nexus` → `git` | 8–9 |
| 硬件任务 | 上一行 + `megatronus` | 9–10 |

## 七、结论

1. **已决定保留 13 个角色。** 不归并；通过动态编排让每次只激活 2–4 个，减少 handoff。先补共享执行服务、动态编排、交互层。
2. **如果必须减到 10**：按第四节的归并，但接受 L2 独立性和侦察/架构边界的下降。
3. **必须保留一个专职 Git agent**：`vector-prime` 改为版本控制与交付官，负责 commit / push / PR；不要让每个编码角色都碰 git。
4. **真正的能力缺口**不是「少 3 个角色」，而是「构建/测试/lint/运行/联网」没有归属——这些应由共享 runner 提供，而不是再加 agent。
