"""Capability grants for irreversible and out-of-scope actions.

A grant is requested by the kernel on behalf of a node, approved only by a
human through the host, and consumed at dispatch time.  The module is pure:
storage and events live in ``host_v6``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


GRANT_KINDS = (
    "read.expand",
    "network.read",
    "write.expand",
    "exec.expand",
    "pkg.install",
    "vcs.write",
    "vcs.push",
    "external.write",
    "deploy",
    "device",
    "dangerous.confirm",
)
IRREVERSIBLE_KINDS = frozenset({"device", "deploy", "vcs.push", "external.write",
                                 "dangerous.confirm"})
DEFAULT_TTL_SECONDS = 8 * 60 * 60
MAX_TTL_SECONDS = 24 * 60 * 60


class GrantRejected(ValueError):
    """A grant request or approval violates the grant contract."""


def normalize_kind(value: Any) -> str:
    if value not in GRANT_KINDS:
        raise GrantRejected(f"unknown grant kind: {value!r}")
    return value


def normalize_scope(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise GrantRejected("scope must be an object")
    return json.loads(json.dumps(value, sort_keys=True))


def normalize_constraints(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise GrantRejected("constraints must be an object")
    return json.loads(json.dumps(value, sort_keys=True))


def clamp_ttl(value: Any) -> int:
    if value is None:
        return DEFAULT_TTL_SECONDS
    if type(value) is not int or value < 60:
        raise GrantRejected("ttl_seconds must be an integer >= 60")
    return min(value, MAX_TTL_SECONDS)


def binding_hash(run_id: str, node_id: str, kind: str,
                 scope: Mapping[str, Any], constraints: Mapping[str, Any],
                 nonce: str) -> str:
    payload = json.dumps({
        "run_id": run_id, "node_id": node_id, "kind": kind,
        "scope": scope, "constraints": constraints, "nonce": nonce,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _covers(granted: Any, requested: Any) -> bool:
    if granted is None:
        return True
    if isinstance(granted, dict) and isinstance(requested, dict):
        return all(key in granted and _covers(granted[key], value)
                   for key, value in requested.items())
    if isinstance(granted, (list, tuple)) and isinstance(requested, (list, tuple)):
        return all(any(_covers(candidate, value) for candidate in granted)
                   for value in requested)
    if isinstance(granted, str) and isinstance(requested, str):
        return granted == requested
    return granted == requested


def covers(grant: Mapping[str, Any], node_id: str, kind: str,
           scope: Mapping[str, Any]) -> bool:
    node_ok = grant.get("node_id") in {node_id, "*"}
    return (node_ok and grant.get("kind") == kind
            and _covers(grant.get("scope") or {}, scope or {}))
