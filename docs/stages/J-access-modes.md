# 后续阶段 J：访问模式与可读 run 目录

状态：本地开发验收通过；未改变既有角色权限表，full 模式仅在 run 级显式授权。

## 交付内容

- 新增 run 级 `access_mode`，与宿主的三种权限语义对齐：
  - `read-only`：禁止任何文件写入；只读扫描可在用户主目录运行，不做全量快照。
  - `workspace`：默认值；写入必须留在项目内，并继续受角色 `write_roots` 与节点 `write_scope` 约束。
  - `full`：仅当用户明确授权项目外路径（桌面、下载、`../`、绝对路径等）时使用；放开角色 write_roots，但仍硬拒绝 `.git`、`.opencode`、`.cybertron/runs` 与 `opencode.jsonc`。full 模式不遍历整个 workspace，不承诺对项目外文件做回滚，只对声明的产物做哈希取证。
- `cy_plan` 增加 `access_mode` 参数；Prima 从自然语言判断：只读请求 → read-only；普通开发 → workspace；明确要求桌面/下载/项目外 → full；含糊时先用原生 `question` 卡片确认。
- 原生子会话权限随模式生成：workspace 逐条列出 `write_scope`；full 允许 `edit *` 与 `external_directory *`，同时显式拒绝生成配置与 run 状态；read-only 全部拒绝。
- 运行目录改用 `<slug>--<run_id 前 8 位>`，例如 `.cybertron/runs/create-notes-file--3a4d82f9/`。`run_id` 仍是完整 UUID；`run.json` 保存 title、slug、host_session_id 与 access_mode。旧 UUID 目录继续可读。
- 旧 `SessionStore` 新建会话同样使用 `<slug>--<session_id 前 8 位>` 目录；改名时移动该目录并保留旧 slug 为 alias。阶段 B/C 的 UUID 目录不迁移，继续按 UUID 寻址。

## 快照裁剪

`ScopeGuard` 在 workspace 快照中保留 `node_modules`、`.venv`、`__pycache__`、缓存等目录自身，但不递归读取其内容；`.git`、`.opencode`、`.cybertron/runs` 仍保留在快照中以便检测越界写入。项目级大仓库的派发成本因此显著下降。

## 边界

- full 模式是用户显式授权后的“完全权限”，不是默认值；没有声明产物的项目外写入无法由 `scope_guard` 回滚。
- 模型选择改为跟随 OpenCode 会话：用户手动选择的模型优先，配置模型只作为默认值；不再因模型不一致中断会话。
- 旧全局插件应移除或由项目配置 `plugins: ["-cybertron.runtime"]` 禁用。
