#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t03_step67_full_input_internal}"
RUN_ID="${RUN_ID:-}"
RUN_ROOT="${RUN_ROOT:-}"
INTERVAL_SEC="${INTERVAL_SEC:-10}"
RECENT_CASES="${RECENT_CASES:-8}"
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

if ! [[ "$RECENT_CASES" =~ ^[1-9][0-9]*$ ]]; then
  echo "[BLOCK] RECENT_CASES must be a positive integer: $RECENT_CASES" >&2
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

dirs = [
    path
    for path in out_root.iterdir()
    if path.is_dir() and path.name != "_internal"
]
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
  RECENT_CASES="$RECENT_CASES" \
  DEBUG_VISUAL="$DEBUG_VISUAL" \
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


def iso_or_dash(value):
    if not value:
        return "-"
    return str(value)


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


run_root = Path(os.environ["RUN_ROOT"])
recent_cases = int(os.environ["RECENT_CASES"])
debug_visual = os.environ.get("DEBUG_VISUAL", "0") == "1"
internal_root = run_root.parent / "_internal" / run_root.name
case_progress_root = internal_root / "case_progress"
summary_path = run_root / "summary.json"
review_summary_path = run_root / "step67_review_summary.json"
preflight_path = run_root / "preflight.json"
internal_progress_path = internal_root / "internal_full_input_progress.json"

summary_doc = load_json(summary_path) if summary_path.is_file() else None
review_summary_doc = load_json(review_summary_path) if review_summary_path.is_file() else None
preflight_doc = load_json(preflight_path) if preflight_path.is_file() else None
internal_progress_doc = load_json(internal_progress_path) if internal_progress_path.is_file() else None

selected_case_ids = []
for source in (summary_doc, preflight_doc, internal_progress_doc):
    if not source:
        continue
    values = source.get("effective_case_ids") or source.get("selected_case_ids")
    if values:
        selected_case_ids = [str(value) for value in values]
        break

known_case_ids = set(selected_case_ids)
if case_progress_root.is_dir():
    known_case_ids.update(path.stem for path in case_progress_root.glob("*.json"))
cases_root = run_root / "cases"
if cases_root.is_dir():
    known_case_ids.update(path.name for path in cases_root.iterdir() if path.is_dir())

rows = []
accepted = 0
rejected = 0
runtime_failed = 0
running = 0

for case_id in sorted(known_case_ids, key=lambda item: (0, int(item)) if item.isdigit() else (1, item)):
    internal_case_doc = load_json(case_progress_root / f"{case_id}.json") if case_progress_root.is_dir() else None
    watch_status_path = cases_root / case_id / "step67_watch_status.json"
    watch_doc = load_json(watch_status_path) if watch_status_path.is_file() else None
    step7_status_path = cases_root / case_id / "step7_status.json"
    step7_doc = load_json(step7_status_path) if step7_status_path.is_file() else None

    doc = internal_case_doc or {}
    if watch_doc:
        doc = {**doc, **watch_doc}
    if step7_doc and not watch_doc:
        doc = {
            **doc,
            "state": str(step7_doc.get("step7_state") or "completed"),
            "current_stage": "completed",
            "reason": str(step7_doc.get("reason") or "-"),
            "detail": str(step7_doc.get("note") or step7_doc.get("reason") or "-"),
            "updated_at": None,
        }

    state = str(doc.get("state") or "pending")
    current_stage = str(doc.get("current_stage") or "-")
    reason = str(doc.get("reason") or "-")
    detail = truncate(doc.get("detail"))
    updated_at = iso_or_dash(doc.get("updated_at"))

    if state == "accepted":
        accepted += 1
    elif state == "rejected":
        rejected += 1
    elif state == "failed":
        runtime_failed += 1
    elif state == "running":
        running += 1

    rows.append(
        {
            "case_id": case_id,
            "state": state,
            "current_stage": current_stage,
            "reason": reason,
            "detail": detail,
            "updated_at": updated_at,
            "mtime": max(
                safe_mtime(watch_status_path),
                safe_mtime(step7_status_path),
                safe_mtime(case_progress_root / f"{case_id}.json"),
            ),
        }
    )

total = len(selected_case_ids) if selected_case_ids else len(rows)
completed = accepted + rejected + runtime_failed
pending = max(total - completed - running, 0)
success = accepted
failed = rejected + runtime_failed

phase = "-"
phase_status = "-"
phase_message = "-"
if internal_progress_doc:
    phase = str(internal_progress_doc.get("phase") or "-")
    phase_status = str(internal_progress_doc.get("status") or "-")
    phase_message = str(internal_progress_doc.get("message") or "-")
elif summary_doc:
    phase = "completed"
    phase_status = "completed"
    phase_message = "summary.json written"

rows.sort(key=lambda item: (item["mtime"], item["case_id"]), reverse=True)

print(f"[MONITOR] snapshot_at={datetime.now().isoformat(timespec='seconds')}")
print(f"[MONITOR] run_root={run_root}")
print(f"[MONITOR] internal_root={internal_root}")
print(f"[MONITOR] preflight_path={preflight_path}")
print(f"[MONITOR] summary_path={summary_path}")
print(f"[PHASE] phase={phase} status={phase_status} message={truncate(phase_message, 120)}")
print(
    "[COUNTS] "
    f"total={total} "
    f"completed={completed} "
    f"running={running} "
    f"pending={pending} "
    f"success={success} "
    f"failed={failed}"
)
print(
    "[DETAIL] "
    f"business_rejected={rejected} "
    f"runtime_failed={runtime_failed}"
)

if debug_visual and review_summary_doc:
    visual_counts = review_summary_doc.get("visual_class_counts") or {}
    parts = []
    for visual_key in (
        "V1 认可成功",
        "V2 业务正确但几何待修",
        "V3 漏包 required",
        "V4 误包 foreign",
        "V5 明确失败",
    ):
        parts.append(f"{visual_key.split()[0]}={int(visual_counts.get(visual_key, 0))}")
    print("[VISUAL] " + " ".join(parts))

print("[RECENT]")
for row in rows[:recent_cases]:
    print(
        f"  {row['case_id']}: state={row['state']} stage={row['current_stage']} "
        f"reason={truncate(row['reason'], 48)} updated_at={row['updated_at']}"
    )
    print(f"    detail={row['detail']}")
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
