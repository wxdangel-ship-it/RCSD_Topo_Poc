#!/usr/bin/env bash

# One-off SpecKit validation artifact; not an official repository entrypoint.
# It always returns 0 so an interactive WSL parent shell remains open.
set -uo pipefail

REPO="${REPO:-/mnt/d/Work/RCSD_Topo_Poc}"
SOURCE_RUN_ROOT="${SOURCE_RUN_ROOT:-/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t10_innernet_full_pipeline/t10_innernet_full_no_t08_20260713_154417}"
STAMP="${STAMP:-$(date +%Y%m%d_%H%M%S)}"
CANDIDATE_RUN_ROOT="${CANDIDATE_RUN_ROOT:-${SOURCE_RUN_ROOT}_t06_perf_candidate_${STAMP}}"
RUN_DOWNSTREAM="${RUN_DOWNSTREAM:-1}"
VALIDATION_DIR="$REPO/specs/t06-innernet-performance-50pct-20260716/validation"
VALIDATE_PY="$VALIDATION_DIR/validate_innernet_candidate.py"
COLLECT_PY="$VALIDATION_DIR/collect_innernet_validation.py"
SOURCE_MANIFEST="$SOURCE_RUN_ROOT/t10_innernet_full_pipeline_manifest.json"
CANDIDATE_MANIFEST="$CANDIDATE_RUN_ROOT/t10_innernet_full_pipeline_manifest.json"
LOG_ROOT="$CANDIDATE_RUN_ROOT/logs"
EVIDENCE_DIR="$LOG_ROOT/t06_perf_validation"
LAUNCHER_LOG="$EVIDENCE_DIR/launcher.log"
STATUS_FILE="$CANDIDATE_RUN_ROOT/t06_perf_validation.status"
PYTHON_BIN="$REPO/.venv/bin/python"

safe_stop() {
  local message="$1"
  echo "[BLOCK] $message" >&2
  echo "[NOTE] No existing result was modified; parent WSL shell remains open." >&2
  exit 0
}

[[ -d "$REPO/.git" ]] || safe_stop "Repository does not exist: $REPO"
[[ -x "$PYTHON_BIN" ]] || safe_stop "Repository Python is not executable: $PYTHON_BIN"
[[ -f "$SOURCE_MANIFEST" ]] || safe_stop "Source manifest does not exist: $SOURCE_MANIFEST"
[[ -f "$VALIDATE_PY" ]] || safe_stop "Validator does not exist: $VALIDATE_PY"
[[ -f "$COLLECT_PY" ]] || safe_stop "Collector does not exist: $COLLECT_PY"
[[ ! -e "$CANDIDATE_RUN_ROOT" ]] || safe_stop "Candidate root already exists: $CANDIDATE_RUN_ROOT"
git -C "$REPO" merge-base --is-ancestor f870a835d5f58731279fc2a1d5d81f43584305e3 HEAD \
  || safe_stop "Current HEAD does not contain frozen baseline f870a83."
grep -q "def _assign_added_rcsd_nodes_to_junction_states" \
  "$REPO/src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_replacement_relation_support.py" \
  || safe_stop "T06 full-scale junction index optimization is absent."

