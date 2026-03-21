#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


# Windows reference: D:\TestData\POC_Data\first_layer_road_net_v0\A200_road.shp
A200_INPUT_PATH = Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/A200_road.shp")

# Windows reference: D:\TestData\POC_Data\first_layer_road_net_v1_patch\rc_patch_road.shp
RC_PATCH_ROAD_INPUT_PATH = Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v1_patch/rc_patch_road.shp")

# Windows reference: D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch.geojson
OUTPUT_PATH = Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/A200_road_patch.geojson")

# Windows reference: D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch_unmatched.geojson
UNMATCHED_OUTPUT_PATH = Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/A200_road_patch_unmatched.geojson")

TARGET_EPSG = 3857
DEFAULT_INPUT_CRS = f"EPSG:{TARGET_EPSG}"


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

    from rcsd_topo_poc.modules.t00_utility_toolbox import RoadPatchJoinConfig, run_road_patch_join

    try:
        summary = run_road_patch_join(
            RoadPatchJoinConfig(
                a200_input_path=A200_INPUT_PATH,
                rc_patch_road_input_path=RC_PATCH_ROAD_INPUT_PATH,
                output_path=OUTPUT_PATH,
                unmatched_output_path=UNMATCHED_OUTPUT_PATH,
                target_epsg=TARGET_EPSG,
                default_input_crs_text=DEFAULT_INPUT_CRS,
            )
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"run_id={summary['run_id']}")
    print(f"total_a200_count={summary['total_a200_count']}")
    print(f"matched_count={summary['matched_count']}")
    print(f"unmatched_count={summary['unmatched_count']}")
    print(f"duplicate_road_id_count={summary['duplicate_road_id_count']}")
    print(f"conflicting_patch_id_count={summary['conflicting_patch_id_count']}")
    print(f"multi_patch_assignment_count={summary['multi_patch_assignment_count']}")
    print(f"output_path={summary['output_path']}")
    print(f"unmatched_output_path={summary['unmatched_output_path']}")
    print(f"log_path={summary['log_path']}")
    print(f"summary_path={summary['summary_path']}")
    return 0 if summary["unmatched_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
