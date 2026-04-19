#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_SCRIPT="$SCRIPT_DIR/t03_watch_internal_full_input.sh"

echo "[MIGRATED] scripts/t03_watch_step67_internal_full_input.sh 已迁移到 scripts/t03_watch_internal_full_input.sh；当前继续兼容转发。" >&2
exec "$TARGET_SCRIPT" "$@"
