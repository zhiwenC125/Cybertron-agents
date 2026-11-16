"""Create an isolated OpenCode project for the M0c manual host gate."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cybertron.exporters import compile_opencode_v2_assets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    destination = args.destination.absolute()
    if destination.exists():
        parser.error("destination must not exist")
    source = Path(__file__).resolve().parent.parent
    destination.mkdir(parents=True)
    compile_opencode_v2_assets(destination, disable_legacy_cybertron=True)
    runtime = destination / "cybertron"
    runtime.mkdir()
    for file in (source / "cybertron").glob("*.py"):
        shutil.copy2(file, runtime / file.name)
    plugin_dir = destination / ".opencode" / "plugins"
    plugin_dir.mkdir(parents=True)
    for name in ("cybertron.js", "hook_logic.mjs"):
        shutil.copy2(source / "cybertron" / "v6_plugin" / name, plugin_dir / name)
    (destination / "AGENTS.md").write_text(
        "# M0c host gate fixture\n\nWrite only `notes.md` in this project root.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(destination)], check=True)
    print(destination)


if __name__ == "__main__":
    main()
