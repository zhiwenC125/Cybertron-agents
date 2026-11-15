# 后续阶段 C：session、slug 与审计查询

状态：本地开发验收通过；运行态仍只保存在项目本机。

## 交付内容

- `cybertron session create/list/show/rename/archive/unarchive` 管理 session 的可读 slug、标题与归档状态。目录和事件继续使用不可变 `session_id`；改名只更新 `session.json`，旧 slug 作为 alias 保留。
- `cybertron run create <request> --session <slug>` 在已有 session 下新建 run；`run list --session <slug>` 查询多次 run 的阶段、状态和事件序号。阶段 B 生成的旧 session 可用 UUID 查看并重命名，不移动事件目录。
- slug 统一为 1–48 个 ASCII 小写字母、数字和连字符；空格/下划线归一为连字符。大小写冲突、保留字、路径穿越和符号链接均拒绝。创建与改名持有 session 索引锁，防止并发重名。
- 归档后的 session 保留查询能力，禁止新增 run；取消归档后可以继续创建。默认无限期本地保留，不自动上传或删除。导出与删除尚无自动命令：导出应由用户明确指定目标，并避免包含凭证或固件；删除应要求明确 session ID 和备份确认，放在后续实现。

## 使用方式

```bash
python3 -m cybertron.installer session create motor-control --title "电机控制" --project .
python3 -m cybertron.installer run create "检查 PWM 驱动" --session motor-control --project .
python3 -m cybertron.installer run list --session motor-control --project .
python3 -m cybertron.installer session rename motor-control drive-control --project .
python3 -m cybertron.installer session show motor-control --project .
python3 -m cybertron.installer session archive drive-control --project .
```

`session list/show` 返回 ID、slug、标题、别名、归档状态与 run 数量。`run list` 返回每次 run 的当前阶段、快照及配置状态。所有数据仍位于被 Git 忽略的 `.cybertron/`。

## 验收与限制

结构化回执见 [`C-session-acceptance.json`](C-session-acceptance.json)。测试覆盖多个 run、重命名后旧入口、大小写冲突、归档/取消归档、非法输入、符号链接和 CLI。更新阶段 C 的运行时代码会使阶段 B 旧 run 的代码摘要不匹配；它们仍可只读查看，但在提供显式迁移前不能自动恢复执行。没有调用外部模型、飞书或硬件。

## 下一阶段接口

阶段 D 在稳定的 session/run/dispatch/attempt 标识上记录证据来源、审批对象和副作用生命周期；归档只控制新增 run，不替代审批。若阶段升级改变运行时代码摘要，旧 run 保持只读，直到提供显式兼容迁移。
