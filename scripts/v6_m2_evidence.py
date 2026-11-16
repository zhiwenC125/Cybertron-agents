"""Record direct M2 host-bridge checks against a disposable C project."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STAGES = ROOT / "docs" / "stages"


def capture(command: list[str], *, input_text: str | None = None) -> dict:
    result = subprocess.run(command, cwd=ROOT, input=input_text, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            check=False, timeout=180)
    output = result.stdout
    return {"cmd": " ".join(command), "cwd": str(ROOT), "exit": result.returncode,
            "utc": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(output.encode()).hexdigest(),
            "source": "tool", "output": output}


def main() -> None:
    records = []
    with tempfile.TemporaryDirectory(prefix="cybertron-v6-m2-c-") as directory:
        project = Path(directory)
        (project / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20)\nproject(hello C)\n"
            "add_executable(hello main.c)\n", encoding="utf-8")
        (project / "main.c").write_text(
            '#include <stdio.h>\nint main(void){puts("Hello, World!");return 0;}\n',
            encoding="utf-8")
        for target in ("lint", "build"):
            record = capture([sys.executable, "-m", "cybertron.host_v6_cli", "check",
                              "--project", str(project)],
                             input_text=json.dumps({"target": target}))
            record["target"] = target
            record["stdin_json"] = {"target": target}
            path = STAGES / f"v6-m2-{target}.log"
            path.write_text(record.pop("output"), encoding="utf-8")
            record["output_path"] = str(path.relative_to(ROOT))
            records.append(record)
    (STAGES / "v6-m2-check-receipts.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for record in records:
        result = json.loads((ROOT / record["output_path"]).read_text())
        print(record["target"], record["exit"], result["status"],
              [(item["exit"], item["sha256"]) for item in result["receipts"]])


if __name__ == "__main__":
    main()
