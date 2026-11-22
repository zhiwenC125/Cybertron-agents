# 十三角色职责与权限

职责和宿主权限由 [角色注册表](../cybertron/registry.py) 定义，动作上限与审批规则由 [权限矩阵](../cybertron/authority.py) 约束。角色 Markdown 与 OpenCode JSON 通过导出器生成。[当前架构](cybertron_13_primes_architecture.md)

| 角色 ID | 职责与范围 |
| --- | --- |
| `prima` | 默认编排入口。接续 run、派发、跟踪、结算和报告证据。计划创建和修订由 Thirteenth 负责。 |
| `thirteenth` | 理解意图、澄清关键歧义、规划架构和验收、提交与修订计划。`mode: all` 支持直接选择或由 Prima 调用。 |
| `onyx-prime` | 只读侦察仓库结构、模块关系和入口调用链。 |
| `vector-prime` | Git 历史、差异、基线和分支。涉及 Git 写入时遵守具体命令权限及审批。 |
| `quintus-prime` | 复现与诊断故障、验证假设、定位根因、提出修复建议，提供接口、HAL 和脚手架设计支持。业务代码由 Solus 修改。 |
| `solus-prime` | 常规源码实现、修复、重构、解耦、优化和移植。写入限制在计划分配的范围内。 |
| `amalgamous` | 定义临时专才的任务、工具和约束，受已注册的权限上限约束。 |
| `alpha-trion` | 工程文档与知识整理。通过指定网关进行受空间约束的飞书 Wiki 同步。 |
| `micronus-prime` | L1 质量检查。静态审查用已授权的读工具，绑定隔离检查的验证节点可以执行对应检查。 |
| `liege-maximo` | L2 深度审查。核对逻辑、接口、架构、并发与权限边界。 |
| `alchemist` | 测试策略、编写、运行和场景执行。保存真实工具回执。 |
| `nexus-prime` | 构建准备、打包、部署和结果处理。物理操作和远程部署需要专项授权。 |
| `megatronus` | 核对交付物与真实回执是否满足验收条件。 |

角色的能力仍需绑定到实际节点。宿主根据真实工具、目标和授权决定能否操作，工具回执和产物哈希用于结算。详细的适用条件见 [安全基线](../AGENTS.md)。

旧版本的权限审查记录见 [v0.9.0 历史树](https://github.com/zhiwenC125/Cybertron-agents/blob/v0.9.0/design/role-capability-matrix.md)。
