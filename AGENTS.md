# Cybertron 项目协作与安全基线

本文件记录当前阶段的工程约束，供后续开发者和角色读取。架构目标与角色分工见 `design/cybertron_13_primes_architecture.md`；当前实现状态见 `DEVELOPMENT_PLAN.md` 和 `docs/stages/`。

## 当前执行边界

1. `cybertron/registry.py` 是角色权限的源头，`opencode.jsonc` 与 `.opencode/agents/*.md` 由导出器生成。业务、测试和构建角色不得通过文件编辑权限改写这些配置。修改权限须经代码审查和导出一致性测试。
2. 本地 `cybertron/policy.py` 只用于自检，不拦截 OpenCode 的真实工具调用。真实执行以 OpenCode V2 的权限检查为准。
3. 任何物理烧录、设备上电或远程部署都需明确的目标设备、固件、擦写范围、回滚方案和人工审批。模拟审批不构成真实授权。
4. `pytest`、`make`、`cmake`、`ruff` 等命令可能执行项目脚本或改写文件；隔离运行器接入宿主角色工具调用前，不向普通角色开放直接 Shell 执行。
5. 任何 L1/L2/测试结果都要保存结构化证据。模型生成的文字不是工具运行回执；真实工具报告需单独核验。

## 开发验收

运行 `python3 -m unittest discover -s tests -v`、`python3 -m cybertron.stage5_verify` 和 `python3 cybertron_primes_engine.py`。修改角色权限后，重新生成根目录和测试目录的 OpenCode 配置，核查 Markdown 与 JSON 权限一致，再由开发者运行 `opencode2 debug config`。用户已决定不授权向外部模型发送项目文件，因此不运行只读 L2 探针。
