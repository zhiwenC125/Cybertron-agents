"""M5 template distillation for validated v6 plans.

A template is a learned *seed*, never an authority. Distillation happens only
from a run whose every node completed. Replay rebuilds ordinary ``PlanNode``
objects and passes them through ``PlanGraph``, so capability, role, write
scope, and cycle checks still apply. A tampered or stale template fails the
same validation as any model-proposed plan.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .graph import GraphRejected, PlanGraph, PlanNode

TEMPLATE_SCHEMA_VERSION = 1
_TEMPLATE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_REQUEST_CLASS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+-]{0,127}$")
_SCOPE_SLOTS = frozenset({"literal", "target", "tests"})
_TOP_KEYS = frozenset({"schema_version", "template_id", "request_class", "signature",
                       "created_utc", "source_run_id", "source_plan_sha256",
                       "nodes", "learned", "metrics"})
_NODE_KEYS = frozenset({"node_id", "kind", "capability", "role", "objective_template",
                        "depends_on", "read_scope", "write_scope", "scope_slot", "acceptance",
                        "verifiers", "check_target"})
_LEARNED_KEYS = frozenset({"dispatch_count", "human_interventions", "retry_fingerprints",
                           "human_questions", "gate_failures"})
_METRIC_KEYS = frozenset({"node_count", "dispatch_count", "human_interventions", "duration_s"})


class TemplateRejected(ValueError):
    """A template is malformed, unsafe, or no longer validates."""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode()


def plan_digest(graph: PlanGraph) -> str:
    """Digest the plan projection, excluding runtime state."""
    nodes = [node.to_dict() for node in graph.nodes.values()]
    for node in nodes:
        node.pop("status", None)
    return _hash(_canonical({"schema_version": 2, "nodes": nodes,
                             "gates": list(graph.gates)}))


def request_class_of(nodes: Iterable[PlanNode]) -> str:
    """Derive a stable class when the caller does not name one."""
    capabilities = sorted({node.capability for node in nodes})
    return "auto:" + "+".join(capabilities)


def is_request_class(value: Any) -> bool:
    return isinstance(value, str) and bool(_REQUEST_CLASS.fullmatch(value))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:40] or "template"


def templates_dir(project: Path) -> Path:
    root = Path(project) / ".cybertron" / "templates"
    for parent in (Path(project) / ".cybertron", root):
        if parent.is_symlink():
            raise TemplateRejected("template storage may not be a symlink")
    return root


def template_path(project: Path, template_id: str) -> Path:
    if not isinstance(template_id, str) or not _TEMPLATE_ID.fullmatch(template_id):
        raise TemplateRejected("invalid template_id")
    return templates_dir(project) / f"{template_id}.json"


def _string_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise TemplateRejected(f"invalid {field}")
    if not allow_empty and not value:
        raise TemplateRejected(f"empty {field}")
    return list(value)


def _scope_tuple(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise TemplateRejected(f"invalid {field}")
    return tuple(_string_list(list(value), field))


def validate_template(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized copy; unknown fields fail closed."""
    if not isinstance(data, Mapping) or set(data) - _TOP_KEYS:
        raise TemplateRejected("invalid template fields")
    if data.get("schema_version") != TEMPLATE_SCHEMA_VERSION:
        raise TemplateRejected("unsupported template schema_version")
    template_id = data.get("template_id")
    if not isinstance(template_id, str) or not _TEMPLATE_ID.fullmatch(template_id):
        raise TemplateRejected("invalid template_id")
    request_class = data.get("request_class")
    if not isinstance(request_class, str) or not _REQUEST_CLASS.fullmatch(request_class):
        raise TemplateRejected("invalid request_class")
    signature = data.get("signature")
    if signature is not None and (not isinstance(signature, str) or len(signature) > 128):
        raise TemplateRejected("invalid signature")
    created = data.get("created_utc")
    if not isinstance(created, str) or not created:
        raise TemplateRejected("invalid created_utc")
    source_run = data.get("source_run_id")
    if not isinstance(source_run, str) or not source_run:
        raise TemplateRejected("invalid source_run_id")
    source_plan = data.get("source_plan_sha256")
    if not isinstance(source_plan, str) or not re.fullmatch(r"[0-9a-f]{64}", source_plan):
        raise TemplateRejected("invalid source_plan_sha256")

    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise TemplateRejected("template requires nodes")
    nodes: list[dict[str, Any]] = []
    for raw in raw_nodes:
        if not isinstance(raw, Mapping) or set(raw) - _NODE_KEYS or "node_id" not in raw:
            raise TemplateRejected("invalid template node")
        try:
            node = {
                "node_id": raw["node_id"],
                "kind": raw["kind"],
                "capability": raw["capability"],
                "role": raw["role"],
                "objective_template": raw.get("objective_template", "{objective}"),
                "depends_on": _string_list(raw.get("depends_on", []), "depends_on"),
                "read_scope": _string_list(raw.get("read_scope", []), "read_scope"),
                "write_scope": _string_list(raw.get("write_scope", []), "write_scope"),
                "scope_slot": raw.get("scope_slot", "literal"),
                "acceptance": _string_list(raw.get("acceptance", []), "acceptance"),
                "verifiers": _string_list(raw.get("verifiers", []), "verifiers"),
            }
        except KeyError as exc:
            raise TemplateRejected("invalid template node") from exc
        if not isinstance(node["node_id"], str) or not node["node_id"]:
            raise TemplateRejected("invalid node_id")
        if node["scope_slot"] not in _SCOPE_SLOTS:
            raise TemplateRejected("invalid scope_slot")
        objective = node["objective_template"]
        if not isinstance(objective, str) or not objective.strip():
            raise TemplateRejected("invalid objective_template")
        if "check_target" in raw:
            if raw["check_target"] not in ("lint", "build", "test", "sim"):
                raise TemplateRejected("invalid check_target")
            node["check_target"] = raw["check_target"]
        nodes.append(node)
    learned = data.get("learned", {})
    if not isinstance(learned, Mapping) or set(learned) - _LEARNED_KEYS:
        raise TemplateRejected("invalid learned facts")
    learned = {
        "dispatch_count": learned.get("dispatch_count", 0),
        "human_interventions": learned.get("human_interventions", 0),
        "retry_fingerprints": _string_list(learned.get("retry_fingerprints", []), "retry_fingerprints"),
        "human_questions": _string_list(learned.get("human_questions", []), "human_questions"),
        "gate_failures": learned.get("gate_failures", 0),
    }
    for field in ("dispatch_count", "human_interventions", "gate_failures"):
        if type(learned[field]) is not int or learned[field] < 0:
            raise TemplateRejected("invalid learned counts")
    metrics = data.get("metrics", {})
    if not isinstance(metrics, Mapping) or set(metrics) - _METRIC_KEYS:
        raise TemplateRejected("invalid template metrics")
    metrics = {
        "node_count": metrics.get("node_count", len(nodes)),
        "dispatch_count": metrics.get("dispatch_count", learned["dispatch_count"]),
        "human_interventions": metrics.get("human_interventions", learned["human_interventions"]),
        "duration_s": metrics.get("duration_s", 0.0),
    }
    for field in ("node_count", "dispatch_count", "human_interventions"):
        if type(metrics[field]) is not int or metrics[field] < 0:
            raise TemplateRejected("invalid template metric counts")
    if metrics["node_count"] != len(nodes):
        raise TemplateRejected("metric node_count does not match nodes")
    if not isinstance(metrics["duration_s"], (int, float)) or metrics["duration_s"] < 0:
        raise TemplateRejected("invalid template duration")
    normalized = {
        "schema_version": TEMPLATE_SCHEMA_VERSION,
        "template_id": template_id,
        "request_class": request_class,
        "signature": signature or "",
        "created_utc": created,
        "source_run_id": source_run,
        "source_plan_sha256": source_plan,
        "nodes": nodes,
        "learned": learned,
        "metrics": metrics,
    }
    _validate_graph_shape(normalized)
    return normalized


