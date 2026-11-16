# Cybertron v6 里程碑进度

| 里程碑 | 状态 | 证据文件 | 阻塞原因 | 下一动作 |
| --- | --- | --- | --- | --- |
| M0a | passed | `docs/stages/v6-m0a.json` | — | 本会话停止；下一会话从 M0b 开始 |
| M0b | passed | `docs/stages/v6-m0b.json` | — | 本会话停止；下一会话从 M0c 开始 |
| M0c | passed | `docs/stages/v6-m0c.json` | — | 本会话停止；下一会话从 M1 开始 |
| M1 | passed | `docs/stages/v6-m1.json` | — | 本会话停止；下一会话从 M2 开始 |
| M2 | passed | `docs/stages/v6-m2.json` | — | 本会话停止；下一会话从 M3 开始 |
| M3 | pending | — | M2 未通过 | 等待 M2 门禁 |
| M4 | pending | — | M3 未通过 | 等待 M3 门禁 |
| M5 | pending | — | M4 未通过 | 等待 M4 门禁 |

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
