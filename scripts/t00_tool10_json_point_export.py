#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


OUTPUT_EPSG = 4326
PROGRESS_INTERVAL = 50000


def _find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "src").is_dir():
            return candidate
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stream pickup spots from a JSON/NDJSON file into one GPKG with all and recommended layers."
        )
    )
    parser.add_argument("input_json", help="Input JSON or NDJSON file path.")
    parser.add_argument(
        "-o",
        "--output",
        help="Output GPKG path. Defaults to the input path with .gpkg suffix.",
    )
    parser.add_argument(
        "--max-output-features",
        type=int,
        default=None,
        help="Optional cap for all pickup spot exports. By default all spots are exported.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

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
                input_path=Path(args.input_json),
                output_path=Path(args.output) if args.output else None,
                output_epsg=OUTPUT_EPSG,
                max_output_features=args.max_output_features,
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
    print(f"spot_candidate_count={summary['spot_candidate_count']}")
    print(f"all_spot_output_count={summary['all_spot_output_count']}")
    print(f"recommended_spot_output_count={summary['recommended_spot_output_count']}")
    print(f"failed_spot_count={summary['failed_spot_count']}")
    print(f"source_crs={summary['source_crs']}")
    print(f"output_crs={summary['output_crs']}")
    print(f"layer_names={summary['layer_names']}")
    print(f"output_path={summary['output_path']}")
    print(f"log_path={summary['log_path']}")
    print(f"summary_path={summary['summary_path']}")

    if summary["status"] != "completed":
        blocking_reason = summary.get("blocking_reason")
        if blocking_reason:
            print(f"blocking_reason={blocking_reason}", file=sys.stderr)
        return 1
    return 0 if summary["failed_spot_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
