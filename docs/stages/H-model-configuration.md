# 阶段 H：十三角色模型配置与混合编队

日期：2026-11-15。状态：本地候选版已实现并验收；公开 `0.1.1` 尚未包含。

## 用户路径

三种安装方式完成后，运行 `cybertron models setup`。交互向导展示当前十三角色映射，支持只改一个角色、重新指定高/中/低三档、统一模型或退出。再次运行同一命令即可切换；`show` 查看最终映射，`doctor` 对照 OpenCode 模型目录、角色文件、命令文件与实际加载的角色，`rollback` 恢复上一份配置。`--project DIR` 配置公司项目；项目完整编队覆盖用户全局编队。

已有 OpenCode 认证由 OpenCode 继续管理。`provider-add` 只登记 OpenAI 兼容网关的地址、环境变量名称和模型 ID，不读取或保存 Key；模型选择必须能从 OpenCode 模型目录中查到。可选 `--probe` 在只有合成文件的临时目录检查所选模型的读取工具和结构化回复，可能产生费用。公司网关如只配置在项目局部，在线探测需要先将该网关登记到全局 OpenCode 作用域。

OpenCode 中仍用 Shift+Tab 选 `prima` 后输入自然语言，或在 Build 中运行 `/cybertron`。插件将主角色会话切换到编队中的模型并核对上下文；子角色派单显式带对应模型。run 保存编队摘要，编队切换时旧 run 阻塞，避免在同一 run 内混用模型。模型配置层不修改 `registry.py` 中的角色权限，也不授予物理操作许可。

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

本地 `0.2.0` 候选版可在用户机器上使用。公开 npm、PyPI 和 GitHub Release 仍是 `0.1.1`，发布需单独完成正式 tag、归档校验和渠道上传。公司环境的接口认证与真实 38 模型能力由公司机器上的 OpenCode 与可选 `--probe` 验证；本地验收不代表公司网关已连通。
