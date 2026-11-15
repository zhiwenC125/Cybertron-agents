"""Add non-secret custom provider metadata to a local OpenCode JSONC config."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from .installer import strip_jsonc
from .model_config import ModelConfigError, _next_backup, _write_atomic


def _masked(text: str) -> str:
    """Mask comments while retaining byte positions and quoted strings."""
    chars = list(text)
    i = 0
    quoted = False
    while i < len(chars):
        if quoted:
            if chars[i] == "\\":
                i += 2
                continue
            if chars[i] == '"':
                quoted = False
            i += 1
            continue
        if chars[i] == '"':
            quoted = True
            i += 1
            continue
        if chars[i:i + 2] == ["/", "/"]:
            end = text.find("\n", i)
            end = len(chars) if end < 0 else end
            for pos in range(i, end):
                chars[pos] = " "
            i = end
            continue
        if chars[i:i + 2] == ["/", "*"]:
            end = text.find("*/", i + 2)
            if end < 0:
                raise ModelConfigError("OpenCode 配置存在未闭合注释")
            for pos in range(i, end + 2):
                if chars[pos] != "\n":
                    chars[pos] = " "
            i = end + 2
            continue
        i += 1
    return "".join(chars)


def _object_bounds(masked: str, start: int) -> tuple[int, int]:
    if masked[start] != "{":
        raise ModelConfigError("OpenCode 配置不是对象")
    depth = 0
    quote = False
    i = start
    while i < len(masked):
        ch = masked[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                quote = False
        elif ch == '"':
            quote = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return start, i
        i += 1
    raise ModelConfigError("OpenCode 配置对象未闭合")


def _top_level_providers(masked: str, root_start: int, root_end: int) -> tuple[int, int] | None:
    depth = 1
    i = root_start + 1
    while i < root_end:
        ch = masked[i]
        if ch == '"':
            start = i
            i += 1
            while i < root_end:
                if masked[i] == "\\":
                    i += 2
                elif masked[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            if depth == 1:
                name = json.loads(masked[start:i])
                j = i
                while j < root_end and masked[j].isspace():
                    j += 1
                if j < root_end and masked[j] == ":" and name == "providers":
                    j += 1
                    while j < root_end and masked[j].isspace():
                        j += 1
                    return _object_bounds(masked, j)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return None


def _insert_entry(raw: str, bounds: tuple[int, int], key: str, value: dict) -> str:
    start, end = bounds
    contents = raw[start + 1:end]
    last = _masked(contents).rstrip()
    separator = "" if not last or last.endswith(",") else ","
    entry = json.dumps(key) + ": " + json.dumps(value, ensure_ascii=False, indent=2)
    return raw[:end] + separator + "\n  " + entry + "\n" + raw[end:]


def provider_entry(provider_id: str, base_url: str, env_name: str,
                   model_ids: list[str]) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", provider_id):
        raise ModelConfigError("供应商 ID 无效")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", env_name):
        raise ModelConfigError("环境变量名称无效")
    url = urlsplit(base_url)
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost")):
        raise ModelConfigError("接口地址必须使用 HTTPS；本机 localhost 可使用 HTTP")
    if not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ModelConfigError("接口地址不能包含账号、密钥、查询参数或片段")
    if not model_ids or len(set(model_ids)) != len(model_ids) or any(
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", item) for item in model_ids):
        raise ModelConfigError("请提供不重复的模型 ID")
    return {"name": provider_id, "env": [env_name],
            "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": base_url},
            "models": {model: {"name": model} for model in model_ids}}


def add_provider(config: Path, provider_id: str, entry: dict) -> Path | None:
    if config.is_symlink() or config.parent.is_symlink():
        raise ModelConfigError("拒绝符号链接 OpenCode 配置")
    raw = config.read_text(encoding="utf-8") if config.exists() else '{"$schema":"https://opencode.ai/config.json"}\n'
    try:
        data = json.loads(strip_jsonc(raw))
    except json.JSONDecodeError as exc:
        raise ModelConfigError("OpenCode JSONC 无法安全解析，请先修复") from exc
    if not isinstance(data, dict) or not isinstance(data.get("providers", {}), dict):
        raise ModelConfigError("OpenCode providers 字段不是对象")
    if provider_id in data.get("providers", {}):
        raise ModelConfigError("供应商 ID 已存在；请在 OpenCode 配置中审核现有定义")
    mask = _masked(raw)
    root_start = mask.find("{")
    root = _object_bounds(mask, root_start)
    providers = _top_level_providers(mask, *root)
    if providers:
        changed = _insert_entry(raw, providers, provider_id, entry)
    else:
        changed = _insert_entry(raw, root, "providers", {provider_id: entry})
    try:
        check = json.loads(strip_jsonc(changed))
    except json.JSONDecodeError as exc:
        raise ModelConfigError("生成的 OpenCode 配置无效，未写入") from exc
    if check.get("providers", {}).get(provider_id) != entry:
        raise ModelConfigError("供应商配置生成校验失败")
    backup = _next_backup(config) if config.is_file() else None
    if backup:
        _write_atomic(backup, raw.encode())
    try:
        _write_atomic(config, changed.encode())
    except Exception:
        if backup:
            _write_atomic(config, raw.encode())
            backup.unlink(missing_ok=True)
        raise
    return backup
