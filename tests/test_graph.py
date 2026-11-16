"""M0a graph contract: reject invalid plans before mutating live state."""

import copy
import unittest

from cybertron.graph import GraphRejected, PlanGraph, PlanNode


def node(node_id="n1", *, role="solus-prime", capability="code.write", depends_on=(), write_scope=("src/app/**",)):
    return PlanNode(
        node_id=node_id,
        kind="task",
        capability=capability,
        role=role,
        objective="Implement the task",
        depends_on=depends_on,
        read_scope=("src/**",),
        write_scope=write_scope,
        acceptance=("AC1 [auto]",),
        verifiers=("scope_guard",),
        budget={"max_attempts": 2},
    )


class GraphTests(unittest.TestCase):
    def test_cycle_rejected_atomically(self):
        graph = PlanGraph([node("n1"), node("n2", depends_on=("n1",))])
        before = graph.to_dict()["nodes"]
        with self.assertRaises(GraphRejected):
            graph.apply_op({"op_id": "edge-1", "plan_revision": 0, "op": "add_edge", "node_id": "n1", "depends_on": "n2"})
        self.assertEqual(graph.to_dict()["nodes"], before)
        self.assertEqual(graph.revision, 0)
        self.assertEqual(graph.events[-1]["type"], "plan.op.rejected")

    def test_unknown_capability_and_role_mismatch_rejected(self):
        for candidate in (node(capability="invented.write"), node(role="onyx-prime")):
            with self.subTest(candidate=candidate):
                with self.assertRaises(GraphRejected):
                    PlanGraph([candidate])

    def test_write_scope_outside_role_and_hard_denials_rejected(self):
        for scope in ("tests/**", ".git/config", ".cybertron/runs/r1/**", "../src/**"):
            with self.subTest(scope=scope):
                with self.assertRaises(GraphRejected):
                    PlanGraph([node(write_scope=(scope,))])

    def test_doc_scope_cannot_exceed_generated_host_permissions(self):
        with self.assertRaises(GraphRejected):
            PlanGraph([node(role="alpha-trion", capability="doc.write", write_scope=("arbitrary.md",))])

    def test_add_node_rejection_preserves_revision_and_nodes(self):
        graph = PlanGraph([node()])
        before = graph.to_dict()["nodes"]
        with self.assertRaises(GraphRejected):
            graph.apply_op({"op_id": "bad", "plan_revision": 0, "op": "add_node", "node": node("n2", write_scope=("tests/**",)).to_dict()})
        self.assertEqual(graph.to_dict()["nodes"], before)
        self.assertEqual(graph.revision, 0)

    def test_op_id_is_idempotent_and_revision_is_checked(self):
        graph = PlanGraph([node()])
        operation = {"op_id": "add-2", "plan_revision": 0, "op": "add_node", "node": node("n2", depends_on=("n1",)).to_dict()}
        self.assertEqual(graph.apply_op(operation), 1)
        self.assertEqual(graph.apply_op(copy.deepcopy(operation)), 1)
        self.assertEqual(len(graph.nodes), 2)
        self.assertEqual(sum(e["type"] == "plan.op.applied" for e in graph.events), 1)
        with self.assertRaises(GraphRejected):
            graph.apply_op({**operation, "node": node("n3").to_dict()})
        with self.assertRaises(GraphRejected):
            graph.apply_op({"op_id": "stale", "plan_revision": 0, "op": "add_node", "node": node("n3").to_dict()})
        self.assertEqual(graph.revision, 1)

    def test_ready_nodes_and_round_trip(self):
        graph = PlanGraph([node("n1"), node("n2", depends_on=("n1",))])
        self.assertEqual([n.node_id for n in graph.ready_nodes()], ["n1"])
        graph.nodes["n1"].status = "completed"
        self.assertEqual([n.node_id for n in graph.ready_nodes()], ["n2"])
        self.assertEqual(PlanGraph.from_dict(graph.to_dict()).to_dict(), graph.to_dict())

    def test_missing_dependency_and_invalid_state_rejected(self):
        with self.assertRaises(GraphRejected):
            PlanGraph([node("n2", depends_on=("missing",))])
        candidate = node()
        candidate.status = "imaginary"
        with self.assertRaises(GraphRejected):
            PlanGraph([candidate])

    def test_invalid_node_list_item_rejected(self):
        candidate = node()
        candidate.acceptance = (None,)
        with self.assertRaises(GraphRejected):
            PlanGraph([candidate])

    def test_proposed_event_keeps_replayable_operation(self):
        graph = PlanGraph([node()])
        operation = {"op_id": "new", "plan_revision": 0, "op": "add_node", "node": node("n2").to_dict()}
        graph.apply_op(operation)
        self.assertEqual(graph.events[0]["operation"], operation)


if __name__ == "__main__":
    unittest.main()
