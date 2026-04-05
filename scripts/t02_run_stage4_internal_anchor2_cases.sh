#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

CASE_ROOT="${CASE_ROOT:-/mnt/d/TestData/POC_Data/T02/Anchor_2}"
BUNDLE_GLOB="${BUNDLE_GLOB:-*.txt}"
CASE_SEARCH_MAX_DEPTH="${CASE_SEARCH_MAX_DEPTH:-3}"
DIRECT_CASE_REGEX="${DIRECT_CASE_REGEX:-[0-9]+}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t02_stage4_anchor2_internal}"
RUN_ID="${RUN_ID:-t02_stage4_anchor2_internal_$(date +%Y%m%d_%H%M%S)}"
RUN_ROOT="$OUT_ROOT/$RUN_ID"
DECODE_ROOT="${DECODE_ROOT:-$RUN_ROOT/decoded}"
CASES_ROOT="$RUN_ROOT/cases"
CASE_LOG_ROOT="$RUN_ROOT/case_logs"
CANDIDATE_LIST_PATH="$RUN_ROOT/candidate_mainnodeids.txt"
SUMMARY_PATH="$RUN_ROOT/batch_summary.json"
VISUAL_CHECK_DIR="${VISUAL_CHECK_DIR:-$RUN_ROOT/visual_checks}"

WORKERS="${WORKERS:-4}"
DEBUG_FLAG="${DEBUG_FLAG:---debug}"
FAIL_ON_NON_ACCEPTED="${FAIL_ON_NON_ACCEPTED:-0}"
DECODE_BUNDLES="${DECODE_BUNDLES:-1}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if ! [[ "$WORKERS" =~ ^[1-9][0-9]*$ ]]; then
  echo "[BLOCK] WORKERS must be a positive integer: $WORKERS" >&2
  exit 2
fi

if ! [[ "$CASE_SEARCH_MAX_DEPTH" =~ ^[1-9][0-9]*$ ]]; then
  echo "[BLOCK] CASE_SEARCH_MAX_DEPTH must be a positive integer: $CASE_SEARCH_MAX_DEPTH" >&2
  exit 2
fi

if [[ -z "$DIRECT_CASE_REGEX" ]]; then
  echo "[BLOCK] DIRECT_CASE_REGEX must not be empty." >&2
  exit 2
fi

if [[ "$DECODE_BUNDLES" != "0" && "$DECODE_BUNDLES" != "1" ]]; then
  echo "[BLOCK] DECODE_BUNDLES must be 0 or 1: $DECODE_BUNDLES" >&2
  exit 2
fi

if [[ ! -d "$CASE_ROOT" ]]; then
  echo "[BLOCK] CASE_ROOT does not exist: $CASE_ROOT" >&2
  exit 2
fi

mkdir -p "$RUN_ROOT" "$DECODE_ROOT" "$CASES_ROOT" "$CASE_LOG_ROOT" "$VISUAL_CHECK_DIR"
cd "$REPO_DIR"

mapfile -d '' BUNDLE_TXT_PATHS < <(find "$CASE_ROOT" -maxdepth 1 -type f -name "$BUNDLE_GLOB" -print0 | sort -z)

