# 阶段 1：模块解耦与基线

状态：已完成。目标是把原来的单文件原型拆成可替换的模块，同时保留 `python3 cybertron_primes_engine.py` 命令。

## 对应代码

- `cybertron/schema.py`：消息与工具调用结构。
- `cybertron/compaction.py`：上下文压缩，保留工具调用与结果的原子组。
- `cybertron/policy.py`：本地权限与重复调用熔断。
- `cybertron/registry.py`：13 个角色的静态定义。
- `cybertron/exporters.py`：宿主配置导出。
- `cybertron_primes_engine.py`：兼容入口。

关键接口摘录（`cybertron/registry.py`）：

```python
@dataclass
class PrimeAgentSpec:
    agent_id: str
    cn_name: str
    en_name: str
    # 其余字段描述模型、职责、输入输出和权限
```

角色定义与运行时逻辑分开，后续替换宿主时无需复制角色宪章。此阶段不证明宿主真实执行。

## 验收

`python3 -m unittest discover -s tests -v` 和 `python3 cybertron_primes_engine.py` 均通过；导出包含 13 个 OpenCode 角色。

## 参考

- [项目 v5 架构白皮书](../../design/cybertron_13_primes_architecture.md)
- [Datawhale Hello Agents：从原理到框架实现](https://datawhalechina.github.io/hello-agents/#/)
- [Hello Agents 开源仓库](https://github.com/datawhalechina/hello-agents)
