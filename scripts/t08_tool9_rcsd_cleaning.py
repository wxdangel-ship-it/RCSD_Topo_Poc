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
    parser = argparse.ArgumentParser(description="T08 Tool9: clean RCSD Node/Road by road surface coverage.")
    parser.add_argument("--rcsdnode-gpkg", required=True, help="Input RCSD Node GPKG.")
    parser.add_argument("--rcsdroad-gpkg", required=True, help="Input RCSD Road GPKG.")
    parser.add_argument("--road-surface-gpkg", required=True, help="Input road surface polygon GPKG.")
    parser.add_argument("--nodes-output", required=True, help="Output cleaned RCSD Node GPKG; name must end with _tool9.")
    parser.add_argument("--roads-output", required=True, help="Output cleaned RCSD Road GPKG; name must end with _tool9.")
    parser.add_argument("--rcsdnode-layer", help="Optional RCSD Node layer name.")
    parser.add_argument("--rcsdroad-layer", help="Optional RCSD Road layer name.")
    parser.add_argument("--road-surface-layer", help="Optional road surface layer name.")
    parser.add_argument("--summary-output", help="Optional summary JSON output path; name must end with _tool9.")
    parser.add_argument("--target-epsg", type=int, default=3857, help="Final target EPSG. Default: 3857.")
    parser.add_argument("--rcsdnode-default-crs", help="Default CRS for RCSD Node input if missing.")
    parser.add_argument("--rcsdroad-default-crs", help="Default CRS for RCSD Road input if missing.")
    parser.add_argument("--road-surface-default-crs", help="Default CRS for road surface input if missing.")
    parser.add_argument(
        "--node-predicate",
        choices=("covers", "contains"),
        default="covers",
        help="Spatial predicate for node-in-road-surface test. Default: covers.",
    )
    parser.add_argument("--progress-interval", type=int, default=10000, help="Print progress every N road records. Default: 10000.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        print("Repo root not found. Expected SPEC.md and src/ above this script.", file=sys.stderr)
        return 2
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from rcsd_topo_poc.modules.t08_preprocess import run_t08_rcsd_cleaning

    args = _parse_args(argv)
    try:
        artifacts = run_t08_rcsd_cleaning(
            rcsdnode_gpkg=Path(args.rcsdnode_gpkg),
            rcsdroad_gpkg=Path(args.rcsdroad_gpkg),
            road_surface_gpkg=Path(args.road_surface_gpkg),
            nodes_output=Path(args.nodes_output),
            roads_output=Path(args.roads_output),
            rcsdnode_layer=args.rcsdnode_layer,
            rcsdroad_layer=args.rcsdroad_layer,
            road_surface_layer=args.road_surface_layer,
            summary_output=Path(args.summary_output) if args.summary_output else None,
            target_epsg=args.target_epsg,
            rcsdnode_default_crs_text=args.rcsdnode_default_crs,
            rcsdroad_default_crs_text=args.rcsdroad_default_crs,
            road_surface_default_crs_text=args.road_surface_default_crs,
            node_predicate=args.node_predicate,
            progress_callback=_print_progress,
            progress_interval=args.progress_interval,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({key: str(value) for key, value in artifacts.__dict__.items()}, ensure_ascii=False, indent=2))
    return 0


def _print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
