#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t03_step67_full_input_internal}"
RUN_ID="${RUN_ID:-}"
RUN_ROOT="${RUN_ROOT:-}"
INTERVAL_SEC="${INTERVAL_SEC:-5}"
ONCE="${ONCE:-0}"
CLEAR_SCREEN="${CLEAR_SCREEN:-1}"
DEBUG_VISUAL="${DEBUG_VISUAL:-0}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if ! [[ "$INTERVAL_SEC" =~ ^[1-9][0-9]*$ ]]; then
  echo "[BLOCK] INTERVAL_SEC must be a positive integer: $INTERVAL_SEC" >&2
  exit 2
fi

if [[ "$DEBUG_VISUAL" != "0" && "$DEBUG_VISUAL" != "1" ]]; then
  echo "[BLOCK] DEBUG_VISUAL must be 0 or 1: $DEBUG_VISUAL" >&2
  exit 2
fi

resolve_run_root() {
  if [[ -n "$RUN_ROOT" ]]; then
    printf '%s\n' "$RUN_ROOT"
    return 0
  fi

  if [[ -n "$RUN_ID" ]]; then
    printf '%s\n' "$OUT_ROOT/$RUN_ID"
    return 0
  fi

  OUT_ROOT="$OUT_ROOT" "$PYTHON_BIN" - <<'PY'
import os
import sys
from pathlib import Path

out_root = Path(os.environ["OUT_ROOT"])
if not out_root.is_dir():
    sys.exit(1)

dirs = [path for path in out_root.iterdir() if path.is_dir() and path.name != "_internal"]
if not dirs:
    sys.exit(2)

latest = max(dirs, key=lambda path: path.stat().st_mtime)
print(latest)
PY
}

RESOLVED_RUN_ROOT="$(resolve_run_root || true)"
if [[ -z "$RESOLVED_RUN_ROOT" ]]; then
  echo "[BLOCK] Cannot resolve T03 Step67 run root. Pass RUN_ROOT, or set RUN_ID / OUT_ROOT to an existing batch." >&2
  exit 2
fi

if [[ ! -d "$RESOLVED_RUN_ROOT" ]]; then
  echo "[BLOCK] RUN_ROOT does not exist: $RESOLVED_RUN_ROOT" >&2
  exit 2
fi

while true; do
  if [[ "$CLEAR_SCREEN" == "1" ]] && [[ -t 1 ]]; then
    printf '\033c'
  fi

  RUN_ROOT="$RESOLVED_RUN_ROOT" \
  DEBUG_VISUAL="$DEBUG_VISUAL" \
  PYTHONUNBUFFERED=1 \
  "$PYTHON_BIN" - <<'PY'
import json
import os
from datetime import datetime
from pathlib import Path


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


run_root = Path(os.environ["RUN_ROOT"])
debug_visual = os.environ.get("DEBUG_VISUAL", "0") == "1"
internal_root = run_root.parent / "_internal" / run_root.name
preflight_doc = load_json(run_root / "preflight.json") or {}
summary_doc = load_json(run_root / "summary.json") or {}
review_summary_doc = load_json(run_root / "step67_review_summary.json") or {}
internal_progress_doc = load_json(internal_root / "internal_full_input_progress.json") or {}

phase = str(
    internal_progress_doc.get("phase")
    or ("completed" if summary_doc else "bootstrap")
)
status = str(
    internal_progress_doc.get("status")
    or ("completed" if summary_doc else "running")
)
message = str(
    internal_progress_doc.get("message")
    or ("summary.json written" if summary_doc else "waiting for progress")
)
entered_case_execution = bool(internal_progress_doc.get("entered_case_execution_stage", phase == "direct_case_execution"))

total = int(
    internal_progress_doc.get("selected_case_count")
    or preflight_doc.get("selected_case_count")
    or summary_doc.get("effective_case_count")
    or 0
)
completed = int(
    internal_progress_doc.get("completed_case_count")
    or (
        int(summary_doc.get("step7_accepted_count", 0))
        + int(summary_doc.get("step7_rejected_count", 0))
        + len(summary_doc.get("failed_case_ids", []))
    )
)
success = int(
    internal_progress_doc.get("success_case_count")
    or internal_progress_doc.get("accepted_case_count")
    or summary_doc.get("step7_accepted_count")
    or 0
)
business_rejected = int(
    internal_progress_doc.get("rejected_case_count")
    or summary_doc.get("step7_rejected_count")
    or 0
)
runtime_failed = int(
    internal_progress_doc.get("runtime_failed_case_count")
    or len(summary_doc.get("failed_case_ids", []))
)
failed = business_rejected + runtime_failed
running = int(internal_progress_doc.get("running_case_count") or 0)
pending = int(
    internal_progress_doc.get("pending_case_count")
    if "pending_case_count" in internal_progress_doc
    else max(total - completed - running, 0)
)

performance = internal_progress_doc.get("performance") or {}
elapsed_seconds_total = performance.get("elapsed_seconds_total")
avg_completed_case_seconds = performance.get("avg_completed_case_seconds")
completed_cases_per_minute = performance.get("completed_cases_per_minute")
last_completed_case_id = internal_progress_doc.get("last_completed_case_id") or "-"
last_completed_at = internal_progress_doc.get("last_completed_at") or "-"

print(f"[MONITOR] snapshot_at={datetime.now().isoformat(timespec='seconds')}", flush=True)
print(f"[RUN] run_root={run_root}", flush=True)
print(f"[RUN] internal_root={internal_root}", flush=True)
print(
    f"[PHASE] phase={phase} status={status} entered_case_execution={'yes' if entered_case_execution else 'no'}",
    flush=True,
)
print(f"[MESSAGE] {message}", flush=True)
print(
    "[COUNTS] "
    f"total={total} completed={completed} success={success} failed={failed} running={running} pending={pending}",
    flush=True,
)
print(
    "[DETAIL] "
    f"business_rejected={business_rejected} runtime_failed={runtime_failed}",
    flush=True,
)
print(
    "[PERF] "
    f"elapsed_s={elapsed_seconds_total if elapsed_seconds_total is not None else '-'} "
    f"avg_case_s={avg_completed_case_seconds if avg_completed_case_seconds is not None else '-'} "
    f"case_per_min={completed_cases_per_minute if completed_cases_per_minute is not None else '-'} "
    f"last_completed_case_id={last_completed_case_id} last_completed_at={last_completed_at}",
    flush=True,
)

if debug_visual and review_summary_doc:
    visual_counts = review_summary_doc.get("visual_class_counts") or {}
    print(
        "[VISUAL] "
        f"V1={int(visual_counts.get('V1 认可成功', 0))} "
        f"V2={int(visual_counts.get('V2 业务正确但几何待修', 0))} "
        f"V3={int(visual_counts.get('V3 漏包 required', 0))} "
        f"V4={int(visual_counts.get('V4 误包 foreign', 0))} "
        f"V5={int(visual_counts.get('V5 明确失败', 0))}",
        flush=True,
    )
PY

  if [[ "$ONCE" == "1" ]]; then
    break
  fi

  if [[ -f "$RESOLVED_RUN_ROOT/summary.json" ]]; then
    echo "[DONE] summary.json detected. Monitor stops." >&2
    break
  fi

  sleep "$INTERVAL_SEC"
done
