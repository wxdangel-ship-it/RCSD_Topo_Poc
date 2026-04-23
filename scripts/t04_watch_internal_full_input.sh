#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t04_internal_full_input}"
RUN_ID="${RUN_ID:-}"
RUN_ROOT="${RUN_ROOT:-}"
INTERVAL_SEC="${INTERVAL_SEC:-10}"
RECENT_CASES="${RECENT_CASES:-8}"
ONCE="${ONCE:-0}"
CLEAR_SCREEN="${CLEAR_SCREEN:-1}"
CASE_SCAN="${CASE_SCAN:-auto}"
CASE_SCAN_THRESHOLD="${CASE_SCAN_THRESHOLD:-1000}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

for numeric_var in INTERVAL_SEC RECENT_CASES CASE_SCAN_THRESHOLD; do
  if ! [[ "${!numeric_var}" =~ ^[1-9][0-9]*$ ]]; then
    echo "[BLOCK] $numeric_var must be a positive integer: ${!numeric_var}" >&2
    exit 2
  fi
done

if [[ "$ONCE" != "0" && "$ONCE" != "1" ]]; then
  echo "[BLOCK] ONCE must be 0 or 1: $ONCE" >&2
  exit 2
fi

if [[ "$CASE_SCAN" != "auto" && "$CASE_SCAN" != "on" && "$CASE_SCAN" != "off" ]]; then
  echo "[BLOCK] CASE_SCAN must be auto, on or off: $CASE_SCAN" >&2
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
dirs = [path for path in out_root.iterdir() if path.is_dir()]
if not dirs:
    sys.exit(2)
print(max(dirs, key=lambda path: path.stat().st_mtime))
PY
}

RESOLVED_RUN_ROOT="$(resolve_run_root || true)"
if [[ -z "$RESOLVED_RUN_ROOT" || ! -d "$RESOLVED_RUN_ROOT" ]]; then
  echo "[BLOCK] Cannot resolve T04 run root. Pass RUN_ROOT, or set RUN_ID / OUT_ROOT to an existing batch." >&2
  exit 2
fi

while true; do
  if [[ "$CLEAR_SCREEN" == "1" && -t 1 ]]; then
    printf '\033c'
  fi

  RUN_ROOT="$RESOLVED_RUN_ROOT" \
  RECENT_CASES="$RECENT_CASES" \
  CASE_SCAN="$CASE_SCAN" \
  CASE_SCAN_THRESHOLD="$CASE_SCAN_THRESHOLD" \
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


def safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def truncate(value, limit=88):
    text = str(value or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def int_value(source, key, default=0):
    try:
        return int(source.get(key, default))
    except Exception:
        return default


run_root = Path(os.environ["RUN_ROOT"])
recent_cases = int(os.environ["RECENT_CASES"])
case_scan = os.environ["CASE_SCAN"]
case_scan_threshold = int(os.environ["CASE_SCAN_THRESHOLD"])
progress = load_json(run_root / "t04_internal_full_input_progress.json") or {}
summary = load_json(run_root / "summary.json") or {}
failure = load_json(run_root / "t04_internal_full_input_failure.json") or {}
preflight = load_json(run_root / "preflight.json") or {}

selected_ids = progress.get("selected_case_ids") or summary.get("selected_case_ids") or preflight.get("selected_case_ids") or []
selected = len(selected_ids)
completed = int_value(progress, "completed_case_count", int_value(summary, "completed_case_count", 0))
running = int_value(progress, "running_case_count", 0)
pending = int_value(progress, "pending_case_count", max(selected - completed - running, 0))
accepted = int_value(progress, "accepted_case_count", int_value(summary, "accepted_count", 0))
rejected = int_value(progress, "rejected_case_count", int_value(summary, "rejected_count", 0))
runtime_failed = int_value(progress, "runtime_failed_case_count", int_value(summary, "runtime_failed_count", 0))
missing_status = int_value(progress, "missing_status_case_count", int_value(summary, "missing_status_count", 0))
phase = str(progress.get("phase") or ("completed" if summary else "preflight"))
status = str(progress.get("status") or ("completed" if summary else "running"))
message = str(progress.get("message") or ("summary.json written" if summary else "waiting for progress"))
entered = bool(progress.get("entered_case_execution") or progress.get("entered_case_execution_stage"))
perf = progress.get("performance") or summary.get("performance") or {}

print(f"[MONITOR] snapshot_at={datetime.now().isoformat(timespec='seconds')}")
print(f"[MONITOR] run_root={run_root}")
print(f"[MONITOR] preflight_path={run_root / 'preflight.json'}")
print(f"[MONITOR] progress_path={run_root / 't04_internal_full_input_progress.json'}")
print(f"[MONITOR] summary_path={run_root / 'summary.json'}")
print(
    "[COUNTS] "
    f"selected={selected} completed={completed} running={running} pending={pending} "
    f"accepted={accepted} rejected={rejected} runtime_failed={runtime_failed} missing_status={missing_status}"
)
print(
    "[EXECUTION] "
    f"phase={phase} status={status} entered_case_execution={'yes' if entered else 'no'}"
)
print(
    "[PERF] "
    f"elapsed_seconds_total={perf.get('elapsed_seconds_total', '-')} "
    f"avg_completed_case_seconds={perf.get('avg_completed_case_seconds', '-')} "
    f"completed_cases_per_minute={perf.get('completed_cases_per_minute', '-')} "
    f"estimated_remaining_seconds={perf.get('estimated_remaining_seconds', '-')} "
    f"last_completed_case_id={progress.get('last_completed_case_id') or '-'} "
    f"last_completed_at={progress.get('last_completed_at') or '-'}"
)
print(f"[MESSAGE] {truncate(message, 140)}")
if failure:
    print(f"[FAILURE] phase={failure.get('phase', '-')} failure={truncate(failure.get('failure'), 140)}")

should_scan = False
skip_reason = ""
if case_scan == "on":
    should_scan = True
elif case_scan == "off":
    skip_reason = "CASE_SCAN=off"
elif selected > case_scan_threshold:
    skip_reason = f"large_batch selected={selected} threshold={case_scan_threshold}"
else:
    should_scan = True

if should_scan:
    case_ids = set(str(value) for value in selected_ids)
    cases_root = run_root / "cases"
    if cases_root.is_dir():
        case_ids.update(path.name for path in cases_root.iterdir() if path.is_dir())
    rows = []
    for case_id in sorted(case_ids, key=lambda value: (0, int(value)) if value.isdigit() else (1, value)):
        case_dir = cases_root / case_id
        watch_path = case_dir / "t04_case_watch_status.json"
        step7_path = case_dir / "step7_status.json"
        watch_doc = load_json(watch_path) or {}
        step7_doc = load_json(step7_path) or {}
        if step7_doc:
            state = str(step7_doc.get("final_state") or "missing_status")
            stage = "completed"
            reason = "|".join(step7_doc.get("reject_reasons") or []) or state
            updated_at = step7_doc.get("updated_at") or "-"
        elif watch_doc:
            state = str(watch_doc.get("state") or "running")
            stage = str(watch_doc.get("current_stage") or "-")
            reason = str(watch_doc.get("reason") or "-")
            updated_at = watch_doc.get("updated_at") or "-"
        else:
            state = "pending"
            stage = "-"
            reason = "-"
            updated_at = "-"
        rows.append(
            {
                "case_id": case_id,
                "state": state,
                "stage": stage,
                "reason": reason,
                "updated_at": updated_at,
                "mtime": max(safe_mtime(watch_path), safe_mtime(step7_path)),
            }
        )
    rows.sort(key=lambda item: (item["mtime"], item["case_id"]), reverse=True)
    print("[RECENT]")
    if not rows:
        print("  no case-level status files yet")
    for row in rows[:recent_cases]:
        print(
            f"  {row['case_id']}: state={row['state']} stage={row['stage']} "
            f"reason={truncate(row['reason'], 52)} updated_at={row['updated_at']}"
        )
else:
    print(f"[RECENT] skipped case-level scan ({skip_reason}); set CASE_SCAN=on to force.")
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
