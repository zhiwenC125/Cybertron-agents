# Cybertron 安装与发布方案

## 当前发布状态（2026-11-19）

> 状态：0.8.0 发布准备；下列渠道地址在正式发布后生效。

| 渠道 | 版本 | 地址 |
| --- | --- | --- |
| npm | `cybertron-agents@0.8.0` | https://www.npmjs.com/package/cybertron-agents/v/0.8.0 |
| PyPI | `cybertron-agents 0.8.0` | https://pypi.org/project/cybertron-agents/0.8.0/ |
| GitHub tag | `v0.8.0` | https://github.com/zhiwenC125/Cybertron-agents/releases/tag/v0.8.0 |
| `install.sh` SHA-256 | 由 Release 的 `SHA256SUMS` 提供 | Release 附件 |

> `0.8.0` 引入意图优先的动态编排：Intent 契约、Grant、按工具原子的权力矩阵、full-access 拦截器与 `cybertron v6` 查询。`0.7.3` 修复“完成的 run 卡住同一会话”；`0.7.2` 修复 `cy_plan` 的节点 schema；`0.7.1` 引入 `external_scope` 宿主升权；`0.7.0` 收敛为 prima 单一入口。更早渠道核验见[0.3.0 发布验收记录](stages/I-release-030.md)。

## 三条安装路径

Cybertron 的 OpenCode 集成由 13 个角色 Markdown、可选 `/cybertron` 命令、插件和 Python 运行时组成。三条路径共享同一份 payload；`0.3.0` 引入 v6 运行时与 DSH 适配器，`0.4.0` 修复 DSH 加载，`0.5.0` 加入计划评审与 shell 护栏，`0.5.1` 修复 `shell_policy.mjs` 漏复制，`0.6.0` 改为默认全局安装，`0.7.0` 收敛为 prima 单一入口，`0.7.3` 增加外部 scope 与宿主原生升权，`0.8.0` 引入意图优先编排与 Grant：

| 路径 | 命令 | 适合 |
| --- | --- | --- |
| npm CLI | `npx -y cybertron-agents@0.8.0 init` | 装有 Node.js 的开发者 |
| GitHub Shell | `bash install.sh`（先下载、可审阅） | 有 Bash 与 Python 3.9+ 的用户 |
| pipx | `pipx install cybertron-agents`，再 `cybertron init` | 装有 Python 3.9+ 的用户 |

## 共同安全原则

1. **可审阅**：先下载脚本，读一眼再执行；不鼓励 `curl ... | sh` 盲跑。
2. **固定版本**：npm 用 `cybertron-agents@<version>`，shell 用 `--version <tag>`，pipx 用 `cybertron-agents==<version>`。
3. **校验**：shell 支持 `--sha256`；npm 依赖 registry 的 integrity；pipx 依赖 PyPI 哈希。
4. **先预览后写入**：三条路径都默认 dry-run，只有 `--apply` 才落盘。
5. **幂等 + 备份**：源码分支中的新版安装器为每次更新保留编号 `.bak.1`、`.bak.2` 等备份，失败时回滚本次文件改动。
6. **不收集凭证**：不读取、不写入任何模型或飞书密钥。

## 路径一：npm CLI

```bash
npx -y cybertron-agents@0.8.0 init --dry-run           # 预览全局安装
npx -y cybertron-agents@0.8.0 init --apply             # 默认装到全局
npx -y cybertron-agents@0.8.0 init --apply --project . # 可选：项目级安装
```

- **不要在本仓库目录内运行 `npx`**：npm 会向上命中本地同名 `package.json`，从而不安装 registry 包，报 `cybertron: command not found`。请在你自己的项目目录运行。
- `npx` 不会留下全局 `cybertron` 命令。后续 `models`、`doctor` 仍使用 `npx -y cybertron-agents@0.8.0 <command>`；只有执行 `npm install -g cybertron-agents@0.8.0` 后才有全局 `cybertron`。全局安装后仍找不到时，将 `npm config get prefix` 下的 `bin` 加入 `PATH`。
- `--project DIR`：可选的项目级安装；全局与项目同时存在时 `init` 会拒绝，除非加 `--allow-duplicate`。
- `--global`：默认模式，安装到 `${XDG_CONFIG_HOME:-~/.config}/opencode`。
- 目标缺少 `opencode.jsonc` 时写入仅含 `$schema` 的最小配置，保留 OpenCode 的 Build/Plan 默认行为。已有配置保持原字节，包括注释和未知字段；若无法安全解析则拒绝安装。用户通过 Shift+Tab 选择 `prima` 作为唯一入口；prima 会先派 `thirteenth` 澄清并规划，再评审派发。

## 路径二：GitHub Shell

```bash
curl -fsSL https://raw.githubusercontent.com/zhiwenC125/Cybertron-agents/v0.7.0/install.sh -o install.sh
bash install.sh --dry-run            # 先看要改哪些文件
bash install.sh --apply              # 默认全局安装
```

固定版本与校验：

```bash
bash install.sh --apply --version v0.7.0 --sha256 <归档文件的 SHA-256>
```

- 在本地 clone 内运行时直接读取仓库 `.opencode/`。
- 通过 curl 下载运行时，自动拉取对应版本的 GitHub 归档，解压后安装。

## 路径三：pipx（Python 生态）

`pipx` 与 npm 无关：它从 PyPI 安装 Python CLI 到隔离 venv。要求 Python 3.9+。

