"""Validated v6 plan graph and atomic M0a graph operations.

The read-only capability catalogue is temporary. M1 moves this source of truth
to ``registry.py`` and makes the exporter derive host permissions from it.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, Tuple


class GraphRejected(ValueError):
    """A plan or operation violates the graph contract."""


NODE_KINDS = frozenset({"task", "review", "verify", "human", "device_op"})
NODE_STATES = frozenset({"pending", "running", "completed", "failed", "blocked", "cancelled", "stale"})

# M0a bootstrap only; M1 replaces this with the registry role catalogue.
CAPABILITY_CATALOG: Mapping[str, Mapping[str, Tuple[str, ...]]] = MappingProxyType({
    "plan": MappingProxyType({"prima": ()}),
    "route": MappingProxyType({"prima": ()}),
    "intake.clarify": MappingProxyType({"thirteenth": ()}),
    "evidence.external": MappingProxyType({"thirteenth": ()}),
    "accept": MappingProxyType({"thirteenth": ()}),
    "scan.static": MappingProxyType({"onyx-prime": ()}),
    "context.map": MappingProxyType({"onyx-prime": ()}),
    "audit.inventory": MappingProxyType({"onyx-prime": ()}),
    "scan.history": MappingProxyType({"vector-prime": ()}),
    "diagnose": MappingProxyType({"vector-prime": ()}),
    "analysis.special": MappingProxyType({"vector-prime": ()}),
    "design": MappingProxyType({"quintus-prime": (".cybertron/plans/**",)}),
    "plan.draft": MappingProxyType({"quintus-prime": (".cybertron/plans/**",)}),
    "code.write": MappingProxyType({"solus-prime": ("src/**", "app/**", "firmware/**", "drivers/**", "bsp/**")}),
    "code.refactor": MappingProxyType({"amalgamous": ("src/**", "app/**", "lib/**", "firmware/**", "drivers/**", "bsp/**")}),
    "code.port": MappingProxyType({"amalgamous": ("src/**", "app/**", "lib/**", "firmware/**", "drivers/**", "bsp/**")}),
    "code.transform": MappingProxyType({"amalgamous": ("src/**", "app/**", "lib/**", "firmware/**", "drivers/**", "bsp/**")}),
    "review.l1": MappingProxyType({"micronus-prime": ()}),
    "review.l2": MappingProxyType({"liege-maximo": ()}),
    "test.write": MappingProxyType({"alchemist": ("tests/**",)}),
    "build.config": MappingProxyType({"nexus-prime": ("CMakeLists.txt", "Makefile", "platformio.ini", "Dockerfile*", "**/*.ld", "**/*.dts*")}),
    "toolchain": MappingProxyType({"nexus-prime": ("CMakeLists.txt", "Makefile", "platformio.ini", "Dockerfile*", "**/*.ld", "**/*.dts*")}),
    "device.op": MappingProxyType({"megatronus": ()}),
    "doc.write": MappingProxyType({"alpha-trion": ("docs/**", "AGENTS.md", "README.md", "CHANGELOG.md", "notes.md")}),
    "knowledge.sync": MappingProxyType({"alpha-trion": (".cybertron/knowledge/**",)}),
})


def _scope_allowed(scope: str, roots: Tuple[str, ...]) -> bool:
    if not isinstance(scope, str) or not scope or scope.startswith("/"):
        return False
    parts = scope.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if parts[0] == ".git" or parts[:2] == [".cybertron", "runs"]:
        return False
    if scope == "opencode.jsonc" or scope.startswith(".opencode/"):
        return False
    # A scope is either an exact path, a root-level extension glob, or a
    # directory subtree. Reject other glob forms instead of guessing subset.
    if any("*" in part for part in parts[:-1]):
        return False
    if "*" in parts[-1] and parts[-1] != "**" and not (len(parts) == 1 and parts[-1].startswith("*.")):
        return False
    for root in roots:
        if root.endswith("/**"):
            prefix = root[:-3]
            if scope.startswith(prefix + "/"):
                return True
        elif root == scope:
            return True
        elif root.startswith("*.") and len(parts) == 1 and "*" not in scope and scope.endswith(root[1:]):
            return True
    return False


@dataclass
class PlanNode:
    node_id: str
    kind: str
    capability: str
    role: str
    objective: str
    depends_on: Tuple[str, ...] = ()
    read_scope: Tuple[str, ...] = ()
    write_scope: Tuple[str, ...] = ()
    acceptance: Tuple[str, ...] = ()
    verifiers: Tuple[str, ...] = ()
    budget: Dict[str, int] = field(default_factory=lambda: {"max_attempts": 2})
    status: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id, "kind": self.kind,
            "capability": self.capability, "role": self.role,
            "objective": self.objective, "depends_on": list(self.depends_on),
            "read_scope": list(self.read_scope), "write_scope": list(self.write_scope),
            "acceptance": list(self.acceptance), "verifiers": list(self.verifiers),
            "budget": dict(self.budget), "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanNode":
        try:
            return cls(
                node_id=data["node_id"], kind=data["kind"],
                capability=data["capability"], role=data["role"],
                objective=data["objective"],
                depends_on=tuple(data.get("depends_on", ())),
                read_scope=tuple(data.get("read_scope", ())),
                write_scope=tuple(data.get("write_scope", ())),
                acceptance=tuple(data.get("acceptance", ())),
                verifiers=tuple(data.get("verifiers", ())),
                budget=dict(data.get("budget", {"max_attempts": 2})),
                status=data.get("status", "pending"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphRejected("invalid node payload") from exc


class PlanGraph:
    """Graph projection; only ``apply_op`` changes plan structure."""

    def __init__(self, nodes: Iterable[PlanNode] = (), *, revision: int = 0,
                 events: Iterable[Mapping[str, Any]] = (), applied_ops: Mapping[str, Mapping[str, Any]] = None):
        items = list(nodes)
        if len({item.node_id for item in items}) != len(items):
            raise GraphRejected("duplicate node_id")
        self.nodes: Dict[str, PlanNode] = {item.node_id: copy.deepcopy(item) for item in items}
        self.revision = revision
        self.events = [dict(event) for event in events]
        self.applied_ops = copy.deepcopy(dict(applied_ops or {}))
        self.validate()

    def validate(self) -> None:
        if type(self.revision) is not int or self.revision < 0:
            raise GraphRejected("invalid plan_revision")
        for node in self.nodes.values():
            if not isinstance(node.node_id, str) or not node.node_id or not isinstance(node.objective, str) or not node.objective.strip():
                raise GraphRejected("node_id and objective are required")
            if node.kind not in NODE_KINDS or node.status not in NODE_STATES:
                raise GraphRejected("invalid node kind or state")
            if not isinstance(node.capability, str) or not isinstance(node.role, str):
                raise GraphRejected("capability and role must be strings")
            roles = CAPABILITY_CATALOG.get(node.capability)
            if roles is None or node.role not in roles:
                raise GraphRejected("capability has no matching role")
            if any(not isinstance(value, str) or not value for values in
                   (node.depends_on, node.read_scope, node.write_scope, node.acceptance, node.verifiers)
                   for value in values):
                raise GraphRejected("node lists must contain nonempty strings")
            if len(set(node.depends_on)) != len(node.depends_on) or any(dep not in self.nodes for dep in node.depends_on):
                raise GraphRejected("duplicate or missing dependency")
            if not all(_scope_allowed(scope, roles[node.role]) for scope in node.write_scope):
                raise GraphRejected("write_scope exceeds role limit or hard denial")
            attempts = node.budget.get("max_attempts")
            if type(attempts) is not int or attempts < 1:
                raise GraphRejected("invalid max_attempts")
        visiting, visited = set(), set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise GraphRejected("dependency cycle")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dep in self.nodes[node_id].depends_on:
                visit(dep)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in self.nodes:
            visit(node_id)

    def ready_nodes(self) -> List[PlanNode]:
        self.validate()
        return [node for node in self.nodes.values()
                if node.status == "pending" and all(self.nodes[dep].status == "completed" for dep in node.depends_on)]

    def to_dict(self) -> Dict[str, Any]:
        return {"schema_version": 2, "plan_revision": self.revision,
                "nodes": [node.to_dict() for node in self.nodes.values()],
                "events": copy.deepcopy(self.events), "applied_ops": copy.deepcopy(self.applied_ops)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanGraph":
        if data.get("schema_version") != 2:
            raise GraphRejected("unsupported graph schema_version")
        try:
            return cls((PlanNode.from_dict(item) for item in data["nodes"]),
                       revision=data["plan_revision"], events=data.get("events", ()),
                       applied_ops=data.get("applied_ops", {}))
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphRejected("invalid graph payload") from exc

    def apply_op(self, operation: Mapping[str, Any]) -> int:
        op_id = operation.get("op_id")
        if not isinstance(op_id, str) or not op_id:
            raise GraphRejected("op_id is required")
        try:
            fingerprint = hashlib.sha256(json.dumps(operation, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        except (TypeError, ValueError) as exc:
            raise GraphRejected("operation must be JSON serializable") from exc
        previous = self.applied_ops.get(op_id)
        if previous is not None:
            if previous["fingerprint"] != fingerprint:
                raise GraphRejected("op_id reused with different payload")
            return previous["revision"]

        self.events.append({"type": "plan.op.proposed", "op_id": op_id,
                            "operation": copy.deepcopy(dict(operation))})
        try:
            if operation.get("plan_revision") != self.revision:
                raise GraphRejected("stale plan_revision")
            candidate = copy.deepcopy(self.nodes)
            if operation.get("op") == "add_node":
                new_node = PlanNode.from_dict(operation["node"])
                if new_node.node_id in candidate:
                    raise GraphRejected("duplicate node_id")
                candidate[new_node.node_id] = new_node
            elif operation.get("op") == "add_edge":
                target = operation["node_id"]
                dependency = operation["depends_on"]
                if target not in candidate or dependency not in candidate:
                    raise GraphRejected("missing edge endpoint")
                if dependency in candidate[target].depends_on:
                    raise GraphRejected("duplicate edge")
                candidate[target].depends_on += (dependency,)
            else:
                raise GraphRejected("operation is not available in M0a")
            PlanGraph(candidate.values(), revision=self.revision + 1)
        except (GraphRejected, KeyError, TypeError) as exc:
            reason = str(exc) if isinstance(exc, GraphRejected) else "invalid operation payload"
            self.events.append({"type": "plan.op.rejected", "op_id": op_id, "reason": reason})
            raise GraphRejected(reason) from exc
        self.nodes = candidate
        self.revision += 1
        self.applied_ops[op_id] = {"fingerprint": fingerprint, "revision": self.revision}
        self.events.append({"type": "plan.op.applied", "op_id": op_id, "plan_revision": self.revision})
        return self.revision