mkdir -p "$EVIDENCE_DIR"
cp -- "$SOURCE_MANIFEST" "$CANDIDATE_MANIFEST"
for source_dir in "$SOURCE_RUN_ROOT"/*/; do
  [[ -d "$source_dir" ]] || continue
  name="$(basename "$source_dir")"
  case "$name" in
    logs|t06_segment_fusion_precheck|t11_manual_relation_review|t09*) continue ;;
  esac
  ln -s -- "$source_dir" "$CANDIDATE_RUN_ROOT/$name"
done

write_status() {
  local status="$1"
  local rc="$2"
  {
    echo "STATUS=$status"
    echo "PIPELINE_RC=$rc"
    echo "UPDATED_AT=$(date --iso-8601=seconds)"
    echo "REPO=$REPO"
    echo "REPO_HEAD=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
    echo "SOURCE_RUN_ROOT=$SOURCE_RUN_ROOT"
    echo "CANDIDATE_RUN_ROOT=$CANDIDATE_RUN_ROOT"
    echo "EVIDENCE_DIR=$EVIDENCE_DIR"
  } >"$STATUS_FILE"
}

write_status RUNNING 0
cd "$REPO" || safe_stop "Cannot enter repository: $REPO"
: >"$LAUNCHER_LOG"

run_pipeline_group() {
  local label="$1"
  local stages="$2"
  local group_log="$EVIDENCE_DIR/${label}.runner.log"
  local time_log="$EVIDENCE_DIR/${label}.time.txt"
  local group_rc
  echo "[GROUP_START] label=$label stages=$stages at=$(date --iso-8601=seconds)" | tee -a "$LAUNCHER_LOG"
  set +e
  RESUME_RUN_ROOT="$CANDIDATE_RUN_ROOT" \
  RUN_STAGES="$stages" \
  RUN_T08=0 \
  SWSD_INPUT_NODES=/mnt/d/TestData/POC_Data/first_layer_road_net_v0/nodes.gpkg \
  SWSD_INPUT_ROADS=/mnt/d/TestData/POC_Data/first_layer_road_net_v0/roads.gpkg \
  DRIVEZONE_PATH=/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  DIVSTRIPZONE_PATH=/mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg \
  RCSD_INTERSECTION_PATH=/mnt/d/TestData/POC_Data/patch_all/RCSDIntersection.gpkg \
  RCSDROAD_PATH=/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  RCSDNODE_PATH=/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  SW_RESTRICTION_TOOL7=/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T08/sw_restriction_tool7.gpkg \
  SW_ARROW_TOOL8=/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T08/sw_arrow_tool8.gpkg \
  LC_ALL=C /usr/bin/time -v -o "$time_log" \
    bash scripts/t10_run_innernet_full_pipeline.sh \
    2>&1 | tee "$group_log" | tee -a "$LAUNCHER_LOG"
  group_rc="${PIPESTATUS[0]}"
  echo "[GROUP_FINISH] label=$label rc=$group_rc at=$(date --iso-8601=seconds) time=$time_log" | tee -a "$LAUNCHER_LOG"
  return "$group_rc"
}

PIPELINE_RC=0
run_pipeline_group t06_step12 t06_step12 || PIPELINE_RC="$?"
if [[ "$PIPELINE_RC" == "0" ]]; then
  run_pipeline_group t06_step3 t06_step3 || PIPELINE_RC="$?"
fi

VALIDATION_RC=99
if [[ "$PIPELINE_RC" == "0" ]]; then
  set +e
  "$PYTHON_BIN" "$VALIDATE_PY" \
    --baseline-run-root "$SOURCE_RUN_ROOT" \
    --candidate-run-root "$CANDIDATE_RUN_ROOT" \
    --out-dir "$EVIDENCE_DIR" \
    2>&1 | tee "$EVIDENCE_DIR/validation.log" | tee -a "$LAUNCHER_LOG"
  VALIDATION_RC="${PIPESTATUS[0]}"
  if [[ "$VALIDATION_RC" != "0" ]]; then
    PIPELINE_RC=90
  fi
fi

if [[ "$PIPELINE_RC" == "0" && "$RUN_DOWNSTREAM" == "1" ]]; then
  run_pipeline_group t11_t09 t11,t09 || PIPELINE_RC="$?"
fi

write_status "$([[ "$PIPELINE_RC" == "0" ]] && echo PASSED || echo FAILED)" "$PIPELINE_RC"
set +e
"$PYTHON_BIN" "$COLLECT_PY" \
  --repo "$REPO" \
  --candidate-run-root "$CANDIDATE_RUN_ROOT" \
  --evidence-dir "$EVIDENCE_DIR" \
  2>&1 | tee "$EVIDENCE_DIR/collect.log" | tee -a "$LAUNCHER_LOG"
COLLECT_RC="${PIPESTATUS[0]}"

echo "[FINISHED] pipeline_rc=$PIPELINE_RC validation_rc=$VALIDATION_RC collect_rc=$COLLECT_RC"
echo "[RESULT] candidate_run_root=$CANDIDATE_RUN_ROOT"
echo "[STATUS] $STATUS_FILE"
echo "[BUNDLE_DIR] $EVIDENCE_DIR/handoff_bundle"
echo "[NOTE] Script returns 0 intentionally; inspect STATUS and validation summary for verdict."
exit 0
