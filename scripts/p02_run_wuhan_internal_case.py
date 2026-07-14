#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rcsd_topo_poc.modules.p02_wuhan_local_experiment.internal_case_runner import (  # noqa: E402
    run_wuhan_internal_case,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the P02 Wuhan local Case from four raw GeoJSON inputs through "
            "T08, T01, T05, T06 and QGIS project generation."
        )
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        type=Path,
        help="Directory containing node.geojson, road.geojson, RCSDNode.geojson and RCSDRoad.geojson.",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "outputs" / "_work" / "p02_wuhan_local_experiment",
        help="Parent output directory. A new run-id directory is always created.",
    )
    parser.add_argument("--run-id", help="Optional unique run id. Defaults to a timestamped id.")
    parser.add_argument(
        "--qgis-mode",
        choices=("required", "skip"),
        default="required",
        help="QGIS is required by default. Use skip only for developer diagnostics.",
    )
    parser.add_argument(
        "--qgis-python",
        help="Optional python-qgis-ltr/python-qgis executable override.",
    )
    args = parser.parse_args()
    result = run_wuhan_internal_case(
        input_dir=args.input_dir,
        out_root=args.out_root,
        run_id=args.run_id,
        qgis_mode=args.qgis_mode,
        qgis_python=args.qgis_python,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
