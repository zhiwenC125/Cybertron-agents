# M0c 真实 OpenCode 宿主验收交接

验收已于 2026-11-16 在 `r4` 完成。父会话、子会话、原生卡片、事件账本和产物哈希见 `v6-m0c-host-r4-acceptance.json`。以下步骤保留为复核记录，无需重复执行。

临时项目：`/private/tmp/cybertron-v6-m0c-host-gate-20261116-r4`。该目录已由 `scripts/v6_m0c_host_fixture.py` 从当前 registry、导出器和插件源生成；`opencode2 debug config` 已通过。`r3` 的真实会话失败，原始回执与截图见 `v6-m0c-host-r3-failure.json`；`r4` 尚未进行真实派单。

## 用户操作

1. 在终端运行 `opencode2 --standalone /private/tmp/cybertron-v6-m0c-host-gate-20261116-r4`，在界面选 `prima`，开启新会话。
2. 发送普通用户需求：`请在这个项目根目录新建 notes.md，写入“Cybertron v6 M0c host acceptance”。完成后告诉我文件在哪里。` 不在提示中指定工具、角色、节点或写范围，让 `prima` 自行规划和派单。
3. 核查 `prima` 自行调用 `cy_plan` 创建单节点文档计划，随后调用原生 `subagent` 派给 `alpha-trion`。界面应出现原生子代理卡片，卡片描述包含实际节点 ID、`doc.write` 和 `notes.md`，并显示子代理会话与工具流。后台时节点仍应为 `running`；子代理结束并核验后应为 `completed`。不要在此项目进行部署、设备操作或飞书写入。
4. 在该临时项目检查 `notes.md` 和 `.cybertron/runs/<run_id>/events.jsonl`。事件应依次包含 `plan.created`、`dispatch.started`、`dispatch.returned`、`node.completed`；最终事件的 `artifacts.notes.md` 应为文件 SHA-256，`evidence.source` 应为 `host`，并带命令、退出码、UTC 时间、输出哈希与子会话 ID。
5. 将父会话 ID、子会话 ID、`run_id`、卡片可见的截图或录屏路径，以及临时项目中 `events.jsonl` 的路径返回。只有核验这些真实宿主回执后，才把 `docs/stages/v6-m0c.json` 的 `host` 填实并标记 `passed`。

`notes.md` 是固定的验收目标，便于核对一次派单、写入范围和产物哈希；提示措辞和正文可以变化。自动钩子测试中的假宿主对象只用于单元测试，不能代替第 1–5 步。若卡片、派发拒绝原因或事件链不符合预期，保持 M0c `blocked` 并附上原始宿主输出。
