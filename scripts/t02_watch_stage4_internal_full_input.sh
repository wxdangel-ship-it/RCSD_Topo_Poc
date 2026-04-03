#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t02_stage4_divmerge_full_input_internal}"
RUN_ID="${RUN_ID:-}"
RUN_ROOT="${RUN_ROOT:-}"
INTERVAL_SEC="${INTERVAL_SEC:-10}"
RECENT_CASES="${RECENT_CASES:-8}"
ONCE="${ONCE:-0}"
CLEAR_SCREEN="${CLEAR_SCREEN:-1}"

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

latest = max(dirs, key=lambda path: path.stat().st_mtime)
print(latest)
PY
}

RESOLVED_RUN_ROOT="$(resolve_run_root || true)"
if [[ -z "$RESOLVED_RUN_ROOT" ]]; then
  echo "[BLOCK] Cannot resolve Stage4 run root. Pass RUN_ROOT, or set RUN_ID / OUT_ROOT to an existing batch." >&2
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


run_root = Path(os.environ["RUN_ROOT"])
recent_cases = int(os.environ["RECENT_CASES"])
cases_root = run_root / "cases"
candidate_list_path = run_root / "candidate_mainnodeids.txt"
summary_path = run_root / "batch_summary.json"

candidate_ids = []
if candidate_list_path.is_file():
    candidate_ids = [line.strip() for line in candidate_list_path.read_text(encoding="utf-8").splitlines() if line.strip()]

case_dirs = sorted([path for path in cases_root.iterdir() if path.is_dir()], key=lambda path: path.name) if cases_root.is_dir() else []
case_ids = sorted(set(candidate_ids) | {path.name for path in case_dirs})

accepted = 0
review_required = 0
rejected = 0
completed = 0
running = 0
pending = 0
missing_status = 0
rows = []

for case_id in case_ids:
    case_dir = cases_root / case_id
    progress_path = case_dir / "stage4_progress.json"
    status_path = case_dir / "stage4_status.json"
    log_path = run_root / "case_logs" / f"{case_id}.log"
    progress_doc = load_json(progress_path) if progress_path.is_file() else None
    status_doc = load_json(status_path) if status_path.is_file() else None

    if status_doc is not None:
        completed += 1
        acceptance_class = str(status_doc.get("acceptance_class") or "missing_status")
        acceptance_reason = str(status_doc.get("acceptance_reason") or status_doc.get("status") or "missing_status")
        detail = truncate(status_doc.get("detail"))
        updated_at = status_doc.get("updated_at") or status_doc.get("finished_at") or "-"
        current_stage = "completed"
        state = acceptance_class
        if acceptance_class == "accepted":
            accepted += 1
        elif acceptance_class == "review_required":
            review_required += 1
        elif acceptance_class == "rejected":
            rejected += 1
        else:
            missing_status += 1
    elif progress_doc is not None:
        running += 1
        state = str(progress_doc.get("status") or "running")
        current_stage = str(progress_doc.get("current_stage") or "-")
        acceptance_reason = str(progress_doc.get("message") or "-")
        detail = truncate(progress_doc.get("message"))
        updated_at = progress_doc.get("updated_at") or "-"
    else:
        pending += 1
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
            "mtime": max(safe_mtime(progress_path), safe_mtime(status_path), safe_mtime(log_path)),
        }
    )

selected_case_count = len(candidate_ids) if candidate_ids else len(case_ids)
if selected_case_count and pending == 0:
    pending = max(selected_case_count - completed - running, 0)

rows.sort(key=lambda item: (item["mtime"], item["case_id"]), reverse=True)
summary_doc = load_json(summary_path) if summary_path.is_file() else None

print(f"[MONITOR] snapshot_at={datetime.now().isoformat(timespec='seconds')}")
print(f"[MONITOR] run_root={run_root}")
print(f"[MONITOR] candidate_list_path={candidate_list_path}")
print(f"[MONITOR] batch_summary_path={summary_path}")
print(
    "[COUNTS] "
    f"selected={selected_case_count} "
    f"completed={completed} "
    f"running={running} "
    f"pending={pending} "
    f"accepted={accepted} "
    f"review_required={review_required} "
    f"rejected={rejected} "
    f"missing_status={missing_status}"
)

if summary_doc is not None:
    print(
        "[BATCH] "
        f"finished_at={summary_doc.get('finished_at', '-')} "
        f"accepted={summary_doc.get('accepted_case_count', 0)} "
        f"review_required={summary_doc.get('review_required_case_count', 0)} "
        f"rejected={summary_doc.get('rejected_case_count', 0)} "
        f"unexpected_exit={summary_doc.get('unexpected_exit_case_count', 0)}"
    )
else:
    print("[BATCH] summary not written yet")

print("[RECENT]")
for row in rows[:recent_cases]:
    print(
        f"  {row['case_id']}: state={row['state']} stage={row['current_stage']} "
        f"reason={truncate(row['acceptance_reason'], 48)} updated_at={row['updated_at']}"
    )
    print(f"    detail={row['detail']}")
PY

  if [[ "$ONCE" == "1" ]]; then
    break
  fi

  if [[ -f "$RESOLVED_RUN_ROOT/batch_summary.json" ]]; then
    echo "[DONE] batch_summary.json detected. Monitor stops." >&2
    break
  fi

  sleep "$INTERVAL_SEC"
done
