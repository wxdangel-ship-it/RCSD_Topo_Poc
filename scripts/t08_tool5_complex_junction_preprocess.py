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
    parser = argparse.ArgumentParser(description="T08 Tool5: build complex junctions and repair node_error_2 one-to-many junctions.")
    parser.add_argument("--nodes-gpkg", required=True, help="Input Nodes GPKG.")
    parser.add_argument("--roads-gpkg", required=True, help="Input Roads GPKG.")
    parser.add_argument("--nodes-output", required=True, help="Output Nodes GPKG.")
    parser.add_argument("--roads-output", required=True, help="Output Roads GPKG.")
    parser.add_argument("--audit-nodes-output", required=True, help="Output audit Nodes GPKG for nodes touched by Tool5 processes.")
    parser.add_argument("--node-error2-gpkg", help="Optional node_error_2 GPKG for one-to-many repair.")
    parser.add_argument("--intersection-gpkg", help="Optional RCSDIntersection GPKG for one-to-many repair.")
    parser.add_argument("--nodes-layer", help="Optional Nodes input layer name.")
    parser.add_argument("--roads-layer", help="Optional Roads input layer name.")
    parser.add_argument("--node-error2-layer", help="Optional node_error_2 layer name.")
    parser.add_argument("--intersection-layer", help="Optional RCSDIntersection layer name.")
    parser.add_argument("--summary-output", help="Optional summary JSON output path.")
    parser.add_argument("--target-epsg", type=int, default=3857, help="Final target EPSG. Default: 3857.")
    parser.add_argument("--nodes-default-crs", help="Default CRS for Nodes input if missing.")
    parser.add_argument("--roads-default-crs", help="Default CRS for Roads input if missing.")
    parser.add_argument("--node-error2-crs", help="CRS override for node_error_2 input.")
    parser.add_argument("--intersection-crs", help="CRS override for RCSDIntersection input.")
    parser.add_argument("--skip-complex-divmerge", action="store_true", help="Skip complex div/merge junction construction.")
    parser.add_argument("--skip-one-to-many", action="store_true", help="Skip node_error_2 one-to-many repair.")
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

    from rcsd_topo_poc.modules.t08_preprocess import run_t08_complex_junction_preprocess

    args = _parse_args(argv)
    try:
        artifacts = run_t08_complex_junction_preprocess(
            nodes_gpkg=Path(args.nodes_gpkg),
            roads_gpkg=Path(args.roads_gpkg),
            nodes_output=Path(args.nodes_output),
            roads_output=Path(args.roads_output),
            audit_nodes_output=Path(args.audit_nodes_output),
            node_error2_gpkg=Path(args.node_error2_gpkg) if args.node_error2_gpkg else None,
            intersection_gpkg=Path(args.intersection_gpkg) if args.intersection_gpkg else None,
            nodes_layer=args.nodes_layer,
            roads_layer=args.roads_layer,
            node_error2_layer=args.node_error2_layer,
            intersection_layer=args.intersection_layer,
            summary_output=Path(args.summary_output) if args.summary_output else None,
            target_epsg=args.target_epsg,
            nodes_default_crs_text=args.nodes_default_crs,
            roads_default_crs_text=args.roads_default_crs,
            node_error2_crs_text=args.node_error2_crs,
            intersection_crs_text=args.intersection_crs,
            enable_complex_divmerge=not args.skip_complex_divmerge,
            enable_one_to_many=not args.skip_one_to_many,
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
