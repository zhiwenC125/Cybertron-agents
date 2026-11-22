# 阶段 H：十三角色模型配置与混合编队

> 历史阶段记录，正文反映当时的版本和验证范围。当前行为见 [开发状态](../../DEVELOPMENT_PLAN.md)。

日期：2026-11-15。状态：本地验收完成，并随公开 `0.2.0` 发布。

当前安装、模型配置和两种 OpenCode 入口以 [安装指南](../packaging-and-installation.md) 为准。以下保留 0.2.0 交付时的实现和验收说明。

## 实现与恢复

- 全局编队：`${XDG_CONFIG_HOME:-~/.config}/cybertron/models.json`；项目编队：`DIR/.cybertron/models.json`，自动创建本地 `.gitignore`。配置只含模型 ID、三档、供应商白名单与版本。
- 保存前检查十三角色完整性及 OpenCode 当前目录。保存后调用 `opencode2 debug agents --standalone` 核对实际加载；不一致则恢复原编队和角色文件。更新安装包时重新应用当前编队。
- 重配保留编号备份；`rollback` 恢复前一份。运行中的 run 遇到编队摘要变化会阻塞，新任务开始新 run。不同供应商之间没有静默自动回退。
- Shell 安装在目标 `.opencode/bin/cybertron` 提供启动器。npm 和 Python 安装包均提供 `cybertron` CLI。三种方式不修改 PATH 或读取用户已有 Key。

## 验收证据

1. `python3 -m unittest discover -s tests -v`：112 项测试通过，4 项按环境跳过。
2. `python3 -m cybertron.stage5_verify`：隔离 QA 完成；项目写入、设备读取、网络连接被阻止，测试证据保存在沙箱回执。
3. `python3 cybertron_primes_engine.py`：自检通过；权限导出保持一致。
4. npm tarball 与 Python wheel 的 13 个角色、命令、插件和运行时文件一致。各自临时项目与 Shell 安装均能设置模型并通过 `models doctor`；npm 临时项目的 `opencode2 debug config --standalone` 解析成功。
5. 临时项目真实 OpenCode 会话曾验证 `prima` 按项目编队从默认模型切换至 `deepseek/deepseek-flash`，并调用 `cybertron_run`。公司 38 模型目录用合成 ID 在独立临时 OpenCode 配置中登记，`opencode2 models --standalone` 检出了 38 个；未使用公司真实 Key。

## 交付范围

`0.2.0` 已在 npm、PyPI 和 GitHub Release 公开；渠道与归档核验见[发布记录](I-release-020.md)。公司环境的接口认证与真实 38 模型能力仍由公司机器上的 OpenCode 与可选 `--probe` 验证；本地验收不代表公司网关已连通。
