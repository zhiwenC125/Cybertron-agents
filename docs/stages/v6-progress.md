# Cybertron v6 里程碑进度

| 里程碑 | 状态 | 证据文件 | 阻塞原因 | 下一动作 |
| --- | --- | --- | --- | --- |
| M0a | passed | `docs/stages/v6-m0a.json` | — | 本会话停止；下一会话从 M0b 开始 |
| M0b | passed | `docs/stages/v6-m0b.json` | — | 本会话停止；下一会话从 M0c 开始 |
| M0c | passed | `docs/stages/v6-m0c.json` | — | 本会话停止；下一会话从 M1 开始 |
| M1 | passed | `docs/stages/v6-m1.json` | — | 本会话停止；下一会话从 M2 开始 |
| M2 | pending | — | M1 未通过 | 等待 M1 门禁 |
| M3 | pending | — | M2 未通过 | 等待 M2 门禁 |
| M4 | pending | — | M3 未通过 | 等待 M3 门禁 |
| M5 | pending | — | M4 未通过 | 等待 M4 门禁 |

启动检查（2026-11-16）：`git status --short` 仅有本里程碑的进度文件；`python3 -m unittest discover -s tests` 为 112 tests OK。

门禁判定：以里程碑声明的 `required_gates` 为准。M0a 仅需自动门禁，`host: null` 不阻止其通过。M0a 验收为 121 tests OK；命令与输出哈希见 `v6-m0a.json`。

M0b 验收（2026-11-16）：135 tests OK；临时项目的真实子进程派发完成一次，越界写入一次并自动回滚。事件、命令、退出码、UTC 时间与哈希见 `v6-m0b.json` 和 `v6-m0b-integration-probe.json`。M0b 的 `required_gates` 不包含宿主卡片；宿主门禁属于 M0c。

M0c 自动门禁（2026-11-16）：148 tests OK，JavaScript 钩子测试 4 项通过；权限导出和 `r4` 的 `opencode2 debug config` 通过。`r3` 宿主失败记录保留在 `v6-m0c-host-r3-failure.json`；`r4` 使用独立 v6 插件 ID，并通过导出器禁用旧插件。

M0c 真实宿主门禁（2026-11-16）：`r4` 的 prima 会话创建一个 `doc.write` 节点，原生子代理卡片派给 alpha-trion，description 与 `cy_plan` 返回 card 完全相同；`cy_state(wait=true)` 返回 completed。`notes.md` 字节内容与 SHA-256、写入范围、四条事件、宿主子会话回执均核对通过。证据见 `v6-m0c-host-r4-acceptance.json`；`required_gates` 全部通过，状态改为 `passed`。本会话只完成 M0c；M1 留待下一会话。

M1 自动门禁（2026-11-16）：169 tests OK，JavaScript 钩子 4 项通过；目录七条不变量均有拒绝反例；角色权限经导出器生成，Markdown 与 JSON 一致，`opencode2 debug config` 通过。工具进程驱动的计划探针记录 1/1、4/4、9/9 节点/派单；语义计划测试分别覆盖单文件文档、四节点修 bug 模板和九节点硬件计划（硬件只做图校验，无设备操作）。命令、退出码、UTC 时间、输出 SHA-256 见 `v6-m1.json`，派单逐项回执见 `v6-m1-plan-shapes.json`。M1 的 `required_gates` 不包含新人工宿主门禁；M2 门禁事实接口保持 fail-closed。本会话只完成 M1；M2 留待下一会话。
