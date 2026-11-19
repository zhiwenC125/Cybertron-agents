# 阶段 N（Phase 4）：full-access 拦截器、standing grant、DSH Grant 与 seed_from

状态：Phase 4 已实现；本阶段完成后，intent-first 实施线的 6 个检查点全部交付。
日期：2026-11-19

## 交付范围

1. full-access（`danger-full-access`）执行拦截器；
2. 高危动作 `dangerous.confirm`：run 级授权之外，仍要节点级人工确认；
3. 飞书 `external.write` 的 standing grant（8h 滑动 / 24h 上限）；
4. DSH `cy_escalate` 入口（请求 Grant，宿主批准）；
5. `seed_from_run_id`：只复制计划形状，不复制证据。

## full-access 拦截器

`access_mode="danger-full-access"` 时，常规跨区域读写自动放行；以下动作必须再次确认：

| 类别 | 例子 |
| --- | --- |
| 文件系统 | `rm -rf`、`mkfs*`、`dd of=/dev/*`、`shred`、`truncate -s 0` |
| 数据库 | `DROP DATABASE/TABLE`、`TRUNCATE TABLE`、无 WHERE 的 `DELETE FROM` |
| Git | `git push --force`、`git reset --hard` |
| 系统 | `shutdown`、`reboot`、`kill -9 1`、`pkill` |
| 远程执行 | `curl ... | sh`、`wget ... | sh` |
| 核心配置 | 覆盖 `opencode.jsonc`、`.git/config`、`AGENTS.md`、shell rc、`/etc/**`、SSH 配置 |

流程：

```text
tool.execute.before
  → 拦截器 classify()
  → 普通动作：放行，写 interceptor.allowed
  → 高危动作：写 interceptor.confirm_required，提示 cy_escalate
  → cy_escalate(kind="dangerous.confirm", node_id="*", scope.command_sha256)
  → cy_ask 人工确认
  → 重试工具，拦截器消费 Grant 并放行
```

- `dangerous.confirm` 只作用一次，不能 `always`。
- 清单是代码常量，只有代码审查能修改。
- full-access 不覆盖 `intent.non_goals`、硬拒绝红线、角色 `never`、控制面工具。

## 飞书 standing grant

- 类型：`external.write`，`mode="standing"`，只发给 `alpha-trion`。
- scope：`space_id` / doc 范围；换空间重新授权。
- TTL：8 小时滑动（按最后一次 `grant.used` 续期），绝对上限 24 小时。
- 首次 `cy_ask` 批准后，后续写入不再逐次弹窗；每次写入仍记事件。
- 可撤销；`cy_state` 可见。

## DSH Grant 入口

- DSH preset 新增 `cy_escalate`，可创建 Grant 请求；
- DSH 没有 OpenCode 的权限卡，本 bundle 不会自行批准；宿主必须通过桥接 API 或外部流程批准；
- `cy_state` 会显示 pending grant；
- 未批准时 `before()` 返回 `needs_grant`，派发不会发生。

## seed_from_run_id

```json
{"seed_from_run_id": "<old-run>", "intent": {...}, "satisfies": {"n1": ["d1"]}}
```

- 只复制节点形状：objective、capability、role、依赖、scope、acceptance、verifiers、budget；
- 不复制 `status` / `satisfies` / `requires` / 证据；
- 新 intent 的 `satisfies` 映射需要重新给出；
- 旧 run 仍完整保留，可审计。

## 验证

```bash
python3 -m unittest tests.test_phase4_v6 -v
python3 -m unittest discover -s tests
node --test tests/v6_plugin_runtime.test.mjs tests/v6_plugin_hook.test.mjs tests/dsh_adapter_bridge.test.mjs
```

当前环境全绿：Python `319 tests OK (skipped=1)`，Node `15/15`。

## OpenCode 硬化（Phase 5）

见 [OpenCode 硬化文档](O-opencode-hardening.md)：Grant 自动推断、结构化高危分类、`cybertron v6` CLI、指标、v5 legacy 收口、0.8.0 版本与迁移。

## 限制

- 高危清单是已知模式的硬编码，不是完备语义分析；它降低风险，不替代宿主沙箱和人工确认。
- full-access 的自动放行与高危拦截只在 OpenCode 插件中接线；DSH 仍是单 persona + 外部审批。
- DSH 的 `cy_escalate` 只创建请求，approval 需要宿主外部完成。
- `seed_from_run_id` 不复制证据，不能减少新 run 的验收工作量。
