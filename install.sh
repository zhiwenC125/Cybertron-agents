#!/usr/bin/env bash
# Cybertron 安装脚本：把 13 个角色与 /cybertron 命令安装到 OpenCode 配置目录。
# 默认只预览（dry-run），必须显式 --apply 才写盘。
set -euo pipefail

REPO="zhiwenC125/Cybertron-agents"
MODE="global"
PROJECT_DIR="."
APPLY=0
VERSION="v0.7.3"
EXPECTED_SHA256=""
DOCTOR=0
ALLOW_DUPLICATE=0

usage() {
  cat <<'EOF'
Cybertron 安装脚本

用法:
  ./install.sh [选项]

选项:
  --global              安装到全局 OpenCode 配置目录
  --project DIR         安装到 DIR/.opencode（需显式指定；默认全局）
  --apply               真正写入文件（默认只预览）
  --dry-run             只预览（默认）
  --version REF         指定 tag（默认 v0.7.3）；分支仅用于显式开发测试
  --sha256 HEX          校验下载归档的 SHA-256
  --allow-duplicate     允许全局与项目同时安装（不推荐）
  --doctor              只检查本地安装，不下载或写入
  -h, --help            显示本帮助

示例:
  sh install.sh --dry-run              # 预览全局安装
  sh install.sh --apply                # 全局安装
  sh install.sh --apply --project .    # 项目安装
  sh install.sh --apply --version v0.1.0 --sha256 <hex>
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --global) MODE="global" ;;
    --project)
      MODE="project"
      PROJECT_DIR="${2:?--project 需要一个目录参数}"
      shift
      ;;
    --project=*) MODE="project"; PROJECT_DIR="${1#*=}" ;;
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    --allow-duplicate) ALLOW_DUPLICATE=1 ;;
    --doctor) DOCTOR=1 ;;
    --version)
      VERSION="${2:?--version 需要一个分支或 tag 参数}"
      shift
      ;;
    --version=*) VERSION="${1#*=}" ;;
    --sha256)
      EXPECTED_SHA256="${2:?--sha256 需要一个十六进制校验值}"
      shift
      ;;
    --sha256=*) EXPECTED_SHA256="${1#*=}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

if [ "$MODE" = "global" ]; then
  BASE="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
  OTHER="$PROJECT_DIR/.opencode"
else
  BASE="$PROJECT_DIR/.opencode"
  OTHER="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
fi

if [ "$DOCTOR" != "1" ] && [ -f "$OTHER/plugins/cybertron.js" ]; then
  if [ "$ALLOW_DUPLICATE" != "1" ]; then
    echo "检测到另一处 Cybertron 安装: $OTHER" >&2
    echo "请先移除其中一处，或显式使用 --allow-duplicate（不推荐）。" >&2
    exit 2
  fi
  echo "警告: 同时存在另一处安装 $OTHER；两个插件会被重复加载。"
fi

