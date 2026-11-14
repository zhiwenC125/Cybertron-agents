# Cybertron Thirteen Primes

当前开发阶段和每阶段验收条件见 [开发计划](DEVELOPMENT_PLAN.md)。

当前项目协作与权限基线见 [AGENTS.md](AGENTS.md)。普通角色的测试、构建和静态检查 Shell 权限暂时关闭；阶段 5 的本地隔离运行器尚未接入 OpenCode 角色工具调用。

**当前状态（2026-11-14）**：七阶段的最小闭环基线已达到。阶段 7 的 STM32 最小 App 已经人工批准真机烧录、读回、观察 SRAM 心跳并恢复原固件；完整 OTA App、ESP32-S3、九步自动接力和宿主审批接口仍在开发。证据见[阶段 7 文档](docs/stages/07-deployment.md)。在其他电脑使用或规划一条命令安装，请先看[安装与发布方案](docs/packaging-and-installation.md)。

各阶段的代码摘录、验收记录与后续实现建议见 [阶段文档目录](docs/stages/01-foundation.md)：[1](docs/stages/01-foundation.md) · [2](docs/stages/02-local-execution.md) · [3](docs/stages/03-opencode-config.md) · [4](docs/stages/04-opencode-executor.md) · [5](docs/stages/05-quality-gates.md) · [6](docs/stages/06-feishu.md) · [7](docs/stages/07-deployment.md)。参考资料新增 [Datawhale Hello Agents](https://datawhalechina.github.io/hello-agents/#/)。

本仓库是 [v5 架构白皮书](design/cybertron_13_primes_architecture.md)的 Python 原型。当前实现包含 13 个角色的静态定义、权限规则、9 步任务账本、飞书 Wiki OpenAPI 网关，以及 OpenCode V2 / DeepSeek Harness 配置导出。已有一个只读角色的 OpenCode V2 命令行适配器；完整多智能体流程仍在开发中。角色模型 ID 以 `cybertron/registry.py` 为准；白皮书中的旧 DeepSeek 模型名保留为当时的设计记录。

## 运行

需要 Python 3.9 或更新版本，无第三方 Python 依赖。

项目根目录已包含可供 OpenCode V2 加载的 `opencode.jsonc` 与 `.opencode/agents/`。本机 `opencode2` v2.3.0 的 `debug config` 与 `debug agents` 已确认加载 13 个 Cybertron 角色；首次在新电脑使用时请自行连接 DeepSeek，并用 `opencode2 models` 核对 `deepseek/deepseek-flash` 与 `deepseek/deepseek-v4-pro`。以下单元测试、导出和配置检查均不会调用模型；交互提示和第 1 步真实执行会调用模型。

```bash
python3 -m unittest discover -s tests -v
python3 cybertron_primes_engine.py
python3 -m cybertron.simulation "开发示例功能"
python3 -m cybertron.opencode_v2 --output opencode_v2_smoke
python3 -m cybertron.opencode_run "请澄清 STM32F4 电机控制任务还缺少哪些关键参数"
```

第二条命令会在当前目录生成 `cybertron_workspace_dist/`，其中有 13 份 OpenCode 智能体 Markdown、`opencode.jsonc` 和一份 DeepSeek Harness 预设 JSON。原脚本路径继续作为兼容入口；实现已拆分到 `cybertron/`。

第三条命令使用统一的 `AgentTask` / `AgentResult` 执行接口运行本地模拟接力。第 3 步依次派发锐天骁、维克多、昆图斯；第 5 步派发微米天、谎言天尊；第 9 步派发钛师傅、第十三天尊。默认在第 8 步硬件审批前停下，不会调用模型、飞书或硬件工具。若只想检验九步状态转换，可显式运行 `python3 -m cybertron.simulation --simulate-hardware-approval`；该选项仅改变模拟结果，不代表真实人工授权。

第四条命令生成供 OpenCode V2 配置加载测试的独立目录，默认不启用飞书 MCP。进入 `opencode_v2_smoke/` 后运行 `opencode2 debug config` 检查宿主加载；此步骤不会调用模型。飞书 MCP 可在有凭证时通过导出命令的 `--include-feishu` 显式启用。

第五条命令在项目根目录运行，会真实调用 OpenCode V2 的 `thirteenth` 角色。若终端仍在 `opencode_v2_smoke/`，重新生成导出包后可直接运行 `python3 run_first_agent.py "请澄清 STM32F4 电机控制任务还缺少哪些关键参数"`。此测试需要该角色配置的 DeepSeek 模型可用。它只执行账本第 1 步，不继续派发其他角色；模型回复不符合结构化格式、超时或命令失败时，账本会阻塞。

阶段 5 的只读接力探针在项目根目录运行：`python3 -m cybertron.opencode_readonly "查看本项目源码与当前 Git 基线"`。项目根目录已生成 `opencode.jsonc` 和 `.opencode/agents/`，让角色能读取真正的项目源码。探针用模拟前置条件跳过步骤 1、2，只真实调用 `onyx-prime` 和 `vector-prime`，不会执行后续写入角色。

阶段 5 保留 `cybertron.opencode_l2_probe` 作为真实宿主审查探针；前置步骤和 L1 是模拟结果。用户已决定不向外部模型发送项目文件，因此它不属于当前离线验收命令。

阶段 5 的离线终端验收运行 `python3 -m unittest discover -s tests -q`、`python3 -m cybertron.stage5_verify` 和 `opencode2 debug config`。第二条命令通过 macOS `sandbox-exec` 核查项目写入、设备读取及网络连接均被拒绝，再将实际单元测试报告作为 `test` 证据写入账本；不会调用模型或飞书。

阶段 6 的离线测试包含在单元测试中。真实飞书测试使用自建应用身份：在本机设置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 和测试空间的 `FEISHU_WIKI_SPACE_ID`，依次运行 `python3 -m cybertron.stage6_verify --check-env`、`--check-auth` 和 `--live`；最后一项会在该空间创建并保留一篇测试文档、追加正文并回读验证。完整步骤见[阶段 6 文档](docs/stages/06-feishu.md)。不要把 App Secret 或租户令牌提交到仓库或贴进聊天。

## 安装到 OpenCode

三条安装路径共享同一份 payload（13 个角色 + `/cybertron` 命令），默认 dry-run，`--apply` 才写入。当前已发布版本为 **0.1.1**：

```bash
# 1) npm（在你自己的项目目录运行，不要在 Cybertron-Agent 仓库内运行）
npx -y cybertron-agents@0.1.1 init --dry-run
npx -y cybertron-agents@0.1.1 init --apply --project .

# 2) pipx（Python 生态，与 npm 无关）
pipx install cybertron-agents==0.1.1
cybertron init --dry-run
cybertron init --apply --project .

# 3) GitHub Shell
curl -fsSL https://raw.githubusercontent.com/zhiwenC125/Cybertron-agents/main/install.sh -o install.sh
sh install.sh --dry-run
sh install.sh --apply --project .
```

安装目标：

- `--project DIR`：写入 `DIR/.opencode/agents` 与 `DIR/.opencode/commands`
- `--global`：写入 `${XDG_CONFIG_HOME:-~/.config}/opencode/agents|commands`

装完在 OpenCode 里：`opencode2 debug agents` 确认 13 个角色；`opencode` 默认 `prima`，`Tab` / `Shift+Tab` 切换；`/cybertron <需求>` 启动编排。`cybertron doctor` 只做本地检查，不会联网下载。

详见[安装与发布方案](docs/packaging-and-installation.md)。`v0.1.1` 的 tag 与 Release 见 [GitHub Release v0.1.1](https://github.com/zhiwenC125/Cybertron-agents/releases/tag/v0.1.1)。

## 模块

| 模块 | 职责 |
| --- | --- |
| `schema.py` | 消息和工具调用数据结构 |
| `compaction.py` | 上下文首尾压缩 |
| `policy.py` | 本地权限与循环熔断检查 |
| `feishu.py` | 自建应用凭证读取、租户令牌缓存、Wiki 节点及 Docx 正文读写网关 |
| `registry.py` | 13 个角色配置 |
| `ledger.py` | SDLC 计划和顺序状态转换 |
| `execution.py` | 宿主无关的任务、结果和执行器协议 |
| `dispatch.py` | 派单、结果校验和账本推进 |
| `simulation.py` | 不产生外部副作用的本地模拟执行器 |
| `isolated_runner.py` | macOS 沙箱内运行单元测试并生成 QA 证据 |
| `deployment.py` | 第七阶段固件、设备、擦写与回滚契约及无硬件仿真 |
| `exporters.py` | 双宿主静态配置导出 |
| `installer.py` | npm / shell / pipx 三条安装路径的 Python 入口 |
| `selfcheck.py` | 命令行自检 |

## 当前边界与下一步

1. `ledger.py` 与 `dispatch.py` 已实现 L1/L2 拒绝后返回编码、重审及超限阻塞；本地隔离测试能生成 QA 回执。真实 L1/L2 宿主审查和人工烧录授权仍需后续阶段接入。
2. `policy.py` 是本地策略原型，不能代替宿主层权限和命令解析。生成配置后的真实权限仍需在目标宿主中验证。
3. DeepSeek Harness 目前只导出预设 JSON，白皮书中的 `.dsh/cordis-cybertron-plugin.mjs` 尚未实现。
4. 阶段 6 的 Wiki OpenAPI 读写已由开发者在专用测试空间验收；阶段 7 的 STM32 最小真机烧录及回滚已通过。完整 OTA App、ESP32-S3、外部 Flash 备份和隔离构建仍待开发。

缺少飞书 App ID 或 App Secret 时，网关默认报错。模拟租户令牌仅能通过显式传入 `mock_if_unset=True` 用于局部测试，不会进入真实 Wiki 请求。
