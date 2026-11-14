# 飞书知识库接入（可选）

Cybertron 的飞书能力由 **alpha-trion（钛师傅）** 独占：它从飞书知识库拉取需求 / 硬件手册，并在结项时把文档归档回去。**默认安装不启用飞书**——需要你自己创建自建应用并提供凭证。本文是面向使用者的接入步骤；阶段验收与排障记录见 [阶段 6 文档](stages/06-feishu.md)。

## 1. 创建飞书自建应用

1. 打开 [飞书开放平台](https://open.feishu.cn/app) → 创建**企业自建应用**。
2. 记录 **App ID** 与 **App Secret**。
3. 在「权限管理」中按**应用身份**开通：
   - `wiki:node:create`（或 `wiki:wiki`，两者任选其一）
   - Wiki 节点读取权限
   - 新版文档（Docx）读取 / 写入权限
4. 发布应用，并按企业要求完成管理员审批。

> 常见错误：`99991672` = 缺少上述 scope；`131006` = 应用没有目标知识空间的权限。

## 2. 授权目标知识空间

1. 取得**知识空间 ID**：打开空间设置页，网址末尾的纯数字即为 ID，例如
   `https://example.feishu.cn/wiki/settings/6992046856314306562` → `6992046856314306562`。
2. 让应用在该空间拥有权限。按飞书限制，机器人不能直接在成员设置里添加，常用做法是：
   - 把应用机器人拉进一个飞书群；
   - 在「知识空间 → 设置 → 成员设置 → 角色与权限」把该**群聊**设为管理员。

   其他知识库的安全设置可能允许可编辑成员创建一级页面，以实际权限模型为准。

## 3. 配置环境变量

```bash
export FEISHU_APP_ID="cli_xxx"
export FEISHU_APP_SECRET="xxx"
export FEISHU_WIKI_SPACE_ID="6992046856314306562"
```

- 只对当前终端会话及其子进程生效，换终端需重新设置。
- **不要把 App Secret 或租户令牌提交到仓库、命令历史或聊天里。**
- Windows PowerShell 用 `$env:FEISHU_APP_ID="..."` 的形式。

## 4. 在 OpenCode 中启用（可选，只读 MCP）

默认安装不包含 MCP。需要让 `alpha-trion` 直接读飞书 Wiki 时，把下面的 `mcp` 块合并进项目的 `opencode.jsonc`（顶层键）：

```jsonc
"mcp": {
  "servers": {
    "feishu_wiki": {
      "type": "local",
      "codemode": false,
      "command": [
        "npx", "-y", "@larksuiteoapi/lark-mcp", "mcp",
        "-a", "{env:FEISHU_APP_ID}",
        "-s", "{env:FEISHU_APP_SECRET}",
        "--token-mode", "tenant_access_token",
        "-c", "dot",
        "-t", "wiki.v2.space.getNode,docx.v1.document.rawContent"
      ],
      "environment": {
        "FEISHU_APP_ID": "{env:FEISHU_APP_ID}",
        "FEISHU_APP_SECRET": "{env:FEISHU_APP_SECRET}",
        "FEISHU_WIKI_SPACE_ID": "{env:FEISHU_WIKI_SPACE_ID}"
      }
    }
  }
}
```

- 只开放 `wiki.v2.space.getNode` 与 `docx.v1.document.rawContent` 两个**只读**工具。
- 写入仍由 Python 网关 `cybertron.feishu` 执行，且调用者必须是 `alpha-trion`。
- 从源码导出（会写入目标目录的配置，谨慎覆盖）：

  ```bash
  python3 -m cybertron.opencode_v2 --output <项目目录> --include-feishu
  ```

## 5. 验证

```bash
# 只检查环境变量是否存在，不联网、不打印值
python3 -m cybertron.stage6_verify --check-env

# 验证应用凭证能换取租户令牌
python3 -m cybertron.stage6_verify --check-auth

# 真实读写：会在测试空间创建并保留一篇测试文档
python3 -m cybertron.stage6_verify --live

# OpenCode 配置加载
opencode2 debug config
```

建议先在**专用测试空间**跑通，再用于正式知识库。

## 6. 安全边界

- 凭证与令牌只在内存中使用，不落盘、不回显；`stage6_verify` 失败时只输出状态码或错误码。
- MCP 只读；真实写入走 Python 网关，并由 `actor_id == "alpha-trion"` 限制。
- 真实 Wiki 写入只在你明确指定的测试空间执行；删除节点不在本指南范围内。
