# 阶段 5：真实接力、返工与质量门禁

状态：已完成约定的离线质量门禁，开发者终端复验通过。真实 OpenCode 全角色接力仍待后续阶段实现。

## 对应代码与当前起点

`cybertron/ledger.py` 的 `reject_review` 将编码和审查步骤退回待执行，`cybertron/dispatch.py` 识别 `REJECTED` 结果：

```python
elif result.status == ResultStatus.REJECTED:
    ledger.reject_review(agent_id, result.summary)
```

`cybertron/execution.py` 定义 `QualityEvidence(kind, passed, source)`。调度器要求微米天、谎言天尊和炼金术士分别提交 `review_l1`、`review_l2`、`test` 的通过证据，并把证据保存在账本中。该检查验证结果结构；模拟报告不能证明真实工具已经执行。

`cybertron/opencode_readonly.py` 可在测试包中依次调用锐天骁和维克多，验证真实的只读角色接力。其前两步是显式标记的模拟前置条件；脚本不会进入会写文件的昆图斯。首次真人验收中锐天骁通过，维克多遇到模型服务 429 配额错误；之后开发者以已配置模型单独重试维克多成功。`--only-vector` 不会重放先前的锐天骁结果到新账本；`--model provider/model` 可在这次探针中使用其他已配置的模型。本地模拟只验证流程状态。审查拒绝后由 `solus-prime` 接收反馈并重新执行两级审查，超过重试上限则阻塞。

维克多已在开发者终端用 `deepseek/deepseek-flash` 成功查询 Git 基线，报告的分支和 HEAD 经本地 Git 命令核对一致。`cybertron/opencode_l2_probe.py` 新增只读 L2 审查测试，前置步骤及 L1 均明确标记为模拟；真实 L2 若声称通过，必须返回 `quality_evidence`。

## 真实 L2 拒绝后的权限修复

首次真实 L2 审查给出 `REJECT`，并注明因工具步数耗尽而未完成全部检查。已核实并修复的配置问题：`nexus-prime` 不再能编辑 `opencode.jsonc`、`.dsh/**`、`.github/**`；`prima` 的子角色调用改为明确的 12 个 ID；`micronus-prime` 不再有源码编辑权；`liege-maximo` 收紧读取范围并去掉无法按路径限定的 `grep`；`alpha-trion` 的通配 Docx 权限留待阶段 6 核对工具名；`thirteenth` 暂停宽泛 `webfetch`。导出校验新增 Markdown 与 JSON 权限一致性检查，并以测试断言任何角色不能编辑权限配置文件。

审查提到的 Shell 通配规则需要逐角色评估。微米天的静态检查、炼金术士的测试以及合体天的构建命令目前全部为 `deny`，直到有能隔离设备、网络和工作区写入的执行器；维克多只保留固定形式的只读 Git 命令。OpenCode V2 官方文档说明复合命令由宿主扫描器逐子命令检查，但顶层 `make`/`pytest` 仍可启动子进程，因此不能仅凭顶层命令的 `ask` 保证硬件安全。本地 `policy.py` 也不是实际 OpenCode 工具调用的拦截器。

复审时 L2 返回 `blocked`：原探针仍以 `opencode_v2_smoke/` 为工作目录，源码在其父目录，路径权限因此无法命中。现已在项目根目录生成 OpenCode 配置，并将探针默认工作目录改为根目录。L2 增加项目源码、设计文档和配置的只读规则及文件名发现权限；`.env` 等未列出的文件仍被首条 deny-all 阻断。适配器在 L2 工作目录不含 `cybertron/registry.py` 时会直接阻塞并提示路径问题。

