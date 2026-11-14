# Cybertron 安装与发布方案

## 当前发布状态（2026-11-14）

| 渠道 | 版本 | 地址 |
| --- | --- | --- |
| npm | `cybertron-agents@0.1.1` | https://www.npmjs.com/package/cybertron-agents |
| PyPI | `cybertron-agents 0.1.1` | https://pypi.org/project/cybertron-agents/0.1.1/ |
| GitHub tag | `v0.1.1` | https://github.com/zhiwenC125/Cybertron-agents/releases/tag/v0.1.1 |
| `install.sh` SHA-256 | `f236333aeb4c157c6373ccd8641bf79cc0c29eb7c200541432ac4534df65c331` | 见 Release 说明 |

> 版本状态：`0.1.1` 已发布到 npm 与 PyPI，包含 `project.license` 改为 SPDX 字符串并打包 `LICENSE`、`cybertron doctor` 不再联网下载 payload 两项修复。`0.1.0` 为上一版。

## 三条安装路径

Cybertron 的 13 个角色本质是 OpenCode 的 Markdown 配置（`.opencode/agents/*.md`）加一个 `/cybertron` 命令。安装 = 把这些文件放进 OpenCode 会扫描的目录。提供三条路径，共享同一份 payload：

| 路径 | 命令 | 适合 |
| --- | --- | --- |
| npm CLI | `npx -y cybertron-agents@0.1.1 init` | 装有 Node.js 的开发者 |
| GitHub Shell | `sh install.sh`（先下载、可审阅） | 零依赖 / 极客用户 |
| pipx | `pipx install cybertron-agents`，再 `cybertron init` | 装有 Python 3.9+ 的用户 |

## 共同安全原则

1. **可审阅**：先下载脚本，读一眼再执行；不鼓励 `curl ... | sh` 盲跑。
2. **固定版本**：npm 用 `cybertron-agents@<version>`，shell 用 `--version <tag>`，pipx 用 `cybertron-agents==<version>`。
3. **校验**：shell 支持 `--sha256`；npm 依赖 registry 的 integrity；pipx 依赖 PyPI 哈希。
4. **先预览后写入**：三条路径都默认 dry-run，只有 `--apply` 才落盘。
5. **幂等 + 备份**：目标已存在且内容不同时，先写 `.bak` 再覆盖。
6. **不收集凭证**：不读取、不写入任何模型或飞书密钥。

## 路径一：npm CLI

```bash
npx -y cybertron-agents@0.1.1 init --dry-run           # 预览
npx -y cybertron-agents@0.1.1 init --apply --project . # 装到当前项目
npx -y cybertron-agents@0.1.1 init --apply --global    # 装到全局
```

- **不要在本仓库目录内运行 `npx`**：npm 会向上命中本地同名 `package.json`，从而不安装 registry 包，报 `cybertron: command not found`。请在你自己的项目目录运行。
- `--project DIR`：安装到 `DIR/.opencode/agents` 与 `DIR/.opencode/commands`。
- `--global`：安装到 `${XDG_CONFIG_HOME:-~/.config}/opencode/agents|commands`。
- 目标缺少 `opencode.jsonc` 时写入最小配置（`default_agent: "prima"`）；已有配置则保守合并，不改动你的其他字段。

## 路径二：GitHub Shell

```bash
curl -fsSL https://raw.githubusercontent.com/zhiwenC125/Cybertron-agents/main/install.sh -o install.sh
sh install.sh --dry-run            # 先看要改哪些文件
sh install.sh --apply --project .  # 确认后安装
```

固定版本与校验：

```bash
sh install.sh --apply --version v0.1.1 --sha256 <归档文件的 SHA-256>
```

- 在本地 clone 内运行时直接读取仓库 `.opencode/`。
- 通过 curl 下载运行时，自动拉取对应版本的 GitHub 归档，解压后安装。

## 路径三：pipx（Python 生态）

`pipx` 与 npm 无关：它从 PyPI 安装 Python CLI 到隔离 venv。要求 Python 3.9+。

```bash
pipx install cybertron-agents==0.1.1
cybertron init --dry-run
cybertron init --apply --project .
cybertron init --apply --global
cybertron doctor
```

- 与 npm/shell 共用同一份 payload：在本地开发目录下优先用仓库 `.opencode/`；安装到 site-packages 后则下载 GitHub 归档，或用 `--payload DIR` 指定本地目录。
- 固定版本：`pipx install cybertron-agents==<version>`。
- 从源码安装（开发用）：`pipx install .`。
- `cybertron doctor` 只做本地检查（角色数量、命令、配置），不联网下载 payload，也不打印任何密钥。

## 关于 pipx 的常见误解

- `pipx` 是 **Python** 生态工具（PyPI + 隔离 venv）。
- `npm` 是 **Node** 生态（registry.npmjs.org）。
- 二者互不相干，`pipx install` 不是 npm 的安装方式，只是第三条独立路径。

## 安装后使用

```bash
opencode2 debug agents          # 确认 13 个角色已加载
opencode                        # 默认 prima；Tab / Shift+Tab 切换
/cybertron 帮我做 STM32F4 电机控制固件
```

## 发布前检查

- npm：`npm pack --dry-run` 确认包内只有 CLI、payload、`install.sh`。
- npm：`npm publish` 需要维护者账号（发布前本地可用 `npx ./cybertron-agents-0.1.1.tgz init --dry-run` 验证）。
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
