# 阶段 O（OpenCode 硬化）：自动推断、CLI、指标、v5 收口与 0.8.0

状态：OpenCode 侧 6 项硬化已实现；版本已 bump 到 `0.8.0`，**尚未发布渠道**。
日期：2026-11-19

## 1. Grant 自动推断

新增 [cybertron/toolgate.py](../../cybertron/toolgate.py)：

| 具体动作 | 推断 Grant |
| --- | --- |
| `git push` | `vcs.push` |
| `git add/commit/tag` | `vcs.write` |
| `openocd` / `esptool` / `st-flash` / `pio run -t upload` | `device` |
| `docker push` / `kubectl apply` / `ssh` / `scp` / `rsync` | `deploy` |
| `pip/npm/pnpm/yarn/cargo install` | `pkg.install` |
| `curl` / `wget` | `network.read` |
| 项目外 `write`/`edit` | `write.expand` |

OpenCode 插件在 `tool.execute.before` 调用 `gate_tool`：

- 缺 Grant → 阻止执行，提示 `cy_escalate` + `cy_ask`；
- 有 Grant → 消费一次并放行；
- 与节点显式 `requires` 互补，不再依赖计划作者记得声明。

## 2. 高危清单结构化

[cybertron/interceptor.py](../../cybertron/interceptor.py) 从纯正则升级为：

- `shlex` token 级判断：`rm -r -f`、`git push -f`、`git reset --hard`、`shutdown`、`kill -9 1`；
- 正则兜底：SQL `DROP/TRUNCATE/DELETE`、`dd of=/dev/*`、`mkfs`、`curl | sh`；
- 写 `write/edit` 时检查核心配置路径。

它不是完备语义分析，但比单条正则更难被参数换序绕过。

## 3. `cybertron v6` 查询 CLI

新增 [cybertron/v6_cli.py](../../cybertron/v6_cli.py)：

```bash
cybertron v6 runs
cybertron v6 show <run-id>
cybertron v6 grants <run-id>
cybertron v6 lineage <run-id>
```

- `runs`：slug、status、intent 覆盖、parent/superseded；
- `show`：Intent、done 证据、节点、Grant 摘要；
- `grants`：kind、node、status、mode、uses、expires；
- `lineage`：父链。
- npm CLI 也支持 `cybertron v6 ...`（透传 Python 运行时）。

## 4. 指标

`cybertron.metrics` 新增：

- `grants_requested/granted/denied/used`；
- `interceptor_allowed`；
- `confirm_required/confirmed`。

`cy_metrics` 面板和 aggregate 都已展示；长任务下 `interceptor.allowed` 事件量仍需观察。

## 5. v5 收口

- `cybertron run/session/workflow` 仍可用，但执行前打印 legacy 警告；
- 帮助文本标记 `v5 legacy`；
- 新查询与操作统一走 `cybertron v6` 与 OpenCode 内 `cy_plan`；
- v5 代码与旧 UUID 目录未删除，保留兼容与审计；后续大版本再下线。

## 6. 版本、迁移、E2E、打包

- 版本：`0.8.0`（`package.json`、`pyproject.toml`、`install.sh`、`DEFAULT_REF` 已对齐）；
- 发布说明：[v0.8.0](../releases/v0.8.0.md)；
- 迁移：[0.7 → 0.8](../migrations/0.7-to-0.8.md)；
- 真实宿主配置校验：
  - `opencode2 debug config` 退出 0；
  - `opencode2 debug agents` 退出 0，加载 13 个 Cybertron 角色；
- payload 已重新生成；npm/PyPI/GitHub Release **尚未发布**，需要维护者凭据与发布窗口。

## 首次真实试用发现与修复（2026-11-19）

在 `/Users/alanbanana/cyto-trial` 的真实试运行中，`notes.md` 成功写入，但 run 卡在 `running`。定位到三个问题并已修复：

1. **单节点状态被 intent 降级为 blocked**：节点仍在 `running`、有 active dispatch 时，单节点结果覆盖逻辑因为 `intent_blockers` 把 status 改成 `blocked`；`cy_state(wait=true)` 只在 `running` 时等待，于是永远不结算。修复：running 节点不再被降级；`cy_state` 在存在 active dispatch 时也等待并 settle。
2. **规划子会话被误判为派发子会话**：thirteenth 创建 run 后，同一子会话刷新 context 时 `parentRun` 已存在，但它是规划子会话，没有 node binding，报 `Native child has no verified Cybertron node binding`。修复：记录 `planner/<child session>`，context hook 优先按规划子会话处理。
3. **能力发现困难**：thirteenth 不知道 capability → role 映射，连续猜 `builder`/`worker` 等，12 步耗尽。修复：新增 `cy_capabilities` 工具，规划提示词要求先查询。

修复后重新安装全局 0.8.0，并复跑真实 OpenCode 任务：

- 第二次 run：`a566e257-920b-5a2a-86fe-fe74e678f7d1`，`status=completed`；
- 单节点 `write_notes`（alpha-trion / doc.write）完成，`scope_guard` 通过；
- `notes.md` 内容为 `Cybertron 0.8.0 fix2 trial`；
- `cy_state(wait=true)` 能正常结算，不再卡 `running`。

另外确认：`workspace-write` 任务**不需要** `cy_ask`。`cy_ask` 只用于 Grant、项目外写和危险动作；普通项目内写入由节点 `write_scope` + `scope_guard` 控制。

最小成功案例见 [`docs/cases/opencode-minimal-file.md`](../cases/opencode-minimal-file.md)。

## 验证

```bash
python3 -m unittest discover -s tests        # 317 tests OK (skipped=1)
node --test ...                              # 15/15 pass
python3 cybertron_primes_engine.py           # PASS
python3 -m cybertron.stage5_verify           # PASS
opencode2 debug config                       # exit 0
opencode2 debug agents                       # exit 0, 13 roles
```

## 清理

- 删除已废弃探针：`cybertron/opencode_readonly.py`、`opencode_l2_probe.py`、`opencode_run.py`；
- 删除一次性交接文档 `docs/stages/v6-m0c-host-handoff.md`；
- 删除此前的 `design/intent-first-authority-matrix.md`；
- 移除生成的 `payload/` 与 `cybertron_workspace_dist/`；
- v5 `run/session/workflow` 仍保留（`stage5_verify`、引擎自检和测试依赖），仅标 legacy 并打印提示；删除它们需要单独的破坏性迁移。

## 仍未完成

- 真实模型 E2E（完整软件任务、Grant 批准/拒绝、supersede）尚未在宿主中跑；
- npm/PyPI/GitHub Release 未发布；
- v5 代码未删除，仅 legacy 标记；
- `cybertron v6 --help` 仍受顶层 REMAINDER 影响，需要 `cybertron v6 runs --help` 查看子命令帮助。
