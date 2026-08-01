#!/usr/bin/env bash
set -Eeuo pipefail

trap 'rc=$?; echo "[ERROR] line=${LINENO} exit=${rc} command=${BASH_COMMAND}" >&2' ERR

cd /mnt/d/Work/RCSD_Topo_Poc

export REPO_DIR="$PWD"
export PYTHON_BIN="$REPO_DIR/.venv/bin/python"
export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

# 内网正式输入；本脚本无需调用者补路径。
export NODES_PATH="/mnt/d/TestData/POC_QA/SWSD/nodes.gpkg"
export ROADS_PATH="/mnt/d/TestData/POC_QA/SWSD/roads.gpkg"
export DRIVEZONE_PATH="/mnt/d/TestData/POC_QA/Patch_vector/DriveZone.gpkg"
export DIVSTRIPZONE_PATH="/mnt/d/TestData/POC_QA/Patch_vector/DivStripZone.gpkg"
export RCSDROAD_PATH="/mnt/d/TestData/POC_QA/FRCSD/RCSDRoad.gpkg"
export RCSDNODE_PATH="/mnt/d/TestData/POC_QA/FRCSD/RCSDNode.gpkg"

export RUN_ID="${RUN_ID:-t03_failed_cases_first50_$(date +%Y%m%d_%H%M%S)}"
export OUT_ROOT="${OUT_ROOT:-$REPO_DIR/outputs/_work/t03_failed_case_bundles}"
export RUN_DIR="$OUT_ROOT/$RUN_ID"
export OUT_TXT="$RUN_DIR/t03_failed_cases_first50.txt"
export DECODE_DIR="$RUN_DIR/decoded"
export ARCHIVE_PATH="$RUN_DIR/t03_failed_cases_first50_bundle.tar.gz"
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

# 前置确认输入角色，并明确接受 1V1 FRCSD 的 snodeId/enodeId/mainNodeId。
"$PYTHON_BIN" - \
  "$NODES_PATH" "$ROADS_PATH" "$RCSDROAD_PATH" "$RCSDNODE_PATH" <<'PY'
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


require("SWSD nodes", sys.argv[1], ("id", "mainnodeid"))
require("SWSD roads", sys.argv[2], ("id", "snodeid", "enodeid", "direction"))
require("RCSDRoad", sys.argv[3], ("id", "snodeid", "enodeid", "direction"))
require("RCSDNode", sys.argv[4], ("id", "mainnodeid"))
PY

echo "[RUN] case_count=${#CASE_IDS[@]}"
echo "[RUN] first_case=${CASE_IDS[0]}"
echo "[RUN] last_case=${CASE_IDS[${#CASE_IDS[@]}-1]}"
echo "[RUN] output=$RUN_DIR"

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
