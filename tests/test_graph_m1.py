"""M1 replanning, rejection, and plan-shape coverage."""

import unittest

from cybertron.graph import GraphRejected, PlanGraph, PlanNode
from cybertron.templates import bug_fix_template, read_only_scan_template
from tests.test_graph import node


def op(graph, ident, kind, **payload):
    return graph.apply_op({"op_id": ident, "plan_revision": graph.revision,
                           "op": kind, **payload})


class GraphM1Tests(unittest.TestCase):
    def test_read_only_scan_template_has_no_writing_node(self):
        graph = read_only_scan_template("Inspect the temporary project directory")
        self.assertEqual(len(graph.nodes), 1)
        scan = graph.nodes["scan"]
        self.assertEqual((scan.capability, scan.role, scan.write_scope),
                         ("scan.static", "onyx-prime", ()))
        with self.assertRaises(ValueError):
            read_only_scan_template(" ")

    def test_reassign_rejects_running_and_role_mismatch(self):
        graph = PlanGraph([node()])
        graph.nodes["n1"].status = "running"
        with self.assertRaises(GraphRejected):
            op(graph, "active", "reassign_role", node_id="n1", role="amalgamous")
        graph.nodes["n1"].status = "pending"
        with self.assertRaises(GraphRejected):
            op(graph, "mismatch", "reassign_role", node_id="n1", role="onyx-prime")
        self.assertEqual(graph.revision, 0)

    def test_split_rewires_downstream_and_rejects_active(self):
        graph = PlanGraph([node("n1"), node("n2", depends_on=("n1",))])
        children = [node("a").to_dict(), node("b", depends_on=("a",)).to_dict()]
        op(graph, "split", "split_node", node_id="n1", nodes=children)
        self.assertEqual(graph.nodes["n2"].depends_on, ("b",))
        self.assertEqual([n.node_id for n in graph.ready_nodes()], ["a"])
        graph.nodes["b"].status = "running"
        with self.assertRaises(GraphRejected):
            op(graph, "active-split", "split_node", node_id="b", nodes=children)

    def test_retry_budget_and_feedback(self):
        candidate = node()
        candidate.status = "failed"
        graph = PlanGraph([candidate])
        with self.assertRaises(GraphRejected):
            op(graph, "no-feedback", "retry_node", node_id="n1")
        op(graph, "retry", "retry_node", node_id="n1", feedback="tool failure")
        self.assertEqual(graph.nodes["n1"].status, "pending")
        graph.nodes["n1"].status = "failed"
        with self.assertRaises(GraphRejected):
            op(graph, "retry2", "retry_node", node_id="n1", feedback="new diagnostic")

    def test_gates_can_only_be_added_and_m2_operations_fail_closed(self):
        graph = PlanGraph([node()])
        op(graph, "gate", "insert_gate", gate="scope_guard")
        with self.assertRaises(GraphRejected):
            op(graph, "duplicate", "insert_gate", gate="scope_guard")
        with self.assertRaises(GraphRejected):
            op(graph, "na", "mark_not_applicable", gate="scope_guard", reason="unneeded", evidence={})
        with self.assertRaises(GraphRejected):
            op(graph, "done", "complete_run")
        self.assertEqual(graph.gates, ["scope_guard"])

    def test_request_human_requires_question_and_round_trips(self):
        graph = PlanGraph([node()])
        with self.assertRaises(GraphRejected):
            op(graph, "empty", "request_human", question=" ")
        op(graph, "ask", "request_human", question="Which board?")
        self.assertEqual(PlanGraph.from_dict(graph.to_dict()).human_requests, ["Which board?"])

    def test_small_medium_and_large_plan_shapes(self):
        for size in (1, 4, 9):
            with self.subTest(size=size):
                graph = PlanGraph()
                for index in range(size):
                    op(graph, f"add-{index}", "add_node", node=node(
                        f"n{index}", depends_on=(f"n{index-1}",) if index else ()).to_dict())
                self.assertEqual(len(graph.nodes), size)
                dispatched = []
                while graph.ready_nodes():
                    ready = graph.ready_nodes()
                    self.assertEqual(len(ready), 1)
                    ready[0].status = "completed"
                    dispatched.append(ready[0].node_id)
                self.assertEqual(len(dispatched), size)
                self.assertEqual(PlanGraph.from_dict(graph.to_dict()).to_dict(), graph.to_dict())

    def test_bug_template_preserves_investigation_before_fix_and_review(self):
        graph = bug_fix_template("Fix parser null dereference", ("src/parser.py",))
        self.assertEqual(len(graph.nodes), 4)
        self.assertEqual({node.node_id for node in graph.ready_nodes()},
                         {"scan-static", "scan-history"})
        self.assertEqual(graph.nodes["fix"].depends_on,
                         ("scan-static", "scan-history"))
        self.assertEqual(graph.nodes["review"].depends_on, ("fix",))
        with self.assertRaises(GraphRejected):
            bug_fix_template("Fix parser null dereference", ("tests/parser.py",))

    def test_nexus_build_files_follow_catalog_and_host_globs(self):
        PlanGraph([node(role="nexus-prime", capability="build.config",
                        write_scope=("Dockerfile.dev", "firmware/linker.ld"))])
        with self.assertRaises(GraphRejected):
            PlanGraph([node(role="nexus-prime", capability="build.config",
                            write_scope=("Dockerfile.dev/secrets",))])

    def test_three_semantic_plan_shapes(self):
        simple = PlanGraph([PlanNode("doc", "task", "doc.write", "alpha-trion",
                                     "Write notes.md", write_scope=("notes.md",))])
        bug = bug_fix_template("Fix parser null dereference", ("src/parser.py",))
        steps = [
            ("clarify", "human", "intake.clarify", "thirteenth", (), ()),
            ("scan", "task", "scan.static", "onyx-prime", ("clarify",), ()),
            ("history", "task", "scan.history", "vector-prime", ("clarify",), ()),
            ("design", "task", "design", "quintus-prime", ("scan", "history"), (".cybertron/plans/dma.md",)),
            ("code", "task", "code.write", "solus-prime", ("design",), ("firmware/dma.c",)),
            ("test", "task", "test.write", "alchemist", ("design",), ("tests/dma_test.py",)),
            ("review", "review", "review.l2", "liege-maximo", ("code", "test"), ()),
            ("device", "device_op", "device.op", "nexus-prime", ("review",), ()),
            ("doc", "task", "doc.write", "alpha-trion", ("device",), ("docs/dma.md",)),
        ]
        hardware = PlanGraph(PlanNode(identifier, kind, capability, role,
                                      f"DMA {identifier}", depends_on=dependencies,
                                      write_scope=scope) for identifier, kind, capability,
                             role, dependencies, scope in steps)
        self.assertEqual((len(simple.nodes), len(bug.nodes), len(hardware.nodes)), (1, 4, 9))
        self.assertEqual([n.node_id for n in hardware.ready_nodes()], ["clarify"])
        self.assertEqual(hardware.nodes["device"].kind, "device_op")


if __name__ == "__main__":
    unittest.main()
