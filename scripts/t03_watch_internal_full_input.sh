#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t03_internal_full_input}"
RUN_ID="${RUN_ID:-}"
RUN_ROOT="${RUN_ROOT:-}"
INTERVAL_SEC="${INTERVAL_SEC:-10}"
RECENT_CASES="${RECENT_CASES:-8}"
ONCE="${ONCE:-0}"
CLEAR_SCREEN="${CLEAR_SCREEN:-1}"
DEBUG_VISUAL="${DEBUG_VISUAL:-0}"
CASE_SCAN="${CASE_SCAN:-auto}"
CASE_SCAN_THRESHOLD="${CASE_SCAN_THRESHOLD:-1000}"

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

if ! [[ "$RECENT_CASES" =~ ^[1-9][0-9]*$ ]]; then
  echo "[BLOCK] RECENT_CASES must be a positive integer: $RECENT_CASES" >&2
  exit 2
fi

if [[ "$DEBUG_VISUAL" != "0" && "$DEBUG_VISUAL" != "1" ]]; then
  echo "[BLOCK] DEBUG_VISUAL must be 0 or 1: $DEBUG_VISUAL" >&2
  exit 2
fi

if [[ "$CASE_SCAN" != "auto" && "$CASE_SCAN" != "on" && "$CASE_SCAN" != "off" ]]; then
  echo "[BLOCK] CASE_SCAN must be auto, on or off: $CASE_SCAN" >&2
  exit 2
fi

if ! [[ "$CASE_SCAN_THRESHOLD" =~ ^[1-9][0-9]*$ ]]; then
  echo "[BLOCK] CASE_SCAN_THRESHOLD must be a positive integer: $CASE_SCAN_THRESHOLD" >&2
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
  echo "[BLOCK] Cannot resolve T03 run root. Pass RUN_ROOT, or set RUN_ID / OUT_ROOT to an existing batch." >&2
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
  RECENT_CASES="$RECENT_CASES" \
  DEBUG_VISUAL="$DEBUG_VISUAL" \
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


def truncate(text, limit=88):
    if not text:
        return "-"
    text = str(text).strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def int_or_default(source, key, default):
    try:
        value = source.get(key)
    except AttributeError:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


run_root = Path(os.environ["RUN_ROOT"])
debug_visual = os.environ.get("DEBUG_VISUAL", "0") == "1"
recent_cases = int(os.environ["RECENT_CASES"])
case_scan_mode = os.environ.get("CASE_SCAN", "auto")
case_scan_threshold = int(os.environ.get("CASE_SCAN_THRESHOLD", "1000"))
internal_root = run_root.parent / "_internal" / run_root.name
preflight_doc = load_json(run_root / "preflight.json") or {}
summary_doc = load_json(run_root / "summary.json") or {}
review_summary_doc = (
    load_json(run_root / "t03_review_summary.json")
    or load_json(run_root / "step67_review_summary.json")
    or {}
)
internal_progress_doc = (
    load_json(internal_root / "t03_internal_full_input_progress.json")
    or load_json(internal_root / "internal_full_input_progress.json")
    or {}
)
internal_failure_doc = (
    load_json(internal_root / "t03_internal_full_input_failure.json")
    or load_json(internal_root / "internal_full_input_failure.json")
    or {}
)
bootstrap_failure_doc = load_json(internal_root / "bootstrap_failure.json") or {}
case_progress_root = internal_root / "case_progress"
cases_root = run_root / "cases"
preflight_path = run_root / "preflight.json"
summary_path = run_root / "summary.json"
internal_progress_path = (
    internal_root / "t03_internal_full_input_progress.json"
    if (internal_root / "t03_internal_full_input_progress.json").is_file()
    else internal_root / "internal_full_input_progress.json"
)

