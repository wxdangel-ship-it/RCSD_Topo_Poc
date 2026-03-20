#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


# Windows reference: D:\TestData\POC_Data\patch_all
PATCH_ALL_ROOT = Path("/mnt/d/TestData/POC_Data/patch_all")

DEFAULT_INPUT_CRS = "EPSG:4326"
SIMPLIFY_TOLERANCE_METERS = 0.3


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

    from rcsd_topo_poc.modules.t00_utility_toolbox import IntersectionMergeConfig, run_intersection_merge

    try:
        summary = run_intersection_merge(
            IntersectionMergeConfig(
                patch_all_root=PATCH_ALL_ROOT,
                default_input_crs_text=DEFAULT_INPUT_CRS,
                simplify_tolerance_meters=SIMPLIFY_TOLERANCE_METERS,
            )
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"run_id={summary['run_id']}")
    print(f"total_patch_count={summary['total_patch_count']}")
    print(f"processed_patch_count={summary['processed_patch_count']}")
    print(f"skip_missing_count={summary['skip_missing_count']}")
    print(f"skip_error_count={summary['skip_error_count']}")
    print(f"output_path={summary['output_path']}")
    print(f"log_path={summary['log_path']}")
    print(f"summary_path={summary['summary_path']}")
    return 0 if summary["skip_error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
