"""Generate and validate an isolated OpenCode V2 configuration bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .exporters import compile_opencode_v2_assets
from .registry import THIRTEEN_PRIMES_REGISTRY


def validate_bundle(root: Path) -> list[str]:
    errors: list[str] = []
    config_path = root / "opencode.jsonc"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Cannot read OpenCode config: {exc}"]
    agents = config.get("agents")
    if not isinstance(agents, dict):
        return ["agents must be an object"]
    expected = {prime.agent_id for prime in THIRTEEN_PRIMES_REGISTRY}
    if set(agents) != expected:
        errors.append(f"Agent IDs differ from registry: {sorted(set(agents) ^ expected)}")
    if config.get("default_agent") != "prima":
        errors.append("default_agent must be prima")
    for agent_id in expected:
        entry = agents.get(agent_id)
        if not isinstance(entry, dict):
            continue
        if entry.get("mode") not in ("primary", "subagent", "all"):
            errors.append(f"{agent_id}: invalid mode")
        rules = entry.get("permissions")
        if not isinstance(rules, list) or not rules:
            errors.append(f"{agent_id}: missing permissions")
        elif rules[0] != {"action": "*", "resource": "*", "effect": "deny"}:
            errors.append(f"{agent_id}: first permission must deny all")
        agent_file = root / ".opencode" / "agents" / f"{agent_id}.md"
        try:
            content = agent_file.read_text(encoding="utf-8")
            if not content.startswith("---\n") or "\n---\n" not in content[4:]:
                errors.append(f"{agent_id}: invalid Markdown frontmatter")
        except OSError:
            errors.append(f"{agent_id}: missing Markdown agent file")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an OpenCode V2 configuration bundle")
    parser.add_argument("--output", type=Path, default=Path("opencode_v2_smoke"))
    parser.add_argument("--include-feishu", action="store_true",
                        help="Enable Feishu MCP; requires valid credentials and npx")
    args = parser.parse_args()
    files = compile_opencode_v2_assets(args.output, include_feishu=args.include_feishu)
    launcher = args.output / "run_first_agent.py"
    package_root = Path(__file__).resolve().parent.parent
    launcher.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        f"sys.path.insert(0, {str(package_root)!r})\n"
        "from cybertron.opencode_run import main\n"
        "main()\n",
        encoding="utf-8",
    )
    errors = validate_bundle(args.output)
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    print(f"Validated {len(files)} OpenCode V2 files in {args.output.resolve()}")
    print("Next: run `opencode2 debug config` from that directory to check host loading.")
    print("Then run `python3 run_first_agent.py <request>` there for the live role test.")


if __name__ == "__main__":
    main()
