#!/usr/bin/env bash
set -Eeuo pipefail

trap 'rc=$?; echo "[ERROR] line=${LINENO} exit=${rc} command=${BASH_COMMAND}" >&2' ERR

cd /mnt/d/Work/RCSD_Topo_Poc

export REPO_DIR="$PWD"
export PYTHON_BIN="$REPO_DIR/.venv/bin/python"
export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

# 本批 Case 来自该次 T10 正式运行。必须复用 manifest 记录的 T03 交接输入，
# 尤其是 T07 Step2 Nodes；不得绕过 T01/T07 直接读取原始 SWSD。
export T10_RUN_ROOT="${T10_RUN_ROOT:-/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t10_frcsd_quality_pipeline/t10_frcsd_quality_full_20260731_200542}"
export T10_MANIFEST_PATH="$T10_RUN_ROOT/t10_innernet_full_pipeline_manifest.json"

export RUN_ID="${RUN_ID:-t03_failed_cases_first50_$(date +%Y%m%d_%H%M%S)}"
export OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t03_failed_case_bundles}"
export RUN_DIR="$OUT_ROOT/$RUN_ID"
export OUT_TXT="$RUN_DIR/t03_failed_cases_first50.txt"
export DECODE_DIR="$RUN_DIR/decoded"
export ARCHIVE_PATH="$RUN_DIR/t03_failed_cases_first50_bundle.tar.gz"
export SOURCE_LINEAGE_PATH="$RUN_DIR/t03_failed_cases_first50_source_lineage.json"
export MAX_TEXT_SIZE_BYTES="${MAX_TEXT_SIZE_BYTES:-256000}"

CASE_IDS=(
  705838 706389 706399 708009 709492 723937 724917 759378 768683 787617
  793459 823840 830724 836915 837069 857899 864079 864147 867264 895511
  899127 899588 909265 912232 920721 922146 928650 949246 950770 952797
  954218 991243 992670 992932 994005 994202 995690 995764 997391 998819
  1017385 1019887 1029724 1042709 1049277 1056008 1056150 1062256 1071049 1071119
)

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[BLOCK] Python 不可执行：$PYTHON_BIN" >&2
  exit 2
fi

if [[ ! -f "$T10_MANIFEST_PATH" ]]; then
  echo "[BLOCK] T10 manifest 不存在：$T10_MANIFEST_PATH" >&2
  exit 2
fi

FORMAL_INPUTS_TEXT="$("$PYTHON_BIN" - "$T10_MANIFEST_PATH" "$T10_RUN_ROOT" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
t10_run_root = Path(sys.argv[2])
payload = json.loads(manifest_path.read_text(encoding="utf-8"))
manifest_run_root = payload.get("run_root")
if not manifest_run_root:
    raise SystemExit(f"[BLOCK] T10 manifest 缺少 run_root：{manifest_path}")
if Path(str(manifest_run_root)).resolve() != t10_run_root.resolve():
    raise SystemExit(
        f"[BLOCK] T10 manifest 的 run_root 与指定成果目录不一致："
        f"manifest={manifest_run_root} expected={t10_run_root}"
    )

t03_stage = (payload.get("stages") or {}).get("t03") or {}
t03_status = str(t03_stage.get("status") or "")
if t03_status != "passed":
    raise SystemExit(f"[BLOCK] T10 manifest 中 T03 未通过：status={t03_status or '<missing>'}")

t03_inputs = t03_stage.get("inputs") or {}
root_inputs = payload.get("inputs") or {}
values = {
    "nodes": t03_inputs.get("nodes"),
    "roads": t03_inputs.get("roads"),
    "drivezone": t03_inputs.get("drivezone"),
    "divstripzone": root_inputs.get("divstripzone"),
    "rcsdroad": t03_inputs.get("rcsdroad"),
    "rcsdnode": t03_inputs.get("rcsdnode"),
}
missing = [key for key, value in values.items() if value in (None, "")]
if missing:
    raise SystemExit(f"[BLOCK] T10 manifest 缺少正式输入：{','.join(missing)}")

print(t03_status)
for key in ("nodes", "roads", "drivezone", "divstripzone", "rcsdroad", "rcsdnode"):
    print(values[key])
