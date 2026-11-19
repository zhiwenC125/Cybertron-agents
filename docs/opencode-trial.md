# OpenCode 0.8.0 试用清单

这份清单用于在真实 OpenCode 中验收 intent-first 编排。先不要升级 DSH。

## 前置

```bash
opencode2 debug config
opencode2 debug agents   # 应看到 13 个 Cybertron 角色
```

在一个空目录启动 `opencode2`，按 **Shift+Tab** 选择 `prima`。

## 场景 A：最小文档任务

输入：

> 在当前目录创建 notes.md，写入 “Cybertron 0.8.0 trial”，并告诉我文件路径。

预期：

1. prima 派 thirteenth 澄清；如果需求已经足够明确，thirteenth 直接给出 intent + done；
2. `cy_plan` 创建 run，`cy_plan_review` 通过；
3. 原生 subagent 卡片派给 alpha-trion；
4. 完成后 `notes.md` 存在，`cy_state` 里 `intent_coverage` 的 `d1` 为 satisfied。

检查：

```bash
cybertron v6 runs
cybertron v6 show <run-id>
```

## 场景 B：一次 Grant 拒绝

让任务需要项目外写入或 `device` Grant，例如：

> 在 `/tmp/cyto-out/result.txt` 写一行测试内容。

预期：

- `before()` 返回 `needs_grant`，prima 调 `cy_escalate`；
- `cy_ask` 弹出人工审批卡；
- 选择拒绝后，节点不派发，`cybertron v6 grants <run-id>` 显示 `denied`。

## 场景 C：supersede

先创建场景 A 的 run，不完成它，然后输入：

> 补充验收条件：notes.md 必须包含版本号；用新的 run 执行。

预期：

- 旧 run 状态 `superseded`，新 run 有 `parent_run_id`；
- `cybertron v6 lineage <new-run-id>` 能看到父子链。

## 场景 D：full-access 高危确认

如果确实需要使用 `danger-full-access`：

- 普通跨区域读写应直接放行；
- `rm -rf` 等动作应被拦截，要求 `cy_escalate(kind=dangerous.confirm)` + `cy_ask`；
- 拒绝后命令不执行。

## 记录

试用后把以下内容发回：

- `opencode2 debug agents` 的角色数；
- 场景 A 的 `run_id` 与 `cybertron v6 show` 输出；
- 场景 B 的 Grant 状态；
- 场景 C 的 lineage 输出；
- 任何模型没有按提示调用 `cy_plan` / `cy_ask` 的原始对话。

## 注意

- 0.8.0 尚未发布到 npm/PyPI；当前全局安装来自本地 payload。
- DSH 仍是实验性宿主，先不要用它验收本清单。
