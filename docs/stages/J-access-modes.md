# 后续阶段 J：宿主原生权限与可读 run 目录

> 历史阶段记录，正文反映当时的版本和验证范围。当前行为见 [开发状态](../../DEVELOPMENT_PLAN.md)。

状态：本地开发验收通过；权限词汇与 DeepSeek Harness 的 `SandboxMode` 完全一致。

## 交付内容

- run 级 `access_mode` 直接采用 DSH 的原生沙箱模式，不再维护一套平行命名：
  - `read-only`：禁止任何文件写入；只读扫描可在用户主目录运行，不做全量快照。
  - `workspace-write`：默认值；写入留在项目内，并继续受角色 `write_roots` 与节点 `write_scope` 约束。
  - `danger-full-access`：仅当用户明确授权项目外路径（桌面、下载、`../`、绝对路径等）时使用；放开角色 write_roots，但仍硬拒绝 `.git`、`.opencode`、`.cybertron/runs` 与 `opencode.jsonc`。该模式不遍历整个 workspace，不承诺对项目外文件做回滚，只对声明的产物做哈希取证。
- OpenCode 侧不新增模式实现，只把同一个模式翻译成 OpenCode 原生权限规则：`edit` 与 `external_directory` 的 allow/deny。子会话权限由 [cybertron.js](../../cybertron/v6_plugin/cybertron.js) 生成。
- DSH 侧使用同一组 `SandboxMode` 值；DSH adapter 的 `cy_plan` payload 接受 `access_mode`，由 DSH 的沙箱策略执行。Cybertron 不在工具里自行提升 DSH 权限：用户在 DSH 的 Permissions 选择器里选择相同模式，Cybertron 只记录并与计划对齐。Cybertron 不再定义第二套"仅查看/项目内/完全"语义。
- `cy_plan` 增加 `access_mode` 与 `slug` 参数；Prima 从自然语言判断：只读请求 → `read-only`；普通开发 → `workspace-write`；明确要求桌面/下载/项目外 → `danger-full-access`；含糊时先用原生 `question` 卡片确认。
- 运行目录使用纯英文 slug：`.cybertron/runs/create-notes-file/`。`run_id` 仍是完整 UUID，只保存在 `run.json`、事件和返回值中；重名时使用 `-2`、`-3` 后缀。`run.json` 保存 title、slug、host_session_id 与 access_mode。旧 UUID 目录继续可读。
- 旧 `SessionStore` 新建会话同样使用纯 slug 目录；改名时移动目录并保留旧 slug 为 alias。阶段 B/C 的 UUID 目录不迁移，继续按 UUID 寻址。

## 项目外写入：范围声明 + 宿主原生升权

原则：Cybertron 只声明「这个节点可能写哪些项目外路径」，**升权方式跟随宿主**，不再维护第三套审批机制。

- `write_scope` 仍是项目内路径，走 `ScopeGuard` 快照、diff 和回滚；
- `external_scope` 列项目外的**字面路径**（绝对路径或 `~`；不允许 glob、`..`、`.git`、`.opencode`、`.cybertron/runs`、`opencode.jsonc`）。它不参与快照，**没有回滚**，只对落盘产物做 SHA-256 取证；
- 同一个节点不允许同时声明 `external_scope` 与 `danger-full-access`；后者继续用 `write_scope` 表达外部路径。

### OpenCode：用它的 ask / once / always

- 派单时给子会话绑定规则：项目 scope `allow`，声明过的外部路径 `ask`，其余外部路径 `deny`；
- 用户在原生权限卡上选 `once` / `always` / `reject`，这就是 OpenCode 自己的升权方式；
- 插件只做两件事：把**未声明**的外部路径强制 `deny`（防止模型反复试探），以及把判定结果记入账本——`permission.requested`（每次请求）或 `permission.granted`（`always` 之后以 `allow` 到达的常设授权）；
- `always` 由 OpenCode 保存成项目级 allow 规则，后续写入直接放行，不再弹卡；
- `finish` 对外部产物要求 `permission.requested` 或 `permission.granted`（同一 `call_id`），两者都没有才判 `failed`。

### DSH：用它的会话模式与单次升权

- 升权完全交给 DSH：会话 `SandboxMode`（read-only / workspace-write / danger-full-access）+ 工具的 `sandbox_permissions` 单次重试 + 审批 seam；
- Cybertron **不签发、也不要求自己的审批回执**：`run.json` 里 `host=dsh`，`finish` 只对 `external_scope` 产物做哈希，不判「未批准」；
- 待 DSH 的 dispatch 绑定落地后，再把宿主 approval 事件作为回执来源接进来。

### 证据强度对照

| 宿主 | 触发方式 | 会记住吗 | 账本记录 | 项目外回滚 |
| --- | --- | --- | --- | --- |
| OpenCode | 规则 `ask` + 原生卡 | `always` 持久保存 | `permission.requested` / `permission.granted` | 无 |
| DSH | 会话模式 + `sandbox_permissions` | 单次，不记 | 产物哈希（审批在宿主侧） | 无 |

插件订阅 `permission.replied`，把 `once` / `always` / `reject` 记成 `permission.resolved`。收到 `always` 时，插件还会在会话存储里记一条 run 级授权；后续写同一 scope 时直接放行，不再弹卡。这样即使 OpenCode 没有保存规则（见下），「总是允许」也能生效。

`run.json` 与 `cy_state` 现在带 `evidence_level`：OpenCode 是 `kernel-receipt`，DSH 是 `host-approved`。

### 已验证：saved approval 的优先级

前提是「用户选 always 后，保存的 allow 规则要压过会话里的 `ask`」。已对照安装版本（`opencode2 --version` = v2.3.0）的源码验证，仓库 `anomalyco/opencode`、 tag `v2.3.0`、`packages/core/src/permission.ts`：

```ts
const rules = yield* configured(input.sessionID, input.agent)
if (denied(input, rules)) return { effect: "deny" as const, rules }
const all = [...rules, ...(yield* savedRules())]
```

- `denied()` 只看**配置规则**，所以配置里的硬 `deny` 永远优先；
- `savedRules()` 的结果**拼在配置规则之后**，而 `evaluate()` 用 `findLast` 取最后一条匹配——所以 saved `allow` 会覆盖会话里的 `ask`；
- 前提成立，但仅当用户点 always 时请求带 `save` 列表：`if (input.reply === "always" && existing.request.save?.length) { saved.add(...) }`。若 `save` 为空，OpenCode 不保存规则；插件自己的 run 级授权兜住这种情况。

未验证的部分：没有真实驱动一次 OpenCode UI 点击（二进制需要重定向 `XDG_*` 才能在当前沙箱启动，且真实会话需要模型）。上面的结论是版本精确的源码级验证，不是运行时回归。

## 快照裁剪

`ScopeGuard` 在 workspace 快照中保留 `node_modules`、`.venv`、`__pycache__`、缓存等目录自身，但不递归读取其内容；`.git`、`.opencode`、`.cybertron/runs` 仍保留在快照中以便检测越界写入。

## 边界

- `danger-full-access` 是用户显式授权后的宿主模式，不是默认值；没有声明产物的项目外写入无法由 `scope_guard` 回滚。
- 模型选择改为跟随 OpenCode 会话：用户手动选择的模型优先，配置模型只作为默认值；不再因模型不一致中断会话。
- 旧全局插件应移除或由项目配置 `plugins: ["-cybertron.runtime"]` 禁用。