PY
)"
mapfile -t FORMAL_INPUTS <<<"$FORMAL_INPUTS_TEXT"
if (( ${#FORMAL_INPUTS[@]} != 7 )); then
  echo "[BLOCK] 无法从 T10 manifest 唯一解析 T03 正式输入。" >&2
  exit 2
fi

export T03_STAGE_STATUS="${FORMAL_INPUTS[0]}"
export NODES_PATH="${FORMAL_INPUTS[1]}"
export ROADS_PATH="${FORMAL_INPUTS[2]}"
export DRIVEZONE_PATH="${FORMAL_INPUTS[3]}"
export DIVSTRIPZONE_PATH="${FORMAL_INPUTS[4]}"
export RCSDROAD_PATH="${FORMAL_INPUTS[5]}"
export RCSDNODE_PATH="${FORMAL_INPUTS[6]}"

for path in \
  "$NODES_PATH" \
  "$ROADS_PATH" \
  "$DRIVEZONE_PATH" \
  "$DIVSTRIPZONE_PATH" \
  "$RCSDROAD_PATH" \
  "$RCSDNODE_PATH"; do
  if [[ ! -f "$path" ]]; then
    echo "[BLOCK] 输入不存在：$path" >&2
    exit 2
  fi
done

if [[ -e "$RUN_DIR" ]]; then
  echo "[BLOCK] 输出目录已存在，拒绝覆盖：$RUN_DIR" >&2
  exit 2
fi
mkdir -p "$RUN_DIR"

# 前置确认正式 T03 输入字段及全部 50 个代表节点的候选状态；
# 同时明确接受 1V1 FRCSD 的 snodeId/enodeId/mainNodeId。
"$PYTHON_BIN" - \
  "$NODES_PATH" "$ROADS_PATH" "$RCSDROAD_PATH" "$RCSDNODE_PATH" "${CASE_IDS[@]}" <<'PY'
import sys
from pathlib import Path

import fiona


def fields(path_text: str) -> dict[str, str]:
    path = Path(path_text)
    layers = fiona.listlayers(path)
    if not layers:
        raise SystemExit(f"[BLOCK] 无可读图层：{path}")
    with fiona.open(path, layer=layers[0]) as src:
        return {name.casefold(): name for name in src.schema.get("properties", {})}


def require(label: str, path_text: str, required: tuple[str, ...]) -> None:
    available = fields(path_text)
    missing = [name for name in required if name.casefold() not in available]
    if missing:
        raise SystemExit(f"[BLOCK] {label} 缺少字段：{','.join(missing)}；path={path_text}")
    resolved = ",".join(f"{name}->{available[name.casefold()]}" for name in required)
    print(f"[PASS] {label} fields={resolved}")


def normalize_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        try:
            return str(int(float(text)))
        except ValueError:
            pass
    return text or None


def normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    return text or None


require("T07 Step2 nodes", sys.argv[1], ("id", "mainnodeid", "has_evd", "is_anchor", "kind_2", "grade_2"))
require("SWSD roads", sys.argv[2], ("id", "snodeid", "enodeid", "direction"))
require("RCSDRoad", sys.argv[3], ("id", "snodeid", "enodeid", "direction"))
require("RCSDNode", sys.argv[4], ("id", "mainnodeid"))

case_ids = set(sys.argv[5:])
representatives: dict[str, dict[str, object]] = {}
with fiona.open(sys.argv[1], layer=fiona.listlayers(sys.argv[1])[0]) as src:
    for feature in src:
        properties = {str(key).casefold(): value for key, value in dict(feature["properties"]).items()}
        node_id = normalize_id(properties.get("id"))
        if node_id in case_ids:
            representatives[node_id] = properties

missing_cases = sorted(case_ids - representatives.keys(), key=int)
if missing_cases:
    raise SystemExit(f"[BLOCK] T07 Step2 nodes 缺少代表节点：{','.join(missing_cases)}")

invalid_cases: list[str] = []
for case_id in sorted(case_ids, key=int):
    properties = representatives[case_id]
    mainnodeid = normalize_id(properties.get("mainnodeid"))
    has_evd = normalize_text(properties.get("has_evd"))
    is_anchor = normalize_text(properties.get("is_anchor"))
    try:
        kind_2 = int(float(str(properties.get("kind_2"))))
    except (TypeError, ValueError):
        kind_2 = None
    if mainnodeid not in {None, case_id} or has_evd != "yes" or is_anchor != "no" or kind_2 not in {4, 2048}:
        invalid_cases.append(
            f"{case_id}(mainnodeid={mainnodeid},has_evd={has_evd},is_anchor={is_anchor},kind_2={kind_2})"
        )
if invalid_cases:
    raise SystemExit("[BLOCK] 以下代表节点不满足正式 T03 候选条件：" + ";".join(invalid_cases))
print(f"[PASS] T07 Step2 nodes 中 {len(case_ids)} 个代表节点均满足 T03 候选条件")
PY

CASE_IDS_TEXT="$(printf '%s\n' "${CASE_IDS[@]}")" \
"$PYTHON_BIN" - \
  "$SOURCE_LINEAGE_PATH" "$T10_RUN_ROOT" "$T10_MANIFEST_PATH" "$T03_STAGE_STATUS" \
  "$NODES_PATH" "$ROADS_PATH" "$DRIVEZONE_PATH" "$DIVSTRIPZONE_PATH" "$RCSDROAD_PATH" "$RCSDNODE_PATH" \
  "$(git rev-parse HEAD)" <<'PY'
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    output_path,
    t10_run_root,
    manifest_path,
    t03_stage_status,
    nodes_path,
    roads_path,
    drivezone_path,
    divstripzone_path,
    rcsdroad_path,
    rcsdnode_path,
    repository_commit,
) = sys.argv[1:]
case_ids = [value for value in os.environ["CASE_IDS_TEXT"].splitlines() if value]
manifest_bytes = Path(manifest_path).read_bytes()
payload = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "source_policy": "exact_formal_t03_handoff",
    "repository_commit": repository_commit,
    "t10_run_root": t10_run_root,
    "t10_manifest_path": manifest_path,
    "t10_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    "t03_stage_status": t03_stage_status,
    "inputs": {
        "nodes": {"path": nodes_path, "producer": "T07 Step2"},
        "roads": {"path": roads_path, "producer": "T01"},
        "drivezone": {"path": drivezone_path},
        "divstripzone": {"path": divstripzone_path},
        "rcsdroad": {"path": rcsdroad_path},
        "rcsdnode": {"path": rcsdnode_path},
    },
    "case_count": len(case_ids),
    "case_ids": case_ids,
}
Path(output_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[PASS] 已写入输入来源清单：{output_path}")
PY

echo "[RUN] case_count=${#CASE_IDS[@]}"
echo "[RUN] first_case=${CASE_IDS[0]}"
echo "[RUN] last_case=${CASE_IDS[${#CASE_IDS[@]}-1]}"
echo "[RUN] output=$RUN_DIR"
echo "[RUN] t10_run_root=$T10_RUN_ROOT"
echo "[RUN] t10_manifest=$T10_MANIFEST_PATH"
echo "[RUN] T03_NODES_FROM_T07_STEP2=$NODES_PATH"
echo "[RUN] T03_ROADS_FROM_T01=$ROADS_PATH"

bash scripts/t03_export_text_bundle_internal_multi_mainnodeids.sh \
  --nodes-path "$NODES_PATH" \
  --roads-path "$ROADS_PATH" \
  --drivezone-path "$DRIVEZONE_PATH" \
  --divstripzone-path "$DIVSTRIPZONE_PATH" \
  --rcsdroad-path "$RCSDROAD_PATH" \
  --rcsdnode-path "$RCSDNODE_PATH" \
  --mainnodeid "${CASE_IDS[@]}" \
  --out-txt "$OUT_TXT" \
  --decode-dir "$DECODE_DIR" \
  --decode-after-export 1 \
  --max-text-size-bytes "$MAX_TEXT_SIZE_BYTES"

CASE_IDS_TEXT="$(printf '%s\n' "${CASE_IDS[@]}")" \
"$PYTHON_BIN" - "$DECODE_DIR" <<'PY'
import os
import sys
from pathlib import Path

case_ids = [value.strip() for value in os.environ["CASE_IDS_TEXT"].splitlines() if value.strip()]
decoded = Path(sys.argv[1])
missing = [case_id for case_id in case_ids if not (decoded / case_id / "manifest.json").is_file()]
if missing:
    raise SystemExit(f"[BLOCK] 解包校验缺少 {len(missing)} 个 Case：{','.join(missing)}")
if len(case_ids) != 50:
    raise SystemExit(f"[BLOCK] 脚本 Case 数量不是 50：{len(case_ids)}")
print(f"[PASS] 50 个 Case 均已成功提取并通过解包校验：{decoded}")
PY

# 归档文本 bundle 的全部分片与体量报告，不重复打包 decoded 校验目录。
(
  cd "$RUN_DIR"
  mapfile -d '' BUNDLE_FILES < <(
    find . -maxdepth 1 -type f \
      \( -name 't03_failed_cases_first50*.txt' -o -name 't03_failed_cases_first50*.json' \) \
      -print0
  )
  if (( ${#BUNDLE_FILES[@]} == 0 )); then
    echo "[BLOCK] 未发现可归档的文本 bundle 文件。" >&2
    exit 2
  fi
  printf '%s\0' "${BUNDLE_FILES[@]}" | tar --null -T - -czf "$ARCHIVE_PATH"
)

echo
echo "[DONE] T03 前 50 个失败 Case 已打包并校验"
echo "[RESULT] 文本 bundle 首分片：$OUT_TXT"
echo "[RESULT] 传输归档：$ARCHIVE_PATH"
echo "[RESULT] 解包校验目录：$DECODE_DIR"
echo "[RESULT] 输入来源清单：$SOURCE_LINEAGE_PATH"