第二次真实 L2 返回 `REJECT`。其中本地 `fnmatch` 对 `src/../opencode.jsonc` 和 `tests/../cybertron/policy.py` 的放行已复现。`MegatronusCircuitBreaker` 现拒绝 `..`、绝对路径、反斜杠穿越和指向工作区外的符号链接，并保存回归测试。该本地检查器并未接入 OpenCode 真实调用路径；宿主权限仍须独立验收。报告指出 `AGENTS.md` 不存在，现已建立本项目安全基线文件。`src/**` 与 `firmware/**` 仍未建立，本轮 L2 只能审查配置与引擎，不能代表业务源码通过审查。

针对构建/测试脚本间接调用烧录工具的风险，当前导出权限已对普通角色关闭静态检查、测试和构建命令的直接 Shell 执行。维克多的 Git 权限改为固定形式的只读命令；震天尊保留真实烧录命令的 `ask`，暂不开放 ssh/scp、Git 回滚及删除命令。OpenCode V2 根目录配置已由 `opencode2 debug config` 成功加载。外部模型 L2 复审因项目源码和配置外发未经明确授权而被自动审批拦截。

开发者随后决定不授权外发项目文件。阶段 5 改用离线验收：路径穿越与越权回归测试、导出配置一致性、宿主加载、返工循环、结构化证据，以及隔离运行器对测试/构建脚本的硬件与网络隔离验证。外部 L2 复审不再是完成条件。

## 最后两项离线验收

`cybertron/isolated_runner.py` 在 macOS `sandbox-exec` 中运行测试，默认拒绝网络和写入，仅允许写临时目录，并拒绝读取 `/dev`。环境变量只传入运行所需的最小集合。未找到沙箱工具时直接报错，不运行裸命令。关键配置如下：

```python
"(deny default)\n"
"(deny network*)\n"
'(deny file-read* (subpath "/dev"))\n'
f'(allow file-write* (subpath "{scratch}"))\n'
```

`cybertron/stage5_verify.py` 的第一项检查在沙箱内实际尝试临时目录写入、项目目录写入、`/dev/null` 读取和本机回环连接。预期只有临时目录写入成功。第二项检查在同一沙箱中运行真实 `unittest`，`AlchemistTestExecutor` 将退出码为 0 的报告转换为 `QualityEvidence(TEST, True, sandbox://sha256/...)`，再通过 `PrimaDispatcher` 写入账本第 6 步；脚本核对账本保存的证据与执行结果一致。前 1–5 步仍是明确标记的合成前置条件，所以这项检查证明 QA 证据接线，不代表此前步骤真实执行。

开发者终端复验结果：`python3 -m unittest discover -s tests -q` 通过 30 项；`python3 -m cybertron.stage5_verify` 的四项隔离探针符合预期，QA 账本第 6 步为 `completed`，保存 `QualityEvidence(kind=TEST, passed=True, source=sandbox://sha256/...)`；`opencode2 debug config` 输出包含项目根目录 `opencode.jsonc`。沙箱验证须在允许启动 `sandbox-exec` 的 macOS 宿主运行；某些外层沙箱会先拦截该系统调用，出现 `sandbox_apply: Operation not permitted`。隔离运行器目前仅接入 Python 账本验收脚本，未开放 OpenCode 导出角色的 Shell 测试或构建权限，构建流水线接入留待阶段 7。

复验命令：

```bash
python3 -m unittest discover -s tests -q
python3 -m cybertron.stage5_verify
opencode2 debug config
```

## 阶段知识沉淀：给后续开发者

### 代码分工与调用链