if (( ${#BUNDLE_TXT_PATHS[@]} > 0 )); then
  echo "[RUN] CASE_ROOT bundles discovered: ${#BUNDLE_TXT_PATHS[@]}"
  for bundle_txt in "${BUNDLE_TXT_PATHS[@]}"; do
    bundle_name="$(basename "$bundle_txt")"
    bundle_stem="${bundle_name%.*}"
    decode_dir="$DECODE_ROOT/$bundle_stem"
    echo "[RUN] decode bundle: $bundle_txt -> $decode_dir"
    rm -rf "$decode_dir"
    if [[ "$DECODE_BUNDLES" == "1" ]]; then
      PYTHONPATH=src "$PYTHON_BIN" -m rcsd_topo_poc t02-decode-text-bundle \
        --bundle-txt "$bundle_txt" \
        --out-dir "$decode_dir"
    fi
  done
else
  echo "[RUN] No bundle txt discovered under CASE_ROOT root."
fi

DISCOVERY_JSON="$(
  CASE_ROOT="$CASE_ROOT" \
  DECODE_ROOT="$DECODE_ROOT" \
  CASE_SEARCH_MAX_DEPTH="$CASE_SEARCH_MAX_DEPTH" \
  DIRECT_CASE_REGEX="$DIRECT_CASE_REGEX" \
  "$PYTHON_BIN" - <<'PY'
import json
import os
import re
from pathlib import Path
from typing import Optional


REQUIRED_FILES = {"nodes.gpkg", "roads.gpkg", "drivezone.gpkg", "rcsdroad.gpkg", "rcsdnode.gpkg"}


def is_case_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    names = {child.name for child in path.iterdir() if child.is_file()}
    return REQUIRED_FILES.issubset(names)


def within_depth(root: Path, path: Path, max_depth: int) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return len(relative.parts) <= max_depth


def manifest_mainnodeid(case_dir: Path) -> Optional[str]:
    manifest_path = case_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = manifest.get("mainnodeid")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_case_id(case_dir: Path) -> Optional[str]:
    dirname = case_dir.name.strip()
    if dirname and re.fullmatch(r"[0-9A-Za-z_.-]+", dirname):
        return dirname
    return manifest_mainnodeid(case_dir)


def normalize_root_case_id(case_dir: Path, direct_case_regex: str) -> Optional[str]:
    dirname = case_dir.name.strip()
    if dirname and re.fullmatch(direct_case_regex, dirname):
        return dirname
    return None


def collect(root: Path, max_depth: int, *, root_mode: bool, direct_case_regex: str):
    if not root.is_dir():
        return []
    collected = []
    for path in sorted(root.rglob("*")):
        if not path.is_dir():
            continue
        if not within_depth(root, path, max_depth):
            continue
        if is_case_dir(path):
            case_id = (
                normalize_root_case_id(path, direct_case_regex)
                if root_mode
                else normalize_case_id(path)
            )
            if case_id is None:
                label = "root_case_id_unresolved" if root_mode else "case_id_unresolved"
                raise SystemExit(json.dumps({"error": f"{label}:{path}"}, ensure_ascii=False))
            collected.append({"case_id": case_id, "case_dir": str(path)})
    return collected


case_root = Path(os.environ["CASE_ROOT"])
decode_root = Path(os.environ["DECODE_ROOT"])
max_depth = int(os.environ["CASE_SEARCH_MAX_DEPTH"])
direct_case_regex = os.environ["DIRECT_CASE_REGEX"]

# CASE_ROOT 约定只接受根目录下的 bundle txt 和一级纯数字 mainnodeid case 目录；
# 不向下递归扫描历史嵌套目录，也不把其它目录名当正式 case。
direct_cases = collect(case_root, 1, root_mode=True, direct_case_regex=direct_case_regex)
decoded_cases = collect(decode_root, max_depth, root_mode=False, direct_case_regex=direct_case_regex)

by_case_id = {}
duplicates = {}
for item in [*direct_cases, *decoded_cases]:
    case_id = item["case_id"]
    existing = by_case_id.get(case_id)
    if existing is None:
        by_case_id[case_id] = item
        continue
    if Path(existing["case_dir"]) == Path(item["case_dir"]):
        continue
    duplicates.setdefault(case_id, []).append(item["case_dir"])
    duplicates[case_id].insert(0, existing["case_dir"])

payload = {
    "direct_case_count": len(direct_cases),
    "decoded_case_count": len(decoded_cases),
    "cases": [by_case_id[key] for key in sorted(by_case_id)],
    "duplicates": duplicates,
}
print(json.dumps(payload, ensure_ascii=False))
PY
)"

DISCOVERY_ERROR="$(
  DISCOVERY_JSON="$DISCOVERY_JSON" "$PYTHON_BIN" - <<'PY'
import json
import os

payload = json.loads(os.environ["DISCOVERY_JSON"])
print(payload.get("error", ""))
PY
)"
if [[ -n "$DISCOVERY_ERROR" ]]; then
  echo "[BLOCK] $DISCOVERY_ERROR" >&2
  exit 2
fi

DUPLICATE_CASE_IDS="$(
  DISCOVERY_JSON="$DISCOVERY_JSON" "$PYTHON_BIN" - <<'PY'
import json
import os

payload = json.loads(os.environ["DISCOVERY_JSON"])
for case_id in sorted((payload.get("duplicates") or {}).keys()):
    print(case_id)
PY
)"
if [[ -n "$DUPLICATE_CASE_IDS" ]]; then
  echo "[BLOCK] Duplicate case_id discovered under CASE_ROOT / DECODE_ROOT. Clean the root first:" >&2
  echo "$DUPLICATE_CASE_IDS" >&2
  exit 2