def _validate_graph_shape(template: Mapping[str, Any]) -> None:
    """Apply graph rules without inventing run-specific goals.

    Write slots are checked at replay time against the caller's concrete
    scopes; here only the capability/role mapping, dependency closure, and
    acyclic shape are fixed.
    """
    nodes = template["nodes"]
    ids = {node["node_id"] for node in nodes}
    if len(ids) != len(nodes):
        raise TemplateRejected("duplicate node_id")
    if any(dep not in ids for node in nodes for dep in node["depends_on"]):
        raise TemplateRejected("missing template dependency")
    if any(node["scope_slot"] != "literal" and not _role_can_write(node["role"])
           for node in nodes):
        raise TemplateRejected("write slot has no writable role")
    if any(node["scope_slot"] == "tests" and node["capability"] != "test.write"
           for node in nodes):
        raise TemplateRejected("tests write slot requires test.write")
    try:
        PlanGraph([PlanNode(node_id=node["node_id"], kind=node["kind"],
                            capability=node["capability"], role=node["role"],
                            objective="template",
                            depends_on=tuple(node["depends_on"]),
                            read_scope=tuple(node["read_scope"]),
                            write_scope=(tuple(node["write_scope"])
                                         if node["scope_slot"] == "literal" else ()),
                            acceptance=tuple(node["acceptance"]),
                            verifiers=tuple(node["verifiers"]), check_target=node.get("check_target"))
                  for node in nodes])
    except GraphRejected as exc:
        raise TemplateRejected(str(exc)) from exc


