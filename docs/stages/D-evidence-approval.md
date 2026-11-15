# 后续阶段 D：证据来源、审批与副作用围栏

状态：本地离线开发验收通过；未接入真实宿主审批或硬件执行。

## 交付内容

- `QualityEvidence` 增加来源类型、工具或命令、退出码、UTC 时间、输出摘要、验证者和引用。旧三字段证据读取为 `unverified`，不能冒充工具通过。OpenCode 模型返回的 L2 结论标为 `model`；隔离测试回执标为 `sandbox`，并由执行器按实际报告摘要核对。
- L1、L2 和测试门禁要求格式完整的工具、沙箱或宿主回执，并要求执行器提供独立验证方法。纯模型文字或自称 `host` 的对象不能通过。离线模拟需显式启用 `allow_simulated_evidence`，其结果不构成真实验收。
- `SideEffectGuard` 记录 `operation.planned → approval.granted → operation.started → operation.completed/failed`。计划摘要覆盖设备或飞书空间、操作范围、固件、擦写范围及回滚摘要；审批回执绑定 `run_id`、`plan_id`、计划摘要、目标和范围。没有可信宿主验证回调，批准与执行回执均被拒绝。
- 每个计划有幂等键。已开始但缺少工具回执时状态为 `outcome_unknown`，同一计划不能自动再次开始。事件 payload 有摘要校验；操作只记录脱敏引用和输出哈希，不复制完整工具输出。

## 开发者接入约束

`SideEffectGuard` 不执行操作。阶段 E 的宿主适配器须从宿主权限/审批事件构造验证回调；不能将模型生成的 JSON 当作验证器。真实烧录、设备上电、远程部署仍需本仓库 `AGENTS.md` 要求的逐次人工批准。飞书写入仍只允许 `alpha-trion` 通过受测试空间约束的 Python 网关执行。本阶段的测试批准均为假回执，不构成任何真实操作授权。

## 验收与限制

结构化回执见 [`D-evidence-approval-acceptance.json`](D-evidence-approval-acceptance.json)。离线测试覆盖模型和伪造来源拒绝、隔离 QA 真报告验证、审批与目标/固件/run 绑定、回执丢失后的 `outcome_unknown`、拒绝重复启动、飞书空间约束和事件 payload 篡改。原阶段 5 隔离检查保持通过。没有调用外部模型、飞书或硬件。

公开验收文件仅保存结论与摘要；没有原始工具输出时，第三方无法凭摘要完整复验。完整本机回执应由操作宿主保存，阶段 E 将记录其引用和校验方式。

## 下一阶段接口

阶段 E 将 OpenCode 的会话、派单、权限和工具结果映射到 Cybertron run，并在宿主层验证回执；先以假宿主完成九步和返工，再逐步开放真实只读角色。