if [ "$DOCTOR" = "1" ]; then
  AGENT_COUNT=0
  COMMAND_COUNT=0
  for f in "$BASE"/agents/*.md; do [ -e "$f" ] && AGENT_COUNT=$((AGENT_COUNT + 1)); done
  for f in "$BASE"/commands/*.md; do [ -e "$f" ] && COMMAND_COUNT=$((COMMAND_COUNT + 1)); done
  echo "目标: $BASE"
  if [ -f "$OTHER/plugins/cybertron.js" ]; then echo "另一处安装: 检测到 $OTHER"; else echo "另一处安装: 无"; fi
  echo "已安装角色: ${AGENT_COUNT}（期望 13）"
  echo "已安装命令: ${COMMAND_COUNT}（期望 1）"
  echo "运行时: $BASE/plugins/cybertron.js、hook_logic.mjs、shell_policy.mjs 与 $BASE/cybertron-runtime/cybertron/plugin_cli.py"
  [ "$AGENT_COUNT" -eq 13 ] && [ "$COMMAND_COUNT" -eq 1 ] && [ -f "$BASE/opencode.jsonc" ] \
    && [ -f "$BASE/plugins/cybertron.js" ] && [ -f "$BASE/plugins/hook_logic.mjs" ] \
    && [ -f "$BASE/plugins/shell_policy.mjs" ] \
    && [ -f "$BASE/cybertron-runtime/cybertron/plugin_cli.py" ]
  exit $?
fi

# 定位源：本地 clone 直接用仓库，否则下载 GitHub 归档
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [ -n "$SCRIPT_DIR" ] && [ -d "$SCRIPT_DIR/.opencode/agents" ]; then
  SRC="$SCRIPT_DIR"
  echo "使用本地仓库: $SRC"
else
  echo "本地未找到 .opencode/，改为下载归档: $REPO@$VERSION"
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT
  if [[ "$VERSION" == v* ]]; then
    ARCHIVE_URL="https://github.com/$REPO/archive/refs/tags/$VERSION.tar.gz"
  else
    ARCHIVE_URL="https://github.com/$REPO/archive/refs/heads/$VERSION.tar.gz"
  fi
  curl -fsSL "$ARCHIVE_URL" -o "$TMP_DIR/src.tar.gz"
  if [ -n "$EXPECTED_SHA256" ]; then
    if command -v shasum >/dev/null 2>&1; then
      ACTUAL_SHA="$(shasum -a 256 "$TMP_DIR/src.tar.gz" | awk '{print $1}')"
    else
      ACTUAL_SHA="$(sha256sum "$TMP_DIR/src.tar.gz" | awk '{print $1}')"
    fi
    if [ "$ACTUAL_SHA" != "$EXPECTED_SHA256" ]; then
      echo "SHA-256 校验失败：期望 ${EXPECTED_SHA256}，实际 ${ACTUAL_SHA}" >&2
      exit 1
    fi
    echo "SHA-256 校验通过"
  fi
  tar -xzf "$TMP_DIR/src.tar.gz" -C "$TMP_DIR" --strip-components=1
  SRC="$TMP_DIR"
fi

echo "安装目标: $BASE"
if [ "$APPLY" = "1" ]; then
  echo "模式: 写入（--apply）"
else
  echo "模式: 预览（dry-run，加 --apply 才会写入）"
fi

NEW=0
UPD=0
SAME=0
CONFIG="$BASE/opencode.jsonc"
if [ -L "$BASE" ] || [ -L "$CONFIG" ]; then
  echo "拒绝符号链接安装目录或配置: $BASE" >&2
  exit 2
fi
if [ -e "$CONFIG" ]; then
  if ! PYTHONPATH="$SRC${PYTHONPATH:+:$PYTHONPATH}" python3 -c '
import json
import sys
from pathlib import Path
from cybertron.installer import strip_jsonc
try:
    parsed = json.loads(strip_jsonc(Path(sys.argv[1]).read_text(encoding="utf-8")))
except (json.JSONDecodeError, OSError):
    raise SystemExit(2)
if not isinstance(parsed, dict):
    raise SystemExit(2)
' "$CONFIG"
  then
    echo "已有 OpenCode 配置无法安全解析: $CONFIG" >&2
    exit 2
  fi
fi
if [ -L "$BASE/cybertron-runtime" ]; then
  echo "拒绝符号链接运行时目录: $BASE/cybertron-runtime" >&2
  exit 2
fi

CHANGED_TARGETS=()
CHANGED_KINDS=()
CHANGED_BACKUPS=()
DONE=0
rollback() {
  if [ "$DONE" = "1" ]; then return; fi
  for ((i=${#CHANGED_TARGETS[@]}-1; i>=0; i--)); do
    target="${CHANGED_TARGETS[$i]}"
    if [ "${CHANGED_KINDS[$i]}" = "new" ]; then
      rm -f "$target"
    else
      cp "${CHANGED_BACKUPS[$i]}" "$target"
      rm -f "${CHANGED_BACKUPS[$i]}"
    fi
  done
}
trap rollback EXIT

for kind in agents commands plugins cybertron-runtime; do
  src_dir="$SRC/.opencode/$kind"
  target_dir="$BASE/$kind"
  extension=md
  if [ "$kind" = "plugins" ]; then extension=js; fi
  if [ "$kind" = "cybertron-runtime" ]; then
    src_dir="$SRC/cybertron"
    target_dir="$BASE/cybertron-runtime/cybertron"
    extension=py
  fi
  [ -d "$src_dir" ] || continue
  if [ -L "$target_dir" ]; then echo "拒绝符号链接安装目录: $target_dir" >&2; exit 2; fi
  if [ "$kind" = "plugins" ]; then
    files=("$src_dir"/*.js "$src_dir"/*.mjs)
  else
    files=("$src_dir"/*."$extension")
  fi
  for f in "${files[@]}"; do
    [ -e "$f" ] || continue
    name="$(basename "$f")"
    target="$target_dir/$name"
    if [ -L "$target" ]; then echo "拒绝符号链接安装目标: $target" >&2; exit 2; fi
    if [ -e "$target" ]; then
      if cmp -s "$f" "$target"; then
        echo "  = $target"
        SAME=$((SAME + 1))
      else
        echo "  ~ $target (保留编号备份后覆盖)"
        UPD=$((UPD + 1))
        if [ "$APPLY" = "1" ]; then
          mkdir -p "$target_dir"
          index=1
          while [ -e "$target.bak.$index" ]; do index=$((index + 1)); done
          backup="$target.bak.$index"
          cp "$target" "$backup"
          CHANGED_TARGETS+=("$target")
          CHANGED_KINDS+=("update")
          CHANGED_BACKUPS+=("$backup")
          cp "$f" "$target"
        fi
      fi
    else
      echo "  + $target"
      NEW=$((NEW + 1))
      if [ "$APPLY" = "1" ]; then
        mkdir -p "$target_dir"
          CHANGED_TARGETS+=("$target")
          CHANGED_KINDS+=("new")
          CHANGED_BACKUPS+=("")
        cp "$f" "$target"
      fi
    fi
  done
done

if [ -e "$CONFIG" ]; then
  echo "  = $CONFIG (已有配置，保持原字节)"
else
  echo "  + $CONFIG (最小配置，沿用 OpenCode 默认角色)"
  if [ "$APPLY" = "1" ]; then
    mkdir -p "$BASE"
    CHANGED_TARGETS+=("$CONFIG")
    CHANGED_KINDS+=("new")
    CHANGED_BACKUPS+=("")
    printf '{\n  "$schema": "https://opencode.ai/config.json",\n  "plugins": ["-cybertron.runtime"]\n}\n' > "$CONFIG"
  fi
fi

echo
echo "新增 ${NEW}，更新 ${UPD}，未变 ${SAME}"
if [ "$APPLY" != "1" ]; then
  DONE=1
  echo "这是预览。确认后加 --apply 执行。"
  exit 0
fi
if [ "$MODE" = "global" ]; then
  model_args=(--global)
else
  model_args=(--project "$PROJECT_DIR")
fi
launcher="$BASE/bin/cybertron"
if [ -L "$launcher" ] || [ -L "$BASE/bin" ]; then
  echo "拒绝符号链接启动器目录: $launcher" >&2
  exit 2
fi
mkdir -p "$BASE/bin"
if [ -e "$launcher" ]; then
  index=1
  while [ -e "$launcher.bak.$index" ]; do index=$((index + 1)); done
  backup="$launcher.bak.$index"
  cp "$launcher" "$backup"
  CHANGED_TARGETS+=("$launcher")
  CHANGED_KINDS+=("update")
  CHANGED_BACKUPS+=("$backup")
else
  CHANGED_TARGETS+=("$launcher")
  CHANGED_KINDS+=("new")
  CHANGED_BACKUPS+=("")
fi
printf '#!/usr/bin/env bash\nexport CYBERTRON_PROJECT_CWD="$PWD"\nexport PYTHONPATH=%q${PYTHONPATH:+:$PYTHONPATH}\ncd %q\nexec python3 -m cybertron.installer "$@"\n' "$BASE/cybertron-runtime" "$BASE/cybertron-runtime" > "$launcher"
chmod 755 "$launcher"
PYTHONPATH="$BASE/cybertron-runtime${PYTHONPATH:+:$PYTHONPATH}" python3 -m cybertron.model_cli apply "${model_args[@]}"
DONE=1
echo "安装完成。运行: opencode2 debug agents"
echo "未修改 PATH；后续命令请使用下面的绝对路径："
echo "  模型编队: $launcher models setup ${model_args[*]}"
echo "  本地检查: $launcher doctor ${model_args[*]}"
