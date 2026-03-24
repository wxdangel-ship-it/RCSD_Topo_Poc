#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


DEFAULT_INPUT_CRS = None


def _find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "src").is_dir():
            return candidate
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert all top-level GeoJSON files under a directory into sibling GPKG files."
    )
    parser.add_argument("directory", help="Directory containing top-level .geojson files.")
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
        GeoJsonToGpkgDirectoryConfig,
        run_geojson_to_gpkg_directory_export,
    )

    try:
        summary = run_geojson_to_gpkg_directory_export(
            GeoJsonToGpkgDirectoryConfig(
                directory_path=Path(args.directory),
                default_input_crs_text=DEFAULT_INPUT_CRS,
            )
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"run_id={summary['run_id']}")
    print(f"directory_path={summary['directory_path']}")
    print(f"geojson_file_count={summary['geojson_file_count']}")
    print(f"converted_file_count={summary['converted_file_count']}")
    print(f"failed_file_count={summary['failed_file_count']}")
    print(f"log_path={summary['log_path']}")
    print(f"summary_path={summary['summary_path']}")
    return 0 if summary["failed_file_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