fi

mapfile -t CASE_IDS < <(
  DISCOVERY_JSON="$DISCOVERY_JSON" "$PYTHON_BIN" - <<'PY'
import json
import os

for item in json.loads(os.environ["DISCOVERY_JSON"]).get("cases", []):
    print(item["case_id"])
PY
)

if (( ${#CASE_IDS[@]} == 0 )); then
  echo "[BLOCK] No Stage4 case-package directories were found under CASE_ROOT / decoded bundles." >&2
  exit 3
fi

printf '%s\n' "${CASE_IDS[@]}" > "$CANDIDATE_LIST_PATH"
CASE_MAP_JSON="$(
  DISCOVERY_JSON="$DISCOVERY_JSON" "$PYTHON_BIN" - <<'PY'
import json
import os

mapping = {}
for item in json.loads(os.environ["DISCOVERY_JSON"]).get("cases", []):
    mapping[item["case_id"]] = item["case_dir"]
print(json.dumps(mapping, ensure_ascii=False))
PY
)"

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] CASE_ROOT=$CASE_ROOT"
echo "[RUN] BUNDLE_GLOB=$BUNDLE_GLOB"
echo "[RUN] DECODE_ROOT=$DECODE_ROOT"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
echo "[RUN] RUN_ID=$RUN_ID"
echo "[RUN] RUN_ROOT=$RUN_ROOT"
echo "[RUN] WORKERS=$WORKERS"
echo "[RUN] VISUAL_CHECK_DIR=$VISUAL_CHECK_DIR"
echo "[RUN] CANDIDATE_LIST_PATH=$CANDIDATE_LIST_PATH"
echo "[RUN] SUMMARY_PATH=$SUMMARY_PATH"
echo "[RUN] CASE_IDS=${CASE_IDS[*]}"

CASE_IDS_TEXT="$(printf '%s\n' "${CASE_IDS[@]}")"
CASE_IDS_JSON="$(
  CASE_IDS_TEXT="$CASE_IDS_TEXT" "$PYTHON_BIN" - <<'PY'
import json
import os

print(json.dumps([line.strip() for line in os.environ["CASE_IDS_TEXT"].splitlines() if line.strip()], ensure_ascii=False))
PY
)"

set +e
PYTHONPATH=src \
PYTHON_BIN="$PYTHON_BIN" \
REPO_DIR="$REPO_DIR" \
CASES_ROOT="$CASES_ROOT" \
CASE_LOG_ROOT="$CASE_LOG_ROOT" \
SUMMARY_PATH="$SUMMARY_PATH" \
VISUAL_CHECK_DIR="$VISUAL_CHECK_DIR" \
CASE_IDS_JSON="$CASE_IDS_JSON" \
CASE_MAP_JSON="$CASE_MAP_JSON" \
WORKERS="$WORKERS" \
DEBUG_FLAG="$DEBUG_FLAG" \
"$PYTHON_BIN" - <<'PY'
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


repo_dir = Path(os.environ["REPO_DIR"])
python_bin = os.environ["PYTHON_BIN"]
cases_root = Path(os.environ["CASES_ROOT"])
case_log_root = Path(os.environ["CASE_LOG_ROOT"])
summary_path = Path(os.environ["SUMMARY_PATH"])
visual_check_dir = Path(os.environ["VISUAL_CHECK_DIR"])
case_ids = json.loads(os.environ["CASE_IDS_JSON"])
case_map = json.loads(os.environ["CASE_MAP_JSON"])
workers = int(os.environ["WORKERS"])
debug_enabled = os.environ.get("DEBUG_FLAG", "").strip() == "--debug"


