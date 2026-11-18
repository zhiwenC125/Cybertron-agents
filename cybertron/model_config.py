"""Local, credential-free model fleet profiles for installed OpenCode agents."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .registry import THIRTEEN_PRIMES_REGISTRY


AGENTS = tuple(prime.agent_id for prime in THIRTEEN_PRIMES_REGISTRY)
DEFAULTS = {prime.agent_id: prime.model for prime in THIRTEEN_PRIMES_REGISTRY}
HIGH = {"prima", "solus-prime", "liege-maximo", "megatronus"}
LOW = {"onyx-prime", "vector-prime"}
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:/-]*(?:#[A-Za-z0-9._-]+)?$")
MODEL_LINE = re.compile(r"(?m)^model: [^\n]+$")


class ModelConfigError(ValueError):
    pass


def profile_path(project: Path, global_install: bool = False) -> Path:
    if global_install:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        return config_home / "cybertron" / "models.json"
    return project.resolve() / ".cybertron" / "models.json"


def effective_profile_path(project: Path) -> Path | None:
    local = profile_path(project)
    global_ = profile_path(project, True)
    return local if local.is_file() else global_ if global_.is_file() else None


def validate_profile(data: object) -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ModelConfigError("模型编队配置格式或版本无效")
    models = data.get("agents")
    if not isinstance(models, dict) or set(models) != set(AGENTS):
        raise ModelConfigError("模型编队必须包含全部十三个角色")
    for role, model in models.items():
        if not isinstance(model, str) or not MODEL_RE.fullmatch(model):
            raise ModelConfigError(f"{role} 的模型 ID 无效；应为 provider/model")
    allowed = data.get("allowed_providers")
    if not isinstance(allowed, list) or not allowed or any(
            not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", item)
            for item in allowed):
        raise ModelConfigError("必须指定允许的供应商")
    if any(model.split("/", 1)[0] not in allowed for model in models.values()):
        raise ModelConfigError("角色模型超出了允许的供应商范围")
    tiers = data.get("tiers", {})
    if not isinstance(tiers, dict) or any(
            key not in ("high", "middle", "low") or not isinstance(value, str) or
            not MODEL_RE.fullmatch(value) for key, value in tiers.items()):
        raise ModelConfigError("三档模型配置无效")
    return data


def load_profile(path: Path | None) -> dict | None:
    if path is None or not path.is_file():
        return None
    if path.is_symlink():
        raise ModelConfigError("拒绝符号链接模型配置")
    try:
        return validate_profile(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelConfigError("无法安全读取模型编队配置") from exc


def effective_profile(project: Path) -> dict | None:
    return load_profile(effective_profile_path(project))


def profile_digest(project: Path) -> str | None:
    path = effective_profile_path(project)
    load_profile(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path else None


def model_for(project: Path, agent_id: str) -> str | None:
    profile = effective_profile(project)
    return profile["agents"][agent_id] if profile else None


def make_profile(models: dict[str, str], tiers: dict[str, str] | None = None) -> dict:
    data = {"schema_version": 1, "agents": dict(models), "tiers": tiers or {},
            "allowed_providers": sorted({model.split("/", 1)[0] for model in models.values()})}
    return validate_profile(data)


def tier_mapping(high: str, middle: str, low: str) -> dict[str, str]:
    return {agent: high if agent in HIGH else low if agent in LOW else middle for agent in AGENTS}


def available_models(project: Path, binary: str = "opencode2") -> set[str]:
    try:
        result = subprocess.run([binary, "models"], cwd=project, text=True,
                                capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ModelConfigError("无法读取 OpenCode 模型目录；请先检查 OpenCode 安装和连接") from exc
    if result.returncode:
        raise ModelConfigError("OpenCode 模型目录查询失败；请运行 opencode2 models")
    return {line.strip() for line in result.stdout.splitlines() if MODEL_RE.fullmatch(line.strip())}


def missing_models(profile: dict, available: set[str]) -> set[str]:
    return set(profile["agents"].values()) - available


def _replace_model(raw: str, model: str) -> str:
    if not raw.startswith("---\n") or not MODEL_LINE.search(raw):
        raise ModelConfigError("角色文件格式无效，无法安全修改 model 字段")
    return MODEL_LINE.sub("model: " + model, raw, count=1)


def _command_agent(raw: str) -> str:
    match = re.search(r"(?m)^agent: ([a-z][a-z0-9-]*)$", raw)
    if not match:
        raise ModelConfigError("/cybertron 命令缺少有效的 agent 字段")
    return match.group(1)


def _render_command(raw: str, model: str, agent_id: str) -> str:
    if not raw.startswith("---\n") or f"\nagent: {agent_id}\n" not in raw:
        raise ModelConfigError("/cybertron 命令格式无效")
    if MODEL_LINE.search(raw):
        return _replace_model(raw, model)
    return raw.replace(f"\nagent: {agent_id}\n", f"\nagent: {agent_id}\nmodel: {model}\n", 1)


def _write_atomic(path: Path, content: bytes) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ModelConfigError(f"拒绝符号链接目标: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".cybertron-model-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _next_backup(path: Path) -> Path:
    index = 1
    while path.with_name(f"{path.name}.bak.{index}").exists():
        index += 1
    return path.with_name(f"{path.name}.bak.{index}")


def apply_to_install(base: Path, profile: dict) -> None:
    validate_profile(profile)
    updates = []
    for agent in AGENTS:
        target = base / "agents" / f"{agent}.md"
        if not target.is_file() or target.is_symlink():
            raise ModelConfigError(f"缺少已安装角色: {agent}")
        before = target.read_bytes()
        after = _replace_model(before.decode("utf-8"), profile["agents"][agent]).encode()
        updates.append((target, before, after))
    command = base / "commands" / "cybertron.md"
    if not command.is_file() or command.is_symlink():
        raise ModelConfigError("缺少已安装的 /cybertron 命令")
    before = command.read_bytes()
    command_text = before.decode("utf-8")
    command_agent = _command_agent(command_text)
    if command_agent not in profile["agents"]:
        raise ModelConfigError(f"/cybertron 命令指向未知角色: {command_agent}")
    updates.append((command, before,
                    _render_command(command_text, profile["agents"][command_agent],
                                    command_agent).encode()))
    changed = []
    try:
        for target, before, after in updates:
            if before != after:
                _write_atomic(target, after)
                changed.append((target, before))
    except Exception:
        for target, before in reversed(changed):
            _write_atomic(target, before)
        raise


def save_profile(path: Path, profile: dict, base: Path) -> Path | None:
    validate_profile(profile)
    if path.is_symlink() or path.parent.is_symlink():
        raise ModelConfigError("拒绝符号链接模型配置目录")
    old = path.read_bytes() if path.is_file() else None
    if path.parent.name == ".cybertron":
        ignore = path.parent / ".gitignore"
        if ignore.is_symlink():
            raise ModelConfigError("拒绝符号链接运行目录忽略文件")
        if not ignore.exists():
            _write_atomic(ignore, b"*\n!.gitignore\n")
    targets = [base / "agents" / f"{agent}.md" for agent in AGENTS]
    targets.append(base / "commands" / "cybertron.md")
    original_files = {target: target.read_bytes() for target in targets}
    backup = _next_backup(path) if old is not None else None
    if backup is not None:
        _write_atomic(backup, old)
    payload = (json.dumps(profile, ensure_ascii=False, indent=2) + "\n").encode()
    try:
        apply_to_install(base, profile)
        _write_atomic(path, payload)
    except Exception:
        if old is not None:
            _write_atomic(path, old)
        else:
            path.unlink(missing_ok=True)
        for target, original in original_files.items():
            _write_atomic(target, original)
        if backup is not None:
            backup.unlink(missing_ok=True)
        raise
    return backup
