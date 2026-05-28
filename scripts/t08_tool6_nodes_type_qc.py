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
    parser = argparse.ArgumentParser(description="T08 Tool6: QC Nodes semantic junction types without repair.")
    parser.add_argument("--nodes-gpkg", required=True, help="Input Nodes GPKG with id/kind_2 fields.")
    parser.add_argument("--roads-gpkg", required=True, help="Input Roads GPKG with id/snodeid/enodeid/direction fields.")
    parser.add_argument("--csv-output", required=True, help="Output node error CSV; last column is 是否修复, default 1.")
    parser.add_argument("--error-nodes-output", required=True, help="Output node_error Tool6 GPKG for visual review.")
    parser.add_argument("--nodes-layer", help="Optional Nodes input layer name.")
    parser.add_argument("--roads-layer", help="Optional Roads input layer name.")
    parser.add_argument("--summary-output", help="Optional summary JSON output path.")
    parser.add_argument("--target-epsg", type=int, default=3857, help="Final target EPSG. Default: 3857.")
    parser.add_argument("--nodes-default-crs", help="Default CRS for Nodes input if missing.")
    parser.add_argument("--roads-default-crs", help="Default CRS for Roads input if missing.")
    parser.add_argument("--divmerge-search-distance-m", type=float, default=100.0, help="Max divmerge trace distance. Default: 100.")
    parser.add_argument("--vertical-parallel-angle-degrees", type=float, default=20.0, help="Parallel threshold. Default: 20.")
    parser.add_argument("--vertical-endpoint-distance-m", type=float, default=20.0, help="Endpoint distance threshold. Default: 20.")
    parser.add_argument("--horizontal-angle-degrees", type=float, default=35.0, help="Horizontal collinearity threshold. Default: 35.")
    parser.add_argument("--progress-interval", type=int, default=10000, help="Print progress every N features. Default: 10000.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        print("Repo root not found. Expected SPEC.md and src/ above this script.", file=sys.stderr)
        return 2
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from rcsd_topo_poc.modules.t08_preprocess import run_t08_nodes_type_qc

    args = _parse_args(argv)
    try:
        artifacts = run_t08_nodes_type_qc(
            nodes_gpkg=Path(args.nodes_gpkg),
            roads_gpkg=Path(args.roads_gpkg),
            csv_output=Path(args.csv_output),
            error_nodes_output=Path(args.error_nodes_output),
            nodes_layer=args.nodes_layer,
            roads_layer=args.roads_layer,
            summary_output=Path(args.summary_output) if args.summary_output else None,
            target_epsg=args.target_epsg,
            nodes_default_crs_text=args.nodes_default_crs,
            roads_default_crs_text=args.roads_default_crs,
            divmerge_search_distance_m=args.divmerge_search_distance_m,
            vertical_parallel_angle_degrees=args.vertical_parallel_angle_degrees,
            vertical_endpoint_distance_m=args.vertical_endpoint_distance_m,
            horizontal_angle_degrees=args.horizontal_angle_degrees,
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
