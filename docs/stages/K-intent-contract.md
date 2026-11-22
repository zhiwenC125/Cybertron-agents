# 阶段 K（Phase 1）：Intent 契约与完成对账

> 历史阶段记录，正文反映当时的版本和验证范围。当前行为见 [开发状态](../../DEVELOPMENT_PLAN.md)。

状态：Phase 1 + 1.5a + 1.5b 已实现；未改变任何角色权限、Grant 或升权行为。
日期：2026-11-19

## 交付范围

本阶段只做三件事：

1. 把“用户要什么、什么算完成”变成计划里的一等公民（`Intent`）；
2. 每个节点声明它覆盖哪条 done（`satisfies`），计划评审检查覆盖与禁止项；
3. 完成判定从“节点全绿”改为“每条 done 都有真实证据”。

权限矩阵、Grant、full-access 拦截器属于后续阶段。

## 数据模型

```json
{
  "goal": "把 README 的安装段改成 pipx",
  "source": "chat",
  "confirmed": true,
  "done": [
    {"id": "d1", "criterion": "README 含 pipx 安装段", "evidence": "artifact"},
    {"id": "d2", "criterion": "命令示例可以解析", "evidence": "test"}
  ],
  "non_goals": ["不改 CI 配置"],
  "forbidden_capabilities": ["device"],
  "forbidden_paths": ["tests/**"]
}
```

- `done` 至少一条；`id` 唯一，匹配 `[a-z][a-z0-9_-]{0,31}`。
- `evidence` 取 `artifact` / `test` / `review` / `receipt`。
- `confirmed` 必须在创建 run 时为 `true`；未确认的 intent 直接被拒绝，不进入评审。
- `forbidden_capabilities` 和 `forbidden_paths` 由评审强制。

节点新增可选字段：

```json
{"satisfies": ["d1"]}
```

`PlanGraph.validate()` 会拒绝：

- 没有 intent 却声明 `satisfies`；
- `satisfies` 指向不存在的 done id；
- 重复的 done id 或未知字段。

## 计划评审

`cy_plan_review` 增加：

| 检查 | 结果 |
| --- | --- |
| 某条 done 没有任何节点 `satisfies` | blocking `intent.done.uncovered` |
| 节点 capability 在 `forbidden_capabilities` | blocking `intent.capability` |
| 节点 write/external scope 命中 `forbidden_paths` | blocking `intent.path` |
| `confirmed=false` | 创建时直接拒绝（旧 run 若已有 false 仍只告警） |

计划缺 done 覆盖时，评审不通过，`review_current=false`，派发被拒。

## 完成判定

`cy_state` 新增：

```json
{
  "intent": {...},
  "intent_coverage": [
    {"id": "d1", "criterion": "...", "evidence": "artifact",
     "covered_by": ["n1"], "satisfied_by": ["n1"],
     "satisfied": true, "reason": null}
  ],
  "intent_blockers": []
}
```

证据规则（Phase 1）：

| evidence | 满足条件 |
| --- | --- |
| `artifact` | 覆盖节点完成，且 `node.completed` 带非空 `artifacts` |
| `test` | 覆盖节点完成，且有**绑定到该节点**的 `test`/`sim` `gate.check` 通过 |
| `review` | 覆盖节点是 review 节点且已完成 |
| `receipt` | 覆盖节点完成（宿主回执存在） |

任何一条未满足：`status=blocked`，`intent_blockers` 给出原因，不会写 `run.completed`；节点都完成但仍缺证据时，账本追加一次 `intent.unmet` 事件。

## 使用方式

`cy_plan` / DSH `cy_plan` payload：

```json
{
  "objective": "把 README 的安装段改成 pipx",
  "intent": {
    "goal": "把 README 的安装段改成 pipx",
    "confirmed": true,
    "done": [
      {"id": "d1", "criterion": "README 含 pipx 安装段", "evidence": "artifact"}
    ]
  },
  "node": {
    "node_id": "n1", "kind": "task", "capability": "doc.write",
    "role": "alpha-trion", "objective": "改写 README 安装段",
    "write_scope": ["README.md"],
    "acceptance": ["安装段使用 pipx"],
    "verifiers": ["scope_guard"],
    "satisfies": ["d1"]
  }
}
```

