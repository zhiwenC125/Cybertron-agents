# 后续阶段 B：离线 RunStore 与可恢复账本

状态：本地开发验收通过；尚无真实宿主自动接力。

## 交付内容

- 项目级 `.cybertron/sessions/<session_id>/runs/<run_id>/` 保存版本化元数据、`events.jsonl` 和 `ledger.json`。`session_id`、`run_id`、事件 ID 均为不可变 UUID。运行目录被 `.gitignore` 排除。
- 事件先写入并同步到磁盘，快照再原子替换。事件记录九步账本状态及哈希；快照只是投影。快照缺失、过期或无效时，`resume` 能依据完整事件日志重建。
- 同一 run 使用非阻塞独占文件锁。连续序号、重复事件、截断尾部、未知 schema、事件身份和哈希均经过校验；损坏日志会阻止恢复。配置、运行时代码或工作区改变时，旧 run 可查看但不能继续推进。
- 提供 Python CLI：`cybertron run create/show/verify/resume`。本阶段的 `resume` 只核验并修复快照，不调用模型、不派单，也不重试任何副作用。当前同步 `LedgerStep` API 保持兼容。

## 使用方式

```bash
python3 -m cybertron.installer run create "开发一个离线任务" --project .
python3 -m cybertron.installer run show <run_id> --project .
python3 -m cybertron.installer run verify <run_id> --project .
python3 -m cybertron.installer run resume <run_id> --project .
```

`show` 显示当前阶段、下一个角色、事件序号和快照状态；`verify` 返回 `verified` 布尔值；`resume` 只完成离线恢复。当前一次 `create` 自动新建一个 session；同一 session 内创建多个 run、slug 改名和列表查询属于阶段 C。

## 恢复判定

| 情况 | 处理 |
| --- | --- |
| 事件完整、快照落后或损坏 | `verify` 报未通过；`resume` 从事件重建快照 |
| 事件截断、重复、身份不符或未知 schema | 阻断；不跳过事件 |
| 快照序号超前或 schema 未知 | 阻断，避免掩盖存储版本冲突 |
| OpenCode 配置、运行时代码或工作区改变 | 可只读查看；阻止 `resume` 与新的状态转换 |
| 派单已发出而回执缺失 | 本阶段不自动重试；阶段 D 定义 `outcome_unknown` 核对流程 |

账本事件包含原始任务文字，属于本地运行态。不要把 `.cybertron/`、模型对话、凭证或固件备份加入 Git 或安装包。

## 验收证据

结构化回执见 [`B-runstore-acceptance.json`](B-runstore-acceptance.json)。测试覆盖进程重启后的 CLI 读取、九步进度与返工次数、事件写入后快照失败、截断和重复事件、未知 schema、配置变化、并发写入以及符号链接。阶段 5 隔离测试继续通过；在禁止读取 `/dev/urandom` 的 macOS 沙箱内，RunStore 测试使用确定性测试 UUID，真实 UUIDv4 及 CLI 由宿主离线测试覆盖。

## 下一阶段接口

阶段 C 在既有稳定 ID 之上增加 slug 索引、多个 run 和审计查询，不迁移已有事件目录。阶段 D 为派单、证据和副作用增加可核验来源与审批绑定。运行时代码摘要发生变化后，旧 run 可查看但需兼容性迁移才能继续推进。
