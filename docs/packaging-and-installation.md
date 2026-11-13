# Cybertron 安装与发布方案

## 当前可用范围（2026-11-14）

七个开发阶段的**最小闭环基线**已到达：前六阶段按各自离线或指定测试空间条件验收；第七阶段的 STM32 最小 App 经人工批准后完成真机烧录、SRAM 心跳和原固件逐字节回滚。完整 OTA App、ESP32-S3、隔离构建接入角色工具、宿主审批回执与 DeepSeek Harness 插件仍在开发。真机结果是特定设备的验收证据，不属于安装包运行时。

本仓库现在可在 **OpenCode V2** 中加载 13 个角色，当前验证版本为 `opencode v2.3.0`。`opencode2 debug config` 已读取项目配置，`opencode2 debug agents` 已列出全部 13 个 Cybertron 角色；全部角色的模型 ID 均在本机模型目录中。配置加载不等于真实模型调用或九步自动接力：本仓库的真实执行器目前只接入第 1 步的 `thirteenth` 角色，其余流程仍以离线模拟和局部宿主权限测试为主。

## 现在可以复现的项目内使用

先安装 Python 3.9+ 和 [OpenCode V2](https://opencode.ai/docs/)。使用者自行在 OpenCode 中连接 DeepSeek；凭证不由 Cybertron 安装脚本收集，也不得写入仓库。以下命令只加载配置和运行本地测试，不调用模型：

```bash
git clone https://github.com/zhiwenC125/Cybertron-agents.git
cd Cybertron-agents
python3 -m unittest discover -s tests -q
opencode2 debug config
opencode2 debug agents
```

在仓库目录运行 `opencode2` 可进入交互界面并看到默认 `prima` 角色；发送提示后会调用配置的模型。`python3 -m cybertron.opencode_run "你的需求"` 是当前第 1 步真实执行入口，同样会调用模型。**不要把 `opencode2 debug config` 或单元测试的通过，解释为完整多角色自动开发已可用。** 本机已迁移到 `deepseek/deepseek-flash` 与 `deepseek/deepseek-v4-pro`；在新电脑上仍需用 `opencode2 models` 检查该版本的模型目录和账号权限。模型调用可能产生费用。

飞书是可选功能。默认配置不启用 MCP；要使用阶段 6 的 Wiki 网关，使用者必须自行准备自建应用、测试空间、环境变量和知识库管理员权限。真实 Wiki 写入只在明确指定的测试空间执行，详见 [阶段 6](stages/06-feishu.md)。

## 下一步封装成一条安装命令

1. **固定发布边界**：给稳定基线打版本标签（建议 `v0.1.0`），在发布说明中列出 OpenCode V2 与 Python 支持版本、当前只接入第 1 步的限制，以及阶段 7 的真机验收范围。仓库中的 `local_backups/`、凭证和本机构建产物不进入发布包。
2. **Python 包与命令行**：增加 `pyproject.toml`，用 `pipx` 或 `uv tool` 安装 `cybertron-agents` 命令。提供 `cybertron init --target /path/to/project --dry-run` 和显式 `--apply`，从 `registry.py` 导出项目级 `opencode.jsonc` 与 `.opencode/agents/`。默认不启用飞书，不改用户全局 OpenCode 配置；目标文件已存在时显示差异并要求明确覆盖，先备份再写入。加入 `cybertron doctor` 检查 Python、OpenCode 版本、模型目录、配置一致性和可选凭证是否存在，但不打印密钥。
3. **可审核安装入口**：发布版使用固定 tag/提交和校验值；在 GitHub Releases 提供 wheel/sdist 与 SHA-256。文档推荐 `pipx install cybertron-agents==<version>`（发布到包索引后）或固定 tag 的 Git URL。避免将远端脚本直接通过 `curl | sh` 执行。安装命令只安装文件，项目初始化由使用者单独执行并预览变更。
4. **多平台验收**：CI 在 macOS、Linux、Windows 检查包构建、13 角色导出、Markdown/JSON 权限一致性、OpenCode 配置解析和 `doctor`。当前 `stage5_verify` 使用 macOS `sandbox-exec`，跨平台版本需要各系统的隔离后端；未完成前只承诺配置可加载，不承诺测试/构建 Shell 的宿主隔离。
5. **后续接力与 Harness**：先实现 OpenCode 中的九步宿主执行、结构化 QA 证据和不可伪造的人工审批回执，再将同一 `registry.py` 契约映射到 `.dsh/cordis-cybertron-plugin.mjs`。DeepSeek Harness 目前只有静态预设 JSON，应作为独立实验包和验收矩阵，避免把预设误当成可运行插件。

推荐的最终用户流程是：安装固定版本 → `cybertron doctor` → 在目标项目运行 `cybertron init --dry-run` → 审核后 `--apply` → `opencode2 debug agents` → 自行连接模型并开始使用。项目级安装便于回滚与版本锁定，也不会把 Cybertron 权限扩散到用户的所有项目。

## 参考

- [OpenCode V2 安装](https://opencode.ai/docs/)
- [OpenCode 项目配置位置与优先级](https://opencode.ai/docs/config)
- [OpenCode 智能体文件](https://opencode.ai/docs/agents)
- [DeepSeek 模型更新](https://api-docs.deepseek.com/news/news260424/)
