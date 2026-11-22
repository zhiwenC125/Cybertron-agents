# v6 动态任务图设计记录

早期 v6 方案将固定九步账本迁移为动态任务图。M0–M5 分别覆盖宿主接入、可扩展计划、工具门禁、调度与返工、设备验证和模板复用。里程碑的实际覆盖范围见 [历史验收索引](../docs/stages/v6-progress.md)。

`0.9.0` 已在 v6 图之上交付轻量化 Harness Loop，引入两种入口、同一 run 重规划和按任务匹配的验证。[当前架构](cybertron_13_primes_architecture.md) · [实现记录](../docs/plans/cybertron-lightweight-harness-loop.md) · [开发状态](../DEVELOPMENT_PLAN.md)

完整的初版方案、当时的诊断和实施顺序见 [v0.9.0 历史树](https://github.com/zhiwenC125/Cybertron-agents/blob/v0.9.0/design/DEVELOPMENT_PLAN.md)。
