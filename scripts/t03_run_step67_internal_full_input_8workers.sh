#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_SCRIPT="$SCRIPT_DIR/t03_run_internal_full_input_8workers.sh"

echo "[MIGRATED] scripts/t03_run_step67_internal_full_input_8workers.sh 已迁移到 scripts/t03_run_internal_full_input_8workers.sh；当前继续兼容转发。" >&2
exec "$TARGET_SCRIPT" "$@"
