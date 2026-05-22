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
    parser = argparse.ArgumentParser(description="T08 Tool1: convert one or more Shapefiles to GPKG.")
    parser.add_argument("--input-shp", action="append", required=True, help="Input .shp path. Repeat for multiple inputs.")
    parser.add_argument("--out-dir", required=True, help="Output directory; each input writes <input_stem>.gpkg.")
    parser.add_argument("--summary-output", help="Optional summary JSON output path.")
    parser.add_argument("--target-epsg", type=int, help="Optional target EPSG. Omit to preserve source CRS.")
    parser.add_argument("--default-crs", help="Default CRS for Shapefiles without .prj, e.g. EPSG:4326.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        print("Repo root not found. Expected SPEC.md and src/ above this script.", file=sys.stderr)
        return 2
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from rcsd_topo_poc.modules.t08_preprocess import run_t08_tool1_shp_to_gpkg

    args = _parse_args(argv)
    try:
        summary = run_t08_tool1_shp_to_gpkg(
            input_shp_paths=[Path(value) for value in args.input_shp],
            out_dir=Path(args.out_dir),
            summary_output=Path(args.summary_output) if args.summary_output else None,
            target_epsg=args.target_epsg,
            default_crs_text=args.default_crs,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
