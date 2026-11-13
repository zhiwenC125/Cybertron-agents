import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from cybertron import PrimaDispatcher, PrimaPlanOrchestrator, ResultStatus
from cybertron.opencode_executor import OpenCodeV2Executor


class OpenCodeExecutorTests(unittest.TestCase):
    def test_valid_json_event_completes_first_step(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "opencode.jsonc").write_text("{}")
            event = {"type": "text", "part": {"text": json.dumps({
                "status": "completed", "summary": "需求明确", "evidence": ["用户给出目标芯片"],
            }, ensure_ascii=False)}}

            def runner(command, **kwargs):
                self.assertEqual(command[command.index("--agent") + 1], "thirteenth")
                self.assertIn("--standalone", command)
                return subprocess.CompletedProcess(command, 0, json.dumps(event), "")

            ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger("STM32F4")
            result = PrimaDispatcher(OpenCodeV2Executor(root, runner=runner)).run_next(ledger)
            self.assertEqual(result.status, ResultStatus.COMPLETED)
            self.assertEqual(ledger.plan[0].evidence, ["用户给出目标芯片"])

    def test_invalid_reply_blocks_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "opencode.jsonc").write_text("{}")

            def runner(command, **kwargs):
                return subprocess.CompletedProcess(command, 0, '{"type":"text","part":{"text":"hello"}}', "")

            ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger("demo")
            result = PrimaDispatcher(OpenCodeV2Executor(root, runner=runner)).run_next(ledger)
            self.assertEqual(result.status, ResultStatus.BLOCKED)
            self.assertEqual(ledger.plan[0].status, "blocked")


if __name__ == "__main__":
    unittest.main()
