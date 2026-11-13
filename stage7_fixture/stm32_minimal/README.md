# STM32F103C8T6 Stage 7 最小真机验证固件

此测试固件供已安装的 `OTA_Upgrade_System` Bootloader 从 App 分区 `0x08002000` 启动。它不初始化 W25Q32、串口或其他外设，不访问外部 Flash，不写内部 Flash。复位后它关闭中断，在 SRAM `0x20000000` 写入标记 `0xC7B70001`，并在 `0x20000004` 持续递增计数。可通过 ST-LINK 两次读取 SRAM 来验证运行；读回 App 分区可验证烧录结果。

本机已使用 Arm GNU Toolchain 15.3.Rel2 构建出 100 字节的 `heartbeat.bin`，SHA-256 为 `62554f5a0043bc92d2cfc6456e0ab116348324a1b699af62891532559e00476d`。向量表栈顶为 `0x20005000`，复位入口为 `0x08002041`；ELF 的可装载段只有 App 分区内 `0x08002000` 起的 100 字节，权限为 R/E。

```bash
arm-none-eabi-gcc -mcpu=cortex-m3 -mthumb -nostdlib \
  -Wl,-T,stage7_fixture/stm32_minimal/app.ld -Wl,--gc-sections \
  -o stage7_fixture/stm32_minimal/build/heartbeat.elf \
  stage7_fixture/stm32_minimal/heartbeat.s
arm-none-eabi-objcopy -O binary \
  stage7_fixture/stm32_minimal/build/heartbeat.elf \
  stage7_fixture/stm32_minimal/build/heartbeat.bin
```

构建产物只用于本机阶段 7 受控测试。烧录前必须保存设备现有固件备份，核实目标、镜像哈希与擦写范围，并取得真实人工审批。完成测试后应恢复原 App 分区并读回比对。
