# 阶段 L（Phase 2）：Grant 核心与派发授权

> 历史阶段记录，正文反映当时的版本和验证范围。当前行为见 [开发状态](../../DEVELOPMENT_PLAN.md)。

状态：Phase 2 已实现；未改变 full-access 拦截器与飞书 standing grant（属于后续）。
日期：2026-11-19

## 交付范围

1. `Grant` 契约：请求、批准、拒绝、撤销、消费；
2. 节点 `requires` 声明所需授权；
3. `before()` 在派发前检查授权，缺失时返回 `needs_grant`；
4. OpenCode `cy_escalate` + `cy_ask` 的人工批准链路；
5. 按角色 `escalatable` 上限拒绝越权申请；
6. 事件账本记录 `grant.requested/granted/denied/used/revoked`；
7. `cy_state` 暴露 `grants` / `active_grants`。

## Grant 对象

```json
{
  "grant_id": "uuid",
  "request_id": "uuid",
  "run_id": "uuid",
  "node_id": "n3",
  "kind": "device",
  "scope": {"device_id": "stm32f103"},
  "constraints": {"firmware_sha256": "...", "rollback_sha256": "..."},
  "mode": "once",
  "max_uses": 1,
  "issued_by": "human",
  "issued_via": "opencode.permission",
  "expires_utc": "2026-11-19T10:00:00+00:00",
  "binding_sha256": "..."
}
```

- 类型：`read.expand`、`network.read`、`write.expand`、`exec.expand`、`pkg.install`、`vcs.write`、`vcs.push`、`external.write`、`deploy`、`device`。
- `mode=once` 默认单次；`mode=run` 最多 10 次，仍绑定同一 run/node/kind/scope。
- TTL 默认 8 小时，绝对上限 24 小时；过期后 `status=expired`。
- 只有 `issued_by=human` 能创建授权；`grant_approve(approver="model")` 直接拒绝。

## 节点声明

```json
{"node_id": "n3", "requires": ["device"], "...": "..."}
```

`PlanNode.requires` 在 `PlanGraph` 校验时只接受 `GRANT_KINDS`；重复项拒绝。

## 派发链路

```text
before() 发现 requires 没有有效 Grant
  → 返回 {rejected:true, needs_grant:[...], node_id}
  → prima 调用 cy_escalate(run_id, node_id, kind, scope, constraints)
  → 得到 pending request_id
  → prima 调用 cy_ask（宿主原生权限卡）
  → 人类批准 → 插件 bridge('grant_approve')
  → 重新派发 → before() 消费 Grant → dispatch.started
```

- `cy_escalate` 只创建请求，不批准；批准只发生在宿主人工回调。
- `cy_ask` 批准后若当前 session 有 pending request，插件调用 `grant_approve`。
- `before()` 先检查所有 `requires` 再消费，避免部分授权被消耗。

## 角色上限

`grant_request` 会读取节点的 role，并用 [cybertron/authority.py](../../cybertron/authority.py) 的 `escalatable` 列表拒绝越权申请。例如：

- `vector-prime` 可申请 `vcs.write` / `vcs.push`；
- `megatronus` 可申请 `device` / `deploy`；
- `prima` 不能申请任何 Grant；
- `solus-prime` 不能申请 `device`。

## 验证

```bash
python3 -m unittest tests.test_grants_v6 tests.test_authority_v6 -v
python3 -m unittest discover -s tests
node --test tests/v6_plugin_runtime.test.mjs tests/v6_plugin_hook.test.mjs tests/dsh_adapter_bridge.test.mjs
```

当前环境全绿：Python `319 tests OK (skipped=1)`，Node `15/15`。

## 限制

- `before()` 只检查节点显式声明的 `requires`；尚未根据 `device_op` / `external_scope` 自动推断必需 Grant，因此计划作者必须声明。
- DSH 已有 `cy_escalate` 请求入口，但没有 OpenCode 的 `cy_ask` 权限卡；Grant 需要宿主通过桥接 API 或外部流程批准。
- 飞书 standing grant、full-access 拦截器、`dangerous.confirm` 已在 Phase 4 实现，见 [N-phase4.md](N-phase4.md)。
- `grant_approve` 的“人类”身份由调用方传入，桥接层必须只把它暴露给宿主审批回调；当前 OpenCode 链路是 `cy_ask` 权限卡。
