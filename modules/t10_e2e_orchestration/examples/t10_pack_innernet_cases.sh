#!/usr/bin/env bash
set -euo pipefail

# T10 innernet case evidence packer example.
# This file is an example, not a registered repo entrypoint.
# Run from repo root on the innernet machine after filling the required paths.

REPO_ROOT="${REPO_ROOT:-$(pwd)}"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: PYTHON_BIN is not executable: $PYTHON_BIN" >&2
  exit 2
fi

export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

RADIUS_M="${RADIUS_M:-250}"
OUT_ROOT="${OUT_ROOT:-$REPO_ROOT/outputs/_work/t10_case_evidence}"
BUNDLE_ROOT="${BUNDLE_ROOT:-$REPO_ROOT/outputs/_work/t10_case_evidence_bundles}"
PACKAGE_ID="${PACKAGE_ID:-}"
INCLUDE_FILES="${INCLUDE_FILES:-1}"
MAX_TEXT_SIZE_BYTES="${MAX_TEXT_SIZE_BYTES:-256000}"

case_ids=("$@")
if [[ ${#case_ids[@]} -eq 0 && -n "${CASE_IDS:-}" ]]; then
  IFS=',' read -r -a case_ids <<< "$CASE_IDS"
fi
if [[ ${#case_ids[@]} -eq 0 ]]; then
  echo "ERROR: provide case ids as arguments or CASE_IDS='id1,id2'." >&2
  exit 2
fi

required_env=(
  PREPARED_SWSD_NODES
  PREPARED_SWSD_ROADS
  DRIVEZONE
  DIVSTRIPZONE
  RCSD_INTERSECTION
  RCSDROAD
  RCSDNODE
  SW_RESTRICTION_TOOL7
  SW_ARROW_TOOL8
)

for key in "${required_env[@]}"; do
  value="${!key:-}"
  if [[ -z "$value" ]]; then
    echo "ERROR: missing required env: $key" >&2
    exit 2
  fi
  if [[ ! -f "$value" ]]; then
    echo "ERROR: $key does not point to a file: $value" >&2
    exit 2
  fi
done

mkdir -p "$OUT_ROOT" "$BUNDLE_ROOT"

"$PYTHON_BIN" - "$OUT_ROOT" "$BUNDLE_ROOT" "$RADIUS_M" "$INCLUDE_FILES" "$MAX_TEXT_SIZE_BYTES" "$PACKAGE_ID" "${case_ids[@]}" <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from rcsd_topo_poc.modules.t10_e2e_orchestration import (
    build_multi_case_evidence_package,
    export_t10_case_evidence_text_bundle,
)

out_root = Path(sys.argv[1])
bundle_root = Path(sys.argv[2])
radius_m = float(sys.argv[3])
include_files = sys.argv[4].strip() not in {"0", "false", "False", "no", "NO"}
max_text_size_bytes = int(sys.argv[5])
package_id = sys.argv[6].strip() or None
case_ids = [item.strip() for item in sys.argv[7:] if item.strip()]

manifest = {
    "external_inputs": {
        "prepared_swsd_nodes": os.environ["PREPARED_SWSD_NODES"],
        "prepared_swsd_roads": os.environ["PREPARED_SWSD_ROADS"],
        "drivezone": os.environ["DRIVEZONE"],
        "divstripzone": os.environ["DIVSTRIPZONE"],
        "rcsd_intersection": os.environ["RCSD_INTERSECTION"],
        "rcsdroad": os.environ["RCSDROAD"],
        "rcsdnode": os.environ["RCSDNODE"],
        "sw_restriction_tool7": os.environ["SW_RESTRICTION_TOOL7"],
        "sw_arrow_tool8": os.environ["SW_ARROW_TOOL8"],
    },
    "handoffs": {},
}

package = build_multi_case_evidence_package(
    manifest=manifest,
    out_root=out_root,
    semantic_junction_ids=case_ids,
    radius_m=radius_m,
    package_id=package_id,
    include_files=include_files,
)

bundle_txt = bundle_root / f"{package.package_dir.name}.txt"
bundle = export_t10_case_evidence_text_bundle(
    package_dir=package.package_dir,
    out_txt=bundle_txt,
    max_text_size_bytes=max_text_size_bytes,
)

result = {
    "package_dir": str(package.package_dir),
    "manifest": str(package.manifest_json),
    "summary": str(package.summary_json),
    "bundle_first_part": str(bundle.bundle_txt_path),
    "bundle_parts": [str(path) for path in bundle.part_txt_paths],
    "bundle_size_bytes": bundle.bundle_size_bytes,
    "max_part_size_bytes": bundle.max_part_size_bytes,
    "case_ids": case_ids,
    "radius_m": radius_m,
    "include_files": include_files,
}
print(json.dumps(result, ensure_ascii=False, indent=2))
PY
