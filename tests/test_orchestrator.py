import itertools
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cybertron.execution import AgentResult, ResultStatus
from cybertron.hosts import FakeHost, OpenCodeReadOnlyHost
from cybertron.orchestrator import HostTurnResult, RunCoordinator
from cybertron.runstore import RunLocked, RunStore

ROOT = Path(__file__).resolve().parent.parent


class RunCoordinatorTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CYBERTRON_SANDBOX"):
            numbers = itertools.count(300)
            patcher = patch("cybertron.orchestrator.uuid.uuid4",
                            side_effect=lambda: uuid.UUID(int=next(numbers)))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scratch = tempfile.TemporaryDirectory(prefix="cybertron-orchestrator-")
        self.workspace = Path(self.scratch.name)
        (self.workspace / "opencode.jsonc").write_text('{"default_agent":"prima"}\n')
        self.store = RunStore(self.workspace)
        self.run_id = self.store.create("离线九步测试")["run_id"]

    def tearDown(self):
        self.scratch.cleanup()

    def test_fake_host_completes_nine_stages_and_records_mapping(self):
        host = FakeHost(simulate_hardware_approval=True)
        state = RunCoordinator(self.store, host).run_until_blocked(self.run_id)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(host.turns, 13)
        events = self.store.events(self.run_id)
        starts = [item for item in events if item["type"] == "dispatch.started"]
        ends = [item for item in events if item["type"] == "dispatch.completed"]
        self.assertEqual(len(starts), len(ends))
        self.assertTrue(all(item["payload"]["host_session_id"] for item in starts))
        self.assertEqual(len({item["dispatch_id"] for item in starts}), 13)

    def test_rejection_reworks_code_and_both_reviews(self):
        host = FakeHost(reject_review_once=True, simulate_hardware_approval=True)
        state = RunCoordinator(self.store, host).run_until_blocked(self.run_id)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(self.store.load_ledger(self.run_id).review_retry_count, 1)
        completed = [item for item in self.store.events(self.run_id)
                     if item["type"] == "dispatch.completed"]
        agents = [item["payload"]["agent_id"] for item in completed]
        self.assertEqual(agents.count("solus-prime"), 2)
        self.assertEqual(agents.count("micronus-prime"), 2)
        self.assertEqual(agents.count("liege-maximo"), 2)

    def test_restart_continues_original_run_without_repeating_turn(self):
        first_host = FakeHost()
        first_state = RunCoordinator(self.store, first_host).step(self.run_id)
        self.assertEqual(first_state["stage_id"], 2)
        restarted = RunCoordinator(RunStore(self.workspace), FakeHost())
        state = restarted.run_until_blocked(self.run_id)
        self.assertEqual(state["status"], "blocked")  # hardware approval boundary
        agents = [item["payload"]["agent_id"] for item in self.store.events(self.run_id)
                  if item["type"] == "dispatch.started"]
        self.assertEqual(agents.count("thirteenth"), 1)

    def test_host_crash_leaves_unknown_outcome_and_no_automatic_retry(self):
        class CrashingHost(FakeHost):
            def execute(self, task, **kwargs):
                self.turns += 1
                raise RuntimeError("host crashed after start")

        host = CrashingHost()
        state = RunCoordinator(self.store, host).step(self.run_id)
        self.assertEqual(state["dispatch_status"], "outcome_unknown")
        self.assertTrue(state["host_session_id"])
        again = RunCoordinator(RunStore(self.workspace), host).step(self.run_id)
        self.assertEqual(again["dispatch_status"], "outcome_unknown")
        self.assertEqual(host.turns, 1)

    def test_stale_transition_cannot_start_a_second_dispatch(self):
        previous_seq = self.store.show(self.run_id)["event_seq"]
        RunCoordinator(self.store, FakeHost()).step(self.run_id)
        with self.assertRaises(RunLocked):
            self.store.transition(self.run_id, "dispatch.started", lambda ledger: None,
                                  expected_seq=previous_seq)
        self.assertEqual(len([event for event in self.store.events(self.run_id)
                              if event["type"] == "dispatch.started"]), 1)

    def test_mismatched_agent_result_blocks_ledger(self):
        class WrongHost(FakeHost):
            def execute(self, task, *, host_session_id, dispatch_id, attempt_id):
                return HostTurnResult(AgentResult(task.step_id, "wrong-agent",
                                                  ResultStatus.COMPLETED, "claim",
                                                  evidence=("fake://claim",)),
                                      host_session_id, "host-turn")

        state = RunCoordinator(self.store, WrongHost()).step(self.run_id)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["dispatch_status"], "idle")

    def test_real_host_scope_is_read_only_and_unsupported_role_blocks(self):
        host = OpenCodeReadOnlyHost(self.workspace)
        self.assertTrue(host.can_execute(self._task(1, "thirteenth")))
        self.assertFalse(host.can_execute(self._task(2, "alpha-trion")))
        self.assertFalse(host.can_execute(self._task(4, "solus-prime")))
        # Advance the initial read-only stage with a fake host, then verify
        # real host scope before a model call would be made.
        RunCoordinator(self.store, FakeHost()).step(self.run_id)
        state = RunCoordinator(self.store, host).step(self.run_id)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(len([event for event in self.store.events(self.run_id)
                              if event["type"] == "dispatch.started"]), 1)

    def test_workflow_cli_requires_explicit_real_model_flag(self):
        if os.environ.get("CYBERTRON_SANDBOX"):
            self.skipTest("CLI UUID generation uses denied /dev/urandom in this macOS sandbox")

        def cli(*parts):
            return subprocess.run([sys.executable, "-m", "cybertron.installer", "workflow", *parts,
                                   "--project", str(self.workspace)], cwd=ROOT,
                                  capture_output=True, text=True)

        created = cli("create", "CLI 工作流")
        self.assertEqual(created.returncode, 0, created.stderr)
        run_id = json.loads(created.stdout)["run_id"]
        denied = cli("step", run_id, "--host", "opencode-readonly")
        self.assertNotEqual(denied.returncode, 0)
        self.assertEqual(len([event for event in self.store.events(run_id)
                              if event["type"] == "dispatch.started"]), 0)
        fake = cli("run", run_id)
        self.assertEqual(fake.returncode, 0, fake.stderr)
        self.assertEqual(json.loads(fake.stdout)["stage_id"], 8)

    @staticmethod
    def _task(step_id, agent_id):
        from cybertron.execution import AgentTask
        return AgentTask(step_id, agent_id, "test", "objective", "input", "output")


if __name__ == "__main__":
    unittest.main()
