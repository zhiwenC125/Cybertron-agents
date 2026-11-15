# Cybertron v6 里程碑进度

| 里程碑 | 状态 | 证据文件 | 阻塞原因 | 下一动作 |
| --- | --- | --- | --- | --- |
| M0a | passed | `docs/stages/v6-m0a.json` | — | 本会话停止；下一会话从 M0b 开始 |
| M0b | pending | — | — | 下一会话实施写范围守卫与单节点内核 |
| M0c | pending | — | M0b 未通过 | 等待 M0b 门禁 |
| M1 | pending | — | M0c 未通过 | 等待 M0c 门禁 |
| M2 | pending | — | M1 未通过 | 等待 M1 门禁 |
| M3 | pending | — | M2 未通过 | 等待 M2 门禁 |
| M4 | pending | — | M3 未通过 | 等待 M3 门禁 |
| M5 | pending | — | M4 未通过 | 等待 M4 门禁 |

启动检查（2026-11-16）：`git status --short` 仅有本里程碑的进度文件；`python3 -m unittest discover -s tests` 为 112 tests OK。

门禁判定：以里程碑声明的 `required_gates` 为准。M0a 仅需自动门禁，`host: null` 不阻止其通过。M0a 验收为 121 tests OK；命令与输出哈希见 `v6-m0a.json`。