def _role_can_write(role: str) -> bool:
    from .registry import PRIME_ROLES
    entry = PRIME_ROLES.get(role)
    return bool(entry and entry.write_roots)


def distill_template(graph: PlanGraph, events: Sequence[Mapping[str, Any]], *,
                     completed_node_ids: Iterable[str], request_class: str,
                     run_id: str, request: str = "") -> dict[str, Any]:
    """Turn one fully completed run into a replayable template."""
    completed = set(completed_node_ids)
    if set(graph.nodes) - completed:
        raise TemplateRejected("only completed runs can be distilled")
    if not isinstance(request_class, str) or not _REQUEST_CLASS.fullmatch(request_class):
        raise TemplateRejected("invalid request_class")
    if not isinstance(run_id, str) or not run_id:
        raise TemplateRejected("run_id is required")
    if not isinstance(request, str):
        raise TemplateRejected("request must be a string")

    def objective_template(node: PlanNode) -> str:
        if request and request in node.objective:
            return node.objective.replace(request, "{objective}")
        return node.objective

    writers = [node for node in graph.nodes.values() if node.write_scope]
    single_writer = len(writers) == 1
    nodes = []
    for node in graph.nodes.values():
        if node.write_scope and single_writer:
            scope_slot = "tests" if node.capability == "test.write" else "target"
        else:
            scope_slot = "literal"
        nodes.append({
            "node_id": node.node_id, "kind": node.kind,
            "capability": node.capability, "role": node.role,
            "objective_template": objective_template(node),
            "depends_on": list(node.depends_on), "read_scope": list(node.read_scope),
            "write_scope": list(node.write_scope), "scope_slot": scope_slot,
            "acceptance": list(node.acceptance), "verifiers": list(node.verifiers),
            **({"check_target": node.check_target} if node.check_target else {}),
        })
    dispatches = sum(event.get("type") == "dispatch.started" for event in events)
    interventions = sum(event.get("type") in {"human.requested", "approval.granted", "external.write.requested"}
                        for event in events)
    questions = [event.get("question") for event in events
                 if event.get("type") == "human.requested" and isinstance(event.get("question"), str)]
    retries = [event.get("failure_fingerprint") for event in events
               if event.get("type") in {"node.failed", "node.blocked"}
               and isinstance(event.get("failure_fingerprint"), str)]
    gate_failures = sum(event.get("type") == "gate.check" and event.get("status") != "pass"
                        for event in events)
    try:
        start = datetime.fromisoformat(events[0]["utc"]) if events else None
        end = datetime.fromisoformat(events[-1]["utc"]) if events else None
        duration = max(0.0, (end - start).total_seconds()) if start and end else 0.0
    except (KeyError, TypeError, ValueError):
        duration = 0.0
    template_id = f"{_slug(request_class)}-{_hash((run_id + plan_digest(graph)).encode())[:8]}"
    data = {
        "schema_version": TEMPLATE_SCHEMA_VERSION,
        "template_id": template_id,
        "request_class": request_class,
        "signature": hashlib.sha256(_canonical(sorted({n.capability for n in graph.nodes.values()}))).hexdigest(),
        "created_utc": _utc(),
        "source_run_id": run_id,
        "source_plan_sha256": plan_digest(graph),
        "nodes": nodes,
        "learned": {"dispatch_count": dispatches, "human_interventions": interventions,
                    "retry_fingerprints": sorted(set(retries)), "human_questions": questions,
                    "gate_failures": gate_failures},
        "metrics": {"node_count": len(nodes), "dispatch_count": dispatches,
                    "human_interventions": interventions, "duration_s": duration},
    }
    return validate_template(data)


