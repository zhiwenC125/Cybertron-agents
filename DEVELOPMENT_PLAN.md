# Cybertron 开发状态

当前公开版本为 **0.9.0**，主开发分支为 `main`，`release/0.9.0` 对应发布提交。[发布说明](docs/releases/v0.9.0.md) · [文档目录](docs/README.md)

## 已交付

| 范围 | 当前状态与证据 |
| --- | --- |
| OpenCode 日常软件任务 | Prima 默认入口、Thirteenth 直接规划、同一 run 修订、按任务验证，均有隔离项目验收。[实现记录](docs/plans/cybertron-lightweight-harness-loop.md) · [结构化回执](docs/testing/harness-loop-release-validation.json) |
| 角色权限与质量门禁 | 角色注册表、宿主权限、隔离 QA 和来源校验已接入。隔离配置适用于 macOS `sandbox-exec`。[权限说明](design/role-capability-matrix.md) · [阶段 5](docs/stages/05-quality-gates.md) |
| 安装与模型配置 | npm、PyPI 和 GitHub Release 已提供安装入口。模型编队支持全局、项目覆盖和回滚。[安装与升级](docs/packaging-and-installation.md) |
| 飞书 | 自建应用在专用测试空间完成网关读写。按 Wiki 空间授权启用。[用户指南](docs/feishu-setup.md) · [历史回执](docs/stages/06-feishu-acceptance.json) |
| STM32 最小设备闭环 | 旧阶段已验证最小 App 的受控烧录、SRAM 心跳和原固件恢复。[设备阶段记录](docs/stages/07-deployment.md) |
| DSH 适配 | 随包提供实验性单一 persona 和账本工具。十三角色子会话和回执绑定仍以 OpenCode 路径为准。[适配器说明](cybertron/dsh_adapter/docs/DETAIL.md) |

## 尚待覆盖

- 完整 OTA App 与 ESP32-S3 的真机结果仍需分别验收。
- 通用设备上电和远程部署的宿主入口仍待接入。每次实际动作继续按项目安全基线取得授权。
- DSH 的子会话写入范围和可信回执绑定仍待实现。

历史架构、阶段记录和旧版本验收从 [历史里程碑](docs/stages/v6-progress.md) 访问。当前开发验证和发布规则见 [贡献指南](CONTRIBUTING.md) 与 [发布流程](RELEASE.md)。
