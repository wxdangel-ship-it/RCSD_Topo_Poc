#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Windows reference: D:\TestData\POC_Data\first_layer_road_net_v0\SW\MIF
DEFAULT_INPUT_PATH = Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/SW/MIF")
PROGRESS_INTERVAL = 10000


def _find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "src").is_dir():
            return candidate
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a MIF file, or all top-level MIF files in a directory, into sibling GeoJSON and GPKG files."
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        default=str(DEFAULT_INPUT_PATH),
        help="Input .mif file or directory containing top-level .mif files.",
    )
    parser.add_argument(
        "--default-crs",
        help="Default CRS to use when a MIF has no CRS metadata, for example EPSG:4326.",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=PROGRESS_INTERVAL,
        help="Print progress every N features per output. Default: 10000.",
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
        MifToVectorConfig,
        run_mif_to_vector_export,
    )

    try:
        summary = run_mif_to_vector_export(
            MifToVectorConfig(
                input_path=Path(args.input_path),
                default_crs_text=args.default_crs,
                progress_interval=args.progress_interval,
            )
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed_file_count"] == 0 and summary["total_failed_feature_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
