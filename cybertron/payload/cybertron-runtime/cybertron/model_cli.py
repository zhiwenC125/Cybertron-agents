"""Terminal model fleet setup; OpenCode remains the only credential manager."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .installer import default_base
from .model_config import (AGENTS, DEFAULTS, ModelConfigError, _write_atomic, apply_to_install,
                           available_models, effective_profile, load_profile,
                           make_profile, missing_models, profile_path, save_profile,
                           tier_mapping)


def _scope(args) -> tuple[Path, Path, Path]:
    if args.action in ("setup", "rollback", "provider-add") and args.project is None:
        args.global_ = True
    caller = Path(os.environ.get("CYBERTRON_PROJECT_CWD", ".")).resolve()
    requested = Path(args.project) if args.project else caller
    project = (requested if requested.is_absolute() else caller / requested).resolve()
    base = default_base(args.global_, str(project))
    path = profile_path(project, args.global_)
    return project, base, path


def _choice(options: list[str], prompt: str, *, current: str = "") -> str:
    if current:
        print(f"当前: {current}")
    query = input(f"{prompt}（输入搜索词；直接回车保留当前值）: ").strip()
    if not query and current:
        return current
    matches = [item for item in options if query.casefold() in item.casefold()]
    if not matches:
        raise ModelConfigError("没有匹配的可用模型，请先在 OpenCode 中配置或连接该模型")
    for index, item in enumerate(matches, 1):
        print(f"  {index:>2}. {item}")
    if len(matches) == 1:
        return matches[0]
    selected = input("选择编号: ").strip()
    if not selected.isdigit() or not 1 <= int(selected) <= len(matches):
        raise ModelConfigError("模型编号无效")
    return matches[int(selected) - 1]


def _show(profile: dict | None, label: str) -> None:
    print(f"模型编队: {label}")
    if profile is None:
        print("尚未配置；角色使用发行包默认模型。")
    models = profile["agents"] if profile else DEFAULTS
    for agent in AGENTS:
        print(f"  {agent:<17} {models[agent]}")


def _catalog(project: Path, global_install: bool) -> set[str]:
    if not global_install:
        return available_models(project)
    with tempfile.TemporaryDirectory(prefix="cybertron-model-catalog-") as directory:
        return available_models(Path(directory))


def _probe(profile: dict) -> None:
    """Optional live probe from a fresh empty directory; never reads user project files."""
    from .opencode_executor import OpenCodeV2Executor
    with tempfile.TemporaryDirectory(prefix="cybertron-model-probe-") as directory:
        workspace = Path(directory)
        (workspace / "probe.txt").write_text("cybertron-probe-ok\n", encoding="utf-8")
        visible = available_models(workspace)
        missing = missing_models(profile, visible)
        if missing:
            raise ModelConfigError("隔离探测目录无法加载模型（请将供应商配置到 OpenCode 全局作用域）: " +
                                   ", ".join(sorted(missing)))
        for model in sorted(set(profile["agents"].values())):
            prompt = ("Use the read tool to read probe.txt. Then return only JSON: "
                      '{"status":"ok","value":"cybertron-probe-ok"}. '
                      "Do not read any other file.")
            try:
                result = subprocess.run(["opencode2", "run", "--standalone", "--archived",
                                         "--agent", "build", "--model", model,
                                         "--format", "json", prompt],
                                        cwd=workspace, text=True, capture_output=True,
                                        timeout=90, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ModelConfigError(f"在线能力检查未完成: {model}") from exc
            if result.returncode:
                raise ModelConfigError(f"在线能力检查调用失败: {model}（退出码 {result.returncode}）")
            parts = []
            for line in result.stdout.splitlines():
                try:
                    parts.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            read_ok = any(row.get("type") == "tool_use" and
                          row.get("part", {}).get("tool") == "read" and
                          row.get("part", {}).get("state", {}).get("status") == "completed"
                          for row in parts)
            response = "".join(row.get("part", {}).get("text", "") for row in parts
                               if row.get("type") == "text")
            parsed = OpenCodeV2Executor._extract_json_object(response)
            if not read_ok or not parsed or parsed.get("status") != "ok" or \
                    parsed.get("value") != "cybertron-probe-ok":
                raise ModelConfigError(f"模型未通过工具调用及结构化回复检查: {model}")
            print(f"在线能力检查通过: {model}")


def _setup(args) -> int:
    project, base, path = _scope(args)
    if not (base / "agents" / "prima.md").is_file():
        scope = "--global" if args.global_ else f"--project {project}"
        raise ModelConfigError(f"此作用域尚未安装 Cybertron；先运行 cybertron init --apply {scope}")
    current = load_profile(path)
    inherited = effective_profile(project) if not args.global_ else None
    _show(current or inherited, str(path) if current else "继承全局" if inherited else "发行包默认")
    models = dict((current or inherited)["agents"] if (current or inherited) else DEFAULTS)
    tiers = dict((current or inherited).get("tiers", {}) if (current or inherited) else {})
    catalog = _catalog(project, args.global_)
    if not catalog:
        raise ModelConfigError("OpenCode 没有可用模型；请先使用 /connect 或配置公司模型接口")
    choices = sorted(catalog)

    if args.single:
        models = {agent: args.single for agent in AGENTS}
        tiers = {}
    elif args.high or args.middle or args.low:
        if not all((args.high, args.middle, args.low)):
            raise ModelConfigError("三档配置须同时指定 --high、--middle、--low")
        tiers = {"high": args.high, "middle": args.middle, "low": args.low}
        models = tier_mapping(**tiers)
    elif not args.set:
        if not sys.stdin.isatty():
            raise ModelConfigError("交互式设置需要终端；脚本可使用 --single 或 --high/--middle/--low")
        print("\n1. 只改指定角色  2. 调整三档  3. 全部使用同一模型  4. 退出")
        action = input("选择操作: ").strip()
        if action == "1":
            while True:
                for index, agent in enumerate(AGENTS, 1):
                    print(f"{index:>2}. {agent:<17} {models[agent]}")
                selected = input("角色编号（回车完成）: ").strip()
                if not selected:
                    break
                if not selected.isdigit() or not 1 <= int(selected) <= len(AGENTS):
                    raise ModelConfigError("角色编号无效")
                agent = AGENTS[int(selected) - 1]
                models[agent] = _choice(choices, agent, current=models[agent])
        elif action == "2":
            old = dict(tiers)
            tiers = {name: _choice(choices, f"{name} 档", current=old.get(name, ""))
                     for name in ("high", "middle", "low")}
            old_assignments = tier_mapping(**old) if len(old) == 3 else {}
            for agent, assigned in tier_mapping(**tiers).items():
                if not current or models[agent] == old_assignments.get(agent, models[agent]):
                    models[agent] = assigned
        elif action == "3":
            model = _choice(choices, "统一模型")
            models = {agent: model for agent in AGENTS}
            tiers = {}
        elif action == "4":
            return 0
        else:
            raise ModelConfigError("无效操作")
    for item in args.set:
        agent, separator, model = item.partition("=")
        if separator != "=" or agent not in AGENTS:
            raise ModelConfigError("--set 格式应为 role=provider/model")
        models[agent] = model
    profile = make_profile(models, tiers)
    missing = missing_models(profile, catalog)
    if missing:
        raise ModelConfigError("OpenCode 当前不可用的模型: " + ", ".join(sorted(missing)))
    print("\n变更预览:")
    before = (current or inherited)["agents"] if (current or inherited) else DEFAULTS
    for agent in AGENTS:
        mark = "*" if before[agent] != models[agent] else " "
        print(f"{mark} {agent:<17} {before[agent]} -> {models[agent]}")
    if current and profile == current:
        print("配置没有变化。")
        if args.probe:
            _probe(profile)
        return 0
    if not args.yes and input("保存并启用？[y/N]: ").strip().lower() not in ("y", "yes"):
        print("已取消，未更改配置。")
        return 0
    if args.probe:
        print("使用不含项目文件的临时目录检查所选模型；可能产生少量模型费用。")
        _probe(profile)
    previous_profile = path.read_bytes() if path.is_file() else None
    installed = {file: file.read_bytes() for file in
                 [*(base / "agents" / f"{agent}.md" for agent in AGENTS),
                  base / "commands" / "cybertron.md"]}
    backup = save_profile(path, profile, base)
    try:
        verified = _doctor(args) == 0
    except Exception:
        verified = False
    if not verified:
        for file, content in installed.items():
            _write_atomic(file, content)
        if previous_profile is None:
            path.unlink(missing_ok=True)
        else:
            _write_atomic(path, previous_profile)
        if backup:
            backup.unlink(missing_ok=True)
        raise ModelConfigError("OpenCode 加载校验失败，已恢复切换前的模型编队")
    print(f"已启用: {path}" + (f"；上一版: {backup}" if backup else ""))
    print("新任务使用新编队；进行中的 run 不会自动改模。")
    return 0


def _doctor(args) -> int:
    project, base, path = _scope(args)
    profile = load_profile(path) if args.global_ else effective_profile(project)
    inherited_global = not args.global_ and not path.is_file()
    if inherited_global:
        base = default_base(True, str(project))
    _show(profile, str(path) if args.global_ else "当前生效")
    if not profile:
        print("尚未配置本机模型编队。运行 cybertron models setup。")
        return 1
    missing = missing_models(profile, _catalog(project, args.global_))
    if missing:
        print("不可用模型: " + ", ".join(sorted(missing)))
        return 1
    for agent, model in profile["agents"].items():
        file = base / "agents" / f"{agent}.md"
        if not file.is_file() or f"\nmodel: {model}\n" not in file.read_text(encoding="utf-8"):
            print(f"角色配置与编队不一致: {agent}")
            return 1
    command = base / "commands" / "cybertron.md"
    if not command.is_file() or f"\nmodel: {profile['agents']['prima']}\n" not in command.read_text():
        print("/cybertron 命令模型与 prima 不一致")
        return 1
    try:
        if args.global_:
            with tempfile.TemporaryDirectory(prefix="cybertron-model-doctor-") as directory:
                result = subprocess.run(["opencode2", "debug", "agents", "--standalone"], cwd=directory,
                                        text=True, capture_output=True, timeout=20, check=False)
        else:
            result = subprocess.run(["opencode2", "debug", "agents", "--standalone"], cwd=project,
                                    text=True, capture_output=True, timeout=20, check=False)
        loaded = {row["id"]: row.get("model", {}) for row in json.loads(result.stdout)} if result.returncode == 0 else {}
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        loaded = {}
    for agent, model in profile["agents"].items():
        provider, name = model.split("/", 1)
        name = name.split("#", 1)[0]
        if loaded.get(agent, {}).get("providerID") != provider or loaded.get(agent, {}).get("id") != name:
            if inherited_global and (project / ".opencode" / "agents" / f"{agent}.md").is_file():
                print(f"提示: 项目角色文件显示旧模型，Cybertron 运行时将按全局编队覆盖: {agent}")
                continue
            print(f"OpenCode 实际加载模型与编队不一致: {agent}")
            return 1
    print("13 个角色及 /cybertron 模型映射一致；认证与真实工具能力可用可选在线检查进一步验证。")
    if args.probe:
        _probe(profile)
    return 0


def _rollback(args) -> int:
    _, base, path = _scope(args)
    backups = sorted(path.parent.glob(path.name + ".bak.*"),
                     key=lambda item: int(item.name.rsplit(".", 1)[-1])
                     if item.name.rsplit(".", 1)[-1].isdigit() else -1)
    if not backups:
        raise ModelConfigError("没有可恢复的历史编队")
    previous = load_profile(backups[-1])
    if not args.yes and input(f"恢复 {backups[-1]}？[y/N]: ").strip().lower() not in ("y", "yes"):
        return 0
    installed = {file: file.read_bytes() for file in
                 [*(base / "agents" / f"{agent}.md" for agent in AGENTS),
                  base / "commands" / "cybertron.md"]}
    current_bytes = path.read_bytes()
    new_backup = save_profile(path, previous, base)
    if _doctor(args) != 0:
        for file, content in installed.items():
            _write_atomic(file, content)
        _write_atomic(path, current_bytes)
        if new_backup:
            new_backup.unlink(missing_ok=True)
        raise ModelConfigError("OpenCode 加载校验失败，已恢复回滚前的模型编队")
    print("已恢复上一份编队")
    return 0


def _apply(args) -> int:
    project, base, path = _scope(args)
    profile = load_profile(path) if args.global_ else effective_profile(project)
    if profile:
        apply_to_install(base, profile)
    return 0


def _provider_add(args) -> int:
    from .provider_config import add_provider, provider_entry
    project, base, _ = _scope(args)
    if not all((args.provider_id, args.base_url, args.env_name, args.model_id)):
        raise ModelConfigError("provider-add 需要 --provider-id、--base-url、--env-name 和至少一个 --model-id")
    entry = provider_entry(args.provider_id, args.base_url, args.env_name, args.model_id)
    config = base / "opencode.jsonc"
    print(f"将向 {config} 添加供应商 {args.provider_id}、{len(args.model_id)} 个模型，认证变量名 {args.env_name}。")
    print(f"将保存接口地址元数据；不会读取或保存 {args.env_name} 的值。")
    if not args.yes and input("写入 OpenCode 配置？[y/N]: ").strip().lower() not in ("y", "yes"):
        print("已取消，未更改配置。")
        return 0
    backup = add_provider(config, args.provider_id, entry)
    print(f"已写入 {config}" + (f"；上一版: {backup}" if backup else ""))
    print("请确保 OpenCode 已连接该供应商，或在 OpenCode 服务环境中设置认证变量；随后运行 cybertron models setup。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cybertron models")
    parser.add_argument("action", choices=("setup", "show", "doctor", "rollback", "apply", "provider-add"))
    parser.add_argument("--global", dest="global_", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--single")
    parser.add_argument("--high")
    parser.add_argument("--middle")
    parser.add_argument("--low")
    parser.add_argument("--set", action="append", default=[])
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--probe", action="store_true", help="启用前对所选模型运行可选在线能力检查")
    parser.add_argument("--provider-id")
    parser.add_argument("--base-url")
    parser.add_argument("--env-name")
    parser.add_argument("--model-id", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if args.action == "setup":
            return _setup(args)
        if args.action == "doctor":
            return _doctor(args)
        if args.action == "rollback":
            return _rollback(args)
        if args.action == "apply":
            return _apply(args)
        if args.action == "provider-add":
            return _provider_add(args)
        project, _, path = _scope(args)
        profile = load_profile(path) if args.global_ else effective_profile(project)
        _show(profile, str(path) if args.global_ else "当前生效")
        return 0
    except ModelConfigError as exc:
        print(f"模型配置错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
