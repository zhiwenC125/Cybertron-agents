import os
import tempfile
import unittest
from pathlib import Path

from cybertron.host_v6 import HostBridgeError, V6HostBridge


class V6M2HostGateTests(unittest.TestCase):
    def _code_run(self, root):
        bridge = V6HostBridge(root)
        node = {"node_id": "code", "kind": "task", "capability": "code.write",
                "role": "solus-prime", "objective": "Write C hello world",
                "write_scope": ["src/main.c"], "acceptance": ["C source exists"],
                "verifiers": ["scope_guard"]}
        plan = bridge.plan(node, "parent")
        started = bridge.before(plan["run_id"], "code", "solus-prime", plan["card"], "call-1")
        returned = bridge.after(plan["run_id"], "call-1", started["token"],
                                "child-1", "completed", 1)
        (root / "src").mkdir()
        (root / "src" / "main.c").write_text('int main(void){return 0;}\n')
        settled = bridge.finish(plan["run_id"], returned["token"], "child-1")
        return bridge, plan["run_id"], settled

    def test_actual_code_diff_sets_floor_and_prima_cannot_lower_it(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, run_id, settled = self._code_run(Path(directory))
            self.assertEqual(settled["status"], "blocked")
            self.assertEqual(settled["nodes"][0]["status"], "completed")
            self.assertEqual(settled["pending_gates"], ["lint", "review.l2.light", "test"])
            with self.assertRaises(HostBridgeError):
                bridge.plan_op(run_id, {"op_id": "lower", "op": "mark_not_applicable",
                                        "plan_revision": 0, "gate": "test"})

    @unittest.skipIf(os.environ.get("CYBERTRON_SANDBOX") == "1",
                     "nested sandbox-exec is unsupported; run host checks outside stage5 sandbox")
    def test_real_lint_receipt_binds_to_workspace_and_goes_stale_on_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.20)\nproject(hello C)\n"
                "add_executable(hello src/main.c)\n")
            bridge, run_id, _ = self._code_run(root)
            check = bridge.check(run_id, "lint")
            self.assertEqual(check["status"], "pass", check["receipts"][-1]["output"])
            self.assertIn("lint", check["state"]["passed_gates"])
            self.assertIn("test", check["state"]["pending_gates"])
            (root / "src" / "main.c").write_text('int main(void){return 1;}\n')
            self.assertNotIn("lint", bridge.state(run_id)["passed_gates"])


if __name__ == "__main__":
    unittest.main()
