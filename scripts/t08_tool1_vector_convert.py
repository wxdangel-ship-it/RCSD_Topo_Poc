#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "src").is_dir():
            return candidate
    return None


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="T08 Tool1: convert SHP/GeoJSON/FGB to GPKG and GPKG to GeoJSON next to each input file with the same stem."
    )
    parser.add_argument("--input-shp", action="append", default=[], help="Input .shp path. Repeat for multiple inputs.")
    parser.add_argument("--input-geojson", action="append", default=[], help="Input .geojson/.json path. Repeat for multiple inputs.")
    parser.add_argument("--input-fgb", action="append", default=[], help="Input .fgb path. Repeat for multiple inputs.")
    parser.add_argument("--input-gpkg", action="append", default=[], help="Input .gpkg path. Repeat for multiple inputs.")
    parser.add_argument("--summary-output", help="Optional summary JSON output path.")
    parser.add_argument("--target-epsg", type=int, help="Optional target EPSG. Omit to preserve source CRS.")
    parser.add_argument("--default-crs", help="Default CRS for inputs without CRS, e.g. EPSG:4326.")
    parser.add_argument("--progress-interval", type=int, default=10000, help="Print progress every N features. Default: 10000.")
    parser.add_argument("--out-dir", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        print("Repo root not found. Expected SPEC.md and src/ above this script.", file=sys.stderr)
        return 2
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from rcsd_topo_poc.modules.t08_preprocess import run_t08_tool1_conversions

    args = _parse_args(argv)
    if args.out_dir:
        print("ERROR: --out-dir is no longer supported; Tool1 writes outputs next to each input file with the converted extension.", file=sys.stderr)
        return 2
    try:
        summary = run_t08_tool1_conversions(
            input_shp_paths=[Path(value) for value in args.input_shp],
            input_geojson_paths=[Path(value) for value in args.input_geojson],
            input_fgb_paths=[Path(value) for value in args.input_fgb],
            input_gpkg_paths=[Path(value) for value in args.input_gpkg],
            summary_output=Path(args.summary_output) if args.summary_output else None,
            target_epsg=args.target_epsg,
            default_crs_text=args.default_crs,
            progress_callback=_print_progress,
            progress_interval=args.progress_interval,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed_count"] == 0 else 1


def _print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
