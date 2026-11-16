# Cybertron Thirteen Primes

当前开发阶段和每阶段验收条件见 [开发计划](DEVELOPMENT_PLAN.md)。

从当前配置包与内存编排过渡到可恢复运行态的实施顺序、验收门槛与交接事项见 [后续开发 Handoff](docs/handoffs/2026-11-14-runtime-architecture.md)。

当前项目协作与权限基线见 [AGENTS.md](AGENTS.md)。普通角色不能直接执行测试、构建和静态检查 Shell 命令；软件测试由 Cybertron 宿主在 macOS 隔离运行器中执行。

**当前状态（2026-11-17）**：v6 动态任务图 M0–M5 已全部通过门禁，`0.3.0` 是 v6 功能版本。运行时从固定九步账本改为“prima 提议、内核裁决”的图计划：写范围守卫、按实际 diff 计算风险门禁、并发写入锁、Loop-1/2 修复、设备审批与回滚、模板沉淀与指标面板。OpenCode 宿主已用真实模型完成学习门禁；DSH 适配器作为实验性 bundle 随包分发。历史 A–E 与七阶段记录见[阶段文档目录](docs/stages/)和[v6 进度](docs/stages/v6-progress.md)。

各阶段的代码摘录、验收记录与后续实现建议见 [阶段文档目录](docs/stages/01-foundation.md)：[1](docs/stages/01-foundation.md) · [2](docs/stages/02-local-execution.md) · [3](docs/stages/03-opencode-config.md) · [4](docs/stages/04-opencode-executor.md) · [5](docs/stages/05-quality-gates.md) · [6](docs/stages/06-feishu.md) · [7](docs/stages/07-deployment.md)。参考资料新增 [Datawhale Hello Agents](https://datawhalechina.github.io/hello-agents/#/)。

本仓库是 [v6 动态任务图设计](design/DEVELOPMENT_PLAN.md) 的实现，保留 [v5 架构白皮书](design/cybertron_13_primes_architecture.md) 作为历史设计。0.3 运行时包含 13 角色注册表、图计划与写范围守卫、风险门禁与工具链配置档、并发调度与局部返工、设备副作用代理、模板沉淀与指标面板，以及 OpenCode 原生派单插件和 DSH 适配器。角色模型 ID 以 `cybertron/registry.py` 为准。

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

阶段 5 保留 `cybertron.opencode_l2_probe` 作为历史单角色探针；后续阶段 E 已获用户授权，可在真实软件流程中向配置的模型发送临时项目文件并验证宿主回执。

阶段 5 的离线终端验收运行 `python3 -m unittest discover -s tests -q`、`python3 -m cybertron.stage5_verify` 和 `opencode2 debug config`。第二条命令通过 macOS `sandbox-exec` 核查项目写入、设备读取及网络连接均被拒绝，再将实际单元测试报告作为 `test` 证据写入账本；不会调用模型或飞书。

阶段 6 的离线测试包含在单元测试中。真实飞书测试使用自建应用身份：在本机设置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 和测试空间的 `FEISHU_WIKI_SPACE_ID`，依次运行 `python3 -m cybertron.stage6_verify --check-env`、`--check-auth` 和 `--live`；最后一项会在该空间创建并保留一篇测试文档、追加正文并回读验证。完整步骤见[阶段 6 文档](docs/stages/06-feishu.md)。不要把 App Secret 或租户令牌提交到仓库或贴进聊天。

## v6 动态任务图（0.3）

v6 不再把九步流程写死在存储层。prima 通过 `cy_plan` 提交节点与依赖，内核按 `registry.py` 校验能力、角色和 `write_scope`，按实际 diff 计算风险下限；`insert_gate` 只能加门禁，风险下限内的门禁不能被模型标记为 N/A。派发仍走宿主原生 subagent，插件在派发前后校验节点、记录子会话，并在结束时用 `scope_guard` 计算 diff、越界即回滚。

- **M0–M2**：图 schema、单节点计划、写范围守卫、测试门四种结论；prima 规划权、风险门禁与 python/node/cmake-arm 配置档；真实 `clang-tidy`/CMake 回执。
- **M3**：并发写范围锁、Loop-1 修复循环、L2 拒绝后的局部返工。
- **M4**：设备审批绑定设备/固件/擦写范围/回滚镜像，Renode 仿真配置档，STM32 真机烧录与逐字节回滚。
- **M5**：完成后沉淀经重新校验的模板、从事件账本生成指标面板；同类需求第二次运行可复用模板并跳过只读发现节点。OpenCode 真实宿主上节点 2→1、人工干预 1→0。

## 安装到 OpenCode

三条安装路径共享同一份 payload（13 个角色、可选 `/cybertron` 命令、OpenCode 插件、Python 运行时和 DSH 适配器），默认 dry-run，`--apply` 才写入。公开版本为 **0.3.0**。

可从本源码分支安装，也可使用[三种公开安装方式](docs/packaging-and-installation.md)：

```bash
# 从源码分支安装到当前项目
python3 -m cybertron.installer init --dry-run --project /你的项目
python3 -m cybertron.installer init --apply --project /你的项目

# 或安装到当前用户的 OpenCode 全局配置，使所有项目可选择 prima
python3 -m cybertron.installer init --apply --global
```

安装目标：

- `--project DIR`：写入 `DIR/.opencode/` 下的角色、命令、插件及运行时
- `--global`：写入 `${XDG_CONFIG_HOME:-~/.config}/opencode/` 下的同一组文件

### 安装到 DeepSeek Harness（实验性）

bundle 随 npm/PyPI 包分发。先取得目录，再注册到目标 profile，最后新建会话选择 `Cybertron v6` preset：

```bash
BUNDLE="$(cybertron dsh path)"          # npm: npx cybertron-agents dsh path
dsh plugin --profile desktop add "$BUNDLE"
```

preset 只在选中的会话里挂载 `cy_plan`/`cy_state`/`cy_ask`/`cy_templates`/`cy_metrics`，不改变默认模式；工作目录需包含 Cybertron 运行时。DSH 的子代理状态显示在会话头部的子代理目录（运行中/完成、token、时长），不是 OpenCode 的内联卡片。移除：`plugin_manager remove_bundle @local/cybertron-dsh` 或 Plugins 页。限制见[适配器说明](cybertron/dsh_adapter/docs/DETAIL.md)。

安装后在目标项目运行 `opencode2 debug agents`，确认 13 个 Cybertron 角色加载。OpenCode 仍保持原有 Build/Plan 默认行为；用 **Shift+Tab** 选到 `prima`，直接输入自然语言软件需求即可自动创建 run 并接力。也可在 Build 模式输入 `/cybertron <需求>`，命令会选用 `prima` 并触发同一插件工作流。插件使用本机 Python 3.9+；`cybertron doctor` 只做本地检查。

### 配置十三角色模型编队（`0.2.0`）

安装后运行 `cybertron models setup`。默认配置当前用户的全局编队；再次运行同一命令，可以只修改一个角色、调整三档模型，或全部改为同一模型。`cybertron models show` 查看当前生效映射，`cybertron models doctor` 核对 OpenCode 实际加载的角色，`cybertron models rollback` 恢复上一份配置。`--project /path/to/project` 可为公司项目设置独立的完整十三角色编队，覆盖私人全局配置。配置只保存模型 ID，不保存 API Key。

```bash
# 公司的一把 Key 对应的高、中、低档模型已在 OpenCode 登记后
cybertron models setup --project /path/to/project \
  --high company/high --middle company/middle --low company/low --yes

# 个人多厂商混编：保留其余十二位，只切换一位
cybertron models setup --set solus-prime=anthropic/claude-model --yes

cybertron models show
cybertron models doctor
cybertron models rollback
```

已有的 OpenCode `/connect` 认证和 OpenCode 服务环境中的 Key 可以复用。公司使用 OpenAI 兼容网关时，可用 `cybertron models provider-add --provider-id company --base-url https://your-gateway.example/v1 --env-name COMPANY_API_KEY --model-id high --model-id middle --model-id low --yes` 登记非密钥元数据；38 个模型可重复添加 `--model-id` 参数。请通过 OpenCode 认证流程或其运行环境提供 Key。可选 `models setup --probe` 会在只含合成文件的临时目录逐个检查所选模型，可能产生少量模型费用。具体用法见[模型配置阶段记录](docs/stages/H-model-configuration.md)。

源码分支现在可离线创建并检查持久化 run：

```bash
python3 -m cybertron.installer workflow doctor --project .
python3 -m cybertron.installer workflow create "开发示例功能" --project .
python3 -m cybertron.installer workflow status <上一步的 run_id> --project .
python3 -m cybertron.installer workflow run <run_id> --project . --host fake
```

`fake` 仅模拟九步与证据，不能作为真实开发完成的证明。`workflow resume <run_id>` 只恢复账本，不重放宿主调用。手动真实调用使用 `--host opencode --allow-external-model`；在 OpenCode 内通过插件调用时，模型调用由用户选择 `prima` 或 `/cybertron` 触发。详情见[阶段 E 记录](docs/stages/E-opencode-orchestration.md)。

详见[安装与发布方案](docs/packaging-and-installation.md)、[v0.3.0 发布说明](docs/releases/v0.3.0.md)和[GitHub Release v0.3.0](https://github.com/zhiwenC125/Cybertron-agents/releases/tag/v0.3.0)。

## 飞书知识库（可选）

飞书能力由 `alpha-trion` 独占，**默认不启用**。需要时：

1. 在飞书开放平台创建自建应用，按**应用身份**开通 Wiki / Docx 权限并发布；
2. 让应用机器人所在的群聊成为目标知识空间管理员；
3. 设置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_WIKI_SPACE_ID`；
4. 按需在项目 `opencode.jsonc` 中启用只读 MCP（或从源码用 `--include-feishu` 导出）。

完整步骤、权限 scope、常见错误码与安全边界见[飞书知识库接入指南](docs/feishu-setup.md)；阶段验收记录见[阶段 6 文档](docs/stages/06-feishu.md)。

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
| `runstore.py` / `orchestrator.py` | 持久化 run、外层派单及中断恢复 |
| `hosts.py` / `workflow_cli.py` | 假宿主、受限 OpenCode 适配及本地工作流命令 |
| `simulation.py` | 不产生外部副作用的本地模拟执行器 |
| `isolated_runner.py` | macOS 沙箱内运行单元测试并生成 QA 证据 |
| `deployment.py` | 第七阶段固件、设备、擦写与回滚契约及无硬件仿真 |
| `exporters.py` | 双宿主静态配置导出 |
| `installer.py` | npm / shell / pipx 三条安装路径的 Python 入口 |
| `selfcheck.py` | 命令行自检 |

## 当前边界与下一步

1. `ledger.py` 与 `dispatch.py` 已实现 L1/L2 拒绝后返回编码、重审及超限阻塞；真实软件流程已生成宿主审查证明与隔离 QA 回执。宿主回执证明审查发生及项目文件被读取，不保证模型判断一定正确。
2. `policy.py` 是本地策略原型，不能代替宿主层权限和命令解析。生成配置后的真实权限仍需在目标宿主中验证。
3. DeepSeek Harness 适配器已实现为随包分发的 bundle：`cybertron dsh path`（npm 为 `npx cybertron-agents dsh path`）给出目录，再执行 `dsh plugin --profile <profile> add <目录>`，新建会话选择 `Cybertron v6` preset。它目前是单一 prima persona + `cy_*` 工具，DSH 子会话尚未绑定节点 `write_scope`，因此定位为实验性第二宿主。
4. 阶段 6 的 Wiki OpenAPI 读写已由开发者在专用测试空间验收；阶段 7 的 STM32 最小真机烧录及回滚已通过。完整 OTA App、ESP32-S3、外部 Flash 备份和隔离构建仍待开发。

缺少飞书 App ID 或 App Secret 时，网关默认报错。模拟租户令牌仅能通过显式传入 `mock_if_unset=True` 用于局部测试，不会进入真实 Wiki 请求。
