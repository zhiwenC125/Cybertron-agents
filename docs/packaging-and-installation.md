# Cybertron 安装与发布方案

## 安装双路径

Cybertron 的 13 个角色本质是 OpenCode 的 Markdown 配置（`.opencode/agents/*.md`）加一个 `/cybertron` 命令。安装 = 把这些文件放进 OpenCode 会扫描的目录。提供两条路径：

| 路径 | 命令 | 适合 |
| --- | --- | --- |
| npm CLI | `npx cybertron-agents init` | 装有 Node.js 的开发者 |
| GitHub Shell | `sh install.sh`（先下载、可审阅） | 零依赖 / 极客用户 |

两条路径共享同一份 payload（`registry.py` 导出的 13 个 Markdown + `/cybertron` 命令），安装行为一致。

## 共同安全原则

1. **可审阅**：先下载脚本，读一眼再执行；不鼓励 `curl ... | sh` 盲跑。
2. **固定版本**：npm 用 `cybertron-agents@<version>`，shell 用 `--version <tag>`。
3. **校验**：shell 支持 `--sha256`；npm 依赖 registry 的 integrity。
4. **先预览后写入**：默认 dry-run，只有 `--apply` 才落盘。
5. **幂等 + 备份**：目标已存在且内容不同时，先写 `.bak` 再覆盖。
6. **不收集凭证**：不读取、不写入任何模型或飞书密钥。

## 路径一：npm CLI

```bash
# 预览（默认 dry-run，不写任何文件）
npx cybertron-agents@0.1.0 init --dry-run

# 装到当前项目
npx cybertron-agents@0.1.0 init --apply --project .

# 装到全局（所有项目可见）
npx cybertron-agents@0.1.0 init --apply --global
```

- `--project DIR`：安装到 `DIR/.opencode/agents` 与 `DIR/.opencode/commands`。
- `--global`：安装到 `${XDG_CONFIG_HOME:-~/.config}/opencode/agents|commands`。
- 目标缺少 `opencode.jsonc` 时写入最小配置（`default_agent: "prima"`）；已有配置则保守合并，不改动你的其他字段。
- 默认 dry-run；`--apply` 才写盘。

## 路径二：GitHub Shell

```bash
curl -fsSL https://raw.githubusercontent.com/zhiwenC125/Cybertron-agents/main/install.sh -o install.sh
sh install.sh --dry-run            # 先看要改哪些文件
sh install.sh --apply --project .  # 确认后安装
```

固定版本与校验：

```bash
sh install.sh --apply --version v0.1.0 --sha256 <归档文件的 SHA-256>
```

- 在本地 clone 内运行时直接读取仓库 `.opencode/`。
- 通过 curl 下载运行时，自动拉取对应版本的 GitHub 归档，解压后安装。
- `--global` 与 `--project DIR` 语义同 npm 路径。

## 关于 pipx（它不是 npm）

- `pipx` 是 **Python** 生态工具：从 PyPI 安装 Python CLI，放进隔离 venv。
- `npm` 是 **Node** 生态：从 registry.npmjs.org 安装 Node 包。
- 二者互不相干，`pipx install` 不是 npm 的安装方式。
- 本仓库当前的双路径是 Node + Shell，不需要 Python，也不使用 pipx。
- 只有将来把 `cybertron` 做成「Python 引擎 + CLI」时，`pipx install cybertron-agents==<version>` 才会成为**第三条独立路径**，需要新增 `pyproject.toml`，与 npm 无关。

## 安装后使用

```bash
opencode2 debug agents          # 确认 13 个角色已加载
opencode                        # 默认 prima；Tab / Shift+Tab 切换
/cybertron 帮我做 STM32F4 电机控制固件
```

## 发布前检查

- `npm pack --dry-run` 确认包内只有 CLI、payload、`install.sh`，不含 Python 测试与本机备份。
- 在干净目录分别跑 `init --dry-run` 和 `--apply`，用 `opencode2 debug agents` 确认 13 个角色出现。
- 打 tag（建议 `v0.1.0`），在 GitHub Release 附归档与 `install.sh` 的 SHA-256。
- `local_backups/`、凭证、本机构建产物不进入发布包。

## 参考

- [OpenCode 安装](https://opencode.ai/docs/)
- [OpenCode 配置位置与优先级](https://opencode.ai/docs/config)
- [OpenCode 智能体文件](https://opencode.ai/docs/agents)
- [npm files 字段](https://docs.npmjs.com/cli/configuring-npm/package-json#files)
