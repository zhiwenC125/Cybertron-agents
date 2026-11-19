# 案例：OpenCode 最小文件任务（0.8.0）

日期：2026-11-19
宿主：OpenCode V2 (`2.3.0`)
模型：`deepseek/deepseek-flash`
安装：本地 payload 安装的全局 0.8.0

## 输入

在空目录 `/Users/alanbanana/cyto-demo` 中，用 `prima` 执行：

> 在当前目录创建 notes.md，写入 “Cybertron 0.8.0 demo”，完成后告诉我文件路径。

## 结果

- run：`dfbb2f13-4d40-5171-bfbd-c55e1ef0cc3e`
- slug：`create-notes-md-v3`
- 状态：`completed`
- 节点：`write_notes` / `alpha-trion` / `doc.write` / `write_scope=["notes.md"]`
- 门禁：`scope_guard` 通过
- 文件：`/Users/alanbanana/cyto-demo/notes.md`
- 内容：`Cybertron 0.8.0 demo`（单行，行尾换行）

## 账本时间线

| UTC | 事件 |
| --- | --- |
| 13:02:02 | `plan.created` |
| 13:02:23 | `plan.reviewed`（approved） |
| 13:02:26 | `dispatch.started` |
| 13:02:27 | `dispatch.returned` / `dispatch.bound` |
| 13:02:34 | `node.completed`（artifacts.notes.md SHA-256） |
| 13:02:34 | `gate.required`（scope_guard） |
| 13:02:34 | `run.completed` |

## 查询结果

```text
$ cybertron v6 show dfbb2f13-4d40-5171-bfbd-c55e1ef0cc3e
run: dfbb2f13-4d40-5171-bfbd-c55e1ef0cc3e
slug: create-notes-md-v3
status: completed
access_mode: workspace-write
parent: -
superseded_by: -
intent: 在 workspace root 创建 notes.md，单行内容 Cybertron 0.8.0 demo
coverage: 1/1
  [OK] d1: notes.md 内容为 Cybertron 0.8.0 demo
nodes:
  write_notes  completed  alpha-trion
grants: 0
```

## 说明

- 这次没有 `cy_ask`：任务在 `workspace-write` 下，`write_scope` 内写入不需要 Grant；
- `alpha-trion` 的写入由 `scope_guard` 校验，节点完成后 `intent d1` 自动满足；
- `cy_state(wait=true)` 正常结算，没有再出现 11 月 19 日第一次试用中的 `running` 卡住问题；
- `notes.md` 的 SHA-256 记录在 `events.jsonl` 的 `node.completed.artifacts` 中。

## 复现

```bash
mkdir -p ~/cyto-demo && cd ~/cyto-demo
opencode2 run --standalone --agent prima \
  --model deepseek/deepseek-flash --format json --archived \
  "在当前目录创建 notes.md，写入 “Cybertron 0.8.0 demo”，完成后告诉我文件路径。"

cybertron v6 runs
cybertron v6 show <run-id>
```
