# Cybertron Thirteen Primes

当前开发阶段和每阶段验收条件见 [开发计划](DEVELOPMENT_PLAN.md)。

各阶段的代码摘录、验收记录与后续实现建议见 [阶段文档目录](docs/stages/01-foundation.md)：[1](docs/stages/01-foundation.md) · [2](docs/stages/02-local-execution.md) · [3](docs/stages/03-opencode-config.md) · [4](docs/stages/04-opencode-executor.md) · [5](docs/stages/05-quality-gates.md) · [6](docs/stages/06-feishu.md) · [7](docs/stages/07-deployment.md)。参考资料新增 [Datawhale Hello Agents](https://datawhalechina.github.io/hello-agents/#/)。

本仓库是 [v5 架构白皮书](design/cybertron_13_primes_architecture.md)的 Python 原型。当前实现包含 13 个角色的静态定义、权限规则、9 步任务账本、飞书令牌客户端，以及 OpenCode V2 / DeepSeek Harness 配置导出。已有一个只读角色的 OpenCode V2 命令行适配器；完整多智能体流程仍在开发中。

## 运行

需要 Python 3.9 或更新版本，无第三方 Python 依赖。

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

## 模块

| 模块 | 职责 |
| --- | --- |
| `schema.py` | 消息和工具调用数据结构 |
| `compaction.py` | 上下文首尾压缩 |
| `policy.py` | 本地权限与循环熔断检查 |
| `feishu.py` | 飞书租户令牌获取和缓存 |
| `registry.py` | 13 个角色配置 |
| `ledger.py` | SDLC 计划和顺序状态转换 |
| `execution.py` | 宿主无关的任务、结果和执行器协议 |
| `dispatch.py` | 派单、结果校验和账本推进 |
| `simulation.py` | 不产生外部副作用的本地模拟执行器 |
| `exporters.py` | 双宿主静态配置导出 |
| `selfcheck.py` | 命令行自检 |

## 当前边界与下一步

1. `ledger.py` 与 `dispatch.py` 目前只保证顺序、执行结果身份和证据字段完整；尚未验证 L1/L2 审查裁决、测试报告或人工烧录授权的真实性。L2 审查拒绝后目前会阻塞该步，尚未实现返回编码角色修复并重新审查的循环。
2. `policy.py` 是本地策略原型，不能代替宿主层权限和命令解析。生成配置后的真实权限仍需在目标宿主中验证。
3. DeepSeek Harness 目前只导出预设 JSON，白皮书中的 `.dsh/cordis-cybertron-plugin.mjs` 尚未实现。
4. 下一阶段应接入宿主适配器，再将审查、测试、烧录审批证据接入账本；最后做飞书 Wiki 内容操作与真实硬件集成测试。

缺少飞书凭证时，令牌客户端默认报错。模拟令牌仅能通过显式传入 `mock_if_unset=True` 用于局部测试。
