#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-}"

NODES_PATH="${NODES_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg}"
ROADS_PATH="${ROADS_PATH:-/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg}"
DRIVEZONE_PATH="${DRIVEZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg}"
DIVSTRIPZONE_PATH="${DIVSTRIPZONE_PATH:-/mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg}"
RCSDROAD_PATH="${RCSDROAD_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg}"
RCSDNODE_PATH="${RCSDNODE_PATH:-/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg}"

NODES_LAYER="${NODES_LAYER:-}"
NODES_CRS="${NODES_CRS:-}"
ROADS_LAYER="${ROADS_LAYER:-}"
ROADS_CRS="${ROADS_CRS:-}"
DRIVEZONE_LAYER="${DRIVEZONE_LAYER:-}"
DRIVEZONE_CRS="${DRIVEZONE_CRS:-}"
RCSDROAD_LAYER="${RCSDROAD_LAYER:-}"
RCSDROAD_CRS="${RCSDROAD_CRS:-}"
RCSDNODE_LAYER="${RCSDNODE_LAYER:-}"
RCSDNODE_CRS="${RCSDNODE_CRS:-}"

OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t02_stage4_divmerge_full_input_internal}"
RUN_ID="${RUN_ID:-t02_stage4_divmerge_full_input_internal_$(date +%Y%m%d_%H%M%S)}"
WORKERS="${WORKERS:-8}"
MAX_CASES="${MAX_CASES:-}"
DEBUG_FLAG="${DEBUG_FLAG:---debug}"
FAIL_ON_NON_ACCEPTED="${FAIL_ON_NON_ACCEPTED:-0}"

RUN_ROOT="$OUT_ROOT/$RUN_ID"
CASES_ROOT="$RUN_ROOT/cases"
CASE_LOG_ROOT="$RUN_ROOT/case_logs"
CANDIDATE_LIST_PATH="$RUN_ROOT/candidate_mainnodeids.txt"
SUMMARY_PATH="$RUN_ROOT/batch_summary.json"

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

if [[ -n "$MAX_CASES" ]] && ! [[ "$MAX_CASES" =~ ^[1-9][0-9]*$ ]]; then
  echo "[BLOCK] MAX_CASES must be empty or a positive integer: $MAX_CASES" >&2
  exit 2
fi

for path_var in NODES_PATH ROADS_PATH DRIVEZONE_PATH RCSDROAD_PATH RCSDNODE_PATH; do
  path_value="${!path_var}"
  if [[ ! -f "$path_value" ]]; then
    echo "[BLOCK] $path_var does not exist: $path_value" >&2
    exit 2
  fi
done

mkdir -p "$CASES_ROOT" "$CASE_LOG_ROOT"
cd "$REPO_DIR"

mapfile -t CASE_IDS < <(
  PYTHONPATH=src \
  NODES_PATH="$NODES_PATH" \
  NODES_LAYER="$NODES_LAYER" \
  NODES_CRS="$NODES_CRS" \
  MAX_CASES="$MAX_CASES" \
  "$PYTHON_BIN" - <<'PY'
import os
from rcsd_topo_poc.modules.t00_utility_toolbox.common import sort_patch_key
from rcsd_topo_poc.modules.t02_junction_anchor.shared import normalize_id, read_vector_layer_strict


def coerce_int(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "nan"}:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            parsed = float(text)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else None


layer = read_vector_layer_strict(
    os.environ["NODES_PATH"],
    layer_name=os.environ.get("NODES_LAYER") or None,
    crs_override=os.environ.get("NODES_CRS") or None,
    allow_null_geometry=False,
)

case_ids = []
for feature in layer.features:
    props = feature.properties
    node_id = normalize_id(props.get("id"))
    mainnodeid = normalize_id(props.get("mainnodeid"))
    has_evd = normalize_id(props.get("has_evd"))
    is_anchor = normalize_id(props.get("is_anchor"))
    kind_2 = coerce_int(props.get("kind_2"))
    is_representative = (mainnodeid is not None and node_id == mainnodeid) or (mainnodeid is None and node_id is not None)
    if is_representative and has_evd == "yes" and is_anchor == "no" and kind_2 in {8, 16}:
        case_ids.append(mainnodeid or node_id)

case_ids = sorted(set(case_ids), key=sort_patch_key)
max_cases_text = os.environ.get("MAX_CASES", "").strip()
if max_cases_text:
    case_ids = case_ids[: int(max_cases_text)]

for case_id in case_ids:
    print(case_id)
PY
)

