# 后续阶段 A：配置与安装基线

> 历史阶段记录，正文反映当时的版本和验证范围。当前行为见 [开发状态](../../DEVELOPMENT_PLAN.md)。

状态：本地离线开发验收通过；尚未发布新版公共安装包。历史七阶段编号不受影响。

## 交付内容

- 从 `registry.py` 临时导出 OpenCode V2 文件，与仓库根目录 `opencode.jsonc`、13 份角色 Markdown 逐字节比较；同时比较 Python 内置 payload 和根目录的角色、命令文件。根目录配置漂移会使单元测试失败。
- 修复安装器测试使用项目根目录临时文件导致的阶段 5 隔离验收失败。隔离配置仍禁止项目写入、设备读取和网络连接。
- Python wheel 内置 13 份角色和 `/cybertron` 命令；默认不再从 GitHub `main` 下载与包版本不一致的 payload。Shell 下载默认固定到 `v0.1.1` tag，分支必须显式指定。npm 打包仍从仓库配置生成 payload。
- 三入口都默认预览、要求 `--apply` 写入、保留编号备份，并在失败时回滚本次文件改动。已有 JSONC 配置保持原字节；若缺少 `default_agent`，先要求用户修复，避免改写注释或未知字段。Shell 对现有配置只做字段文本检查，最终解析仍须运行 OpenCode 的 `debug config`。
- 新增 macOS CI：单元测试、阶段 5 隔离验收、引擎自检、npm 与 wheel 内容检查。宿主离线测试覆盖 Node CLI；Node 26 在本机 `sandbox-exec` 下启动崩溃，隔离验收只覆盖 Python 与 Shell，未放宽沙箱。

## 用户使用与限制

在源码分支的干净临时项目可分别运行 `python -m cybertron.installer init`、`node bin/cybertron.mjs init` 或 `bash install.sh`。先预览，再加 `--apply`；`doctor` 检查安装数量和配置存在性。已有配置的默认角色可以不是 `prima`，安装器会保留用户选择。新版尚未发布到 npm、PyPI 或 GitHub Release，公共 `0.1.1` 包仍是旧实现；正式发布需统一版本、tag 和归档摘要。

## 验收证据

结构化本机回执见 [`A-installation-baseline-acceptance.json`](A-installation-baseline-acceptance.json)。离线测试覆盖三入口的预览、安装、重复安装、两次升级备份、`doctor`、现有配置保留及失败处理；Python、Node 与 Shell 的失败回滚分别有测试。没有调用外部模型、飞书或硬件。

## 下一阶段接口

阶段 B 增加独立的 RunStore 与离线 CLI，不改变这 13 个角色的权限来源。运行态默认存放项目级 `.cybertron/`，不得进入安装 payload 或 Git。
