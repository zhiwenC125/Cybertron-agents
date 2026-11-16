# Cybertron v6 里程碑进度

| 里程碑 | 状态 | 证据文件 | 阻塞原因 | 下一动作 |
| --- | --- | --- | --- | --- |
| M0a | passed | `docs/stages/v6-m0a.json` | — | 本会话停止；下一会话从 M0b 开始 |
| M0b | passed | `docs/stages/v6-m0b.json` | — | 本会话停止；下一会话从 M0c 开始 |
| M0c | passed | `docs/stages/v6-m0c.json` | — | 本会话停止；下一会话从 M1 开始 |
| M1 | passed | `docs/stages/v6-m1.json` | — | 本会话停止；下一会话从 M2 开始 |
| M2 | passed | `docs/stages/v6-m2.json` | — | 本会话停止；下一会话从 M3 开始 |
| M3 | passed | `docs/stages/v6-m3.json` | — | 本会话停止；下一会话从 M4 开始 |
| M4 | passed | `docs/stages/v6-m4.json` | — | 本会话停止；下一会话从 M5 开始 |
| M5 | passed | `docs/stages/v6-m5.json` | — | v6 计划 M0–M5 完成；本会话停止 |

启动检查（2026-11-16）：`git status --short` 仅有本里程碑的进度文件；`python3 -m unittest discover -s tests` 为 112 tests OK。

门禁判定：以里程碑声明的 `required_gates` 为准。M0a 仅需自动门禁，`host: null` 不阻止其通过。M0a 验收为 121 tests OK；命令与输出哈希见 `v6-m0a.json`。

M0b 验收（2026-11-16）：135 tests OK；临时项目的真实子进程派发完成一次，越界写入一次并自动回滚。事件、命令、退出码、UTC 时间与哈希见 `v6-m0b.json` 和 `v6-m0b-integration-probe.json`。M0b 的 `required_gates` 不包含宿主卡片；宿主门禁属于 M0c。

M0c 自动门禁（2026-11-16）：148 tests OK，JavaScript 钩子测试 4 项通过；权限导出和 `r4` 的 `opencode2 debug config` 通过。`r3` 宿主失败记录保留在 `v6-m0c-host-r3-failure.json`；`r4` 使用独立 v6 插件 ID，并通过导出器禁用旧插件。

M0c 真实宿主门禁（2026-11-16）：`r4` 的 prima 会话创建一个 `doc.write` 节点，原生子代理卡片派给 alpha-trion，description 与 `cy_plan` 返回 card 完全相同；`cy_state(wait=true)` 返回 completed。`notes.md` 字节内容与 SHA-256、写入范围、四条事件、宿主子会话回执均核对通过。证据见 `v6-m0c-host-r4-acceptance.json`；`required_gates` 全部通过，状态改为 `passed`。本会话只完成 M0c；M1 留待下一会话。

M1 自动门禁（2026-11-16）：169 tests OK，JavaScript 钩子 4 项通过；目录七条不变量均有拒绝反例；角色权限经导出器生成，Markdown 与 JSON 一致，`opencode2 debug config` 通过。工具进程驱动的计划探针记录 1/1、4/4、9/9 节点/派单；语义计划测试分别覆盖单文件文档、四节点修 bug 模板和九节点硬件计划（硬件只做图校验，无设备操作）。命令、退出码、UTC 时间、输出 SHA-256 见 `v6-m1.json`，派单逐项回执见 `v6-m1-plan-shapes.json`。M1 的 `required_gates` 不包含新人工宿主门禁；M2 门禁事实接口保持 fail-closed。本会话只完成 M1；M2 留待下一会话。

M2 启动预检（2026-11-16）：工作区干净，169 tests OK；`cmake` 和 Apple `cc` 可用，但 `command -v clang-tidy` 与 `xcrun --find clang-tidy` 均失败。按总控 prompt 的“工具链缺失就停”条件，M2 标为 blocked，尚未开始功能实现；命令、退出码、UTC 时间与输出 SHA-256 见 `v6-m2.json`。不以 `cc` 或其他检查替代真实 `clang-tidy` 回执。

M2 恢复预检（2026-11-16）：用户安装 Homebrew LLVM 后，`/opt/homebrew/opt/llvm/bin/clang-tidy --version` 返回 23.1.5；169 tests OK。已添加门禁策略草稿与拒绝测试，但尚未接入 `cy_check` 或取得 lint/build 验收回执。临时 CMake 项目在 macOS 沙箱中两次于链接阶段返回 `Operation not permitted`，沙箱外控制组配置成功；按“连续两次失败指纹相同即停”条件停止，不将沙箱外结果充当门禁证据。M2 仍为 blocked，未提交实现，M3 未开始。

