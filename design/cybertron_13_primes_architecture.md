# Cybertron 架构

本文对应 `0.9.0` 的 OpenCode 实现。当前以动态任务图执行软件任务，按任务风险选用验证，保留受控硬件交付的独立授权边界。[角色与权限](role-capability-matrix.md) · [实现记录](../docs/plans/cybertron-lightweight-harness-loop.md)

## 宿主、计划与执行

1. OpenCode 提供对话、模型调用、子会话、工具和权限提示。
2. Prima 是默认编排入口。新任务交给 Thirteenth 规划。用户也可以直接选择 Thirteenth 看方案，再回到 Prima。已经提交的计划可以在同一会话接续。
3. Thirteenth 把目标、验收条件、节点、依赖和写入范围提交给内核。提交和修订时检查角色、权限上限、依赖、写范围、验收覆盖与必需验证能否执行。
4. Prima 按就绪状态派发。每次派发有独立回执和快照。OpenCode 原生权限约束子会话，内核结合实际变更判断是否越界。
5. 简单交付可凭文件回读和哈希结算。需要测试、构建或审查时按验收条件取得真实工具回执，再由 Megatronus 核对。执行证据推翻方案时，Thirteenth 在同一 run 修订，已完成且仍有效的工作可以复用。

## 实现入口

| 部分 | 源文件 |
| --- | --- |
| 角色职责与权限导出 | [registry.py](../cybertron/registry.py) · [exporters.py](../cybertron/exporters.py) |
| 计划图和依赖 | [graph.py](../cybertron/graph.py) |
| OpenCode 交接、调度与持久化 | [OpenCode 插件](../cybertron/v6_plugin/cybertron.js) · [host_v6.py](../cybertron/host_v6.py) · [scheduler_v6.py](../cybertron/scheduler_v6.py) |
| 工作区边界、检查和设备操作 | [scope_guard.py](../cybertron/scope_guard.py) · [isolated_runner.py](../cybertron/isolated_runner.py) · [device_broker.py](../cybertron/device_broker.py) |
| 模型编队、飞书与另一宿主 | [model_config.py](../cybertron/model_config.py) · [feishu.py](../cybertron/feishu.py) · [DSH 适配器](../cybertron/dsh_adapter/docs/DETAIL.md) |

运行记录按项目保存在 `.cybertron/`。事件账本记录计划版本、派发、回执和授权。任务模板可以从完成的 run 中提取，复用时再次经过计划校验。早期 `run/session/workflow` 入口继续服务既有账本和兼容验收。

## 验收边界

- OpenCode 处理实际权限，项目外写入及其他受控动作按具体目标授权。真机上电、物理烧录和远程部署遵循项目专项审批。[安全基线](../AGENTS.md)
- 主机单元测试、静态检查和固件构建可以在具备工具链的项目中执行。真实上板结果以设备回执为准。STM32 有单独的历史设备验收，通用上电和远程部署的宿主入口仍待接入。[设备阶段记录](../docs/stages/07-deployment.md)
- DeepSeek Harness 适配器提供单一 persona 和基础工具访问，缺少 OpenCode 的十三角色子会话绑定。[适配器说明](../cybertron/dsh_adapter/docs/DETAIL.md)

早期 v5 白皮书保存在 [v0.9.0 历史树](https://github.com/zhiwenC125/Cybertron-agents/blob/v0.9.0/design/cybertron_13_primes_architecture.md)。当前测试方式和验收结果见 [OpenCode 验收](../docs/testing/opencode-acceptance.md)。
