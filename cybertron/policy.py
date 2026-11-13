"""提供本地 RBAC 匹配、危险命令审批提示和重复调用熔断；宿主权限仍是最终执行边界。"""

from __future__ import annotations
import fnmatch
import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Tuple

# MODULE 3: Megatronus Safety Hooks & Hardware/Software RBAC Engine
# ============================================================================

class PermissionEffect(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass
class PermissionRule:
    action: str      # "read", "edit", "shell", "subagent", "webfetch", "feishu_wiki_*", "*"
    resource: str    # Glob or command pattern: "*", "src/**", "firmware/**", "tests/**", "openocd *"
    effect: PermissionEffect


class MegatronusCircuitBreaker:
    """
    Runtime Policy, Physical Hardware Flash Gate & Loop Guard (Megatronus Prime).
    Enforces Least-Privilege RBAC before any tool executes and intercepts physical hardware flashing
    or destructive commands with mandatory human confirmation (`ask`).
    """
    HIGH_ENTROPY_PATTERNS = (
        "rm -rf", "git push --force", "drop table", "mkfs", "dd if=",
        "openocd ", "esptool", "pio run -t upload", "st-flash",
    )

    def __init__(self, rules: List[PermissionRule], max_identical_calls: int = 3) -> None:
        self.rules = rules
        self.max_identical_calls = max_identical_calls
        self._call_signatures: Dict[str, int] = {}

    def verify_tool_call(self, action: str, resource: str, payload_signature: str) -> Tuple[PermissionEffect, str]:
        # 1. Detect infinite tool call loop
        self._call_signatures[payload_signature] = self._call_signatures.get(payload_signature, 0) + 1
        if self._call_signatures[payload_signature] > self.max_identical_calls:
            return (
                PermissionEffect.DENY,
                f"[Megatronus Circuit Breaker] Identical tool call repeated >{self.max_identical_calls} times. Loop terminated.",
            )

        # 2. Evaluate ordered RBAC rules first (last matching rule wins, matching OpenCode V2 semantics)
        matched_effect = PermissionEffect.DENY
        for rule in self.rules:
            action_match = rule.action == "*" or fnmatch.fnmatch(action, rule.action)
            resource_match = rule.resource == "*" or fnmatch.fnmatch(resource, rule.resource)
            if action_match and resource_match:
                matched_effect = rule.effect

        # 3. If RBAC denied it, return DENY immediately; if allowed/ask on high-entropy hardware/shell, enforce ASK
        if matched_effect == PermissionEffect.DENY:
            return PermissionEffect.DENY, f"RBAC denied {action}:{resource}"

        if action == "shell":
            # Resource patterns describe one command. Do not let a second command
            # inherit an allowance intended for the first executable.
            if "\n" in resource or "`" in resource or "$(" in resource:
                return PermissionEffect.DENY, "Shell substitution or multiline command denied"
            try:
                lexer = shlex.shlex(resource, posix=True, punctuation_chars=";&|<>")
                lexer.whitespace_split = True
                tokens = list(lexer)
            except ValueError:
                return PermissionEffect.DENY, "Malformed shell command denied"
            if any(any(char in token for char in ";&|<>") for token in tokens):
                return PermissionEffect.DENY, "Shell chaining or redirection denied"
            lowered = resource.lower()
            for hazard in self.HIGH_ENTROPY_PATTERNS:
                if hazard in lowered:
                    return (
                        PermissionEffect.ASK,
                        f"[Megatronus Physical/Entropy Gate] Command '{hazard}' requires human approval.",
                    )

        return matched_effect, f"RBAC evaluated to '{matched_effect.value}' for {action}:{resource}"