| 文件 | 本阶段职责 | 后续复用点 |
| --- | --- | --- |
| `cybertron/execution.py` | 定义 `QualityKind`、`QualityEvidence` 和结构化执行结果 | 新的审查、测试或构建回执沿用类型化证据，避免只凭自然语言判定通过 |
| `cybertron/ledger.py` | 保存参与角色及证据；L1/L2 拒绝时清空旧审查证据并回派步骤 4 | 返工必须重新审查，旧 PASS 不可复用；超限后保留阻塞状态 |
| `cybertron/dispatch.py` | 核对执行者身份、结果状态和必需的 L1/L2/测试证据 | 新执行器统一通过调度器入账，不直接改 `LedgerStep.status` |
| `cybertron/policy.py` | 本地路径规范化、越界和符号链接检查 | 仅供本地策略检查；OpenCode 宿主权限需单独验证 |
| `cybertron/registry.py`、`cybertron/opencode_v2.py` | 权限源头及配置导出一致性校验 | 改权限后同时生成并核对 JSON 与角色 Markdown |
| `cybertron/isolated_runner.py`、`cybertron/stage5_verify.py` | macOS 离线隔离和真实 QA 报告入账 | 阶段 7 的构建执行应使用独立隔离配置和产物目录 |

质量门禁的关键约束写在 `PrimaDispatcher.run_next`：

```python
if gate_kind is not None and not any(
    item.kind == gate_kind and item.passed and item.source.strip()
    for item in result.quality_evidence
):
    ledger.block_step(step.step_id, f"Missing passing {gate_kind.value} evidence")
```

### 本阶段遇到的问题与解决原则

1. **429 是模型服务配额问题。** 账本将该角色标为 `blocked` 是正确行为。单角色重试不代表前一角色结果自动写回新账本；要恢复完整接力，需要持久化并验证先前证据。
2. **模型的审查意见必须先复现。** L2 指出的 `src/../opencode.jsonc` 穿越在本地 `fnmatch` 匹配中确实可重现，于是补了路径规范化和回归测试。L2 的其他推断不能当作已验证事实。
3. **权限配置有两层。** `policy.py` 的拒绝结果不约束 OpenCode 实际工具调用；`opencode2 debug config` 只证明配置被加载，也不证明全部规则在宿主运行时有效。写入权、Shell 权和硬件审批仍要分别核查。
4. **脚本入口可能间接触发危险操作。** `pytest`、`make` 等入口能执行子进程。普通角色的直接 Shell 权限因此保持关闭；本阶段的测试只通过本地隔离运行器执行。沙箱实测检查的是项目写入、`/dev/null` 读取和回环连接；不能据此宣称所有设备型号和网络协议都已覆盖。
5. **验收必须区分合成前置条件与真实执行。** `stage5_verify.py` 的前 1–5 步是合成状态，真实运行的是第 6 步单元测试。`sandbox://sha256/...` 是本次命令输出的摘要，不是外部审计签名，也不证明 QEMU/Renode 或硬件仿真已运行。
6. **macOS 沙箱细节会影响可移植性。** Python 启动可能读取 `/dev/urandom`，故运行器固定 `PYTHONHASHSEED`；创建 socket 本身可能成功，验收必须实际尝试连接。若宿主不支持 `sandbox-exec`，运行器直接失败，不能退化为裸执行。

### 阶段边界与交接

本阶段完成的是离线门禁及部分真实只读探针。仍未接入真实 OpenCode 全角色接力，L1/L2 的外部审查也未成为本次验收条件；用户明确决定不外发项目文件。下一阶段优先处理飞书 Wiki 工具名、凭证隔离和测试空间的读写边界。阶段 7 再接入隔离构建、产物清单、设备确认与人工烧录批准。任何角色权限变更都应重复单元测试、导出一致性检查和 `opencode2 debug config`。

## 计划验收

注入一次 L2 拒绝，确认编码角色收到反馈且 L1/L2 均重新运行；缺失审查或测试证据无法推进；超限后保持阻塞。先用模拟和假宿主测试，再让开发者执行真实测试。

## 参考

- [项目 v5 架构白皮书：双级 Review 与测试](../../design/cybertron_13_primes_architecture.md)
- [Hello Agents：多智能体通信和评估目录](https://datawhalechina.github.io/hello-agents/#/)
- [OpenCode V2 子智能体](https://opencode.ai/docs/agents/)
- [OpenCode V2 权限匹配和 Shell 扫描器](https://opencode.ai/docs/permissions/)
