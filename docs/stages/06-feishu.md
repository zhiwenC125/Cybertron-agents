# 阶段 6：飞书知识库接入

状态：自建应用的 `tenant_access_token` 路径已由开发者在专用测试空间完成真实读写回环；可选 MCP 的 OpenCode V2 宿主权限判定已在本机完成 27 项检查。回执来源与验收范围见 [`06-feishu-acceptance.json`](06-feishu-acceptance.json)。实际 MCP 工具调用尚未执行。下文后半部分保留此前排障记录。

## 实现与代码分工

| 文件 | 本阶段工作 |
| --- | --- |
| `cybertron/feishu.py` | 从环境变量读取 App ID 与 App Secret，获取并缓存租户令牌；可替换 HTTPS 传输；限定知识空间；提供 Wiki 节点读取、创建及 Docx 正文追加 |
| `cybertron/stage6_verify.py` | 分别检查变量、在线验证应用凭证能换取租户令牌；显式 `--live` 后创建测试节点、追加标记并读取回验 |
| `cybertron/stage6_mcp_verify.py` | 在本机通过 OpenCode V2 宿主权限接口检查可选 MCP 的角色读写规则，不调用模型、MCP 或飞书 |
| `cybertron/exporters.py` | 可选 MCP 仅启用两项只读工具，避免加载默认的消息、文档授权等宽泛工具集 |
| `cybertron/registry.py` | `alpha-trion` 只被授予两项精确 MCP 读取权限；其他角色保留默认拒绝 |
| `tests/test_feishu_stage6.py` | 离线验证读写回环、角色拒绝、空间越界、凭证缺失、模拟令牌隔离和导出工具清单 |

核心网关要求调用者明确标识角色，并在读写前绑定 `FEISHU_WIKI_SPACE_ID`：

```python
def _require_actor(actor_id: str) -> None:
    if actor_id != "alpha-trion":
        raise PermissionError("Only alpha-trion may access Wiki document content")
```

`get_node` 通过 Wiki `node_token` 获取 `obj_token`，Docx 正文接口使用后者。创建接口只建 `docx` 类型 Wiki 节点；更新采用在文档根块追加文本块，避免覆盖原正文或标题。成功回执必须再次读取并包含写入的标记。HTTP 错误与认证失败只返回状态码或错误码，不输出任何令牌或响应正文。

## 凭证与权限边界

当前 Python 验收路径需要 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 和 `FEISHU_WIKI_SPACE_ID`。脚本从当前进程环境读取应用凭证，通过内部租户令牌接口获取 `tenant_access_token`，在内存中缓存并在到期前刷新；凭证和令牌不落盘、不回显。可选的 `--parent-node-token` 用于在指定父节点下创建测试文档；缺省时在测试知识空间根目录创建。

自建应用需要开通**应用身份**的 Wiki 节点读取、创建和新版文档读写权限，并完成发布及所需审批；测试知识空间和父节点还需授予该应用实际资源权限。用户身份 scope 不适用于租户令牌。具体缺失 scope 与资源拒绝类别以飞书接口返回的安全摘要为准。请勿在聊天、命令历史或 Git 文件中粘贴 App Secret 或租户令牌。Python 网关的 `actor_id` 是内部调用契约，不是独立身份认证；真实 OpenCode 角色的工具使用还由宿主权限控制。

