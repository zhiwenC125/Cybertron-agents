# 历史里程碑与验收

这些记录对应各阶段实际执行的版本与环境。当前 OpenCode 路径及其验收见 [0.9.0 实现记录](../plans/cybertron-lightweight-harness-loop.md) 和 [结构化发布回执](../testing/harness-loop-release-validation.json)。

## v6 动态任务图

| 里程碑 | 历史验收范围 | 结构化摘要 |
| --- | --- | --- |
| M0a | 计划图基础和自动门禁 | [摘要](v6-m0a.json) |
| M0b | 真实子进程派发与越界回滚 | [摘要](v6-m0b.json) |
| M0c | OpenCode 子代理卡片、工具回执和写入范围 | [摘要](v6-m0c.json) |
| M1 | 能力目录、权限一致性与多种任务图形状 | [摘要](v6-m1.json) |
| M2 | 真实 CMake 与 clang-tidy 回执、变更风险门禁 | [摘要](v6-m2.json) |
| M3 | 并发隔离、局部重试与 L2 拒绝后的子图返工 | [摘要](v6-m3.json) |
| M4 | Renode 配置、设备审批和 STM32 最小烧录及回滚 | [摘要](v6-m4.json) |
| M5 | OpenCode 模板复用和 DSH 适配器加载 | [摘要](v6-m5.json) |

每份摘要注明原始证据路径及 SHA-256。原始记录、日志和一次性探针可从发布标签追溯。[历史脚本](https://github.com/zhiwenC125/Cybertron-agents/tree/v0.9.0/scripts) · [完整阶段记录](https://github.com/zhiwenC125/Cybertron-agents/blob/v0.9.0/docs/stages/v6-progress.md)

## 早期基线

- [基础](01-foundation.md) · [本地执行](02-local-execution.md) · [OpenCode 配置](03-opencode-config.md) · [宿主执行器](04-opencode-executor.md) · [质量门禁](05-quality-gates.md)
- [飞书](06-feishu.md) · [设备与固件](07-deployment.md) · [首个持久化与双宿主规划](https://github.com/zhiwenC125/Cybertron-agents/blob/v0.9.0/docs/handoffs/2026-11-14-runtime-architecture.md)
- [历史 OpenCode 0.8.0 试用](https://github.com/zhiwenC125/Cybertron-agents/blob/v0.9.0/docs/opencode-trial.md) · [当前 OpenCode 自然语言验收](../testing/opencode-acceptance.md)
