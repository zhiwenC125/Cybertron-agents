# 后续阶段 E：OpenCode 外层编排

状态：**离线开发切片通过，阶段完整目标未完成**。本轮没有调用外部模型、飞书或设备。

## 已交付

- `RunCoordinator` 将九步账本与宿主的单次角色调用分开。每次先持久化 `dispatch.started`，再调用宿主，最后持久化带 `host_session_id`、turn ID 和结果状态的 `dispatch.completed`。同一 run 使用事件序号检查避免并发派单。
- 调用抛错、进程在派单后中断、宿主身份不符时，状态保持 `outcome_unknown`；`step`、`run`、`resume` 不会自动重试该次调用。用户需核对宿主实际结果后再设计人工消歧流程。
- 假宿主通过九步、一次 L2 拒绝返工、重启续跑、错误角色阻塞、硬件审批前停下等测试。模拟批准只用于离线状态机测试，不是实际设备授权。
- OpenCode 适配器仅开放第 1、3、5 步中的既有只读角色。CLI 调用真实模型要求 `--allow-external-model`。模型生成的 L2 文字仍不能作为真实质量门禁回执；第 2 步写文档等角色会阻塞。
- `workflow create/status/resume/step/run/doctor` 可管理本地 run。`/cybertron` Markdown 入口明确说明只提供提示词，**不会创建持久化 run**。试验性本地插件未能在本机验证加载，未纳入交付，以免干扰现有 OpenCode 使用。

## 开发者与用户怎么用

先运行 `python3 -m cybertron.installer workflow doctor --project .` 核对 13 角色配置，再以 `workflow create "需求" --project .` 创建 run。使用返回的 `run_id` 执行 `workflow status <run_id> --project .`。需要观察离线九步时，用 `workflow run <run_id> --project . --host fake`；输出中的模拟证据不能代替真实测试和审查。OpenCode 中可继续单独使用 13 个已导出的角色，但 `/cybertron` 当前不会替你完成九步接力。

## 仍待完成

1. 用真实 OpenCode 只读回合验证会话和 turn ID、权限拒绝、取消与超时事件；这会向外部模型发送任务内容，本轮遵守用户既有边界而未执行。
2. 将真实宿主的工具、权限及隔离 QA 回执映射为可独立核验的证据，再开放写角色。当前 Python `policy.py` 不能代替 OpenCode 宿主权限。
3. 实现并验证 `/cybertron` 到 Python 编排器的加载连接、宿主查询与人工消歧，使界面能显示 run ID、下一角色和停滞原因。
4. 按具体目标、路径和审批范围开放飞书写入、构建及硬件角色；真机操作继续逐次审批。

## 验收证据

离线命令、退出码及输出摘要见 [`E-opencode-orchestration-acceptance.json`](E-opencode-orchestration-acceptance.json)。该摘要不能证明真实 OpenCode 九步已运行，也不能代替原始宿主回执。
