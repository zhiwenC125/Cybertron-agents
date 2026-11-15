import unittest

from cybertron import AgentTask, QualityKind, ResultStatus
from cybertron.isolated_runner import AlchemistTestExecutor, SandboxReport


class IsolatedRunnerTests(unittest.TestCase):
    def test_successful_report_becomes_typed_qa_evidence(self):
        class FakeRunner:
            def run(self, command):
                return SandboxReport(0, "", "Ran 1 test in 0.001s\nOK", False, "a" * 64)

        task = AgentTask(6, "alchemist", "test", "run", "source", "report")
        result = AlchemistTestExecutor(FakeRunner(), "python3").execute(task)
        self.assertEqual(result.status, ResultStatus.COMPLETED)
        self.assertEqual(result.quality_evidence[0].kind, QualityKind.TEST)
        self.assertTrue(result.quality_evidence[0].source.startswith("sandbox://sha256/"))

    def test_failed_report_cannot_claim_pass(self):
        class FakeRunner:
            def run(self, command):
                return SandboxReport(1, "", "one test failed", False, "b" * 64)

        task = AgentTask(6, "alchemist", "test", "run", "source", "report")
        result = AlchemistTestExecutor(FakeRunner(), "python3").execute(task)
        self.assertEqual(result.status, ResultStatus.BLOCKED)
        self.assertEqual(result.quality_evidence, ())

    def test_zero_tests_cannot_claim_pass(self):
        class FakeRunner:
            def run(self, command):
                return SandboxReport(0, "", "Ran 0 tests in 0.000s\nOK", False, "c" * 64)

        task = AgentTask(6, "alchemist", "test", "run", "source", "report")
        result = AlchemistTestExecutor(FakeRunner(), "python3").execute(task)
        self.assertEqual(result.status, ResultStatus.BLOCKED)
