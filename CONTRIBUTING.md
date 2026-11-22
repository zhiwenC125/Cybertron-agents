# Contributing to Cybertron Agents

感谢参与 Cybertron Agents。当前稳定发布线是 `main`；请从 `main` 新建短期分支，通过 Pull Request 合并。发布包、权限配置和宿主插件会影响所有 13 个角色，请让每个变更可审查、可验证、可回退。

## 开始开发

1. 阅读 [架构设计](design/cybertron_13_primes_architecture.md)、[开发计划](DEVELOPMENT_PLAN.md)、[安全基线](AGENTS.md)和相关[阶段记录](docs/stages/v6-progress.md)。
2. 从最新 `main` 建分支，名称说明目的，例如 `feat/model-routing` 或 `fix/installer-backup`。
3. 修改功能时同步更新使用说明。提交结构化摘要时应去掉本机路径、凭证、私有模型目录、项目文件和设备标识。完整会话和运行日志在本地或经授权的存储中保留。
4. 创建 PR，说明用户可见行为、实现范围、验证命令、实际工具回执和遗留限制。至少由另一位协作者审查；涉及角色权限、发布流程或物理操作的变更须由仓库维护者审查。

## 代码和权限边界

- `cybertron/registry.py` 是角色权限事实源。`opencode.jsonc` 和 `.opencode/agents/*.md` 由导出器生成。修改角色权限时，同步生成、核对 Markdown/JSON 一致性，并在 PR 中标出权限差异。
- `cybertron/policy.py` 只是本地自检；真实 OpenCode 工具权限以宿主检查为准。普通角色不直接获得 Shell、真机烧录或远程部署能力。
- 测试、L1/L2 审查和构建结果应保存结构化证据。模型自述不能替代宿主工具回执。
- 飞书写入、真机上电、物理烧录和远程部署遵守 [AGENTS.md](AGENTS.md) 的专项边界。测试只在获准的临时项目或专用空间进行。
- 模型 API Key、飞书密钥和发布 Token 只通过各服务的认证机制或本机安全环境提供，绝不进入代码、日志、PR 或对话。

## 本地验证

```bash
python3 -m unittest discover -s tests -v
python3 -m cybertron.stage5_verify
python3 cybertron_primes_engine.py
node --test tests/*.test.mjs
python3 scripts/bump_version.py --check
```

涉及安装器、角色、插件或运行时时，还需运行 `node scripts/build-payload.mjs`，分别检查 npm 与 Python 包内容，并在临时项目运行 `opencode2 debug config`、`opencode2 debug agents --standalone`。真实模型调用只在任务需要且有授权的临时项目执行。不要为了低风险文档改动反复调用外部模型。

## PR 审查重点

- 核对 Prima 默认入口、Thirteenth 直接规划和可选的 `/cybertron` 命令能按文档交接。
- 十三个角色的权限和模型映射是否符合任务边界；配置失败是否阻塞或恢复，不能静默回退到未经允许的供应商。
- 运行状态、宿主证据、安装升级和回滚是否可验证。
- 文档是否区分“本地实现”“真实宿主验收”和“已公开发布”。

版本和发布由维护者按照 [RELEASE.md](RELEASE.md) 执行。贡献代码不需要 PyPI、npm 或 GitHub Release 的发布权限。