phase = str(internal_progress_doc.get("phase") or ("completed" if summary_doc else "bootstrap"))
status = str(internal_progress_doc.get("status") or ("completed" if summary_doc else "running"))
message = str(internal_progress_doc.get("message") or ("summary.json written" if summary_doc else "waiting for progress"))
entered_case_execution = bool(
    internal_progress_doc.get("entered_case_execution_stage", phase == "direct_case_execution")
)

selected_case_ids = []
for source in (summary_doc, preflight_doc, internal_progress_doc):
    if not source:
        continue
    values = source.get("effective_case_ids") or source.get("selected_case_ids")
    if values:
        selected_case_ids = [str(value) for value in values]
        break

selected_case_count = len(selected_case_ids)
total_count = int_or_default(internal_progress_doc, "total_case_count", selected_case_count)
completed = int_or_default(internal_progress_doc, "completed_case_count", 0)
running = int_or_default(internal_progress_doc, "running_case_count", 0)
pending = int_or_default(internal_progress_doc, "pending_case_count", 0)
success = int_or_default(internal_progress_doc, "success_case_count", 0)
failed = int_or_default(internal_progress_doc, "failed_case_count", 0)

if total_count == 0 and selected_case_count > 0:
    total_count = selected_case_count
if total_count > 0 and pending == 0 and completed + running < total_count:
    pending = max(total_count - completed - running, 0)

performance = internal_progress_doc.get("performance") or {}
elapsed_seconds_total = performance.get("elapsed_seconds_total")
avg_completed_case_seconds = performance.get("avg_completed_case_seconds")
completed_cases_per_minute = performance.get("completed_cases_per_minute")
estimated_remaining_seconds = performance.get("estimated_remaining_seconds")
last_completed_case_id = internal_progress_doc.get("last_completed_case_id") or "-"
last_completed_at = internal_progress_doc.get("last_completed_at") or "-"

print(f"[MONITOR] snapshot_at={datetime.now().isoformat(timespec='seconds')}", flush=True)
print(f"[MONITOR] run_root={run_root}", flush=True)
print(f"[MONITOR] preflight_path={preflight_path}", flush=True)
print(f"[MONITOR] internal_progress_path={internal_progress_path}", flush=True)
print(f"[MONITOR] summary_path={summary_path}", flush=True)
print(
    "[COUNTS] "
    f"total={total_count} "
    f"completed={completed} "
    f"running={running} "
    f"pending={pending} "
    f"success={success} "
    f"failed={failed}",
    flush=True,
)
print(
    "[EXECUTION] "
    f"entered_case_execution={'yes' if entered_case_execution else 'no'} "
    f"phase={phase} status={status}",
    flush=True,
)
if summary_doc:
    batch_success = int(summary_doc.get("step7_accepted_count", 0))
    batch_failed = int(summary_doc.get("step7_rejected_count", 0)) + len(summary_doc.get("failed_case_ids", []))
    print(
        "[BATCH] "
        f"finished_at={summary_doc.get('updated_at', '-')} "
        f"success={batch_success} "
        f"failed={batch_failed}",
        flush=True,
    )
else:
    print("[BATCH] summary not written yet", flush=True)
print(
    "[PERF] "
    f"elapsed_s={elapsed_seconds_total if elapsed_seconds_total is not None else '-'} "
    f"avg_case_s={avg_completed_case_seconds if avg_completed_case_seconds is not None else '-'} "
    f"case_per_min={completed_cases_per_minute if completed_cases_per_minute is not None else '-'} "
    f"eta_s={estimated_remaining_seconds if estimated_remaining_seconds is not None else '-'} "
    f"last_completed_case_id={last_completed_case_id} last_completed_at={last_completed_at}",
    flush=True,
)
print(f"[MESSAGE] {message}", flush=True)
if internal_failure_doc or bootstrap_failure_doc:
    failure_doc = internal_failure_doc or bootstrap_failure_doc
    print(
        "[FAILURE] "
        f"phase={failure_doc.get('phase', '-')} "
        f"failure={truncate(failure_doc.get('failure'), 120)}",
        flush=True,
    )

