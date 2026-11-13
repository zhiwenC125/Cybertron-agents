# 阶段 5：真实接力、返工与质量门禁

状态：待验收。仓库已有本地模拟返工代码；真实 OpenCode 多角色接力和证据门禁尚未完成。

## 对应代码与当前起点

`cybertron/ledger.py` 的 `reject_review` 将编码和审查步骤退回待执行，`cybertron/dispatch.py` 识别 `REJECTED` 结果：

```python
elif result.status == ResultStatus.REJECTED:
    ledger.reject_review(agent_id, result.summary)
```

下一步应将 `OpenCodeV2Executor` 扩展至其他角色，定义 L1/L2 审查和测试结果的结构化证据，避免凭一句摘要越过门禁。审查拒绝后应让 `solus-prime` 接收反馈并重新执行两级审查；超过重试上限则阻塞。

## 计划验收

注入一次 L2 拒绝，确认编码角色收到反馈且 L1/L2 均重新运行；缺失审查或测试证据无法推进；超限后保持阻塞。先用模拟和假宿主测试，再让开发者执行真实测试。

## 参考

- [项目 v5 架构白皮书：双级 Review 与测试](../../design/cybertron_13_primes_architecture.md)
- [Hello Agents：多智能体通信和评估目录](https://github.com/datawhalechina/hello-agents/blob/main/docs/README.md)
- [OpenCode V2 子智能体](https://opencode.ai/docs/agents/)
