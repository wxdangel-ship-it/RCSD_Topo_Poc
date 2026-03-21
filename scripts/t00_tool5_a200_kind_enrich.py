#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


# Windows reference: D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch.geojson
A200_PATCH_INPUT_PATH = Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/A200_road_patch.geojson")

# Windows reference: D:\TestData\POC_Data\first_layer_road_net_v0\SW\A200-2025M12-road.geojson
SW_INPUT_PATH = Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/SW/A200-2025M12-road.geojson")

# Windows reference: D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch_kind.geojson
OUTPUT_PATH = Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/A200_road_patch_kind.geojson")

TARGET_EPSG = 3857
A200_PATCH_DEFAULT_CRS = f"EPSG:{TARGET_EPSG}"
SW_DEFAULT_CRS = "EPSG:4326"
BUFFER_DISTANCE_METERS = 1.0
SPATIAL_PREDICATE = "covers"


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

    from rcsd_topo_poc.modules.t00_utility_toolbox import RoadKindEnrichConfig, run_road_kind_enrich

    try:
        summary = run_road_kind_enrich(
            RoadKindEnrichConfig(
                a200_patch_input_path=A200_PATCH_INPUT_PATH,
                sw_input_path=SW_INPUT_PATH,
                output_path=OUTPUT_PATH,
                target_epsg=TARGET_EPSG,
                a200_patch_default_crs_text=A200_PATCH_DEFAULT_CRS,
                sw_default_crs_text=SW_DEFAULT_CRS,
                buffer_distance_meters=BUFFER_DISTANCE_METERS,
                spatial_predicate=SPATIAL_PREDICATE,
            )
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"run_id={summary['run_id']}")
    print(f"total_a200_patch_count={summary['total_a200_patch_count']}")
    print(f"sw_feature_count={summary['sw_feature_count']}")
    print(f"matched_kind_count={summary['matched_kind_count']}")
    print(f"unmatched_kind_count={summary['unmatched_kind_count']}")
    print(f"empty_kind_count={summary['empty_kind_count']}")
    print(f"output_path={summary['output_path']}")
    print(f"log_path={summary['log_path']}")
    print(f"summary_path={summary['summary_path']}")
    return 0 if not summary["error_reason_summary"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
