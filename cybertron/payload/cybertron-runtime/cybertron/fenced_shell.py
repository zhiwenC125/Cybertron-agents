"""Execute role-approved software commands in a disposable macOS workspace."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .access import hard_denied
from .authority import denied_for_reviewer
from .registry import FENCED_SHELL_COMMANDS
from .scope_guard import PRUNED_DIRS


class ShellRejected(ValueError):
    pass


_SYSTEM_BIN = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")
_SYSTEM_READ = (
    "/usr/bin", "/bin", "/usr/lib", "/usr/share", "/System/Library", "/Library/Developer/CommandLineTools",
    "/Library/Frameworks/Python.framework", "/private/var/db/xcode_select_link", "/private/var/select",
    "/private/etc/localtime", "/private/etc/passwd", "/private/etc/group",
)
_BUILD_DIRS = frozenset({"build", "dist", "target"})
_OUTPUT_LIMIT = 128 * 1024
_EXECUTION_OPTIONS = {
    "--eval", "-E", "-e", "--print", "--script", "-P", "--install", "--workflow",
    "--fix", "--fix-only", "--fix-errors",
}


def allowed_commands(role: str, commands: object) -> list[list[str]]:
    if not isinstance(commands, list) or not 1 <= len(commands) <= 4:
        raise ShellRejected("cy_shell requires one to four argv commands")
    prefixes = FENCED_SHELL_COMMANDS.get(role, ())
    for argv in commands:
        if (not isinstance(argv, list) or not 1 <= len(argv) <= 32
                or any(not isinstance(arg, str) or not arg or len(arg) > 1024
                       or any(ord(char) < 32 or ord(char) == 127 for char in arg) for arg in argv)):
            raise ShellRejected("each command must be an argv array of nonempty arguments")
        if not any(tuple(argv[:len(prefix)]) == prefix for prefix in prefixes):
            raise ShellRejected("command is outside this role's cy_shell allow-list")
        if any(arg.split("=", 1)[0] in _EXECUTION_OPTIONS for arg in argv[1:]):
            raise ShellRejected("cy_shell accepts build and check arguments only")
    return commands


def _copy_inputs(project: Path, workspace: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        parent = Path(directory)
        ignored = set()
        for name in names:
            path = parent / name
            relative = path.relative_to(project).as_posix().casefold()
            basename = name.casefold()
            if (basename in PRUNED_DIRS or parent == project and basename in _BUILD_DIRS or
                    hard_denied(relative) or denied_for_reviewer(relative) or
                    denied_for_reviewer(basename) or basename in {
                        ".cybertron", ".config", ".docker", ".ssh", ".aws", "secrets"
                    }):
                ignored.add(name)
                continue
            mode = path.lstat()
            if not (stat.S_ISDIR(mode.st_mode)
                    or stat.S_ISREG(mode.st_mode) and mode.st_nlink == 1):
                ignored.add(name)
        return ignored

    shutil.copytree(project, workspace, ignore=ignore, symlinks=True)
    if any(path.is_symlink() for path in workspace.rglob("*")):
        raise ShellRejected("project inputs changed while preparing the sandbox")


def _profile(scratch: Path, writable: list[Path]) -> str:
    toolchains = [Path(path) for path in _SYSTEM_READ]
    for prefix in (Path("/opt/homebrew"), Path("/usr/local")):
        toolchains.extend(prefix / name for name in ("bin", "Cellar", "opt", "lib", "include", "share"))
        toolchains.append(prefix / "Library" / "Homebrew")
        toolchains.extend((prefix / "etc").glob("openssl*"))
    toolchains.extend(Path("/Applications").glob("Xcode*.app/Contents/Developer"))
    read_paths = {path.resolve() for path in toolchains if path.exists()} | {scratch}
    # Allow looking up ancestors, without granting reads of their contents.
    parents = {parent for path in read_paths for parent in path.parents}
    quote = lambda value: json.dumps(str(value), ensure_ascii=False)
    read = " ".join(f"(subpath {quote(path)})" for path in sorted(read_paths))
    metadata = " ".join(f"(literal {quote(path)})" for path in sorted(parents))
    write = " ".join(f"(subpath {quote(path)})" for path in writable)
    return (
        "(version 1)\n(deny default)\n(deny network*)\n"
        "(allow process-fork)\n(allow process-exec)\n(allow sysctl-read)\n"
        f'(allow file-read* (literal "/") {read})\n(allow file-read-metadata {metadata})\n'
        f"(allow file-write* {write})\n"
        '(allow file-read* (literal "/dev/null") (literal "/dev/zero")'
        ' (literal "/dev/random") (literal "/dev/urandom"))\n'
        '(allow file-write* (literal "/dev/null"))\n'
    )


def _source_digest(workspace: Path) -> str:
    """Hash copied sources without scanning generated files or following links."""
    entries = {}
    for directory, dirs, files in os.walk(workspace):
        parent = Path(directory)
        if parent == workspace:
            dirs[:] = [name for name in dirs if name not in _BUILD_DIRS]
        for name in dirs + files:
            path = parent / name
            mode = path.lstat().st_mode
            if stat.S_ISREG(mode):
                digest = hashlib.sha256()
                with path.open("rb") as reader:
                    for chunk in iter(lambda: reader.read(65536), b""):
                        digest.update(chunk)
                content = digest.hexdigest()
            else:
                content = os.readlink(path) if stat.S_ISLNK(mode) else None
            entries[path.relative_to(workspace).as_posix()] = (mode, content)
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def _run(argv: list[str], cwd: Path, env: dict[str, str], deadline: float) -> tuple[int, bytes, str]:
    chunks = bytearray()
    status = "completed"
    with subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          start_new_session=True) as process:
        assert process.stdout is not None
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        status = "timeout"
                        break
                    block = os.read(process.stdout.fileno(), 16384)
                    if not block:
                        process.wait(timeout=max(0, deadline - time.monotonic()))
                        break
                    limit = _OUTPUT_LIMIT - len(chunks)
                    chunks.extend(block[:limit])
                    if len(block) > limit:
                        status = "output_limit"
                        break
        except subprocess.TimeoutExpired:
            status = "timeout"
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    code = {"timeout": 124, "output_limit": 125}.get(status, process.returncode)
    return code, bytes(chunks), status


def run_fenced_shell(project: Path, role: str, commands: object, cwd: str = ".",
                     *, timeout_seconds: int = 90) -> dict:
    commands = allowed_commands(role, commands)
    if (not isinstance(cwd, str) or not cwd or "\0" in cwd or "\\" in cwd
            or cwd.startswith(("/", "~")) or ".." in Path(cwd).parts):
        raise ShellRejected("cy_shell working directory must be project-relative")
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise ShellRejected("cy_shell requires the macOS sandbox-exec runner")
    search_path = os.pathsep.join(_SYSTEM_BIN)
    executables = [shutil.which(argv[0], path=search_path) for argv in commands]
    for argv, executable in zip(commands, executables):
        if executable is None:
            raise ShellRejected(f"required cy_shell tool is unavailable: {argv[0]}")
    with tempfile.TemporaryDirectory(prefix="cybertron-role-shell-") as directory:
        scratch = Path(directory).resolve()
        workspace = scratch / "project"
        _copy_inputs(project, workspace)
        working = workspace / cwd
        if not working.is_dir():
            raise ShellRejected("cy_shell working directory is absent from the sandbox")
        temp = scratch / "tmp"
        home = scratch / "home"
        writable = [temp, home] + [workspace / name for name in sorted(_BUILD_DIRS)]
        for path in writable:
            path.mkdir()
        env = {
            "PATH": search_path, "HOME": str(home), "TMPDIR": str(temp), "TMP": str(temp),
            "TEMP": str(temp), "XDG_CACHE_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0", "PYTEST_ADDOPTS": "-o cache_dir=" + str(temp / "pytest"),
            "CARGO_TARGET_DIR": str(workspace / "target"), "LANG": "C",
        }
        developer_dir = Path("/private/var/select/developer_dir").resolve()
        if (developer_dir == Path("/Library/Developer/CommandLineTools")
                or developer_dir in Path("/Applications").glob("Xcode*.app/Contents/Developer")):
            env["DEVELOPER_DIR"] = str(developer_dir)
        input_sha256 = _source_digest(workspace)
        profile = _profile(scratch, writable)
        deadline = time.monotonic() + timeout_seconds
        receipts = []
        for command, executable in zip(commands, executables):
            code, output, outcome = _run(
                ["/usr/bin/sandbox-exec", "-p", profile, executable, *command[1:]], working, env, deadline)
            receipts.append({
                "source": "sandbox", "argv": command, "exit": code, "outcome": outcome,
                "utc": datetime.now(timezone.utc).isoformat(), "sha256": hashlib.sha256(output).hexdigest(),
                "output": output.decode("utf-8", errors="replace"),
            })
            if code != 0:
                break
        clean = input_sha256 == _source_digest(workspace)
        status = "pass" if clean and receipts[-1]["exit"] == 0 else "fail"
        return {"status": status, "cwd": cwd, "inputs_sha256": input_sha256,
                "source_intact": clean, "receipts": receipts}
