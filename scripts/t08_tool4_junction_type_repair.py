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
    parser = argparse.ArgumentParser(description="T08 Tool4: repair semantic junction type errors.")
    parser.add_argument("--nodes-gpkg", required=True, help="Input Nodes GPKG with id/kind_2 fields.")
    parser.add_argument(
        "--roads-gpkg",
        required=True,
        help="Input Roads GPKG with id/snodeid/enodeid/direction fields; optional formway/kind enable degree exceptions.",
    )
    parser.add_argument("--nodes-output", required=True, help="Output repaired full Nodes GPKG.")
    parser.add_argument(
        "--audit-nodes-output",
        required=True,
        help="Output audit Nodes GPKG for repaired semantic junctions.",
    )
    parser.add_argument("--nodes-layer", help="Optional Nodes input layer name.")
    parser.add_argument("--roads-layer", help="Optional Roads input layer name.")
    parser.add_argument("--roads-output", help="Optional output Roads GPKG. Required when Tool6 divmerge repair deletes roads.")
    parser.add_argument("--tool6-node-error-gpkg", help="Optional Tool6 node_error GPKG input.")
    parser.add_argument("--tool6-node-error-csv", help="Optional Tool6 node_error CSV input with manual 是否修复 values.")
    parser.add_argument("--summary-output", help="Optional summary JSON output path.")
    parser.add_argument("--target-epsg", type=int, default=3857, help="Final target EPSG. Default: 3857.")
    parser.add_argument("--nodes-default-crs", help="Default CRS for Nodes input if missing.")
    parser.add_argument("--roads-default-crs", help="Default CRS for Roads input if missing.")
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

    from rcsd_topo_poc.modules.t08_preprocess import run_t08_junction_type_repair

    args = _parse_args(argv)
    try:
        artifacts = run_t08_junction_type_repair(
            nodes_gpkg=Path(args.nodes_gpkg),
            roads_gpkg=Path(args.roads_gpkg),
            nodes_output=Path(args.nodes_output),
            audit_nodes_output=Path(args.audit_nodes_output),
            roads_output=Path(args.roads_output) if args.roads_output else None,
            tool6_node_error_gpkg=Path(args.tool6_node_error_gpkg) if args.tool6_node_error_gpkg else None,
            tool6_node_error_csv=Path(args.tool6_node_error_csv) if args.tool6_node_error_csv else None,
            nodes_layer=args.nodes_layer,
            roads_layer=args.roads_layer,
            summary_output=Path(args.summary_output) if args.summary_output else None,
            target_epsg=args.target_epsg,
            nodes_default_crs_text=args.nodes_default_crs,
            roads_default_crs_text=args.roads_default_crs,
            progress_callback=_print_progress,
            progress_interval=args.progress_interval,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {key: str(value) if value is not None else None for key, value in artifacts.__dict__.items()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
