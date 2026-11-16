"""Verify both release packages carry the same 13 agents and command."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from zipfile import ZipFile


def main() -> None:
    npm_manifest = json.loads(Path(sys.argv[1]).read_text())[0]
    npm_files = {item["path"] for item in npm_manifest["files"]}
    wheel = next(Path(sys.argv[2]).glob("cybertron_agents-*.whl"))
    with ZipFile(wheel) as archive:
        wheel_files = set(archive.namelist())
        npm_agents = {name.removeprefix("payload/agents/") for name in npm_files
                      if name.startswith("payload/agents/") and name.endswith(".md")}
        wheel_agents = {name.removeprefix("cybertron/payload/agents/") for name in wheel_files
                        if name.startswith("cybertron/payload/agents/") and name.endswith(".md")}
        assert len(npm_agents) == 13 and npm_agents == wheel_agents
        command = "cybertron.md"
        assert f"payload/commands/{command}" in npm_files
        assert f"cybertron/payload/commands/{command}" in wheel_files
        assert archive.read(f"cybertron/payload/commands/{command}") == (
            Path(".opencode/commands") / command).read_bytes()
        for agent in npm_agents:
            assert archive.read(f"cybertron/payload/agents/{agent}") == (
                Path(".opencode/agents") / agent).read_bytes()
        plugin = "plugins/cybertron.js"
        assert f"payload/{plugin}" in npm_files
        assert f"cybertron/payload/{plugin}" in wheel_files
        assert archive.read(f"cybertron/payload/{plugin}") == Path(".opencode/plugins/cybertron.js").read_bytes()
        dsh_files = ("package.json", "cordis.patch.yml", "index.js", "bridge.js",
                     "icon.svg", "locale/en.json", "locale/zh.json", "docs/DETAIL.md")
        for rel in dsh_files:
            npm_path = f"payload/dsh-adapter/{rel}"
            wheel_path = f"cybertron/payload/dsh-adapter/{rel}"
            assert npm_path in npm_files, npm_path
            assert wheel_path in wheel_files, wheel_path
            assert archive.read(wheel_path) == (Path("cybertron/dsh_adapter") / rel).read_bytes()

        runtime = {path.name for path in Path("cybertron").glob("*.py")}
        for filename in runtime:
            npm_path = f"payload/cybertron-runtime/cybertron/{filename}"
            wheel_path = f"cybertron/payload/cybertron-runtime/cybertron/{filename}"
            assert npm_path in npm_files and wheel_path in wheel_files
            assert archive.read(wheel_path) == (Path("cybertron") / filename).read_bytes()
    print("npm and Python packages contain the same agents, command, plugin and runtime")


if __name__ == "__main__":
    main()
