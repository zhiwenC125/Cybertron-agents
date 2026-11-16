"""Fixed, sandboxed check profiles for v6 projects.

Commands are selected by the kernel, never supplied by a model.  Checks run
against a disposable project copy so build products cannot change the source.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class CheckRejected(ValueError):
    pass


@dataclass(frozen=True)
class CheckReceipt:
    source: str
    command: str
    exit: int
    utc: str
    sha256: str
    output: str

    def to_dict(self) -> dict:
        return vars(self).copy()


def detect_profile(project: Path) -> str:
    if (project / "CMakeLists.txt").is_file():
        if any(project.rglob("*.ioc")) or any(project.rglob("*toolchain*.cmake")):
            return "cmake-arm"
        return "cmake-c"
    if (project / "pyproject.toml").is_file() or (project / "setup.py").is_file():
        return "python"
    if (project / "package.json").is_file():
        return "node"
    if (project / "sim.resc").is_file() and (project / "sim.expect").is_file():
        return "renode"
    raise CheckRejected("no supported toolchain profile detected")


def _sandbox_profile(scratch: Path) -> str:
    # CMake and Apple toolchain need OS services and the four inert /dev files.
    # Renode keeps its own config/history under the macOS Application Support
    # directory; that narrow tool-state write is allowed so the simulator can
    # start while project and arbitrary home writes remain denied.
    renode_support = Path.home() / "Library" / "Application Support" / "renode"
    # All other device reads, network access, and writes outside scratch are
    # denied.  /dev/null is also needed as a write sink by toolchain scripts.
    return (
        "(version 1)\n(allow default)\n(deny network*)\n"
        "(deny file-write*)\n"
        f'(allow file-write* (subpath "{scratch}"))\n'
        f'(allow file-write* (subpath "{renode_support}"))\n'
        '(allow file-write* (literal "/dev/null"))\n'
        '(deny file-read* (subpath "/dev"))\n'
        '(allow file-read* (literal "/dev/null"))\n'
        '(allow file-read* (literal "/dev/zero"))\n'
        '(allow file-read* (literal "/dev/random"))\n'
        '(allow file-read* (literal "/dev/urandom"))\n'
    )


def _copy_project(project: Path, destination: Path, *, preserve_build: bool = False) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        blocked = {".git", "node_modules", ".venv", "__pycache__"}
        if not preserve_build:
            blocked.add("build")
        if Path(directory) == project:
            blocked.add(".cybertron")
        return blocked.intersection(names)

    shutil.copytree(project, destination, symlinks=True, ignore=ignore)
    for path in destination.rglob("*"):
        if path.is_symlink():
            raise CheckRejected(f"project contains a symlink: {path.relative_to(destination)}")


def _binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    if name == "clang-tidy":
        for prefix in ("/opt/homebrew", "/usr/local"):
            homebrew = Path(prefix) / "opt" / "llvm" / "bin" / "clang-tidy"
            if homebrew.is_file():
                return str(homebrew)
    raise CheckRejected(f"required tool is unavailable: {name}")


def _run(argv: list[str], cwd: Path, scratch: Path) -> CheckReceipt:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(scratch),
           "TMPDIR": str(scratch), "TMP": str(scratch), "TEMP": str(scratch),
           "XDG_CACHE_HOME": str(scratch), "PYTHONHASHSEED": "0", "LANG": "C"}
    command = " ".join(argv)
    try:
        result = subprocess.run([_binary("sandbox-exec"), "-p", _sandbox_profile(scratch), *argv],
                                cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=120, check=False)
        code, output = result.returncode, result.stdout
    except subprocess.TimeoutExpired as exc:
        code, output = 124, str(exc.stdout or "") + "\ncheck timed out"
    return CheckReceipt("sandbox", command, code, datetime.now(timezone.utc).isoformat(),
                        hashlib.sha256(output.encode()).hexdigest(), output)


def run_check(project: Path, target: str) -> dict:
    project = Path(project).resolve()
    if not project.is_dir() or target not in {"lint", "build", "test", "sim"}:
        raise CheckRejected("invalid project or check target")
    if target == "sim":
        if not (project / "sim.resc").is_file() or not (project / "sim.expect").is_file():
            raise CheckRejected("sim target requires sim.resc and sim.expect")
        profile = "renode"
    else:
        profile = detect_profile(project)
    if profile in {"cmake-c", "cmake-arm"} and target == "test":
        raise CheckRejected("CMake test target requires a declared test framework")
    with tempfile.TemporaryDirectory(prefix="cybertron-check-") as temporary:
        scratch = Path(temporary).resolve()
        copy = scratch / "project"
        _copy_project(project, copy, preserve_build=(target == "sim"))
        receipts: list[CheckReceipt] = []
        if profile == "renode":
            if target != "sim":
                raise CheckRejected(f"{profile} profile does not provide {target}")
            expect = (copy / "sim.expect").read_text().strip()
            if not expect:
                raise CheckRejected("sim.expect is empty")
            receipts.append(_run([_binary("renode"), "--config",
                                  str(scratch / "renode-config.json"),
                                  "--console", "--disable-gui", "--plain", "sim.resc"],
                                 copy, scratch))
            passed = receipts[-1].exit == 0 and expect in receipts[-1].output
            return {"profile": profile, "target": target,
                    "status": "pass" if passed else "fail",
                    "receipts": [item.to_dict() for item in receipts]}
        if profile in {"cmake-c", "cmake-arm"}:
            if profile == "cmake-arm":
                _binary("arm-none-eabi-gcc")
            cmake = _binary("cmake")
            receipts.append(_run([cmake, "-S", ".", "-B", "build",
                                  "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"], copy, scratch))
            if receipts[-1].exit == 0:
                database = json.loads((copy / "build" / "compile_commands.json").read_text())
                if profile == "cmake-arm" and not any(
                    "arm-none-eabi" in entry.get("command", "") for entry in database
                ):
                    raise CheckRejected("ARM CMake profile did not select an ARM cross compiler")
                if target == "lint":
                    sources = sorted({str(Path(entry["file"]).resolve().relative_to(copy))
                                      for entry in database if Path(entry["file"]).suffix == ".c"})
                    if not sources:
                        raise CheckRejected("CMake compile database contains no C sources")
                    receipts.append(_run([_binary("clang-tidy"), "-p", "build",
                                          "--checks=clang-analyzer-*,bugprone-*",
                                          "--warnings-as-errors=*", *sources], copy, scratch))
                else:
                    receipts.append(_run([cmake, "--build", "build"], copy, scratch))
        elif profile == "python":
            if target != "test":
                raise CheckRejected(f"{profile} profile does not provide {target}")
            receipts.append(_run([_binary("python3"), "-m", "unittest", "discover", "-s", "tests"], copy, scratch))
        else:
            if target != "test":
                raise CheckRejected(f"{profile} profile does not provide {target}")
            receipts.append(_run([_binary("node"), "--test"], copy, scratch))
        passed = bool(receipts) and all(item.exit == 0 for item in receipts)
        if target == "test" and profile == "python":
            count = re.search(r"Ran (\d+) tests?", receipts[-1].output)
            passed = passed and count is not None and int(count.group(1)) > 0
        if target == "test" and profile == "node":
            count = re.search(r"(?:^|\n)(?:# )?tests? (\d+)", receipts[-1].output)
            passed = passed and count is not None and int(count.group(1)) > 0
        return {"profile": profile, "target": target,
                "status": "pass" if passed else "fail",
                "receipts": [item.to_dict() for item in receipts]}
