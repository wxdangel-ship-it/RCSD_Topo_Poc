#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


# Windows reference: D:\TestData\POC_Data\first_layer_road_net_v0\A200_node.shp
INPUT_PATH = Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/A200_node.shp")

# Windows reference: D:\TestData\POC_Data\first_layer_road_net_v0\nodes.geojson
OUTPUT_PATH = Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/nodes.geojson")

TARGET_EPSG = 3857
DEFAULT_INPUT_CRS = None


def _find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "src").is_dir():
            return candidate
    return None


def main() -> int:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        print("Repo root not found. Expected SPEC.md and src/ above this script.", file=sys.stderr)
        return 2

    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from rcsd_topo_poc.modules.t00_utility_toolbox import (
        ShapefileGeoJsonExportConfig,
        run_shapefile_geojson_export,
    )

    summary = run_shapefile_geojson_export(
        ShapefileGeoJsonExportConfig(
            input_path=INPUT_PATH,
            output_path=OUTPUT_PATH,
            target_epsg=TARGET_EPSG,
            default_input_crs_text=DEFAULT_INPUT_CRS,
        )
    )

    print(f"run_id={summary['run_id']}")
    print(f"status={summary['status']}")
    print(f"input_feature_count={summary['input_feature_count']}")
    print(f"output_feature_count={summary['output_feature_count']}")
    print(f"input_crs={summary['input_crs']}")
    print(f"output_crs={summary['output_crs']}")
    print(f"repaired_feature_count={summary['repaired_feature_count']}")
    print(f"failed_feature_count={summary['failed_feature_count']}")
    print(f"output_path={summary['output_path']}")
    print(f"log_path={summary['log_path']}")
    print(f"summary_path={summary['summary_path']}")

    if summary["status"] != "completed":
        blocking_reason = summary.get("blocking_reason")
        if blocking_reason:
            print(f"blocking_reason={blocking_reason}", file=sys.stderr)
        return 1
    return 0 if summary["failed_feature_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
