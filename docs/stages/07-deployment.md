# 阶段 7：构建、硬件审批与交付

状态：进行中。已完成硬件无关契约与仿真、选定 STM32 工程的离线交叉编译，以及经开发者明确批准的 STM32 最小 App 真机烧录、SRAM 心跳与原固件回滚闭环。完整 OTA App、ESP32-S3 和 Cybertron 宿主审批接口尚未验收。

## 已确认的目标硬件

当前优先顺序：**STM32F103C8T6 + ST-LINK 作为 MVP**，之后接入 **ESP32-S3-N16R8 + USB**；树莓派 5 暂停。开发者选定本机 `OTA_Upgrade_System` 作为独立固件工程；它同时包含 STM32 和 ESP32-S3 代码，**不属于本仓库的安装包**。该仓库原本没有可直接用于回滚的 `.bin`、`.elf` 或 `.hex` 镜像；现已通过 ST-LINK 两次读取并核对设备现有内部 Flash，备份位于本地忽略目录 `local_backups/`，与新构建镜像明确区分。

| 目标 | 下一步需要确认 | 适配方向 |
| --- | --- | --- |
| STM32F103C8T6 | ST-LINK 已通过 SWD 识别 `STM32F1xx_MD`，内部 Flash 64 KB 已备份；最小 App 烧录与回滚已通过，W25Q32 驱动信息已在 SRAM 复核 | 内部 Flash 以实测 64 KB 为上限；完整型号仍需对照板上芯片丝印，完整 OTA App 的外部 Flash 影响仍需单独验收。 |
| ESP32-S3-N16R8 | 计划走 USB；模块标识对应 16 MB Flash、8 MB PSRAM，仍需开发板型号、所用 USB 口、分区表、当前固件备份 | 先识别 USB 串口/JTAG 或 USB-UART 路径；按实际构建产物记录 bootloader、分区表和应用镜像各自的偏移与哈希，检查分区均落在板载 Flash 内。 |
| 树莓派 5 | 本轮暂停；未来按 SSH 部署上位机应用 | 未来采用独立的 SSH 应用部署契约，不涉及系统镜像或 EEPROM 更新，不复用 MCU 的 Flash 地址契约。 |