if (( ${#CASE_IDS[@]} == 0 )); then
  echo "[BLOCK] No Stage4 eligible mainnodeids were found in NODES_PATH." >&2
  echo "[TIP] Stage4 auto-discovery only keeps representative nodes where has_evd=yes, is_anchor=no, kind_2 in {8, 16}." >&2
  exit 3
fi

printf '%s\n' "${CASE_IDS[@]}" > "$CANDIDATE_LIST_PATH"

echo "[RUN] REPO_DIR=$REPO_DIR"
echo "[RUN] PYTHON_BIN=$PYTHON_BIN"
echo "[RUN] NODES_PATH=$NODES_PATH"
echo "[RUN] ROADS_PATH=$ROADS_PATH"
echo "[RUN] DRIVEZONE_PATH=$DRIVEZONE_PATH"
echo "[RUN] DIVSTRIPZONE_PATH=$DIVSTRIPZONE_PATH"
echo "[RUN] RCSDROAD_PATH=$RCSDROAD_PATH"
echo "[RUN] RCSDNODE_PATH=$RCSDNODE_PATH"
echo "[RUN] OUT_ROOT=$OUT_ROOT"
echo "[RUN] RUN_ID=$RUN_ID"
echo "[RUN] RUN_ROOT=$RUN_ROOT"
echo "[RUN] WORKERS=$WORKERS"
echo "[RUN] MAX_CASES=${MAX_CASES:-<all eligible cases>}"
echo "[RUN] CANDIDATE_LIST_PATH=$CANDIDATE_LIST_PATH"
echo "[RUN] SUMMARY_PATH=$SUMMARY_PATH"
echo "[RUN] Eligible cases are auto-discovered from representative nodes where has_evd=yes, is_anchor=no, kind_2 in {8, 16}."
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
NODES_PATH="$NODES_PATH" \
ROADS_PATH="$ROADS_PATH" \
DRIVEZONE_PATH="$DRIVEZONE_PATH" \
DIVSTRIPZONE_PATH="$DIVSTRIPZONE_PATH" \
RCSDROAD_PATH="$RCSDROAD_PATH" \
RCSDNODE_PATH="$RCSDNODE_PATH" \
NODES_LAYER="$NODES_LAYER" \
NODES_CRS="$NODES_CRS" \
ROADS_LAYER="$ROADS_LAYER" \
ROADS_CRS="$ROADS_CRS" \
DRIVEZONE_LAYER="$DRIVEZONE_LAYER" \
DRIVEZONE_CRS="$DRIVEZONE_CRS" \
RCSDROAD_LAYER="$RCSDROAD_LAYER" \
RCSDROAD_CRS="$RCSDROAD_CRS" \
RCSDNODE_LAYER="$RCSDNODE_LAYER" \
RCSDNODE_CRS="$RCSDNODE_CRS" \
CASES_ROOT="$CASES_ROOT" \
CASE_LOG_ROOT="$CASE_LOG_ROOT" \
SUMMARY_PATH="$SUMMARY_PATH" \
CASE_IDS_JSON="$CASE_IDS_JSON" \
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
case_ids = json.loads(os.environ["CASE_IDS_JSON"])
workers = int(os.environ["WORKERS"])
debug_enabled = os.environ.get("DEBUG_FLAG", "").strip() == "--debug"


def _append_optional_arg(cmd, flag, value):
    if value:
        cmd.extend([flag, value])


def run_case(case_id):
    case_dir = cases_root / case_id
    case_log_path = case_log_root / f"{case_id}.log"
    cmd = [
        python_bin,
        "-m",
        "rcsd_topo_poc",
        "t02-stage4-divmerge-virtual-polygon",
        "--nodes-path",
        os.environ["NODES_PATH"],
        "--roads-path",
        os.environ["ROADS_PATH"],
        "--drivezone-path",
        os.environ["DRIVEZONE_PATH"],
        "--rcsdroad-path",
        os.environ["RCSDROAD_PATH"],
        "--rcsdnode-path",
        os.environ["RCSDNODE_PATH"],
        "--mainnodeid",
        case_id,
        "--out-root",
        str(cases_root),
        "--run-id",
        case_id,
    ]
    _append_optional_arg(cmd, "--nodes-layer", os.environ.get("NODES_LAYER", "").strip())
    _append_optional_arg(cmd, "--nodes-crs", os.environ.get("NODES_CRS", "").strip())
    _append_optional_arg(cmd, "--roads-layer", os.environ.get("ROADS_LAYER", "").strip())
    _append_optional_arg(cmd, "--roads-crs", os.environ.get("ROADS_CRS", "").strip())
    _append_optional_arg(cmd, "--drivezone-layer", os.environ.get("DRIVEZONE_LAYER", "").strip())
    _append_optional_arg(cmd, "--drivezone-crs", os.environ.get("DRIVEZONE_CRS", "").strip())
    divstripzone_path = os.environ.get("DIVSTRIPZONE_PATH", "").strip()
    if divstripzone_path and Path(divstripzone_path).is_file():
        cmd.extend(["--divstripzone-path", divstripzone_path])
    _append_optional_arg(cmd, "--rcsdroad-layer", os.environ.get("RCSDROAD_LAYER", "").strip())
    _append_optional_arg(cmd, "--rcsdroad-crs", os.environ.get("RCSDROAD_CRS", "").strip())
    _append_optional_arg(cmd, "--rcsdnode-layer", os.environ.get("RCSDNODE_LAYER", "").strip())
    _append_optional_arg(cmd, "--rcsdnode-crs", os.environ.get("RCSDNODE_CRS", "").strip())
    if debug_enabled:
        cmd.append("--debug")

    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    case_log_root.mkdir(parents=True, exist_ok=True)
    with case_log_path.open("w", encoding="utf-8") as fp:
        result = subprocess.run(
            cmd,
            cwd=repo_dir,
            env=env,
            stdout=fp,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

    status_path = case_dir / "stage4_status.json"
    status_doc = None
    if status_path.is_file():
        status_doc = json.loads(status_path.read_text(encoding="utf-8"))

    return {
        "mainnodeid": case_id,
        "returncode": result.returncode,
        "case_dir": str(case_dir),
        "case_log": str(case_log_path),
        "status_path": str(status_path),
        "status_doc": status_doc,
    }


started_at = datetime.now().isoformat(timespec="seconds")
rows = []
with ThreadPoolExecutor(max_workers=workers) as executor:
    future_map = {executor.submit(run_case, case_id): case_id for case_id in case_ids}
    for future in as_completed(future_map):
        row = future.result()
        rows.append(row)
        case_id = row["mainnodeid"]
        status_doc = row["status_doc"] or {}
        acceptance_class = status_doc.get("acceptance_class", "missing_status")
        acceptance_reason = status_doc.get("acceptance_reason", "missing_status")
        print(
            f"[CASE] mainnodeid={case_id} returncode={row['returncode']} "
            f"acceptance_class={acceptance_class} acceptance_reason={acceptance_reason}",
            flush=True,
        )

rows.sort(key=lambda item: item["mainnodeid"])
accepted_rows = [row for row in rows if (row["status_doc"] or {}).get("acceptance_class") == "accepted"]
review_rows = [row for row in rows if (row["status_doc"] or {}).get("acceptance_class") == "review_required"]
rejected_rows = [row for row in rows if (row["status_doc"] or {}).get("acceptance_class") == "rejected"]
missing_status_rows = [row for row in rows if row["status_doc"] is None]
unexpected_exit_rows = [row for row in rows if row["returncode"] not in {0, 2}]

summary_doc = {
    "started_at": started_at,
    "finished_at": datetime.now().isoformat(timespec="seconds"),
    "selected_case_count": len(case_ids),
    "accepted_case_count": len(accepted_rows),
    "review_required_case_count": len(review_rows),
    "rejected_case_count": len(rejected_rows),
    "missing_status_case_count": len(missing_status_rows),
    "unexpected_exit_case_count": len(unexpected_exit_rows),
    "rows": [
        {
            "mainnodeid": row["mainnodeid"],
            "returncode": row["returncode"],
            "case_dir": row["case_dir"],
            "case_log": row["case_log"],
            "status_path": row["status_path"],
            "acceptance_class": (row["status_doc"] or {}).get("acceptance_class"),
            "acceptance_reason": (row["status_doc"] or {}).get("acceptance_reason"),
            "success": (row["status_doc"] or {}).get("success"),
            "flow_success": (row["status_doc"] or {}).get("flow_success"),
            "detail": (row["status_doc"] or {}).get("detail"),
        }
        for row in rows
    ],
}
summary_path.write_text(json.dumps(summary_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if unexpected_exit_rows or missing_status_rows:
    sys.exit(2)
sys.exit(0)
PY

batch_exit_code=$?
set -e

echo "[DONE] Stage4 full-input run root: $RUN_ROOT"
echo "[DONE] Stage4 per-case outputs: $CASES_ROOT/<mainnodeid>/"
echo "[DONE] Stage4 batch summary: $SUMMARY_PATH"

if [[ "$FAIL_ON_NON_ACCEPTED" == "1" ]]; then
  non_accepted_count="$(
    SUMMARY_PATH="$SUMMARY_PATH" "$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

summary_path = Path(os.environ["SUMMARY_PATH"])
doc = json.loads(summary_path.read_text(encoding="utf-8"))
print(doc["review_required_case_count"] + doc["rejected_case_count"])
PY
  )"
  if [[ "$non_accepted_count" != "0" ]]; then
    echo "[FAIL] Non-accepted Stage4 cases detected: $non_accepted_count" >&2
    exit 2
  fi
fi

exit "$batch_exit_code"
