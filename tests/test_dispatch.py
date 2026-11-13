import unittest

from cybertron import AgentResult, PrimaDispatcher, PrimaPlanOrchestrator, ResultStatus
from cybertron.simulation import SimulationExecutor


class DispatchTests(unittest.TestCase):
    def test_simulation_stops_before_unapproved_hardware_step(self):
        ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger("demo")
        results = PrimaDispatcher(SimulationExecutor()).run_until_blocked(ledger)
        self.assertEqual(len(results), 11)
        self.assertEqual(results[-1].status, ResultStatus.NEEDS_APPROVAL)
        self.assertEqual(ledger.plan[7].status, "blocked")
        self.assertEqual(ledger.plan[8].status, "pending")
        self.assertEqual(ledger.plan[0].evidence, ["simulation://step/1/thirteenth"])
        self.assertEqual(ledger.plan[2].completed_agents,
                         ["onyx-prime", "vector-prime", "quintus-prime"])
        self.assertEqual(ledger.plan[4].completed_agents,
                         ["micronus-prime", "liege-maximo"])

    def test_explicit_simulation_can_finish_and_preserve_evidence(self):
        ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger("demo")
        results = PrimaDispatcher(SimulationExecutor(
            simulate_hardware_approval=True,
        )).run_until_blocked(ledger)
        self.assertEqual(len(results), 13)
        self.assertIsNone(ledger.next_step())
        self.assertEqual(ledger.plan[7].evidence, ["simulation://step/8/megatronus"])
        self.assertEqual(ledger.plan[8].completed_agents,
                         ["alpha-trion", "thirteenth"])

    def test_bad_executor_result_blocks_step(self):
        class WrongAgent:
            def execute(self, task):
                return AgentResult(task.step_id, "other", ResultStatus.COMPLETED,
                                   "done", evidence=("proof",))

        ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger("demo")
        with self.assertRaises(ValueError):
            PrimaDispatcher(WrongAgent()).run_next(ledger)
        self.assertEqual(ledger.plan[0].status, "blocked")

    def test_second_reviewer_failure_does_not_repeat_first_reviewer(self):
        class RejectOnce:
            def __init__(self):
                self.seen = []
                self.objectives = {}
                self.rejected = False

            def execute(self, task):
                self.seen.append(task.agent_id)
                self.objectives[task.agent_id] = task.objective
                if task.agent_id == "liege-maximo" and not self.rejected:
                    self.rejected = True
                    return AgentResult(task.step_id, task.agent_id,
                                       ResultStatus.BLOCKED, "L2 rejected")
                return AgentResult(task.step_id, task.agent_id,
                                   ResultStatus.COMPLETED, "passed",
                                   evidence=(f"proof:{task.agent_id}",))

        executor = RejectOnce()
        ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger("demo")
        dispatcher = PrimaDispatcher(executor)
        results = dispatcher.run_until_blocked(ledger)
        self.assertEqual(results[-1].agent_id, "liege-maximo")
        self.assertEqual(ledger.plan[4].completed_agents, ["micronus-prime"])
        ledger.resume_step(5)
        dispatcher.run_next(ledger)
        self.assertEqual(ledger.plan[4].completed_agents,
                         ["micronus-prime", "liege-maximo"])
        self.assertEqual(executor.seen.count("micronus-prime"), 1)
        self.assertIn("L1", executor.objectives["micronus-prime"])
        self.assertIn("L2", executor.objectives["liege-maximo"])


if __name__ == "__main__":
    unittest.main()
