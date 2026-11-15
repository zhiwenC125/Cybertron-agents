# Cybertron v6 里程碑进度

| 里程碑 | 状态 | 证据文件 | 阻塞原因 | 下一动作 |
| --- | --- | --- | --- | --- |
| M0a | passed | `docs/stages/v6-m0a.json` | — | 本会话停止；下一会话从 M0b 开始 |
| M0b | passed | `docs/stages/v6-m0b.json` | — | 本会话停止；下一会话从 M0c 开始 |
| M0c | pending | — | — | 下一会话实施宿主原生 task 钩子和最小 cy_* 工具 |
| M1 | pending | — | M0c 未通过 | 等待 M0c 门禁 |
| M2 | pending | — | M1 未通过 | 等待 M1 门禁 |
| M3 | pending | — | M2 未通过 | 等待 M2 门禁 |
| M4 | pending | — | M3 未通过 | 等待 M3 门禁 |
| M5 | pending | — | M4 未通过 | 等待 M4 门禁 |

启动检查（2026-11-16）：`git status --short` 仅有本里程碑的进度文件；`python3 -m unittest discover -s tests` 为 112 tests OK。

门禁判定：以里程碑声明的 `required_gates` 为准。M0a 仅需自动门禁，`host: null` 不阻止其通过。M0a 验收为 121 tests OK；命令与输出哈希见 `v6-m0a.json`。

M0b 验收（2026-11-16）：135 tests OK；临时项目的真实子进程派发完成一次，越界写入一次并自动回滚。事件、命令、退出码、UTC 时间与哈希见 `v6-m0b.json` 和 `v6-m0b-integration-probe.json`。M0b 的 `required_gates` 不包含宿主卡片；宿主门禁属于 M0c。
