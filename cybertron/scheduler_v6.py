"""M3 scheduling decisions and local rework boundaries.

These functions do not dispatch agents or accept evidence. The host bridge
must enforce their decisions against its event ledger before starting work.
"""

from __future__ import annotations

from fnmatch import fnmatchcase

from .graph import PlanGraph, PlanNode


def scopes_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    """Conservatively detect overlap between supported write-scope patterns."""
    if not left or not right:
        return False
    for a in left:
        for b in right:
            if a == b or a == "**" or b == "**":
                return True
            if a.endswith("/**") and (b == a[:-3] or b.startswith(a[:-3] + "/")):
                return True
            if b.endswith("/**") and (a == b[:-3] or a.startswith(b[:-3] + "/")):
                return True
            if "*" in a and ("*" in b or fnmatchcase(b, a)):
                return True
            if "*" in b and fnmatchcase(a, b):
                return True
            # A directory scope's ancestor may be written by the other node.
            if a.startswith(b + "/") or b.startswith(a + "/"):
                return True
    return False


def dispatchable(graph: PlanGraph, active_ids: tuple[str, ...], *, max_writers: int = 1) -> list[PlanNode]:
    """Return ready nodes that fit the active locks and writer budget."""
    if max_writers < 1 or max_writers > 4:
        raise ValueError("max_writers must be between 1 and 4")
    active = [graph.nodes[node_id] for node_id in active_ids]
    writers = sum(bool(node.write_scope) for node in active)
    selected: list[PlanNode] = []
    for node in graph.ready_nodes():
        if not node.write_scope:
            selected.append(node)
            continue
        if writers >= max_writers or any(scopes_overlap(node.write_scope, other.write_scope)
                                         for other in active + selected if other.write_scope):
            continue
        selected.append(node)
        writers += 1
    return selected


def affected_subgraph(graph: PlanGraph, root_id: str) -> tuple[str, ...]:
    """Return a rejected producer and only its transitive consumers."""
    if root_id not in graph.nodes:
        raise ValueError("unknown affected node")
    affected = {root_id}
    changed = True
    while changed:
        before = len(affected)
        affected.update(node.node_id for node in graph.nodes.values()
                        if any(dep in affected for dep in node.depends_on))
        changed = len(affected) != before
    return tuple(node_id for node_id in graph.nodes if node_id in affected)
