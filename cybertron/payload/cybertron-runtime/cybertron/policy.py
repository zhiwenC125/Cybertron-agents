"""提供本地 RBAC 匹配、危险命令审批提示和重复调用熔断；宿主权限仍是最终执行边界。"""

from __future__ import annotations
import fnmatch
import posixpath
import re
import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
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
    Local policy prototype and loop guard used by tests and self-verification.
    It does not intercept OpenCode's real tool calls; the exported host rules do that.
    Callers must supply workspace-relative read/edit paths.
    """
    HIGH_ENTROPY_PATTERNS = (
        "rm -rf", "git push --force", "drop table", "mkfs", "dd if=",
        "openocd ", "esptool", "pio run -t upload", "st-flash",
    )

    def __init__(self, rules: List[PermissionRule], max_identical_calls: int = 3,
                 workspace_root: Path | None = None) -> None:
        self.rules = rules
        self.max_identical_calls = max_identical_calls
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self._call_signatures: Dict[str, int] = {}

    def _normalize_path(self, resource: str) -> str | None:
        """Return a safe workspace-relative path, including symlink resolution."""
        path = resource.replace("\\", "/")
        if not path or "\x00" in path or path.startswith(("/", "~")) \
                or re.match(r"^[A-Za-z]:", path):
            return None
        if ".." in path.split("/"):
            return None
        normalized = posixpath.normpath(path)
        if normalized in (".", ".."):
            return None
        try:
            resolved = (self.workspace_root / normalized).resolve()
            resolved.relative_to(self.workspace_root)
        except (ValueError, OSError, RuntimeError):
            return None
        return normalized

    def verify_tool_call(self, action: str, resource: str, payload_signature: str) -> Tuple[PermissionEffect, str]:
        if action in ("read", "edit"):
            normalized = self._normalize_path(resource)
            if normalized is None:
                return PermissionEffect.DENY, f"Unsafe workspace path denied: {resource}"
            resource = normalized
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
            action_match = rule.action == "*" or fnmatch.fnmatchcase(action, rule.action)
            resource_match = rule.resource == "*" or fnmatch.fnmatchcase(resource, rule.resource)
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
