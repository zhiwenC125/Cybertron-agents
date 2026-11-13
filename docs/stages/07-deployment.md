# 阶段 7：构建、硬件审批与交付

状态：待开发。目标是区分无物理副作用的构建准备与需要人工批准的真机动作。

## 对应代码与当前起点

`cybertron/policy.py` 提供本地权限原型；`cybertron/registry.py` 定义 `nexus-prime` 构建权限与 `megatronus` 烧录审批规则；`cybertron/simulation.py` 默认在第 8 步暂停。

```python
if task.step_id == 8 and not self.simulate_hardware_approval:
    return AgentResult(task.step_id, task.agent_id,
                       ResultStatus.NEEDS_APPROVAL,
                       "模拟硬件步骤等待批准；未执行任何烧录命令")
```

下一步需要固件校验和设备清单、烧录范围、回滚镜像及审批回执的数据契约。真实审批必须由宿主执行；模拟选项不构成授权。

## 计划验收

先完成仿真构建与假设备回执测试；真机前展示目标设备、固件校验值、擦写区间和回滚方案，经人工批准后再执行；校验启动日志和最终交付报告。

## 参考

- [项目 v5 架构白皮书：交叉编译与硬件部署](../../design/cybertron_13_primes_architecture.md)
- [OpenCode V2 权限与审批](https://opencode.ai/docs/permissions/)
- [Hello Agents：智能体评估与实践](https://github.com/datawhalechina/hello-agents/blob/main/docs/README.md)
