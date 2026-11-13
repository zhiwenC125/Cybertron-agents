# 阶段 4：OpenCode V2 单角色执行

状态：已由开发者在本机验收。目标是用真实模型执行一个只读角色，再将结构化结果交给账本。

## 对应代码

- `cybertron/opencode_executor.py` 调用 `opencode2 run --standalone --archived --agent thirteenth --format json`，解析文本事件与 JSON 回复。
- `cybertron/opencode_run.py` 创建账本并只派发第 1 步。
- `opencode_v2_smoke/run_first_agent.py` 是导出包内的本地启动入口。

关键调用摘录（`cybertron/opencode_executor.py`）：

```python
command = [self.binary, "run", "--standalone", "--archived", "--agent",
           task.agent_id, "--format", "json", prompt]
```

适配器将命令失败、超时、无文本事件和格式错误统一映射为 `blocked`。目前只接受 `step_id == 1` 且角色为 `thirteenth`，以限制真实调用范围。

## 验收

开发者已分别从项目根目录和导出目录运行真实调用。信息不足时得到 `blocked`；完整测试规格得到 `Ledger step 1: completed`。本地测试用假 CLI 结果覆盖成功和异常格式。

## 参考

- [OpenCode CLI run、JSON 输出和指定角色](https://opencode.ai/docs/cli/commands)
- [OpenCode V2 智能体权限](https://opencode.ai/docs/agents/)
- [Hello Agents：Agent 框架与结果约定](https://datawhalechina.github.io/hello-agents/#/)
