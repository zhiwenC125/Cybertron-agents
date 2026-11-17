# 后续阶段 J：宿主原生权限与可读 run 目录

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

## 快照裁剪

`ScopeGuard` 在 workspace 快照中保留 `node_modules`、`.venv`、`__pycache__`、缓存等目录自身，但不递归读取其内容；`.git`、`.opencode`、`.cybertron/runs` 仍保留在快照中以便检测越界写入。

## 边界

- `danger-full-access` 是用户显式授权后的宿主模式，不是默认值；没有声明产物的项目外写入无法由 `scope_guard` 回滚。
- 模型选择改为跟随 OpenCode 会话：用户手动选择的模型优先，配置模型只作为默认值；不再因模型不一致中断会话。
- 旧全局插件应移除或由项目配置 `plugins: ["-cybertron.runtime"]` 禁用。
