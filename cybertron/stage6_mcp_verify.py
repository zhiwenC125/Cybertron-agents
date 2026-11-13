"""Probe OpenCode V2's permission engine with the optional Feishu MCP rules.

This is a local host-policy check. It does not connect to the MCP server,
call Feishu, or invoke a model.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from .exporters import compile_opencode_v2_assets
from .opencode_v2 import validate_bundle
from .registry import THIRTEEN_PRIMES_REGISTRY


READ_ACTIONS = (
    "feishu_wiki_wiki_v2_space_getNode",
    "feishu_wiki_docx_v1_document_rawContent",
)
WRITE_ACTION = "feishu_wiki_docx_v1_document_blockChildren_create"


def _command(root: Path, *args: str) -> object:
    completed = subprocess.run(
        ["opencode2", *args], cwd=root, capture_output=True, text=True, timeout=30,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"OpenCode command failed with exit code {completed.returncode}")
    if not completed.stdout.strip():
        return None
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("OpenCode returned invalid JSON") from None


def _api(root: Path, method: str, path: str, payload: dict | None = None) -> dict:
    args = ["api", method, path]
    if payload is not None:
        args += ["--data", json.dumps(payload)]
    result = _command(root, *args, "--standalone")
    if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
        raise RuntimeError("OpenCode API returned no data object")
    return result["data"]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cybertron-stage6-mcp-") as directory:
        root = Path(directory)
        compile_opencode_v2_assets(root, include_feishu=True)
        errors = validate_bundle(root)
        if errors:
            raise RuntimeError("Exported OpenCode bundle failed validation")
        config = json.loads((root / "opencode.jsonc").read_text(encoding="utf-8"))
        server = config["mcp"]["servers"]["feishu_wiki"]
        if server.get("codemode") is not False:
            raise RuntimeError("Feishu MCP tools must be native tools for these agent rules")

        # debug agents loads the exported JSON and Markdown through OpenCode itself.
        loaded = _command(root, "debug", "agents")
        if not isinstance(loaded, list):
            raise RuntimeError("OpenCode did not return an agent list")
        agents = {item["id"]: item for item in loaded if isinstance(item, dict) and "id" in item}
        expected_agents = {spec.agent_id for spec in THIRTEEN_PRIMES_REGISTRY}
        if not expected_agents.issubset(agents):
            raise RuntimeError("OpenCode did not load every Cybertron agent")

        results = []
        for agent_id in sorted(expected_agents):
            # Explicit session rules make the permission API exercise the same
            # merged rules reported by `debug agents`, without a model turn.
            session = _api(root, "POST", "/api/session", {
                "title": "Cybertron stage 6 local MCP permission probe",
                "agent": agent_id,
                "location": {"directory": str(root)},
                "permissions": agents[agent_id]["permissions"],
            })
            session_id = session["id"]
            try:
                actions = (*READ_ACTIONS, WRITE_ACTION) if agent_id == "alpha-trion" else READ_ACTIONS
                for action in actions:
                    reply = _api(root, "POST", f"/api/session/{session_id}/permission", {
                        "agent": agent_id, "action": action, "resources": ["*"],
                    })
                    actual = reply.get("effect")
                    expected = "allow" if agent_id == "alpha-trion" and action in READ_ACTIONS else "deny"
                    results.append({"agent": agent_id, "action": action,
                                    "expected": expected, "actual": actual,
                                    "passed": actual == expected})
            finally:
                _command(root, "api", "DELETE", f"/api/session/{session_id}", "--standalone")

    report = {
        "check": "OpenCode V2 host permission evaluation of exported Feishu MCP actions",
        "model_called": False,
        "mcp_or_feishu_called": False,
        "cases": len(results),
        "passed": sum(item["passed"] for item in results),
        "failed": [item for item in results if not item["passed"]],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