M2 本轮进展（2026-11-16）：定位到原沙箱的 `/dev` 全拒绝影响 Apple 工具链；新的固定检查配置仅为 `/dev/null`、`/dev/zero`、`/dev/random`、`/dev/urandom` 放行，保留网络禁用和临时目录外写入禁用。内核 `cy_check` 在临时 C 项目获得真实 `clang-tidy` 与 CMake 配置/构建回执，命令、退出码、UTC 与输出 SHA-256 见 `v6-m2-check-receipts.json`。175 项 Python 单测、4 项 JS 钩子测试及阶段 5 隔离验证通过。真实 OpenCode 宿主试运行在工具调用前遭遇 `provider.transport/ECONNREFUSED`，10 次重试均未连接模型服务，日志见 `v6-m2-host-provider-failure.jsonl`；未把 CLI 或模拟插件测试当作宿主门禁。风险下限尚未绑定宿主运行图，因此 M2 保持 blocked，未提交、未进入 M3。

M2 继续验收（2026-11-16）：已将实际 diff 的风险下限和 `cy_check` 回执绑定到宿主运行图；回执仅对生成时的工作区快照有效。C 代码变更的本地集成测试验证 lint/test/L2 下限、prima 无法标记下限测试门为 N/A，以及源码变化后 lint 回执失效。177 项 Python 单测、4 项 JS 测试、阶段 5 隔离验证、引擎自检和 `opencode2 debug config` 通过。真实 OpenCode 宿主第二次在模型调用阶段收到 `ECONNREFUSED`，45 秒内没有工具调用；按相同失败指纹停止重试。证据见 `v6-m2.json` 和 `v6-m2-host-retry.jsonl`。M2 仍为 blocked，人工宿主门禁尚未完成，M3 未开始。

M2 最终验收（2026-11-16）：确认 `HTTP_PROXY`/`HTTPS_PROXY` 指向无监听的本机 7897 端口；仅在临时宿主进程中移除代理变量，模型连接恢复。随后发现插件已加载但六个检查角色缺少 `cy_check` 宿主权限；已在 `registry.py` 中补齐，并通过导出器重生成 JSON/Markdown 配置，`opencode2 debug config` 通过。真实 OpenCode 宿主中，nexus-prime 的 `cy_check(build)` 产生 CMake 配置/构建零退出回执；micronus-prime 的 `cy_check(lint)` 产生 clang-tidy 零退出回执。另一真实 prima 会话派发 solus-prime 修改 `src/main.c`，内核从实际 diff 生成代码风险下限 `scope_guard/lint/test/review.l2.light`，对 `mark_not_applicable(test)` 的修订操作给出拒绝事件；随后 micronus-prime 在同一 run 上的 lint 回执使 lint 门禁通过，test/L2 仍待该测试任务后续处理。原始工具事件、运行账本、文件哈希和输出 SHA-256 经独立核验，见 `v6-m2-host-acceptance.json`。最终 179 项 Python 单测、4 项 JS 测试、阶段 5 隔离验证和引擎自检通过。M2 声明的门禁全部通过，状态改为 `passed`；本会话只完成 M2，M3 未开始。

M3 启动与停止（2026-11-16）：工作区干净，基线 179 tests OK。新增调度决策与受影响子图计算的四项单测，全部测试为 183 tests OK。共享工作目录探针复现并发安全冲突：两个写范围不重叠的节点各自保存全局快照，A 验证时将 B 合法写入的 `docs/b.md` 判为越界并删除。现有宿主桥接还使用单个 `snapshot.json` 和活动令牌，无法保持并发派单的独立证据。按总控 prompt 第 1 节“设计冲突立即停”停止，不接入生产派单，不提交、不开始 M4。命令、退出码、UTC 与输出 SHA-256 见 `v6-m3.json`。

M3 最终验收（2026-11-16）：将单次 run 快照拆为每个 `call_id` 独立快照，每个原生子代理在启动前通过宿主会话权限绑定到自己的 `write_scope`；并发完成时只排除与当前派单活动窗口重叠的 peer 写入，已完成的 peer 不能再掩盖后续越界。新增调度锁、Loop-1 重试/升格、L2 受影响子图重跑，以及 `cy_review_reject` 的 liege-maximo 专属权限。真实宿主发现并修复了一个真实阻塞：`cy_plan` 的 `kind` 枚举只允许 `task`，review 节点无法创建；改为 `task|review` 并加入回归断言。实际宿主验收覆盖：两个不相交写者并发完成且各自只拿到自己的文件（`concurrency-r2`）；首次尝试无产物被阻塞、重试成功（`loop1-r5`）；越界写 `docs/escape.md` 被宿主以 `permission.rejected` 拒绝且未落盘（`scope-exec-r1`）；真实 L2 发现 `docs/fix.md` 内容不符并拒绝，只有 fix/review/deliver 重新执行，unrelated 只派发一次（`l2-r6`）。独立核验脚本对回执、事件账本、父/子会话哈希、权限和产物哈希执行 70 项检查，全部通过。最终 191 项 Python 单测、1 项 JS 插件测试、阶段 5 隔离验证、引擎自检和 `opencode2 debug config` 通过。证据见 `v6-m3.json`、`v6-m3-host-acceptance.json`、`v6-m3-host-verification.json` 和 `v6-m3-command-records.json`；实现提交 `ed221c3`。M3 声明的门禁全部通过，状态改为 `passed`；本会话只完成 M3，M4 未开始。