def load_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def run_case(case_id):
    input_dir = Path(case_map[case_id])
    output_dir = cases_root / case_id
    case_log_path = case_log_root / f"{case_id}.log"
    cmd = [
        python_bin,
        "-m",
        "rcsd_topo_poc",
        "t02-stage4-divmerge-virtual-polygon",
        "--nodes-path",
        str(input_dir / "nodes.gpkg"),
        "--roads-path",
        str(input_dir / "roads.gpkg"),
        "--drivezone-path",
        str(input_dir / "drivezone.gpkg"),
        "--rcsdroad-path",
        str(input_dir / "rcsdroad.gpkg"),
        "--rcsdnode-path",
        str(input_dir / "rcsdnode.gpkg"),
        "--mainnodeid",
        case_id,
        "--out-root",
        str(cases_root),
        "--run-id",
        case_id,
    ]
    divstrip_path = input_dir / "divstripzone.gpkg"
    if divstrip_path.is_file():
      cmd.extend(["--divstripzone-path", str(divstrip_path)])
    if debug_enabled:
        cmd.extend(["--debug", "--debug-render-root", str(visual_check_dir)])

    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    case_log_root.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().isoformat(timespec="seconds")
    with case_log_path.open("w", encoding="utf-8") as fp:
        fp.write(f"[START] {started_at}\n")
        fp.write(f"[INPUT] {input_dir}\n")
        fp.write("[CMD] " + " ".join(cmd) + "\n\n")
        fp.flush()
        result = subprocess.run(
            cmd,
            cwd=repo_dir,
            env=env,
            stdout=fp,
            stderr=subprocess.STDOUT,
            text=True,
        )

    status_path = output_dir / "stage4_status.json"
    status_doc = load_json(status_path)
    acceptance_class = str((status_doc or {}).get("acceptance_class") or "")
    acceptance_reason = str((status_doc or {}).get("acceptance_reason") or (status_doc or {}).get("status") or "")
    rendered_map_path = visual_check_dir / f"{case_id}.png"
    return {
        "case_id": case_id,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "log_path": str(case_log_path),
        "rendered_map_png": str(rendered_map_path) if rendered_map_path.is_file() else "",
        "returncode": result.returncode,
        "status_path": str(status_path) if status_path.is_file() else "",
        "status_exists": status_doc is not None,
        "acceptance_class": acceptance_class,
        "acceptance_reason": acceptance_reason,
        "status": (status_doc or {}).get("status"),
        "detail": (status_doc or {}).get("detail"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }


results = []
with ThreadPoolExecutor(max_workers=workers) as executor:
    future_map = {executor.submit(run_case, case_id): case_id for case_id in case_ids}
    for future in as_completed(future_map):
        record = future.result()
        results.append(record)
        print(
            f"[CASE] {record['case_id']} returncode={record['returncode']} "
            f"acceptance_class={record['acceptance_class'] or '-'} "
            f"acceptance_reason={record['acceptance_reason'] or '-'}"
        )
        sys.stdout.flush()

results.sort(key=lambda item: item["case_id"])
accepted = sum(1 for item in results if item["acceptance_class"] == "accepted")
review_required = sum(1 for item in results if item["acceptance_class"] == "review_required")
rejected = sum(1 for item in results if item["acceptance_class"] == "rejected")
unexpected_exit = sum(1 for item in results if item["returncode"] != 0 or not item["status_exists"])

summary = {
    "run_root": str(summary_path.parent),
    "cases_root": str(cases_root),
    "case_log_root": str(case_log_root),
    "visual_check_dir": str(visual_check_dir),
    "selected_case_count": len(case_ids),
    "completed_case_count": len(results),
    "accepted_case_count": accepted,
    "review_required_case_count": review_required,
    "rejected_case_count": rejected,
    "unexpected_exit_case_count": unexpected_exit,
    "finished_at": datetime.now().isoformat(timespec="seconds"),
    "cases": results,
}
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
PY
runner_rc=$?
set -e

if [[ "$runner_rc" -ne 0 ]]; then
  echo "[FAIL] Stage4 Anchor_2 batch runner crashed. See $SUMMARY_PATH and $CASE_LOG_ROOT." >&2
  exit "$runner_rc"
fi

echo "[DONE] Stage4 Anchor_2 batch summary: $SUMMARY_PATH"
echo "[DONE] Stage4 Anchor_2 visual checks directory: $VISUAL_CHECK_DIR"
if [[ "$FAIL_ON_NON_ACCEPTED" == "1" ]]; then
  SUMMARY_PATH="$SUMMARY_PATH" "$PYTHON_BIN" - <<'PY'
import json
import os
import sys
from pathlib import Path

summary = json.loads(Path(os.environ["SUMMARY_PATH"]).read_text(encoding="utf-8"))
if summary.get("accepted_case_count", 0) != summary.get("selected_case_count", 0):
    sys.exit(4)
PY
fi