should_scan_cases = False
scan_skip_reason = None
if recent_cases <= 0:
    scan_skip_reason = "RECENT_CASES<=0"
elif case_scan_mode == "on":
    should_scan_cases = True
elif case_scan_mode == "off":
    scan_skip_reason = "CASE_SCAN=off"
elif total_count > case_scan_threshold:
    scan_skip_reason = f"large_batch total={total_count} threshold={case_scan_threshold}"
else:
    should_scan_cases = True

if should_scan_cases:
    known_case_ids = set(selected_case_ids)
    if case_progress_root.is_dir():
        known_case_ids.update(path.stem for path in case_progress_root.glob("*.json"))
    if cases_root.is_dir():
        known_case_ids.update(path.name for path in cases_root.iterdir() if path.is_dir())
    case_ids = sorted(known_case_ids, key=lambda item: (0, int(item)) if item.isdigit() else (1, item))
    rows = []

    for case_id in case_ids:
        case_dir = cases_root / case_id
        internal_case_path = case_progress_root / f"{case_id}.json"
        watch_status_path = (
            case_dir / "t03_case_watch_status.json"
            if (case_dir / "t03_case_watch_status.json").is_file()
            else case_dir / "step67_watch_status.json"
        )
        step7_status_path = case_dir / "step7_status.json"
        internal_case_doc = load_json(internal_case_path) if internal_case_path.is_file() else None
        watch_doc = load_json(watch_status_path) if watch_status_path.is_file() else None
        step7_doc = load_json(step7_status_path) if step7_status_path.is_file() else None

        if step7_doc is not None:
            state = str(step7_doc.get("step7_state") or "missing_status")
            current_stage = "completed"
            acceptance_reason = str(step7_doc.get("reason") or state)
            detail = truncate(step7_doc.get("note") or step7_doc.get("reason"))
            updated_at = step7_doc.get("updated_at") or "-"
        elif watch_doc is not None:
            state = str(watch_doc.get("state") or "running")
            current_stage = str(watch_doc.get("current_stage") or "-")
            acceptance_reason = str(watch_doc.get("reason") or "-")
            detail = truncate(watch_doc.get("detail"))
            updated_at = watch_doc.get("updated_at") or "-"
        elif internal_case_doc is not None:
            state = str(internal_case_doc.get("state") or "running")
            current_stage = str(internal_case_doc.get("current_stage") or "-")
            acceptance_reason = str(internal_case_doc.get("reason") or "-")
            detail = truncate(internal_case_doc.get("detail"))
            updated_at = internal_case_doc.get("updated_at") or "-"
        else:
            state = "pending"
            current_stage = "-"
            acceptance_reason = "-"
            detail = "-"
            updated_at = "-"

        rows.append(
            {
                "case_id": case_id,
                "state": state,
                "current_stage": current_stage,
                "acceptance_reason": acceptance_reason,
                "detail": detail,
                "updated_at": updated_at,
                "mtime": max(
                    safe_mtime(internal_case_path),
                    safe_mtime(watch_status_path),
                    safe_mtime(step7_status_path),
                ),
            }
        )

    rows.sort(key=lambda item: (item["mtime"], item["case_id"]), reverse=True)
    print("[RECENT]", flush=True)
    if not rows:
        print("  no case-level status files yet", flush=True)
    for row in rows[:recent_cases]:
        print(
            f"  {row['case_id']}: state={row['state']} stage={row['current_stage']} "
            f"reason={truncate(row['acceptance_reason'], 48)} updated_at={row['updated_at']}",
            flush=True,
        )
        print(f"    detail={row['detail']}", flush=True)
else:
    print(
        "[RECENT] "
        f"skipped case-level scan ({scan_skip_reason}); "
        "set CASE_SCAN=on to force.",
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