型号与连接方式参考：[ST STM32F103C8 产品资料](https://www.st.com/content/st_com/en/products/microcontrollers-microprocessors/stm32-32bit-arm-cortex-mcus/stm32-mainstream-mcus/stm32f1-series/stm32f103/stm32f103c8.html)、[ST CubeProgrammer CLI `--list`](https://dev.st.com/stm32cube-docs/prog/2.23.0/en/docs/markup/CubeProg_Command_Lines.html)、[Espressif 模块标识](https://docs.espressif.com/projects/esp-packaging/en/latest/esp32s3/esp-packaging-en-master-esp32s3.pdf)、[Espressif ESP32-S3 USB 串口/JTAG](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/usb-serial-jtag-console.html)。

`python3 -m cybertron.stage7_probe` 只读 macOS USB 注册表并报告工具链可用性，不打开设备。此前本机识别到一个 `STM32 STLink` USB 探针（VID `0x0483`、PID `0x3748`），但尚未通过 SWD 核实目标 MCU；还看到一个通用 USB 串口设备，不能仅凭该描述认定它属于 ESP32。探测回执记录的是当时的工具链状态；后续安装不改写历史回执。识别探针不表示真实目标已获烧录授权。

选定工程的 STM32 链接脚本把内部 Flash 分为 Bootloader `0x08000000` 起 8 KB、App `0x08002000` 起 55 KB、OTA 标志页 `0x0800FC00` 起 1 KB。离线构建必须分别检查两个镜像是否落入对应分区。该仓库还使用外部 W25Q32 作为 OTA 暂存区；后续真机评估需把外部 Flash 写入范围也列出。

2026-11-14 的只读 SWD 核实使用 `stlink 1.9.0`：探针识别到 1 个 `STM32F1xx_MD` 目标，芯片 ID `0x410`、内部 Flash 64 KB、页大小 1 KB、SRAM 20 KB。`st-info --probe` 日志显示它对目标执行了复位，因此不能把该探测称为无副作用。随后使用 `st-flash --hot-plug read` 两次读取完整内部 Flash，两个 65,536 字节文件逐字节一致，SHA-256 见 [`07-stm32-swd-backup.json`](07-stm32-swd-backup.json)。备份目录已加入 `.gitignore`。当前 OTA 标志字为 `0x5A5AA5A5`。这份备份不包含选项字节或外部 W25Q32，不能据此声称整机数据已完整备份。

开发者起初只有 ST-LINK，未连接 W25Q32。选定 OTA App 的 `main()` 在启动时要求初始化 W25Q32，失败便停在循环中，因此当时不能将该 App 直接当作真机心跳验收固件。为验证最小烧录闭环，新增 [`stage7_fixture/stm32_minimal/`](../../stage7_fixture/stm32_minimal/README.md) 的 100 字节测试 App：它不访问外设或 Flash，只在 SRAM 写标记并递增计数。`st-flash --hot-plug read` 已确认 ST-LINK 可以读取目标 SRAM。评估单限定擦写 App 的 55 KB 分区，保留 Bootloader 和 OTA 标志页；测试后恢复原 App 分区。目标、哈希、范围和回滚步骤见 [`07-stm32-flash-proposal.json`](07-stm32-flash-proposal.json)。

开发者随后接好 W25Q32。2026-11-14 再次以 `--hot-plug` 识别同一个 SWD 目标，然后只读其 SRAM；`0x20000828` 处连续字段符合驱动 `W25Qxx_Info_t`：JEDEC ID `0xEF4016`、容量 4 MB、扇区数 1024，第二次读取一致。见 [`07-stm32-w25-readonly.json`](07-stm32-w25-readonly.json)。这是从正在运行的固件内存推断 W25Q32 已被识别，不是我们独立发起的 SPI 指令回执；外部 Flash 内容尚未备份。当前固件有首次启动时向外部 Flash Factory 区写入备份的代码，因此不能把这次检查解释为整机从未写过外部 Flash。

开发者随后明确批准评估单中的最小真机方案。执行前重新读取的内部 64 KB Flash 与原备份逐字节一致；测试固件写入并读回后，Bootloader 与 OTA 标志页保持原样，App 分区其余部分为擦除态。复位后 SRAM 标记为 `0xC7B70001`，计数从 `0x10` 增至 `0x1B`。回滚写入原 App 后，再次读出的完整 64 KB 与烧录前逐字节一致；复位回原固件后，SRAM 再次显示 W25Q32 的 `0xEF4016` 与 4 MB 容量。结构化真实回执见 [`07-stm32-minimal-live-acceptance.json`](07-stm32-minimal-live-acceptance.json)。本轮没有烧录完整 OTA App 或 ESP32，也没有备份外部 W25Q32。

## 选定工程的离线构建

`OTA_Upgrade_System` 原来的 CMake 配置写死 Windows ARM GCC 路径，现已改为共享的 `arm-gcc-toolchain.cmake`，从 `ARM_TOOLCHAIN_PATH` 或 PATH 查找工具链，并在配置时核对 `nano.specs` 与 `nosys.specs`。本机 Homebrew 的编译器单独安装不包含这些库；本轮从 Arm GNU Toolchain 15.3.Rel2 安装包解压到用户目录后完成构建。构建命令没有打开设备：

```bash
cd /path/to/OTA_Upgrade_System
cmake -S . -B build/stage7-app -G Ninja -DARM_TOOLCHAIN_PATH=/path/to/arm-toolchain/bin
cmake --build build/stage7-app
cmake -S Bootloader -B build/stage7-bootloader -G Ninja -DARM_TOOLCHAIN_PATH=/path/to/arm-toolchain/bin
cmake --build build/stage7-bootloader
```

实际验收使用独立临时构建目录，产物复制到仓库内被 `.gitignore` 忽略的 `build/stage7-artifacts/`。App `.bin` 为 29,988 字节，低于 55 KB 上限；Bootloader `.bin` 为 6,168 字节，低于 8 KB 上限；向量表入口均位于各自分区。SHA-256、向量值和构建状态见 [`07-stm32-build-acceptance.json`](07-stm32-build-acceptance.json)。这些是新构建产物，不是设备现有固件的回滚备份。链接器报告 ELF 可装载段含 RWX 权限，Bootloader 的 nano libc 报告 `_close`、`_lseek`、`_read`、`_write` 未实现；需要在上板前判断这些告警是否符合固件设计。

## 对应代码与当前起点

`cybertron/policy.py` 提供本地权限原型；`cybertron/registry.py` 定义 `nexus-prime` 构建权限与 `megatronus` 烧录审批规则；`cybertron/simulation.py` 默认在第 8 步暂停。

`cybertron/deployment.py` 新增纯离线数据契约：读取固件与回滚镜像的 SHA-256 和大小，绑定目标设备与连接标识、Flash 可用地址及擦写区间，生成带摘要的《烧录影响范围评估单》。若文件内容、地址区间或评估单内容发生变化，后续校验失败。`simulate_flash()` 只检查传入的假启动日志是否含预期心跳，并返回明确标记 `simulated: true` 的回执；它不打开串口、运行 Shell 或操作硬件。

```python
if task.step_id == 8 and not self.simulate_hardware_approval:
    return AgentResult(task.step_id, task.agent_id,
                       ResultStatus.NEEDS_APPROVAL,
                       "模拟硬件步骤等待批准；未执行任何烧录命令")
```

最小 ST-LINK 真机测试已由开发者在本次会话中明确批准并执行，结果和回滚核对见真实回执。后续将完整 OTA App 用于真机前，还需备份或明确处置外部 W25Q32 内容、确认串口等应用心跳，并重新准备目标、镜像、擦写范围及回滚方案，取得新的人工批准。手工离线构建仍需纳入隔离构建运行器，宿主审批回执与 Cybertron 真实烧录入口尚未接入；本次聊天审批只授权本次具体操作。

## 计划验收

先完成仿真构建与假设备回执测试；真机前展示目标设备、固件校验值、擦写区间和回滚方案，经人工批准后再执行；校验启动日志和最终交付报告。

当前离线检查：

```bash
python3 -m unittest tests.test_deployment_stage7 -v
python3 -m unittest discover -s tests -v
```

测试覆盖正常评估与仿真心跳、回滚镜像缺失、固件变更、目标或擦写范围无效、原始固件超出擦写范围及符号链接拒绝。结构化结果见 [`07-deployment-offline-acceptance.json`](07-deployment-offline-acceptance.json)。

## 参考

- [项目 v5 架构白皮书：交叉编译与硬件部署](../../design/cybertron_13_primes_architecture.md)
- [OpenCode V2 权限与审批](https://opencode.ai/docs/permissions/)
- [Hello Agents：智能体评估与实践](https://github.com/datawhalechina/hello-agents/blob/main/docs/README.md)