M4 最终验收（2026-11-16）：Renode 1.17.0 与 OpenOCD 0.12.0 已安装；新增 `device_broker.py`（审批绑定设备/固件/擦写范围/回滚镜像、单次使用、超时记 `outcome_unknown` 且不自动重试、失败自动回滚）、`device_node.py`（`device_op` 节点事件链）、`profiles.py` 的 Renode `sim` 配置档，以及 `v6_m4_acceptance.py` 与独立核验脚本。206 项 Python 单测、4 项 JS 测试、阶段 5 隔离验证、引擎自检和 `opencode2 debug config` 通过。

M4 真机门禁（2026-11-16）：ST-LINK 首次读取曾连续两次在 `GET_VERSION`/`ENTER_SWD` 上 USB 超时，按停止条件停止；用 OpenOCD 连接恢复后 `st-flash` 正常。真实 run `m4-20261116t164233z` 中，用户授权 `m4-chat-016a1a46a496b4b8` 绑定新计划 `5d8bc0b7...`；preflight 64 KiB 为 `58e2a250...`，100 字节夹具为 `62554f5a...`，回滚 App 为 `bfa1af7b...`，只擦写 `0x08002000..0x0800FBFF`。烧录后 Bootloader 与 OTA 标志页未变，SRAM 标记 `0xC7B70001`、计数 `1→2`；回滚后完整 64 KiB 与 preflight 逐字节一致，独立重读同样为 `58e2a250...`。共 12 条 `st-flash` 回执、24 条事件，独立核验脚本 59/59 通过；证据见 `v6-m4.json`、`v6-m4-acceptance.json`、`v6-m4-device-events.jsonl`、`v6-m4-verification.json`、`v6-m4-stlink-failure.log` 和 `v6-m4-stlink-recovery.log`。M4 声明的门禁全部通过，状态改为 `passed`；实现与证据提交 `7e5b47e`。本会话只完成 M4，M5 未开始。

M5 本轮进展（2026-11-16）：新增 `cybertron/learning.py`（仅从全部节点 completed 的运行沉淀模板；复用经 `PlanGraph` 重新校验；多写者模板保留字面路径，单写者可用目标覆盖；`skip` 仅允许跳过只读分析节点并重接依赖）、`cybertron/metrics.py`（按事件账本计算节点、派发、重试、人工干预、门禁失败率与时长，输出面板和两次运行对比），并接入 `host_v6.py` 与 `host_v6_cli.py`：运行完成时记 `run.completed` 并沉淀模板，`cy_plan` 支持 `template_id`/`skip`，新增 `templates`/`metrics` 操作。`registry.py` 把 `cy_templates`/`cy_metrics` 授予 prima，导出器重生成根目录与 `cybertron_workspace_dist` 配置，`opencode2 debug config` 通过。OpenCode 插件新增 `cy_templates`/`cy_metrics` 与模板复用参数。

真实宿主学习门禁（OpenCode + 真实 DeepSeek 路由）：冷启动计划 2 个节点（read-only scan → doc.write），派发 2 次，调用 `cy_ask` 1 次；运行完成后沉淀模板。同一 request_class 的热启动通过 `cy_templates` 取得模板，`cy_plan(template_id=..., skip=["scan.static"])` 只保留 1 个 doc 节点，0 次人工提问；两次运行均 `completed`。对比：节点 2→1，人工干预 1→0，模板复用并由内核记录 `skipped_capabilities`。证据见 `v6-m5-host-acceptance.json`、`v6-m5-host-cold/warm-receipt.json`、`v6-m5-metrics.json` 与日志。

DSH 第二宿主：新增可安装 bundle `cybertron/dsh_adapter`（`@local/cybertron-dsh`），声明 `Cybertron v6` preset，仅在 preset 内挂载 `cy_plan`/`cy_state`/`cy_ask`/`cy_templates`/`cy_metrics`，通过 `bridge.js` 调用同一 Python 内核；manifest、patch、locale、图标、DETAIL 与真实内核桥接契约均有测试（`test_dsh_adapter_m5.py`、`dsh_adapter_bridge.test.mjs`）。用户授权继续后，`cybertron/dsh_adapter` 通过 `plugin_manager install_bundle` 安装进运行中的 desktop profile：`application=applied`、无 warnings，`preset-cybertron` 的 `fiberPhase=active`；临时 headless/web 测试 profile 验证组合后已删除。证据见 `v6-m5-dsh-load.json`。DSH 适配目前是单一 prima persona + cy_* 工具，尚未把 13 角色映射为 13 个 DSH preset，也未绑定 DSH 子会话写范围，该限制已写入 bundle 的 DETAIL。M5 门禁全部通过，状态改为 passed。

本轮验证：232 项 Python 单测、7 项 JS 测试、阶段 5 隔离验证、引擎自检和 `opencode2 debug config` 全部通过；命令、退出码、UTC 与 SHA-256 见 `v6-m5.json`。M0–M4 未改动。实现与证据提交 `566c318`。用户可在工作区新建 DSH 会话并选择 `Cybertron v6` preset 做 GUI 验收；真实模型会话属于使用验收，不再阻塞 M5 的加载门禁。
