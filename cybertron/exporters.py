"""把角色注册表编译成 OpenCode V2 配置和 DeepSeek Harness 静态预设。"""

from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List
from .registry import THIRTEEN_PRIMES_REGISTRY

# ============================================================================

def compile_opencode_v2_assets(target_dir: Path, *, include_feishu: bool = False) -> List[Path]:
    """Generates OpenCode V2 native configuration files for all 13 Primes."""
    generated: List[Path] = []
    agents_dir = target_dir / ".opencode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    agents_json_map: Dict[str, Any] = {}
    for prime in THIRTEEN_PRIMES_REGISTRY:
        perm_dicts = [
            {"action": r.action, "resource": r.resource, "effect": r.effect.value}
            for r in prime.permissions
        ]
        perm_yaml_lines = [
            f'  - action: "{r.action}"\n    resource: "{r.resource}"\n    effect: "{r.effect.value}"'
            for r in prime.permissions
        ]
        perm_yaml_block = "\n".join(perm_yaml_lines)

        md_text = (
            f"---\n"
            f'description: "[{prime.cn_name} · {prime.en_name}] {prime.description}"\n'
            f"mode: {prime.mode.value}\n"
            f"model: {prime.model}\n"
            f"steps: {prime.max_steps}\n"
            f'color: "{prime.color}"\n'
            f"permissions:\n{perm_yaml_block}\n"
            f"---\n\n"
            f"# {prime.cn_name} ({prime.en_name}) — 神器：{prime.artifact}\n"
            f"- **所属生命周期阶段 (SDLC Stage)**: `{prime.sdlc_stage}`\n"
            f"- **唯一专职领域 (Exclusive Domain)**: {prime.exclusive_domain}\n"
            f"- **绝对禁止红线 (Strict Prohibitions)**: {prime.strict_prohibitions}\n"
            f"- **标准输入契约 (Input Contract)**: {prime.input_contract}\n"
            f"- **标准输出契约 (Output Contract)**: {prime.output_contract}\n"
            f"- **飞书知识库角色**: {prime.feishu_wiki_role}\n\n"
            f"{prime.system_prompt}\n"
        )
        md_file = agents_dir / f"{prime.agent_id}.md"
        md_file.write_text(md_text, encoding="utf-8")
        generated.append(md_file)

        agents_json_map[prime.agent_id] = {
            "description": f"[{prime.cn_name}] {prime.description}",
            "mode": prime.mode.value,
            "model": prime.model,
            "steps": prime.max_steps,
            "color": prime.color,
            "permissions": perm_dicts,
        }

    opencode_jsonc = {
        "$schema": "https://opencode.ai/config.json",
        "default_agent": "prima",
        "agents": agents_json_map,
    }
    if include_feishu:
        opencode_jsonc["mcp"] = {
            "timeout": {
                "startup": 45000,
                "catalog": 30000,
                "execution": 120000,
            },
            "servers": {
                "feishu_wiki": {
                    "type": "local",
                    "command": [
                        "npx",
                        "-y",
                        "@larksuiteoapi/lark-mcp",
                        "mcp",
                        "-a",
                        "{env:FEISHU_APP_ID}",
                        "-s",
                        "{env:FEISHU_APP_SECRET}",
                        "--token-mode",
                        "tenant_access_token",
                    ],
                    "environment": {
                        "FEISHU_APP_ID": "{env:FEISHU_APP_ID}",
                        "FEISHU_APP_SECRET": "{env:FEISHU_APP_SECRET}",
                        "FEISHU_WIKI_SPACE_ID": "{env:FEISHU_WIKI_SPACE_ID}",
                    },
                }
            },
        }
    jsonc_path = target_dir / "opencode.jsonc"
    jsonc_path.write_text(json.dumps(opencode_jsonc, ensure_ascii=False, indent=2), encoding="utf-8")
    generated.append(jsonc_path)
    return generated


def compile_deepseek_harness_assets(target_dir: Path) -> List[Path]:
    """Generates DeepSeek Harness (dsh) Cordis plugin and preset files."""
    dsh_dir = target_dir / ".dsh"
    dsh_dir.mkdir(parents=True, exist_ok=True)
    generated: List[Path] = []

    preset_data = {
        "name": "cybertron-thirteen-primes-sdlc-hardware",
        "version": "5.0.0",
        "supported_modes": ["standard", "ptc"],
        "orchestration": {
            "pattern": "picoagents-plan-based-sdlc-hardware-ledger",
            "primary_orchestrator": "prima",
            "documentation_and_wiki_steward": "alpha-trion",
            "l1_code_reviewer": "micronus-prime",
            "l2_security_reviewer": "liege-maximo",
            "qa_and_sil_verifier": "alchemist",
            "cross_compile_and_prep": "nexus-prime",
            "physical_flash_gatekeeper": "megatronus",
        },
        "agents": [
            {
                "id": p.agent_id,
                "cn_name": p.cn_name,
                "en_name": p.en_name,
                "artifact": p.artifact,
                "sdlc_stage": p.sdlc_stage,
                "mode": p.mode.value,
                "model": p.model,
                "max_steps": p.max_steps,
                "exclusive_domain": p.exclusive_domain,
                "strict_prohibitions": p.strict_prohibitions,
                "input_contract": p.input_contract,
                "output_contract": p.output_contract,
                "feishu_wiki_role": p.feishu_wiki_role,
                "permissions": [asdict(r) for r in p.permissions],
            }
            for p in THIRTEEN_PRIMES_REGISTRY
        ],
    }
    preset_file = dsh_dir / "cybertron-primes-preset.json"
    preset_file.write_text(json.dumps(preset_data, ensure_ascii=False, indent=2), encoding="utf-8")
    generated.append(preset_file)
    return generated
