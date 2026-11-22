# 后续阶段 E：OpenCode 外层编排

> 历史阶段记录，正文反映当时的版本和验证范围。当前行为见 [开发状态](../../DEVELOPMENT_PLAN.md)。

状态：**软件路径完成本地开发与真实宿主验收；物理硬件执行仍须专项审批；`0.2.0` 待发布。**

## 用户入口

三种安装器都放入 13 个角色、可选命令、插件和 Python 运行时，保留 OpenCode 的 Build/Plan 默认行为。用户在 TUI 中用 Shift+Tab 选 `prima` 后直接输入软件需求，`prima` 会调用 `cybertron_run`。在 Build 模式运行 `/cybertron <需求>` 也会选择 `prima` 并触发相同工具。本机 TUI 已验证后一入口，OpenCode 会话的 `agent` 字段确认为 `prima`。单独运行 CLI `opencode2 run '/cybertron ...'` 会把斜杠文本当普通提示，不等同于 TUI 命令。

插件通过安全分隔的 argv 调用随安装包提供的 Python 运行时；不会让项目目录中的同名 Python 包覆盖运行时代码。用户请求、run ID 和宿主会话的关联保存在本地 `.cybertron/`，其中 `.gitignore` 默认阻止 `git add .` 上传运行记录。每次派单先写 `dispatch.started`，再调用 OpenCode V2；真实 `sessionID`、`messageID` 与结果写入 `dispatch.completed`。未确认结果保持 `outcome_unknown`，不能自动重试。

## 软件九步与证据

- 软件计划保留九步顺序，依次澄清、整理本地需求、侦察与架构、编码、L1/L2 审查、测试、构建检查、无硬件判断、文档交付。纯软件请求不要求飞书或设备；第 8 步使用独立 `stage.skipped` 事件，未伪称震天尊执行烧录。
- 真实宿主仅执行各角色在 OpenCode 配置中获准的文件工具。普通角色不获得直接测试 Shell。L1/L2 宿主回执关联审查消息、项目读取工具事件及输出摘要；宿主回执证明审查确实发生，不能证明模型判断绝对正确。模型自称 PASS 的字段本身不能越过质量门禁。
- 测试角色编写 `tests/**` 后，宿主用 macOS `sandbox-exec` 运行 `unittest`，核对退出码和非零测试数。沙箱拒绝网络、项目写入及设备读取；缺少隔离运行器或测试失败则阻塞。
- 真实软件验收在干净临时项目完成：12 次角色派单、九步账本完成、L1/L2 宿主回执、3 项隔离单元测试通过、重放校验通过。模型调用已按用户新授权执行；没有飞书写入、设备上电或物理烧录。

## 安装与开发者验收

从源码安装候选版：`python3 -m cybertron.installer init --apply --project <目标项目>`，或 `--global` 供所有项目选择 `prima`。npm tarball、Python wheel 和本地 Shell 脚本已分别在干净项目安装，核对角色、插件、运行时及 `doctor`，并各自用真实 OpenCode 会话触发持久化 run。公开 `0.1.1` 尚无此功能；候选版的发布需另行完成。

2026-11-15 已把本地 `0.2.0` 候选版安装到开发机的全局 OpenCode 配置，原有 `opencode.jsonc` 保持原样。全局 `doctor`、`debug agents` 和一个无项目配置的临时目录中的真实 `prima` 调用均通过。其他项目可直接打开 OpenCode，Shift+Tab 选 `prima` 后输入自然语言；Build 中的 `/cybertron <需求>` 是 TUI 快捷入口。

本地回归命令：`python3 -m unittest discover -s tests -q`、`python3 -m cybertron.stage5_verify`、`python3 cybertron_primes_engine.py`、`opencode2 debug config`。结构化回执见 [`E-opencode-orchestration-acceptance.json`](E-opencode-orchestration-acceptance.json)。公开摘要包含结论与哈希，不复制模型对话或项目文件。

## 保持的边界

硬件计划可以推进到物理操作之前；`megatronus` 的真实派单仍被宿主适配器拒绝，直至具备目标设备、固件摘要、擦写范围、回滚方案和针对该次操作的人工批准。飞书写入只允许 `alpha-trion` 经受空间约束的 Python 网关执行，真实测试仍限专用空间。DeepSeek Harness 第二宿主属于阶段 F。已完成的 run 在运行时或权限配置升级后可能需要显式迁移，旧 run 不会被静默重放。
