# Cybertron 安装与发布方案

## 当前发布状态（2026-11-15）

| 渠道 | 版本 | 地址 |
| --- | --- | --- |
| npm | `cybertron-agents@0.2.0` | https://www.npmjs.com/package/cybertron-agents/v/0.2.0 |
| PyPI | `cybertron-agents 0.2.0` | https://pypi.org/project/cybertron-agents/0.2.0/ |
| GitHub tag | `v0.2.0` | https://github.com/zhiwenC125/Cybertron-agents/releases/tag/v0.2.0 |
| `install.sh` SHA-256 | `82dced736623431df720072ca23ba0f2fc2dfc14d8bc95f617dd69907cb5f7b2` | Release 附件 |

> `0.2.0` 已发布到 npm、PyPI 和 GitHub Release，包含阶段 A–E 的 OpenCode 软件工作流和十三角色模型编队。正式渠道核验见[发布验收记录](stages/I-release-020.md)。

## 三条安装路径

Cybertron 的 OpenCode 集成由 13 个角色 Markdown、可选 `/cybertron` 命令、插件和 Python 运行时组成。三条路径共享同一份 payload；公开 `0.2.0` 包含阶段 E 与模型编队：

| 路径 | 命令 | 适合 |
| --- | --- | --- |
| npm CLI | `npx -y cybertron-agents@0.2.0 init` | 装有 Node.js 的开发者 |
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
npx -y cybertron-agents@0.2.0 init --dry-run           # 预览
npx -y cybertron-agents@0.2.0 init --apply --project . # 装到当前项目
npx -y cybertron-agents@0.2.0 init --apply --global    # 装到全局
```

- **不要在本仓库目录内运行 `npx`**：npm 会向上命中本地同名 `package.json`，从而不安装 registry 包，报 `cybertron: command not found`。请在你自己的项目目录运行。
- `--project DIR`：安装到 `DIR/.opencode/agents` 与 `DIR/.opencode/commands`。
- `--global`：安装到 `${XDG_CONFIG_HOME:-~/.config}/opencode/agents|commands`。
- 目标缺少 `opencode.jsonc` 时写入仅含 `$schema` 的最小配置，保留 OpenCode 的 Build/Plan 默认行为。已有配置保持原字节，包括注释和未知字段；若无法安全解析则拒绝安装。用户通过 Shift+Tab 选择 `prima`。

## 路径二：GitHub Shell

```bash
curl -fsSL https://raw.githubusercontent.com/zhiwenC125/Cybertron-agents/v0.2.0/install.sh -o install.sh
bash install.sh --dry-run            # 先看要改哪些文件
bash install.sh --apply --project .  # 确认后安装
```

固定版本与校验：

```bash
bash install.sh --apply --version v0.2.0 --sha256 <归档文件的 SHA-256>
```

- 在本地 clone 内运行时直接读取仓库 `.opencode/`。
- 通过 curl 下载运行时，自动拉取对应版本的 GitHub 归档，解压后安装。

## 路径三：pipx（Python 生态）

`pipx` 与 npm 无关：它从 PyPI 安装 Python CLI 到隔离 venv。要求 Python 3.9+。

```bash
pipx install cybertron-agents==0.2.0
cybertron init --dry-run
cybertron init --apply --project .
cybertron init --apply --global
cybertron doctor
```

- 源码分支中的新版 wheel 内置与 npm 一致的角色、命令、插件和运行时，默认无需下载 GitHub `main`。`--payload DIR` 可显式使用本地目录；`--ref` 可显式选择远程版本。
- 固定版本：`pipx install cybertron-agents==<version>`。
- 从源码安装（开发用）：`pipx install .`。
- `cybertron doctor` 只做本地检查（角色数量、命令、配置），不联网下载 payload，也不打印任何密钥。

## 关于 pipx 的常见误解

- `pipx` 是 **Python** 生态工具（PyPI + 隔离 venv）。
- `npm` 是 **Node** 生态（registry.npmjs.org）。
- 二者互不相干，`pipx install` 不是 npm 的安装方式，只是第三条独立路径。

## 安装后使用

三条安装路径都会提示 `cybertron models setup`。npm、pipx 用安装后的 CLI；Shell 路径会打印 `${目标 .opencode}/bin/cybertron` 启动器的完整路径，不修改 PATH。`setup` 默认写用户全局编队；`--project DIR` 写项目编队。重复运行 `setup` 可逐角色切换，`rollback` 恢复上一版；`doctor` 校验 OpenCode 加载结果。公司自定义网关可用 `models provider-add` 登记接口与模型 ID，Key 只交给 OpenCode 认证或其服务环境，详见[模型编队说明](../README.md#配置十三角色模型编队020)。

```bash
opencode2 debug agents          # 确认 13 个角色已加载
opencode                        # 保留 Build/Plan 默认行为
# Shift+Tab 选 prima 后直接输入自然语言需求
# 或在 Build 模式输入 /cybertron <需求>
```

## 发布前检查

- npm：`npm pack --dry-run` 确认包内有 CLI、角色、插件、Python 运行时和 `install.sh`。
- npm：`npm publish` 需要维护者账号（发布前用本地 `cybertron-agents-0.2.0.tgz` 在临时项目验证）。
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
