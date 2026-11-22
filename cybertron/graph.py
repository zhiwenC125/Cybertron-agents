"""Validated v6 plan graph and atomic plan operations."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from fnmatch import fnmatchcase
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, Tuple


class GraphRejected(ValueError):
    """A plan or operation violates the graph contract."""


NODE_KINDS = frozenset({"task", "review", "verify", "human", "device_op"})
NODE_STATES = frozenset({"pending", "running", "completed", "failed", "blocked", "cancelled", "stale"})
GRAPH_OPERATIONS = ("add_node", "add_edge", "reassign_role", "split_node", "retry_node",
                    "insert_gate", "mark_not_applicable", "request_human", "complete_run",
                    "revise")

# Registry is the only v6 capability and role-scope source of truth.
from .access import (DEFAULT_ACCESS_MODE, hard_denied, is_external_scope,
                     normalize_access_mode)
from .registry import PRIME_ROLES, assert_catalog
from .intent import Intent
from .grants import GRANT_KINDS

CAPABILITY_CATALOG: Mapping[str, Mapping[str, Tuple[str, ...]]] = MappingProxyType({
    capability: MappingProxyType({role.agent_id: role.write_roots})
    for role in PRIME_ROLES.values() for capability in role.capabilities
})


def _scope_allowed(scope: str, roots: Tuple[str, ...]) -> bool:
    if not isinstance(scope, str) or not scope or scope.startswith("/"):
        return False
    parts = scope.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if hard_denied(scope):
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
        elif "*" in root and "*" not in scope and (
            ("/" not in root and "/" not in scope) or root.startswith("**/")) and fnmatchcase(scope, root):
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
    external_scope: Tuple[str, ...] = ()
    acceptance: Tuple[str, ...] = ()
    verifiers: Tuple[str, ...] = ()
    budget: Dict[str, int] = field(default_factory=lambda: {"max_attempts": 2})
    status: str = "pending"
    satisfies: Tuple[str, ...] = ()
    requires: Tuple[str, ...] = ()
    expected_content_sha256: str | None = None
    check_target: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id, "kind": self.kind,
            "capability": self.capability, "role": self.role,
            "objective": self.objective, "depends_on": list(self.depends_on),
            "read_scope": list(self.read_scope), "write_scope": list(self.write_scope),
            "external_scope": list(self.external_scope),
            "acceptance": list(self.acceptance), "verifiers": list(self.verifiers),
            "budget": dict(self.budget), "status": self.status,
            "satisfies": list(self.satisfies), "requires": list(self.requires),
            **({"expected_content_sha256": self.expected_content_sha256}
               if self.expected_content_sha256 is not None else {}),
            **({"check_target": self.check_target} if self.check_target is not None else {}),
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
                external_scope=tuple(data.get("external_scope", ())),
                acceptance=tuple(data.get("acceptance", ())),
                verifiers=tuple(data.get("verifiers", ())),
                budget=dict(data.get("budget", {"max_attempts": 2})),
                status=data.get("status", "pending"),
                satisfies=tuple(data.get("satisfies", ())),
                requires=tuple(data.get("requires", ())),
                expected_content_sha256=data.get("expected_content_sha256"),
                check_target=data.get("check_target"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphRejected("invalid node payload") from exc


class PlanGraph:
    """Graph projection; only ``apply_op`` changes plan structure."""

    def __init__(self, nodes: Iterable[PlanNode] = (), *, revision: int = 0,
                 events: Iterable[Mapping[str, Any]] = (), applied_ops: Mapping[str, Mapping[str, Any]] = None,
                 gates: Iterable[str] = (), human_requests: Iterable[str] = (),
                 attempts: Mapping[str, int] = None, complete: bool = False,
                 access_mode: str = DEFAULT_ACCESS_MODE,
                 intent: Intent | None = None, planned_verification: bool = False):
        assert_catalog()
        self.access_mode = normalize_access_mode(access_mode)
        items = list(nodes)
        if len({item.node_id for item in items}) != len(items):
            raise GraphRejected("duplicate node_id")
        self.nodes: Dict[str, PlanNode] = {item.node_id: copy.deepcopy(item) for item in items}
        self.revision = revision
        self.events = [dict(event) for event in events]
        self.applied_ops = copy.deepcopy(dict(applied_ops or {}))
        self.gates = list(gates)
        self.human_requests = list(human_requests)
        self.attempts = dict(attempts or {})
        self.complete = complete
        if intent is not None and not isinstance(intent, Intent):
            raise GraphRejected("intent must be an Intent")
        self.intent = intent
        self.planned_verification = planned_verification
        self.validate()

    def validate(self) -> None:
        if type(self.revision) is not int or self.revision < 0:
            raise GraphRejected("invalid plan_revision")
        if any(not isinstance(gate, str) or not gate for gate in self.gates) or len(set(self.gates)) != len(self.gates):
            raise GraphRejected("invalid gates")
        if any(not isinstance(q, str) or not q for q in self.human_requests):
            raise GraphRejected("invalid human requests")
        if any(key not in self.nodes or type(value) is not int or value < 0 for key, value in self.attempts.items()):
            raise GraphRejected("invalid attempt counters")
        if type(self.complete) is not bool:
            raise GraphRejected("invalid completion state")
        for node in self.nodes.values():
            if not isinstance(node.node_id, str) or not node.node_id or not isinstance(node.objective, str) or not node.objective.strip():
                raise GraphRejected("node_id and objective are required")
            if node.kind not in NODE_KINDS or node.status not in NODE_STATES:
                raise GraphRejected("invalid node kind or state")
            if not isinstance(node.capability, str) or not isinstance(node.role, str):
                raise GraphRejected("capability and role must be strings")
            roles = CAPABILITY_CATALOG.get(node.capability)
            if roles is None or node.role not in roles:
                role = PRIME_ROLES.get(node.role)
                allowed = ", ".join(role.capabilities) if role else "unknown role"
                raise GraphRejected(f"capability {node.capability!r} has no matching role "
                                    f"{node.role!r}; registered capabilities: {allowed}")
            if any(not isinstance(value, str) or not value for values in
                   (node.depends_on, node.read_scope, node.write_scope, node.external_scope,
                    node.acceptance, node.verifiers)
                   for value in values):
                raise GraphRejected("node lists must contain nonempty strings")
            if len(set(node.depends_on)) != len(node.depends_on) or any(dep not in self.nodes for dep in node.depends_on):
                raise GraphRejected("duplicate or missing dependency")
            self._validate_write_scope(node, roles[node.role])
            if node.expected_content_sha256 is not None:
                targets = (*node.write_scope, *node.external_scope)
                if (not isinstance(node.expected_content_sha256, str)
                        or not re.fullmatch(r"[a-f0-9]{64}", node.expected_content_sha256)
                        or len(targets) != 1 or any(mark in targets[0] for mark in "*?")):
                    raise GraphRejected("expected file content requires one exact path and a SHA-256 hash")
            if node.check_target is not None and not isinstance(node.check_target, str):
                raise GraphRejected("check_target must be a string")
            attempts = node.budget.get("max_attempts")
            if type(attempts) is not int or attempts < 1:
                raise GraphRejected("invalid max_attempts")
            if self.attempts.get(node.node_id, 0) > attempts:
                raise GraphRejected("attempt counter exceeds max_attempts")
            if any(not isinstance(value, str) or not value for value in node.satisfies):
                raise GraphRejected("satisfies must contain nonempty strings")
            if len(set(node.satisfies)) != len(node.satisfies):
                raise GraphRejected("duplicate satisfies id")
            if any(kind not in GRANT_KINDS for kind in node.requires):
                raise GraphRejected("unknown grant requirement")
            if len(set(node.requires)) != len(node.requires):
                raise GraphRejected("duplicate grant requirement")
        if self.intent is not None:
            done_ids = self.intent.done_ids
            for node in self.nodes.values():
                if not set(node.satisfies) <= done_ids:
                    raise GraphRejected(f"node {node.node_id!r} satisfies unknown done id")
        elif any(node.satisfies for node in self.nodes.values()):
            raise GraphRejected("satisfies requires an intent contract")
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

    def _validate_write_scope(self, node: "PlanNode", roots: Tuple[str, ...]) -> None:
        if self.access_mode == "read-only":
            if node.write_scope or node.external_scope:
                raise GraphRejected("read-only plan cannot declare write_scope or external_scope")
            return
        if self.access_mode == "danger-full-access":
            if node.external_scope:
                raise GraphRejected("danger-full-access declares outside paths in write_scope; "
                                    "external_scope is only for workspace-write")
            if any(hard_denied(scope) for scope in node.write_scope):
                raise GraphRejected("write_scope targets generated config, VCS, or run state")
            return
        if any(is_external_scope(scope) for scope in node.write_scope):
            raise GraphRejected("workspace-write access mode cannot write outside the project; "
                                "declare outside paths in external_scope or use "
                                "access_mode=danger-full-access only after the user authorizes it")
        if not all(_scope_allowed(scope, roots) for scope in node.write_scope):
            raise GraphRejected("write_scope exceeds role limit or hard denial")
        for scope in node.external_scope:
            if not is_external_scope(scope):
                raise GraphRejected("external_scope entries must be absolute, home-relative, "
                                    "or parent-relative paths")
            if "*" in scope or "?" in scope:
                raise GraphRejected("external_scope entries must be literal paths without globs")
            parts = [part for part in scope.replace("\\", "/").split("/") if part]
            if any(part in {".", ".."} for part in parts):
                raise GraphRejected("external_scope entries cannot contain '.' or '..' segments")
            if hard_denied(scope):
                raise GraphRejected("external_scope targets generated config, VCS, or run state")

    def ready_nodes(self) -> List[PlanNode]:
        self.validate()
        return [node for node in self.nodes.values()
                if node.status in {"pending", "stale"}
                and all(self.nodes[dep].status == "completed" for dep in node.depends_on)]

    def to_dict(self) -> Dict[str, Any]:
        payload = {"schema_version": 2, "plan_revision": self.revision,
                   "nodes": [node.to_dict() for node in self.nodes.values()],
                   "events": copy.deepcopy(self.events), "applied_ops": copy.deepcopy(self.applied_ops),
                   "gates": list(self.gates), "human_requests": list(self.human_requests),
                   "attempts": dict(self.attempts), "complete": self.complete,
                   "access_mode": self.access_mode}
        if self.intent is not None:
            payload["intent"] = self.intent.to_dict()
        if self.planned_verification:
            payload["planned_verification"] = True
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanGraph":
        if data.get("schema_version") != 2:
            raise GraphRejected("unsupported graph schema_version")
        try:
            return cls((PlanNode.from_dict(item) for item in data["nodes"]),
                       revision=data["plan_revision"], events=data.get("events", ()),
                       applied_ops=data.get("applied_ops", {}), gates=data.get("gates", ()),
                       human_requests=data.get("human_requests", ()),
                       attempts=data.get("attempts", {}), complete=data.get("complete", False),
                       access_mode=data.get("access_mode", DEFAULT_ACCESS_MODE),
                       planned_verification=data.get("planned_verification", False),
                       intent=(Intent.from_dict(data["intent"])
                               if data.get("intent") is not None else None))
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
            if type(operation.get("plan_revision")) is not int or operation["plan_revision"] != self.revision:
                raise GraphRejected("stale plan_revision")
            candidate = copy.deepcopy(self.nodes)
            gates = list(self.gates)
            human_requests = list(self.human_requests)
            attempts = dict(self.attempts)
            complete = self.complete
            planned_verification = self.planned_verification
            kind = operation.get("op")
            if complete:
                raise GraphRejected("completed run cannot be replanned")
            if kind == "add_node":
                new_node = PlanNode.from_dict(operation["node"])
                if new_node.node_id in candidate:
                    raise GraphRejected("duplicate node_id")
                candidate[new_node.node_id] = new_node
            elif kind == "add_edge":
                target = operation["node_id"]
                dependency = operation["depends_on"]
                if target not in candidate or dependency not in candidate:
                    raise GraphRejected("missing edge endpoint")
                if dependency in candidate[target].depends_on:
                    raise GraphRejected("duplicate edge")
                if candidate[target].status != "pending":
                    raise GraphRejected("cannot add edge to started node")
                candidate[target].depends_on += (dependency,)
            elif kind == "reassign_role":
                node = candidate[operation["node_id"]]
                if node.status in {"running", "completed"}:
                    raise GraphRejected("cannot reassign active or completed node")
                node.role = operation["role"]
            elif kind == "split_node":
                target = candidate[operation["node_id"]]
                if target.status in {"running", "completed"}:
                    raise GraphRejected("active or completed nodes cannot be split")
                children = [PlanNode.from_dict(item) for item in operation["nodes"]]
                if len(children) < 2 or len({child.node_id for child in children}) != len(children):
                    raise GraphRejected("split requires at least two distinct children")
                if any(child.node_id in candidate or child.status != "pending" for child in children):
                    raise GraphRejected("split child is duplicate or started")
                if tuple(children[0].depends_on) != target.depends_on:
                    raise GraphRejected("first split child must preserve dependencies")
                for previous, child in zip(children, children[1:]):
                    if previous.node_id not in child.depends_on:
                        raise GraphRejected("split children must form an ordered chain")
                del candidate[target.node_id]
                for child in children:
                    candidate[child.node_id] = child
                for node in candidate.values():
                    if target.node_id in node.depends_on:
                        node.depends_on = tuple(children[-1].node_id if dep == target.node_id else dep for dep in node.depends_on)
            elif kind == "retry_node":
                node = candidate[operation["node_id"]]
                if node.status not in {"failed", "cancelled", "blocked", "stale"}:
                    raise GraphRejected("only terminal unsuccessful nodes can retry")
                feedback = operation.get("feedback")
                if not isinstance(feedback, str) or not feedback.strip():
                    raise GraphRejected("retry requires feedback")
                # Reaching a retry means the initial dispatch already used
                # one attempt, even if the old plan has no counter yet.
                used = attempts.get(node.node_id, 1)
                if used >= node.budget["max_attempts"]:
                    raise GraphRejected("max_attempts exhausted")
                attempts[node.node_id] = used + 1
                node.status = "pending"
            elif kind == "insert_gate":
                gate = operation["gate"]
                if not isinstance(gate, str) or not gate or gate in gates:
                    raise GraphRejected("invalid or duplicate gate")
                gates.append(gate)
            elif kind == "revise":
                reason = operation.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    raise GraphRejected("revision requires a reason")
                changed = [PlanNode.from_dict(item) for item in operation.get("nodes", ())]
                removed = operation.get("remove_nodes", ())
                retried = operation.get("retry_nodes", ())
                ids = [node.node_id for node in changed]
                if (len(set(ids)) != len(ids) or any(node.status != "pending" for node in changed)
                        or not set(removed) <= candidate.keys() or set(removed) & set(ids)
                        or not set(retried) <= candidate.keys() - set(removed)):
                    raise GraphRejected("invalid revision nodes")
                for node_id in removed:
                    del candidate[node_id]
                    attempts.pop(node_id, None)
                for node in changed:
                    candidate[node.node_id] = node
                    attempts.pop(node.node_id, None)
                for node_id in retried:
                    attempts.pop(node_id, None)
                gates = list(operation.get("gates", gates))
                planned_verification = True
            elif kind == "mark_not_applicable":
                # M2 supplies risk-floor and verifier facts. Until then no
                # model proposal can establish this conclusion.
                raise GraphRejected("gate facts unavailable until M2")
            elif kind == "request_human":
                question = operation["question"]
                if not isinstance(question, str) or not question.strip():
                    raise GraphRejected("question is required")
                human_requests.append(question)
            elif kind == "complete_run":
                # M2 binds acceptance to verified gate receipts.
                raise GraphRejected("acceptance evidence unavailable until M2")
            else:
                raise GraphRejected(
                    f"unknown graph operation {kind!r}; expected one of {', '.join(GRAPH_OPERATIONS)}")
            PlanGraph(candidate.values(), revision=self.revision + 1,
                      gates=gates, human_requests=human_requests, attempts=attempts,
                      complete=complete, access_mode=self.access_mode,
                      intent=self.intent, planned_verification=planned_verification)
        except (GraphRejected, KeyError, TypeError, ValueError, AttributeError) as exc:
            reason = str(exc) if isinstance(exc, GraphRejected) else "invalid operation payload"
            self.events.append({"type": "plan.op.rejected", "op_id": op_id, "reason": reason})
            raise GraphRejected(reason) from exc
        self.nodes = candidate
        self.gates = gates
        self.human_requests = human_requests
        self.attempts = attempts
        self.complete = complete
        self.planned_verification = planned_verification
        self.revision += 1
        self.applied_ops[op_id] = {"fingerprint": fingerprint, "revision": self.revision}
        self.events.append({"type": "plan.op.applied", "op_id": op_id, "plan_revision": self.revision})
        return self.revision
