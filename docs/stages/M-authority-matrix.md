# 阶段 M（Phase 3）：权力矩阵、审查者 deny-list 与 Git 归属

> 历史阶段记录，正文反映当时的版本和验证范围。当前行为见 [开发状态](../../DEVELOPMENT_PLAN.md)。

状态：Phase 3 已实现；配置已重新导出。
日期：2026-11-19

## 交付范围

1. 新增 [cybertron/authority.py](../../cybertron/authority.py)：13 角色原子矩阵、`escalatable` 上限、`never` 边界、审查者 deny-list；
2. `grant_request` 按角色的 `escalatable` 校验，越权申请直接拒绝；
3. 审查者 A：`liege-maximo` / `micronus-prime` 项目根只读，敏感路径 deny；
4. Git 写归属 `vector-prime`：shell 白名单增加 commit/push/tag 的 `ask`；
5. 重新导出 13 个角色 Markdown、`opencode.jsonc`、`shell_policy.mjs`。

## 角色矩阵

完整矩阵在 `authority.py` 的 `ROLE_AUTHORITY`。摘要：

| 族 | 角色 | 关键权力 |
| --- | --- | --- |
| 治理 | `prima`、`thirteenth` | `prima` 只有 task/state/review/ask/escalate；`thirteenth` 只有计划、只读与外部只读 |
| 知识 | `alpha-trion`、`onyx-prime` | 文档写入 + 外部写 Grant；只读侦察 |
| 版本/交付 | `vector-prime` | Git 读基线，commit/push 需 Grant |
| 构造 | `quintus`、`solus`、`amalgamous`、`nexus` | 设计、实现、重构、构建；不能碰测试/设备/Git 写 |
| 保证 | `micronus`、`liege`、`alchemist` | L1/L2/测试；写仅 artifacts |
| 不可逆 | `megatronus` | 设备/部署，均需 Grant |

- `ROLE_AUTHORITY[role]["escalatable"]` 是 Grant 申请上限；
- `ROLE_AUTHORITY[role]["never"]` 是不可授红线；
- `assert_authority()` 校验 13 角色齐全、Grant 类型合法、控制面不可授、审查者不持有写副作用原子。

## 审查者 A

`liege-maximo` 的 host 权限改为：

- `read "*"` 允许项目根；
- 随后追加 deny 规则：`.env*`、`*.pem`、`*.key`、`.ssh/**`、`.aws/**`、`.npmrc`、`.pypirc`、`secrets/**`、`.git/**` 等。
- 插件 `tool.execute.before` 对 `read/glob/grep` 再做一次 deny 检查，防止宿主规则被绕过。

`micronus-prime` 保留原有窄读权限；两者的审查者 deny 规则由 `authority.py` 的 `denied_for_reviewer` 统一。

## Git 归属

- `vector-prime` 的 shell 白名单新增 `git add/commit/tag/push`，效果为 `ask`；
- `assert_catalog` 的 Git 写 owner 改为 `vector-prime`；
- 节点若要真正执行提交，应声明 `requires: ["vcs.write"]` 或 `["vcs.push"]`，由 Grant 流程批准；
- `nexus-prime` 不持有 Git 写命令。

## 验证

```bash
python3 -m unittest tests.test_authority_v6 tests.test_opencode_v2 tests.test_v6_permissions -v
python3 -m unittest discover -s tests
node --test tests/v6_plugin_runtime.test.mjs tests/v6_plugin_hook.test.mjs tests/dsh_adapter_bridge.test.mjs
```

当前环境全绿：Python `319 tests OK (skipped=1)`，Node `15/15`。

## 限制

- OpenCode 宿主的权限动作仍是 `read/edit/shell` 等，`bash:*` 原子是内核/授权层的语义，不是宿主的一等权限名；实际命令仍由 shell policy 执行。
- `liege` 的 deny 规则同时存在于 registry 和插件守卫；DSH 单 persona 没有插件读守卫，A 的 deny-list 在 DSH 侧未生效。
- Git Grant 不会自动推断：节点必须声明 `vcs.write` / `vcs.push`，否则 `ask` 只是宿主确认，不是可审计的 Grant。
- `full-access` 拦截器、飞书 standing grant、`dangerous.confirm` 已在 Phase 4 实现，见 [N-phase4.md](N-phase4.md)。
