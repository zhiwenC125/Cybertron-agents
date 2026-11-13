"""运行不依赖模型和硬件的基础配置自检与导出检查。"""

from __future__ import annotations
from pathlib import Path
from .exporters import compile_deepseek_harness_assets, compile_opencode_v2_assets
from .ledger import PrimaPlanOrchestrator
from .policy import MegatronusCircuitBreaker, PermissionEffect
from .registry import THIRTEEN_PRIMES_REGISTRY


def run_self_verification(output_dir: Path) -> None:
    print("=== [Cybertron 13 Primes Engine v5.0 — Full SDLC & Hardware Edition] Starting Self-Verification ===")
    assert len(THIRTEEN_PRIMES_REGISTRY) == 13, f"Expected 13 Primes, got {len(THIRTEEN_PRIMES_REGISTRY)}"

    orchestrator = PrimaPlanOrchestrator()
    ledger = orchestrator.create_full_sdlc_hardware_ledger("开发STM32电机PID控制固件与上位机API并烧录验证")
    assert len(ledger.plan) == 9, "Expected 9 full-lifecycle SDLC steps!"
    print("[PASS] 9-Step Software + Hardware Full-Lifecycle Ledger verified.")

    # 1. Verify Dedicated Tech Writer & Feishu Steward (Alpha Trion)
    alpha_breaker = MegatronusCircuitBreaker(orchestrator.primes["alpha-trion"].permissions)
    solus_breaker = MegatronusCircuitBreaker(orchestrator.primes["solus-prime"].permissions)
    assert alpha_breaker.verify_tool_call("edit", "docs/hardware_pinout.md", "d1")[0] == PermissionEffect.ALLOW
    assert alpha_breaker.verify_tool_call("edit", "README.md", "d2")[0] == PermissionEffect.ALLOW
    assert solus_breaker.verify_tool_call("edit", "docs/hardware_pinout.md", "d3")[0] == PermissionEffect.DENY
    print("[PASS] Dedicated Documentation & Feishu Wiki Steward (Alpha Trion) verified.")

    # 2. Verify Dedicated Two-Tier Code Review (Micronus L1 clang-tidy + Liege Maximo L2 Static Review)
    micronus_breaker = MegatronusCircuitBreaker(orchestrator.primes["micronus-prime"].permissions)
    liege_breaker = MegatronusCircuitBreaker(orchestrator.primes["liege-maximo"].permissions)
    assert micronus_breaker.verify_tool_call("shell", "clang-tidy firmware/main.c", "c1")[0] == PermissionEffect.ALLOW
    assert liege_breaker.verify_tool_call("read", "firmware/main.c", "c2")[0] == PermissionEffect.ALLOW
    assert liege_breaker.verify_tool_call("edit", "firmware/main.c", "c3")[0] == PermissionEffect.DENY
    print("[PASS] Dedicated Two-Tier Code Review (Micronus L1 + Liege Maximo L2) verified.")

    # 3. Verify Hardware Cross-Compilation (Nexus Prime ALLOW) vs Physical Hardware Flashing (Megatronus ASK)
    nexus_breaker = MegatronusCircuitBreaker(orchestrator.primes["nexus-prime"].permissions)
    megatronus_breaker = MegatronusCircuitBreaker(orchestrator.primes["megatronus"].permissions)
    assert nexus_breaker.verify_tool_call("shell", "arm-none-eabi-gcc -c firmware/main.c", "h1")[0] == PermissionEffect.ALLOW
    assert nexus_breaker.verify_tool_call("shell", "openocd -f interface/stlink.cfg", "h2")[0] == PermissionEffect.DENY
    assert megatronus_breaker.verify_tool_call("shell", "openocd -f interface/stlink.cfg", "h3")[0] == PermissionEffect.ASK
    assert megatronus_breaker.verify_tool_call("shell", "esptool.py write_flash 0x1000 fw.bin", "h4")[0] == PermissionEffect.ASK
    print("[PASS] Hardware Deployment Separation verified: Nexus Prime (Cross-Compile=ALLOW, Flash=DENY) vs Megatronus (Physical Flash=ASK).")

    oc_files = compile_opencode_v2_assets(output_dir)
    dsh_files = compile_deepseek_harness_assets(output_dir)
    print(f"[PASS] Exported {len(oc_files)} OpenCode V2 files & {len(dsh_files)} DeepSeek Harness files to {output_dir.resolve()}")
