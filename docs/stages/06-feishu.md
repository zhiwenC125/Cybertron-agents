# 阶段 6：飞书知识库接入

状态：待开发。目标是由 `alpha-trion` 独占知识库正文读写，并把文档证据交给账本。

## 对应代码与当前起点

`cybertron/feishu.py` 当前只实现租户令牌获取与缓存；`cybertron/exporters.py` 可用 `--include-feishu` 加入 MCP 配置。

```python
class FeishuWikiKnowledgeClient:
    def get_tenant_access_token(self, mock_if_unset: bool = False) -> str:
        ...
```

下一步需要 Wiki 节点读取、创建、更新接口及可替换的传输层。默认无凭证报错，测试应使用模拟响应或测试空间，避免把模拟令牌当作真实凭证。

## 计划验收

在测试空间完成一条文档读写回环；无凭证失败；其他角色的知识库正文访问被宿主权限拒绝。

## 参考

- [飞书 Wiki API](https://open.feishu.cn/document/server-docs/docs/wiki-v2/wiki-overview)
- [飞书官方 OpenAPI MCP](https://github.com/larksuite/lark-openapi-mcp)
- [Hello Agents：工具与外部能力扩展](https://datawhalechina.github.io/hello-agents/#/)
