#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$PROJECT_DIR/.agents/skills/game-keyword-scan"
TARGET_ROOT="${CODEX_HOME:-$HOME/.codex}/skills"
TARGET_DIR="$TARGET_ROOT/game-keyword-scan"

mkdir -p "$TARGET_ROOT"

if [[ -e "$TARGET_DIR" && ! -L "$TARGET_DIR" ]]; then
  printf 'Refusing to replace non-symlink path: %s\n' "$TARGET_DIR" >&2
  exit 1
fi

ln -sfn "$SOURCE_DIR" "$TARGET_DIR"
printf 'Installed game-keyword-scan -> %s\n' "$SOURCE_DIR"