```bash
pipx install cybertron-agents==0.8.0
pipx ensurepath
exec zsh
cybertron init --dry-run
cybertron init --apply
cybertron doctor --global
```

`pipx` 会把命令装到 `~/.local/bin`；该目录不在 zsh 的 `PATH` 时，安装成功后仍会报 `zsh: command not found: cybertron`。可先用 `~/.local/bin/cybertron --version` 验证，或临时使用 `pipx run --spec cybertron-agents==0.8.0 cybertron ...`。

- 源码分支中的新版 wheel 内置与 npm 一致的角色、命令、插件和运行时，默认无需下载 GitHub `main`。`--payload DIR` 可显式使用本地目录；`--ref` 可显式选择远程版本。
- 固定版本：`pipx install cybertron-agents==<version>`。
- 从源码安装（开发用）：`pipx install .`。
- `cybertron doctor` 只做本地检查（角色数量、命令、配置），不联网下载 payload，也不打印任何密钥。

## 关于 pipx 的常见误解

- `pipx` 是 **Python** 生态工具（PyPI + 隔离 venv）。
- `npm` 是 **Node** 生态（registry.npmjs.org）。
- 二者互不相干，`pipx install` 不是 npm 的安装方式，只是第三条独立路径。

## 命令找不到（`zsh: command not found: cybertron`）

这是 PATH 与安装渠道不匹配，不是 Cybertron 安装失败。按渠道处理：

| 渠道 | 原因 | 立即验证 |
| --- | --- | --- |
| `npx` | npx 只运行一次，不安装全局命令 | `npx -y cybertron-agents@0.8.0 --version` |
| `npm install -g` | npm 全局 `bin` 不在 zsh PATH | `$(npm config get prefix)/bin/cybertron --version` |
| `pipx` | `~/.local/bin` 不在 zsh PATH | `~/.local/bin/cybertron --version`，然后 `pipx ensurepath` |
| `pip install` | user bin（macOS 常在 `~/Library/Python/3.x/bin`）不在 PATH | `python3 -m cybertron.installer --version` |
| Shell `install.sh` | 脚本按设计不改 PATH | `./.opencode/bin/cybertron --version` |

修改 `PATH` 后执行 `exec zsh` 或重开终端；不要重复安装来“修复”命令找不到。

## 安装到 DeepSeek Harness（实验性）

DSH 适配器随 npm/PyPI 包分发在 `payload/dsh-adapter`。用 CLI 取得绝对路径后注册到目标 profile：

```bash
BUNDLE="$(cybertron dsh path)"          # npm: npx cybertron-agents dsh path
dsh plugin --profile desktop add "$BUNDLE"
```

- 只会新增 `Cybertron` preset，不改变默认 preset；在新建会话时选择它。
- preset 内只挂载 `cy_plan`/`cy_state`/`cy_ask`/`cy_escalate`/`cy_check`/`cy_templates`/`cy_metrics` 和原生 subagent 工具。
- 目前是单一 prima persona，DSH 子会话尚未绑定节点 `write_scope`；定位为实验性第二宿主。
- 移除：`plugin_manager remove_bundle @local/cybertron-dsh` 或 Plugins 页。

## 安装后使用

三条安装路径都会提示模型配置入口，但命令不同：npm 用 `npx -y cybertron-agents@0.8.0 models setup`；pipx 用 `cybertron models setup`（必要时先 `pipx ensurepath`）；Shell 路径会打印 `${目标 .opencode}/bin/cybertron` 启动器的完整路径，不修改 PATH，后续请直接使用该绝对路径。`setup` 默认写用户全局编队；`--project DIR` 写项目编队。重复运行 `setup` 可逐角色切换，`rollback` 恢复上一版；`doctor` 校验 OpenCode 加载结果。公司自定义网关可用 `models provider-add` 登记接口与模型 ID，Key 只交给 OpenCode 认证或其服务环境，详见[模型编队说明](../README.md#配置十三角色模型编队020)。

```bash
opencode2 debug agents          # 确认 13 个角色已加载
opencode                        # 保留 Build/Plan 默认行为
# Shift+Tab 选 prima 后直接输入自然语言需求
# 或在 Build 模式输入 /cybertron <需求>
```

## 发布前检查

- npm：`npm pack --dry-run` 确认包内有 CLI、角色、插件、Python 运行时、DSH 适配器和 `install.sh`。
- npm：`npm publish` 需要维护者账号（发布前用本地 `cybertron-agents-0.7.0.tgz` 在临时项目验证）。
- pipx：`python -m build` 生成 wheel/sdist，再 `twine upload` 到 PyPI；发布前可用 `pipx install .` 验证。
- 在干净目录分别跑三条路径的 `--dry-run` 与 `--apply`，用 `opencode2 debug agents` 确认 13 个角色出现。
- 打 tag（`v0.1.0`、`v0.1.1` 已完成），在 GitHub Release 附归档与 `install.sh` 的 SHA-256。
- `local_backups/`、凭证、本机构建产物不进入发布包。

## 许可证

MIT，见仓库根目录 [`LICENSE`](../LICENSE)。

## 参考

- [OpenCode 安装](https://opencode.ai/docs/)
- [OpenCode 配置位置与优先级](https://opencode.ai/docs/config)
- [OpenCode 智能体文件](https://opencode.ai/docs/agents)
- [pipx 文档](https://pipx.pypa.io/)
- [npm files 字段](https://docs.npmjs.com/cli/configuring-npm/package-json#files)
