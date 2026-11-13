# 阶段 2：本地执行接口与模拟接力

状态：已完成。用统一任务和结果协议隔离调度器与具体宿主，先验证九步 SDLC 和 13 次角色派发。

## 对应代码

- `cybertron/execution.py` 定义 `AgentTask`、`AgentResult`、`AgentExecutor`。
- `cybertron/ledger.py` 保存步骤、参与角色、证据和状态。
- `cybertron/dispatch.py` 派单、校验角色身份并更新账本。
- `cybertron/simulation.py` 产生无外部副作用的模拟结果。

关键接口摘录（`cybertron/execution.py`）：

```python
class AgentExecutor(Protocol):
    def execute(self, task: AgentTask) -> AgentResult:
        ...
```

后续宿主适配器只需实现 `execute`。模拟证据形如 `simulation://step/1/thirteenth`，仅表示流程测试，不能作为真实审查或硬件回执。

## 验收

`python3 -m cybertron.simulation` 默认完成前 7 步并在第 8 步等待审批；`--simulate-hardware-approval` 仅验证九步状态转换。

## 参考

- [项目 v5 架构白皮书：九步工作流](../../design/cybertron_13_primes_architecture.md)
- [Hello Agents：经典智能体范式与框架](https://github.com/datawhalechina/hello-agents/blob/main/docs/README.md)
