#!/usr/bin/env bash
# Cybertron 安装脚本：把 13 个角色与 /cybertron 命令安装到 OpenCode 配置目录。
# 默认只预览（dry-run），必须显式 --apply 才写盘。
set -euo pipefail

REPO="zhiwenC125/Cybertron-agents"
MODE="project"
PROJECT_DIR="."
APPLY=0
VERSION="main"
EXPECTED_SHA256=""

usage() {
  cat <<'EOF'
Cybertron 安装脚本

用法:
  ./install.sh [选项]

选项:
  --global              安装到全局 OpenCode 配置目录
  --project DIR         安装到 DIR/.opencode（默认当前目录）
  --apply               真正写入文件（默认只预览）
  --dry-run             只预览（默认）
  --version REF         指定分支或 tag（默认 main）
  --sha256 HEX          校验下载归档的 SHA-256
  -h, --help            显示本帮助

示例:
  sh install.sh --dry-run
  sh install.sh --apply --project .
  sh install.sh --apply --global
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

# 定位源：本地 clone 直接用仓库，否则下载 GitHub 归档
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
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

if [ "$MODE" = "global" ]; then
  BASE="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
else
  BASE="$PROJECT_DIR/.opencode"
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
for kind in agents commands; do
  src_dir="$SRC/.opencode/$kind"
  [ -d "$src_dir" ] || continue
  for f in "$src_dir"/*.md; do
    [ -e "$f" ] || continue
    name="$(basename "$f")"
    target="$BASE/$kind/$name"
    if [ -e "$target" ]; then
      if cmp -s "$f" "$target"; then
        echo "  = $target"
        SAME=$((SAME + 1))
      else
        echo "  ~ $target (备份为 .bak 后覆盖)"
        UPD=$((UPD + 1))
        if [ "$APPLY" = "1" ]; then
          mkdir -p "$BASE/$kind"
          cp "$target" "$target.bak"
          cp "$f" "$target"
        fi
      fi
    else
      echo "  + $target"
      NEW=$((NEW + 1))
      if [ "$APPLY" = "1" ]; then
        mkdir -p "$BASE/$kind"
        cp "$f" "$target"
      fi
    fi
  done
done

CONFIG="$BASE/opencode.jsonc"
if [ -e "$CONFIG" ]; then
  if grep -q '"default_agent"' "$CONFIG" 2>/dev/null; then
    echo "  = $CONFIG (已有 default_agent)"
  else
    echo "  ! $CONFIG 缺少 default_agent；请手动加入 \"default_agent\": \"prima\""
  fi
else
  echo "  + $CONFIG (最小配置，默认 prima)"
  if [ "$APPLY" = "1" ]; then
    mkdir -p "$BASE"
    printf '{\n  "$schema": "https://opencode.ai/config.json",\n  "default_agent": "prima"\n}\n' > "$CONFIG"
  fi
fi

echo
echo "新增 ${NEW}，更新 ${UPD}，未变 ${SAME}"
if [ "$APPLY" != "1" ]; then
  echo "这是预览。确认后加 --apply 执行。"
  exit 0
fi
echo "安装完成。运行: opencode2 debug agents"
