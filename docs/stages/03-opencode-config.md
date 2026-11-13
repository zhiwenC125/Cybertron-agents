# 阶段 3：OpenCode V2 配置接入

状态：已由开发者在本机验收。目标是将角色注册表导出成 OpenCode V2 可加载的配置。

## 对应代码

- `cybertron/exporters.py` 生成 `opencode.jsonc` 和 `.opencode/agents/*.md`。
- `cybertron/opencode_v2.py` 检查角色数量、默认角色、权限起始规则和 Markdown 文件。

关键配置摘录（`cybertron/exporters.py`）：

```python
opencode_jsonc = {
    "$schema": "https://opencode.ai/config.json",
    "default_agent": "prima",
    "agents": agents_json_map,
}
```

默认测试包不启用飞书 MCP，避免配置加载测试依赖凭证。`--include-feishu` 可显式加入 MCP 配置。静态检查只检查本项目约束，宿主解析仍需由 OpenCode 验证。

## 验收

`python3 -m cybertron.opencode_v2 --output opencode_v2_smoke` 后，在导出目录运行 `opencode2 debug config`。开发者输出显示配置成功加载 13 个角色。

## 参考

- [OpenCode V2 智能体定义](https://opencode.ai/docs/agents/)
- [OpenCode V2 权限规则](https://opencode.ai/docs/permissions/)
- [OpenCode V2 配置](https://opencode.ai/docs/config/)