def save_template(project: Path, template: Mapping[str, Any]) -> Path:
    """Atomically persist a validated template; identical replay is a no-op."""
    normalized = validate_template(template)
    path = template_path(project, normalized["template_id"])
    payload = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or path.read_text(encoding="utf-8") != payload:
            raise TemplateRejected("template_id already exists with different content")
        return path
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)
    return path


def load_template(project: Path, template_id: str) -> dict[str, Any]:
    path = template_path(project, template_id)
    if path.is_symlink() or not path.is_file():
        raise TemplateRejected("template does not exist or is unsafe")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TemplateRejected("template is not valid JSON") from exc
    template = validate_template(data)
    if template["template_id"] != template_id:
        raise TemplateRejected("template_id does not match its file")
    return template


def list_templates(project: Path) -> list[dict[str, Any]]:
    directory = templates_dir(project)
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise TemplateRejected("template storage is not a directory")
    templates = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        templates.append(load_template(project, path.stem))
    return templates


def match_template(project: Path, request_class: str) -> dict[str, Any] | None:
    """Prefer the smallest validated template for the same request class."""
    candidates = [t for t in list_templates(project) if t["request_class"] == request_class]
    if not candidates:
        return None
    return min(candidates, key=lambda t: (len(t["nodes"]),
                                          -t["metrics"]["dispatch_count"],
                                          t["created_utc"], t["template_id"]))


def instantiate(template: Mapping[str, Any], *, objective: str,
                target_scope: Sequence[str] = (), test_scope: Sequence[str] = (),
                skip: Sequence[str] = ()) -> PlanGraph:
    """Rebuild a plan from a template; validation is not skipped.

    ``skip`` may drop only read-only task nodes (discovery/analysis) whose
    result the caller already holds. Writers, reviews, and verifiers cannot
    be skipped, and dependencies are rewired transitively.
    """
    if not isinstance(objective, str) or not objective.strip():
        raise TemplateRejected("objective is required")
    target = _scope_tuple(target_scope, "target_scope")
    tests = _scope_tuple(test_scope, "test_scope")
    skipped = _scope_tuple(skip, "skip") if skip else ()
    slots = {raw["scope_slot"] for raw in template["nodes"]}
    if target and "target" not in slots:
        raise TemplateRejected("template has no target write slot")
    if tests and "tests" not in slots:
        raise TemplateRejected("template has no tests write slot")
    dropped = [raw for raw in template["nodes"] if raw["capability"] in skipped]
    known = {raw["capability"] for raw in template["nodes"]}
    if set(skipped) - known:
        raise TemplateRejected("skip names an absent capability")
    if any(raw["kind"] != "task" or raw["write_scope"] or raw["scope_slot"] != "literal"
           or raw.get("check_target") for raw in dropped):
        raise TemplateRejected("only read-only task nodes can be skipped")
    remaining = [raw for raw in template["nodes"] if raw not in dropped]
    if not remaining:
        raise TemplateRejected("skip would leave no nodes")
    by_id = {raw["node_id"]: raw for raw in dropped}

    def expand(dep: str, seen: set[str]) -> set[str]:
        if dep not in by_id:
            return {dep}
        if dep in seen:
            raise TemplateRejected("skip creates a dependency cycle")
        result: set[str] = set()
        for parent in by_id[dep]["depends_on"]:
            result |= expand(parent, seen | {dep})
        return result

    nodes = []
    for raw in remaining:
        slot = raw["scope_slot"]
        if slot == "target" and not target:
            raise TemplateRejected("template requires a target write scope")
        if slot == "tests" and not tests:
            raise TemplateRejected("template requires a test write scope")
        write_scope = {"target": tuple(target), "tests": tuple(tests),
                       "literal": tuple(raw["write_scope"])}[slot]
        deps: set[str] = set()
        for dep in raw["depends_on"]:
            deps |= expand(dep, set())
        nodes.append(PlanNode(
            node_id=raw["node_id"], kind=raw["kind"], capability=raw["capability"],
            role=raw["role"], objective=raw["objective_template"].replace("{objective}", objective.strip()),
            depends_on=tuple(sorted(deps)), read_scope=tuple(raw["read_scope"]),
            write_scope=write_scope, acceptance=tuple(raw["acceptance"]),
            verifiers=tuple(raw["verifiers"]), check_target=raw.get("check_target")))
    try:
        return PlanGraph(nodes)
    except GraphRejected as exc:
        raise TemplateRejected(str(exc)) from exc
