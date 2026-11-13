import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from cybertron import AgentTask, PrimaDispatcher, PrimaPlanOrchestrator, ResultStatus
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

    def test_read_only_discovery_roles_are_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "opencode.jsonc").write_text("{}")
            seen = []

            def runner(command, **kwargs):
                seen.append(command[command.index("--agent") + 1])
                data = {"status": "completed", "summary": "found", "evidence": ["config:1"]}
                event = {"type": "text", "part": {"text": json.dumps(data)}}
                return subprocess.CompletedProcess(command, 0, json.dumps(event), "")

            executor = OpenCodeV2Executor(root, runner=runner)
            for agent in ("onyx-prime", "vector-prime"):
                task = AgentTask(3, agent, "inspect", "read only", "config", "report")
                self.assertEqual(executor.execute(task).status, ResultStatus.COMPLETED)
            self.assertEqual(seen, ["onyx-prime", "vector-prime"])
            with self.assertRaises(ValueError):
                executor.execute(AgentTask(3, "quintus-prime", "inspect", "build", "config", "files"))

    def test_model_override_is_passed_to_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "opencode.jsonc").write_text("{}")

            def runner(command, **kwargs):
                self.assertEqual(command[command.index("--model") + 1], "provider/usable-model")
                data = {"type": "text", "part": {"text": json.dumps({
                    "status": "completed", "summary": "done", "evidence": ["git log"],
                })}}
                return subprocess.CompletedProcess(command, 0, json.dumps(data), "")

            task = AgentTask(3, "vector-prime", "inspect", "git", "repo", "report")
            result = OpenCodeV2Executor(root, model_override="provider/usable-model",
                                        runner=runner).execute(task)
            self.assertEqual(result.status, ResultStatus.COMPLETED)

    def test_provider_limit_is_reported_without_raw_event_dump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "opencode.jsonc").write_text("{}")
            event = {"type": "error", "error": {
                "type": "provider.free-limit", "message": "Free usage limit reached",
            }}

            def runner(command, **kwargs):
                return subprocess.CompletedProcess(command, 1, json.dumps(event), "")

            executor = OpenCodeV2Executor(root, runner=runner)
            task = AgentTask(3, "vector-prime", "inspect", "git history", "repo", "report")
            result = executor.execute(task)
            self.assertEqual(result.status, ResultStatus.BLOCKED)
            self.assertIn("Free usage limit reached", result.summary)
            self.assertNotIn("sessionID", result.summary)

    def test_json_wrapped_in_prose_is_accepted(self):
        raw = '结果如下：\n```json\n{"status":"completed","summary":"found","evidence":["git log"]}\n```'
        data = OpenCodeV2Executor._extract_json_object(raw)
        self.assertEqual(data["status"], "completed")

    def test_plain_text_stays_blocked_with_short_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "opencode.jsonc").write_text("{}")

            def runner(command, **kwargs):
                event = {"type": "text", "part": {"text": "当前分支为 main。"}}
                return subprocess.CompletedProcess(command, 0, json.dumps(event), "")

            task = AgentTask(3, "vector-prime", "inspect", "git", "repo", "report")
            result = OpenCodeV2Executor(root, runner=runner).execute(task)
            self.assertEqual(result.status, ResultStatus.BLOCKED)
            self.assertIn("当前分支为 main", result.summary)

    def test_l2_requires_typed_passing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "opencode.jsonc").write_text("{}")
            task = AgentTask(5, "liege-maximo", "review", "audit", "config", "verdict")

            def runner(command, **kwargs):
                answer = {"status": "completed", "summary": "L2 passed",
                          "evidence": ["permissions reviewed"],
                          "quality_evidence": [{"kind": "review_l2", "passed": True,
                                                "source": "opencode.jsonc permissions"}]}
                event = {"type": "text", "part": {"text": json.dumps(answer)}}
                return subprocess.CompletedProcess(command, 0, json.dumps(event), "")

            result = OpenCodeV2Executor(root, runner=runner).execute(task)
            self.assertEqual(result.status, ResultStatus.BLOCKED)
            self.assertIn("project root", result.summary)
            source = root / "cybertron"
            source.mkdir()
            (source / "registry.py").write_text("# test")
            result = OpenCodeV2Executor(root, runner=runner).execute(task)
            self.assertEqual(result.status, ResultStatus.COMPLETED)
            self.assertEqual(result.quality_evidence[0].kind.value, "review_l2")


if __name__ == "__main__":
    unittest.main()
