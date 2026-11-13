"""Single-role OpenCode V2 CLI adapter for the first live integration test."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable

from .execution import AgentResult, AgentTask, ResultStatus


class OpenCodeV2Executor:
    def __init__(self, workspace: Path, *, binary: str = "opencode2",
                 timeout_seconds: int = 120,
                 runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self.workspace = workspace
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def execute(self, task: AgentTask) -> AgentResult:
        if task.agent_id != "thirteenth" or task.step_id != 1:
            raise ValueError("This integration adapter currently supports only step 1 / thirteenth")
        if not (self.workspace / "opencode.jsonc").is_file():
            raise FileNotFoundError("OpenCode V2 bundle is missing opencode.jsonc")
        prompt = (
            "你是需求澄清角色。只分析以下任务，不调用工具，不修改文件。"
            "只返回一个 JSON 对象，字段为 status、summary、evidence。"
            "status 只能是 completed 或 blocked；evidence 必须是非空字符串数组。"
            "若关键需求不足以确认，请返回 blocked，并在 summary 中列出缺失项。"
            f"\n用户任务：{task.user_request}\n当前目标：{task.objective}"
        )
        command = [self.binary, "run", "--standalone", "--archived", "--agent",
                   task.agent_id, "--format", "json", prompt]
        try:
            process = self.runner(command, cwd=self.workspace, text=True,
                                  capture_output=True, timeout=self.timeout_seconds,
                                  check=False)
        except subprocess.TimeoutExpired:
            return self._blocked(task, "OpenCode execution timed out")
        except OSError as exc:
            return self._blocked(task, f"OpenCode could not start: {exc}")
        if process.returncode != 0:
            detail = (process.stderr or process.stdout).strip()[-500:]
            return self._blocked(task, f"OpenCode exited with {process.returncode}: {detail}")
        texts = []
        for line in process.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "error":
                return self._blocked(task, "OpenCode emitted an error event")
            if event.get("type") == "text":
                value = event.get("part", {}).get("text")
                if isinstance(value, str):
                    texts.append(value)
        if not texts:
            return self._blocked(task, "OpenCode returned no text event")
        raw = "".join(texts).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._blocked(task, "OpenCode reply was not a JSON object")
        if not isinstance(data, dict) or data.get("status") not in ("completed", "blocked"):
            return self._blocked(task, "OpenCode reply has an invalid status")
        summary = data.get("summary")
        evidence = data.get("evidence")
        if not isinstance(summary, str) or not summary.strip():
            return self._blocked(task, "OpenCode reply has no summary")
        if not isinstance(evidence, list) or not evidence or not all(
                isinstance(item, str) and item.strip() for item in evidence):
            return self._blocked(task, "OpenCode reply has no valid evidence")
        status = ResultStatus(data["status"])
        return AgentResult(task.step_id, task.agent_id, status, summary,
                           evidence=tuple(evidence))

    @staticmethod
    def _blocked(task: AgentTask, reason: str) -> AgentResult:
        return AgentResult(task.step_id, task.agent_id, ResultStatus.BLOCKED, reason)
