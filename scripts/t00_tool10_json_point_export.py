#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


# Windows reference: D:\TestData\poi\beijing_1334198.json
INPUT_PATH = Path("/mnt/d/TestData/poi/beijing_1334198.json")

# Windows reference: D:\TestData\poi\beijing_1334198.gpkg
OUTPUT_PATH = Path("/mnt/d/TestData/poi/beijing_1334198.gpkg")

OUTPUT_EPSG = 4326
MAX_OUTPUT_FEATURES = 50000
PROGRESS_INTERVAL = 50000


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
        JsonPointToGpkgConfig,
        run_json_point_to_gpkg_export,
    )

    try:
        summary = run_json_point_to_gpkg_export(
            JsonPointToGpkgConfig(
                input_path=INPUT_PATH,
                output_path=OUTPUT_PATH,
                output_epsg=OUTPUT_EPSG,
                max_output_features=MAX_OUTPUT_FEATURES,
                progress_interval=PROGRESS_INTERVAL,
            )
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"run_id={summary['run_id']}")
    print(f"status={summary['status']}")
    print(f"input_format={summary['input_format']}")
    print(f"input_record_count={summary['input_record_count']}")
    print(f"output_feature_count={summary['output_feature_count']}")
    print(f"failed_record_count={summary['failed_record_count']}")
    print(f"source_crs={summary['source_crs']}")
    print(f"output_crs={summary['output_crs']}")
    print(f"max_output_features={summary['max_output_features']}")
    print(f"stopped_by_export_limit={summary['stopped_by_export_limit']}")
    print(f"output_path={summary['output_path']}")
    print(f"log_path={summary['log_path']}")
    print(f"summary_path={summary['summary_path']}")

    if summary["status"] != "completed":
        blocking_reason = summary.get("blocking_reason")
        if blocking_reason:
            print(f"blocking_reason={blocking_reason}", file=sys.stderr)
        return 1
    return 0 if summary["failed_record_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
