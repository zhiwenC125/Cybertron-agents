"""OpenCode V2 CLI adapter for explicitly allowed read-only roles."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable

from .execution import AgentResult, AgentTask, QualityEvidence, QualityKind, ResultStatus


class OpenCodeV2Executor:
    def __init__(self, workspace: Path, *, binary: str = "opencode2",
                 timeout_seconds: int = 120,
                 model_override: str | None = None,
                 runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self.workspace = workspace
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.model_override = model_override
        self.runner = runner

    def execute(self, task: AgentTask) -> AgentResult:
        allowed_tasks = {(1, "thirteenth"), (3, "onyx-prime"),
                         (3, "vector-prime"), (5, "liege-maximo")}
        if (task.step_id, task.agent_id) not in allowed_tasks:
            raise ValueError("This adapter currently supports only selected read-only roles")
        if not (self.workspace / "opencode.jsonc").is_file():
            raise FileNotFoundError("OpenCode V2 bundle is missing opencode.jsonc")
        if task.step_id == 5 and not (self.workspace / "cybertron" / "registry.py").is_file():
            return self._blocked(task, "L2 workspace must be the project root containing cybertron/registry.py")
        is_l2 = task.agent_id == "liege-maximo"
        prompt = (
            "你正在执行一个只读研发任务。可以使用该角色已授权的只读工具，但不要修改文件。"
            "只返回一个 JSON 对象，字段为 status、summary、evidence。"
            "status 只能是 completed、blocked 或 rejected；evidence 必须是非空字符串数组。"
            "若无法完成目标，请返回 blocked，并在 summary 中说明原因。"
        )
        if is_l2:
            prompt += ("若 L2 审查通过，另返回 quality_evidence 数组，其中对象必须含"
                       "kind=review_l2、passed=true、source=具体审查依据；发现问题时返回 rejected。")
            prompt += ("当前工作目录必须是项目根目录。请优先读取 opencode.jsonc、"
                       "cybertron/registry.py、cybertron/exporters.py 和 .opencode/agents/。"
                       "AGENTS.md 如不存在，记录该事实并继续审查。只使用 read 和 glob。")
        prompt += (f"\n用户任务：{task.user_request}\n当前目标：{task.objective}"
                   f"\n输入约定：{task.input_artifact}\n已有证据：{list(task.prior_evidence)}")
        command = [self.binary, "run", "--standalone", "--archived", "--agent",
                   task.agent_id, "--format", "json"]
        if self.model_override:
            command.extend(["--model", self.model_override])
        command.append(prompt)
        try:
            process = self.runner(command, cwd=self.workspace, text=True,
                                  capture_output=True, timeout=self.timeout_seconds,
                                  check=False)
        except subprocess.TimeoutExpired:
            return self._blocked(task, "OpenCode execution timed out")
        except OSError as exc:
            return self._blocked(task, f"OpenCode could not start: {exc}")
        if process.returncode != 0:
            detail = self._error_detail(process.stderr or process.stdout)
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
        data = self._extract_json_object(raw)
        if data is None:
            preview = " ".join(raw.split())[:240]
            return self._blocked(task, f"OpenCode reply was not a JSON object; preview: {preview}")
        allowed_statuses = ("completed", "blocked", "rejected") if is_l2 else ("completed", "blocked")
        if not isinstance(data, dict) or data.get("status") not in allowed_statuses:
            return self._blocked(task, "OpenCode reply has an invalid status")
        summary = data.get("summary")
        evidence = data.get("evidence")
        if not isinstance(summary, str) or not summary.strip():
            return self._blocked(task, "OpenCode reply has no summary")
        if not isinstance(evidence, list) or not evidence or not all(
                isinstance(item, str) and item.strip() for item in evidence):
            return self._blocked(task, "OpenCode reply has no valid evidence")
        status = ResultStatus(data["status"])
        quality_evidence = ()
        if is_l2 and status == ResultStatus.COMPLETED:
            items = data.get("quality_evidence")
            if not isinstance(items, list) or not items:
                return self._blocked(task, "L2 reply has no quality_evidence")
            parsed = []
            for item in items:
                if not isinstance(item, dict) or item.get("kind") != "review_l2" \
                        or item.get("passed") is not True \
                        or not isinstance(item.get("source"), str) or not item["source"].strip():
                    return self._blocked(task, "L2 reply has invalid quality_evidence")
                parsed.append(QualityEvidence(QualityKind.REVIEW_L2, True, item["source"]))
            quality_evidence = tuple(parsed)
        return AgentResult(task.step_id, task.agent_id, status, summary,
                           evidence=tuple(evidence), quality_evidence=quality_evidence)

    @staticmethod
    def _blocked(task: AgentTask, reason: str) -> AgentResult:
        return AgentResult(task.step_id, task.agent_id, ResultStatus.BLOCKED, reason)

    @staticmethod
    def _error_detail(output: str) -> str:
        """Prefer the provider message over a truncated raw CLI event."""
        for line in reversed(output.splitlines()):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            error = event.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return error["message"][:500]
        return output.strip()[-500:]

    @staticmethod
    def _extract_json_object(raw: str) -> dict | None:
        """Accept a JSON object even when a model wraps it in prose or a fence."""
        decoder = json.JSONDecoder()
        for index, char in enumerate(raw):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(raw[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None
