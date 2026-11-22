"""Intent-first role authority metadata.

The host still enforces concrete tool permissions.  This module records the
canonical atom matrix so the kernel can validate grant requests, keep the
reviewer deny-list in one place, and detect matrix drift in tests.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from .grants import GRANT_KINDS

ROLE_AUTHORITY: dict[str, dict[str, Any]] = {
    "prima": {
        "atoms": ("task", "cy_state", "cy_ask", "cy_escalate",
                  "question", "cy_templates", "cy_metrics"),
        "escalatable": (),
        "never": ("read", "write", "edit", "bash", "cy_plan"),
    },
    "thirteenth": {
        "atoms": ("read", "glob", "grep", "webfetch", "cy_state", "cy_plan",
                  "cy_templates", "question"),
        "escalatable": ("network.read", "read.expand"),
        "never": ("write", "edit", "bash", "task"),
    },
    "alpha-trion": {
        "atoms": ("read", "glob", "grep", "write", "edit", "webfetch",
                  "external.write"),
        "escalatable": ("external.write", "network.read", "write.expand"),
        "never": ("bash", "device", "deploy"),
    },
    "onyx-prime": {
        "atoms": ("read", "glob", "grep"),
        "escalatable": ("read.expand",),
        "never": ("write", "edit", "bash", "device", "deploy"),
    },
    "vector-prime": {
        "atoms": ("bash:git-read",),
        "escalatable": ("vcs.write", "vcs.push"),
        "never": ("write", "edit", "device", "deploy"),
    },
    "quintus-prime": {
        "atoms": ("read", "glob", "grep", "write", "edit", "cy_check"),
        "escalatable": ("exec.expand", "pkg.install"),
        "never": ("bash:git-write", "bash:git-push", "device", "deploy"),
    },
    "solus-prime": {
        "atoms": ("read", "edit", "bash:lint"),
        "escalatable": ("exec.expand", "pkg.install"),
        "never": ("bash:git-write", "bash:git-push", "device", "deploy"),
    },
    "amalgamous": {
        "atoms": ("read",),
        "escalatable": (),
        "never": ("write", "edit", "bash", "task", "device", "deploy"),
    },
    "micronus-prime": {
        "atoms": ("read", "glob", "grep", "bash:lint", "bash:git-read",
                  "cy_check"),
        "escalatable": ("exec.expand", "read.expand"),
        "never": ("bash:git-write", "bash:git-push", "device", "deploy"),
    },
    "liege-maximo": {
        "atoms": ("read", "glob", "grep", "cy_review_reject"),
        "escalatable": ("exec.expand", "read.expand"),
        "never": ("bash:git-write", "bash:git-push", "device", "deploy"),
    },
    "alchemist": {
        "atoms": ("read", "glob", "grep", "write", "edit", "bash:test",
                  "bash:pkg", "bash:git-read", "cy_check"),
        "escalatable": ("exec.expand", "pkg.install"),
        "never": ("bash:git-write", "bash:git-push", "device", "deploy"),
    },
    "nexus-prime": {
        "atoms": ("read", "glob", "grep", "write", "edit", "bash:build",
                  "bash:pkg", "cy_check", "device", "deploy"),
        "escalatable": ("exec.expand", "pkg.install", "device", "deploy"),
        "never": ("bash:git-write", "bash:git-push"),
    },
    "megatronus": {
        "atoms": ("read", "cy_verify"),
        "escalatable": (),
        "never": ("write", "edit", "bash", "device", "deploy"),
    },
}

REVIEWER_ROLES = frozenset({"micronus-prime", "liege-maximo"})
REVIEWER_DENY_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore",
    "*.jks", "id_rsa*", "id_ed25519*", ".ssh/**", ".aws/**",
    ".config/gcloud/**", ".npmrc", ".pypirc", ".netrc", ".docker/config.json",
    "kubeconfig*", "secrets/**", "**/secrets/**", "credentials*", ".git/**",
)


class AuthorityRejected(ValueError):
    pass


def assert_authority() -> None:
    from .registry import THIRTEEN_PRIMES_REGISTRY
    ids = {prime.agent_id for prime in THIRTEEN_PRIMES_REGISTRY}
    if set(ROLE_AUTHORITY) != ids:
        raise AuthorityRejected("authority matrix must contain exactly the 13 roles")
    for role, entry in ROLE_AUTHORITY.items():
        if not entry["atoms"]:
            raise AuthorityRejected(f"{role} has no baseline atoms")
        if any(kind not in GRANT_KINDS for kind in entry["escalatable"]):
            raise AuthorityRejected(f"{role} has an unknown escalatable grant")
        if "task" in entry["escalatable"] or "cy_plan" in entry["escalatable"]:
            raise AuthorityRejected("control-plane atoms must not be escalatable")
        if role in REVIEWER_ROLES and any(atom in entry["atoms"] for atom in
                                          ("bash:git-write", "bash:git-push", "device")):
            raise AuthorityRejected("reviewers cannot hold write-side-effect atoms")


def can_escalate(role: str, kind: str) -> bool:
    if kind == "dangerous.confirm":
        return True
    entry = ROLE_AUTHORITY.get(role)
    return bool(entry and kind in entry["escalatable"])


def denied_for_reviewer(path_value: str) -> bool:
    normalized = str(path_value).replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    parts = [part for part in normalized.split("/") if part]
    if ".git" in parts:
        return True
    return any(fnmatchcase(normalized, pattern) or fnmatchcase(path_value, pattern)
               for pattern in REVIEWER_DENY_PATTERNS)


def snapshot() -> dict[str, Any]:
    assert_authority()
    return {
        "schema_version": 1,
        "roles": {role: {"atoms": list(entry["atoms"]),
                         "escalatable": list(entry["escalatable"]),
                         "never": list(entry["never"])}
                  for role, entry in ROLE_AUTHORITY.items()},
        "reviewer_deny": list(REVIEWER_DENY_PATTERNS),
    }
