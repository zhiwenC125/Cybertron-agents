import unittest

from cybertron.graph import PlanGraph, PlanNode
from cybertron.scheduler_v6 import affected_subgraph, dispatchable, scopes_overlap


def doc(ident, scope=(), deps=(), status="pending"):
    return PlanNode(ident, "task", "doc.write", "alpha-trion", ident,
                    depends_on=deps, write_scope=scope, status=status)


class SchedulerV6Tests(unittest.TestCase):
    def test_overlapping_directory_and_file_scopes_lock(self):
        self.assertTrue(scopes_overlap(("docs/**",), ("docs/a.md",)))
        self.assertTrue(scopes_overlap(("*.md",), ("notes.md",)))
        self.assertFalse(scopes_overlap(("docs/a.md",), ("docs/b.md",)))

    def test_default_one_writer_and_parallel_readers(self):
        graph = PlanGraph([doc("a", ("docs/a.md",)), doc("b", ("docs/b.md",)),
                           doc("read-a"), doc("read-b")])
        self.assertEqual([n.node_id for n in dispatchable(graph, (), max_writers=1)],
                         ["a", "read-a", "read-b"])
        self.assertEqual([n.node_id for n in dispatchable(graph, ("a",), max_writers=1)],
                         ["read-a", "read-b"])
        self.assertEqual([n.node_id for n in dispatchable(graph, ("a",), max_writers=2)],
                         ["b", "read-a", "read-b"])

    def test_conflicting_writers_queue_even_with_capacity(self):
        graph = PlanGraph([doc("a", ("docs/a.md",)), doc("b", ("docs/**",))])
        self.assertEqual([n.node_id for n in dispatchable(graph, (), max_writers=4)], ["a"])
        self.assertEqual(dispatchable(graph, ("a",), max_writers=4), [])

    def test_l2_rejection_affects_only_consumers(self):
        graph = PlanGraph([doc("scan", status="completed"),
                           doc("fix", ("docs/fix.md",), ("scan",), "completed"),
                           doc("review", (), ("fix",), "completed"),
                           doc("deliver", (), ("review",), "completed"),
                           doc("unrelated", ("docs/other.md",), ("scan",), "completed")])
        self.assertEqual(affected_subgraph(graph, "fix"), ("fix", "review", "deliver"))
        with self.assertRaises(ValueError):
            affected_subgraph(graph, "missing")


if __name__ == "__main__":
    unittest.main()