模板 seed（`template` / `template_id`）可以携带 intent，但必须同时提供顶层 `satisfies` 映射：

```json
{"template_id": "bug-fix-xxxx", "intent": {...},
 "satisfies": {"scan-static": ["d1"], "fix": ["d2"], "review": ["d2"]}}
```

省略映射会在创建时直接报错，而不是等到评审才发现未覆盖。

## 限制

- **Intent 在 run 内不可变是设计不变量**：一个 run 只对一个契约负责。契约变化用 `new_run` 新建 run，并写 `parent_run_id` / `supersedes_run_id` / `change_reason`；旧 run 标 `superseded`，保留审计。
- 旧 run 有 active dispatch 时不允许 supersede；先等它返回或取消。
- `confirmed` 是创建门禁：先通过 `question`/`cy_ask` 拿到人类确认，再建 run。
- `test` 证据按 `call_id → node_id` 绑定；没有节点绑定的旧 gate 不再满足 intent 的 `test` 条件。
- 模板 + intent 必须提供 `satisfies` 映射；模板节点本身不带 `satisfies`。
- DSH 的 `cy_check` 需要显式 `node_id`，内核校验其 ready/active；这比 OpenCode 的 `call_id` 绑定弱一档，已写入 DETAIL。
- `seed_from_run_id`（只复制计划形状、不复制证据）尚未实现；先靠模板和重新规划。
- 权限、Grant、full-access 拦截器未在本阶段改动。

## 验证

```bash
python3 -m unittest tests.test_intent_contract -v
python3 -m unittest discover -s tests
node --test tests/v6_plugin_runtime.test.mjs tests/v6_plugin_hook.test.mjs tests/dsh_adapter_bridge.test.mjs
python3 cybertron_primes_engine.py
```

当前会话为 `danger-full-access`，隔离运行器可正常启动：`319 tests OK (skipped=1)`，Node `15/15` 通过。此前嵌套沙箱下的 `sandbox-exec` 失败已不再复现。

## Phase 1.5a 追加

- 创建 run 时强制 `confirmed=true`；未确认直接拒绝。
- `cy_check` 在子会话中通过 `child/<session>` 绑定取 `call_id`，内核从 `dispatch.started` 解析 `node_id` 并写入 `gate.check`。
- `coverage` 的 `test` 证据只接受绑定到覆盖节点的 gate。
- 新增测试：未确认创建被拒、别的节点的 test gate 不能冒充、补上覆盖节点的 gate 后完成。

## Phase 1.5b 追加

- `V6HostBridge.plan` 支持 `parent_run_id` / `supersedes_run_id` / `change_reason` / `satisfies_map`。
- `new_run` 在插件层：旧 run 非终态时显式 supersede；旧 run 终态时作为 parent 新建；active dispatch 时拒绝。
- 旧 run 写入 `superseded_by`，状态变 `superseded`，插件 `runIsTerminal` 将其视为终态。
- 模板 + intent 的 `satisfies` 映射在 `PlanGraph` 校验前应用，未知 node/done 直接拒绝。
- DSH 增加 `cy_check` 工具；OpenCode 仍用 `call_id` 绑定，DSH 用显式 `node_id` 校验。
- 新增测试：supersede lineage、active dispatch 拒绝、模板式 satisfies 映射、无节点绑定的 gate 不满足覆盖。

## 后续阶段

- Phase 2 已完成：[Grant 核心与派发授权](L-grants.md)。
- Phase 3 已完成：[权力矩阵、审查者 deny-list 与 Git 归属](M-authority-matrix.md)。
- Phase 4 已完成：[full-access 拦截器、standing grant、DSH Grant 与 seed_from](N-phase4.md)。
- OpenCode 硬化已完成：[自动推断、CLI、指标、v5 收口与 0.8.0](O-opencode-hardening.md)。
- 仍待后续：DSH 完整子会话绑定与 13 角色映射。