**本项目本次闭环的空间授权要求：**目标测试知识库的「设置 → 成员设置 → 角色与权限」需要让自建应用机器人获得**管理员**权限。飞书帮助中心说明机器人不能在此处直接添加；可先将同一个应用机器人加入飞书群聊，再将该群聊设为知识库管理员。本次不指定父节点的 `--live` 在空间根目录创建一级页面；开发者报告完成管理员授权后，结果从 `131006 / wiki space permission denied` 进展到 `CREATED` 和 `PASS`。群聊这一具体授权路径未从终端回执独立核验；其他知识库的安全设置可能允许可编辑成员创建一级页面。[飞书知识库成员设置](https://www.feishu.cn/hc/zh-CN/articles/530997871518-%E8%AE%BE%E7%BD%AE%E5%BD%93%E5%89%8D%E7%9F%A5%E8%AF%86%E5%BA%93%E7%AE%A1%E7%90%86%E5%91%98%E5%92%8C%E6%88%90%E5%91%98)

可选 OpenCode MCP 仍默认关闭。即使显式导出，也只启用 `wiki.v2.space.getNode` 和 `docx.v1.document.rawContent`，仅用于读取；写入由 Python 网关完成。MCP 导出显式选用 `tenant_access_token`，使用 App ID 与 App Secret，不注入用户令牌，并设置 `codemode: false` 使两项工具作为原生 MCP 工具暴露，供精确权限规则直接判定。[Lark MCP CLI 说明](https://github.com/larksuite/lark-openapi-mcp/blob/main/docs/reference/cli/cli.md)列出了 `--token-mode`；[OpenCode MCP 说明](https://opencode.ai/docs/mcp-servers)说明原生工具与 Code Mode 的区别。本阶段没有向 OpenCode 角色开放 MCP 写工具。

## 验收

先运行离线测试和导出一致性检查：

```bash
python3 -m unittest discover -s tests -q
python3 -c 'from pathlib import Path; from cybertron.opencode_v2 import validate_bundle; print(validate_bundle(Path(".")))'
```

切换回应用身份后，离线单元测试、第五阶段隔离验证、引擎自检与配置一致性检查均通过。开发者随后在专用测试空间依次运行 `--check-env`、`--check-auth` 和 `--live`；第三项输出 `CREATED` 与 `PASS`，表示节点创建、正文追加及回读标记校验完成。该在线回执来自开发者提供的终端输出，助手未在其终端独立执行；节点与文档 token 未写入仓库。

可选 MCP 宿主权限检查运行 `python3 -m cybertron.stage6_mcp_verify`。脚本临时导出启用 MCP 的配置，让 `opencode2 debug agents` 加载角色规则，再把加载后的规则交给 OpenCode V2 会话权限接口逐项判定；`alpha-trion` 的两项读取工具应放行，其他 12 个角色的读取工具及 `alpha-trion` 的写入动作应拒绝。该检查不连接真实 MCP、不调用飞书或外部模型，因此证明的是**宿主权限判定**，尚不证明真实 MCP 工具注册及调用链路。离线测试不会向飞书发起请求。

真实测试须在开发者选择的**专用测试空间**进行。环境变量只对当前终端会话及其子进程有效，换一个终端窗口后须重新设置。在同一个 zsh 终端逐条执行以下准备命令：

```zsh
export FEISHU_WIKI_SPACE_ID='替换为你的测试空间ID'
read "FEISHU_APP_ID?App ID: "
export FEISHU_APP_ID
read -s "FEISHU_APP_SECRET?App Secret: "; echo
export FEISHU_APP_SECRET
```

输入 App Secret 时不会显示。不要把凭证写入命令历史或仓库。

`FEISHU_WIKI_SPACE_ID` 必须是知识空间设置页网址末尾的纯数字 ID，例如网址 `https://example.feishu.cn/wiki/settings/6992046856314306562` 中的 `6992046856314306562`。不要填写整段网址、单篇文档的 Wiki 节点 token，或示例占位文字。`--check-auth` 仅验证应用凭证可以换取租户令牌，不验证 Wiki 写权。

```bash
python3 -m cybertron.stage6_verify --check-env
python3 -m cybertron.stage6_verify --check-auth
python3 -m cybertron.stage6_verify --live
```

`--check-env` 不联网也不显示变量值；`--check-auth` 在线换取租户令牌但不创建文档。若需指定父节点，在 `--live` 后追加 `--parent-node-token YOUR_TEST_PARENT_NODE_TOKEN`。成功时应输出 `PASS`、空间 ID、Wiki 节点 token 和文档 ID。`--live` 会创建并保留一篇测试文档，不会删除节点。无凭证与其他角色拒绝由离线测试覆盖；真实宿主 MCP 权限拒绝仍需在启用 MCP 的环境中单独核查。

## 应用身份时期的排障记录（历史）

首次开发者终端运行时，凭证检查与空间 ID 旧格式检查通过，但创建节点返回 HTTP 400。按[飞书创建节点 API](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/create)核对后，请求路径及 `obj_type=docx`、`node_type=origin` 符合接口要求。为进一步定位，客户端现从 HTTP 错误体中只提取数字业务错误码，不打印原始响应、App Secret 或访问令牌；空间 ID 检查也收紧为纯数字。再次运行 `--check-env` 和 `--live` 后，根据业务错误码确认是空间 ID、应用 API 权限还是目标空间成员/编辑权限问题。此前的 `--check-auth` 只证明应用凭证有效，不证明应用能在目标空间创建节点。

第二次开发者终端返回 `HTTP 400 / Feishu code 99991672`。按[飞书官方排障文档](https://open.feishu.cn/document/faq/trouble-shooting/how-to-fix-the-99991672-error?lang=zh-CN)，该码表示应用未申请此 API 需要的权限；响应中的 `error.permission_violations` 指明缺少的具体 scope。客户端现只输出其中符合权限名格式的 subject，不输出其余响应内容。到飞书开放平台该应用的「权限管理」中申请“创建知识空间节点”或接口列出的等效权限，再按应用发布流程使权限生效。该问题与 `--check-auth` 成功不矛盾：获取租户令牌不等于已获 Wiki 创建权限。修复 scope 后若出现新的资源权限错误，再核查应用是否加入测试知识空间并拥有目标父节点的编辑权。

第三次开发者终端明确返回 `wiki:node:create, wiki:wiki`。按[创建节点 API 的权限说明](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/create)，这两个是可选权限，申请其中一个即可；优先使用范围更小的 `wiki:node:create`。如果后台显示已经开通却仍返回 `99991672`，核对当前 App ID 对应的应用、应用身份权限是否生效、测试版本与正式版本是否一致，以及需要审核的权限是否已发布并获管理员批准。脚本的提示已从“required scopes”改为“acceptable scopes (grant one)”，避免误导开发者同时申请两个权限。

开发者提供的权限管理截图显示这两个 scope 均为“用户身份”，尽管状态为“已开通”且修改已发布。当时客户端使用 `tenant_access_token`（应用身份），因此用户身份 scope 不会进入该令牌的生效权限。后续曾尝试用户身份，现按开发者最新选择恢复应用身份；验收须检查这些 scope 已在应用身份下开通。参见[飞书租户令牌说明](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/authentication-management/access-token/tenant_access_token)。

之后开发者的 `--live` 从 `99991672` 进展到 `HTTP 400 / 131006`，表明本次调用已越过 API scope 检查，但知识空间或节点的资源权限仍不足。当前脚本不指定父节点时在测试空间根目录创建节点，因此应由测试知识空间管理员将应用加入该知识空间并授予可创建节点的权限；若使用 `--parent-node-token`，还须确保应用拥有该父节点的容器编辑权限。飞书[创建节点接口错误码说明](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/create)将 `131006` 定义为资源权限拒绝。当时的错误包装只保留数字码，无法进一步确认具体子原因。

开发者随后指定了现有父节点；调用在 `create_node()` 的父节点预检查 `get_node()` 阶段停止，返回 `99991672`，可接受的 scope 为 `wiki:node:read` 或 `wiki:node:retrieve`。这是与上一次 `131006` 不同的请求和错误：当前客户端先读取父节点以核对其属于配置的测试空间，创建后还会再次读取新节点，因此即使不指定父节点，完整回环仍需要其中一项 Wiki 节点读取权限。应为当前 `tenant_access_token` 对应的应用身份开通其中一项并发布；之后如再出现 `131006`，继续检查应用在目标空间或父节点上的资源编辑权限。完整回环还包含 Docx 正文写入及读取，须以随后 API 返回的权限错误或官方 Docx 文档为准核对相应 scope。

父节点读取权限开通后，读取请求已通过，但带父节点的创建请求再次返回 `131006`。因此节点 token 至少可被读取；仍不能从数字错误码判断是空间级权限还是父节点容器编辑权。HTTP 错误处理已补充固定白名单诊断，仅显示飞书 `msg` 中匹配到的 `wiki space permission denied`、`node permission denied` 等官方类别，不回显任意服务端文字、文档内容或令牌。开发者需更新代码后重跑同一命令，依据新的 `resource denial` 类别检查测试空间或父节点授权；若无类别，保留 `131006` 并通过飞书服务端日志继续定位。

开发者随后运行不带父节点的 `--live`，诊断明确返回 `131006, resource denial: wiki space permission denied`。此时请求在知识空间根目录创建节点，说明当前应用身份对配置的测试空间缺少足够的空间级权限；此前“已将应用加入空间”的陈述与此并不矛盾，成员身份、角色权限、应用是否为实际调用的 App ID、以及空间 ID 是否指向所添加的空间仍需逐项核对。应在测试知识空间的设置中核对该应用在空间的管理员/可编辑身份及 `FEISHU_WIKI_SPACE_ID` 对应空间，随后重跑；不应通过扩大 API scope 来处理该资源权限错误。

飞书[知识库成员设置帮助](https://www.feishu.cn/hc/zh-CN/articles/530997871518-%E8%AE%BE%E7%BD%AE%E5%BD%93%E5%89%8D%E7%9F%A5%E8%AF%86%E5%BA%93%E7%AE%A1%E7%90%86%E5%91%98%E5%92%8C%E6%88%90%E5%91%98)进一步说明：机器人不能直接添加到“知识库设置 > 成员设置 > 角色与权限”；一种空间级授权方式是先将应用作为机器人加入群聊，再把该群聊添加为知识库的管理员或可编辑成员。另一种“知识库页面 > 更多 > 添加文档应用”只授予该页面的权限，不等同于空间根目录的创建权限。当前根目录 `wiki space permission denied` 应优先核对前一种空间级授权是否完成、群中是否为同一应用、群在正确的测试知识库中是否拥有足够角色。操作后再运行 `--live`；若改用页面内创建，还需核对父节点的容器编辑权。

另外，飞书[知识库权限帮助](https://www.feishu.cn/hc/zh-CN/articles/874534846817-%E7%A7%BB%E5%8A%A8%E4%BA%91%E6%96%87%E6%A1%A3%E5%88%B0%E7%9F%A5%E8%AF%86%E5%BA%93)说明安全设置可能限制“谁可以新建知识库的一级页面”为“仅管理员”。因此若群组仅被加为可编辑成员且根目录创建仍失败，应检查该设置；在测试知识库中由管理员决定是调整设置还是将该群设为管理员。仅对单篇页面添加文档应用无法替代这项空间级授权。

## 知识沉淀与后续交接

1. Wiki 的 `node_token` 是目录入口，Docx 的 `obj_token` 才是正文 API 的文档 ID；不能混用。
2. 模拟令牌只供局部测试，不能缓存成真实令牌。即使曾获取真实令牌，环境变量撤销后仍应拒绝后续请求。
3. 跨知识空间节点在读取正文或追加前拒绝。测试空间限制由客户端执行，也必须在飞书应用侧配置最小权限。
4. `opencode2 debug config` 只能证明配置可解析；`stage6_mcp_verify` 进一步使用宿主权限接口验证导出规则，但不执行 MCP 工具。真实工具调用链路需在有凭证的宿主环境另行核查。
5. 当前接口只处理纯文本 Docx；富文本、图片、附件、批量分页和冲突更新属于后续扩展。真实回环完成后，再把文档链接与摘要接入账本第 2/9 步。

## 参考资料

- [飞书 Wiki API 概览](https://open.feishu.cn/document/server-docs/docs/wiki-v2/wiki-overview)
- [飞书新版文档 API 概览](https://open.feishu.cn/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/docs)
- [飞书官方 OpenAPI MCP](https://github.com/larksuite/lark-openapi-mcp/blob/main/README.md)
- [OpenCode V2 MCP 权限命名](https://opencode.ai/docs/mcp-servers/)
- [Hello Agents：工具与外部能力扩展](https://datawhalechina.github.io/hello-agents/#/)
