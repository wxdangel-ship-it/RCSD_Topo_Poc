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
        description="T08 Tool10: aggregate all Patch Traj PointZ sources into one LineStringZ GPKG."
    )
    parser.add_argument("--patch-dir", required=True, help="Concrete Patch directory containing Traj/.")
    parser.add_argument("--default-crs", help="Explicit CRS for GeoJSON inputs that do not declare CRS.")
    parser.add_argument(
        "--max-distance-gap-m",
        type=float,
        default=10.0,
        help="Split when projected point distance exceeds this threshold. Default: 10.0.",
    )
    parser.add_argument(
        "--max-time-gap-s",
        type=float,
        default=1.0,
        help="Split when parseable timestamp gap exceeds this threshold. Default: 1.0.",
    )
    parser.add_argument(
        "--max-seq-gap",
        type=int,
        default=20_000_000,
        help="Split when ordering sequence gap exceeds this threshold. Default: 20000000.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Atomically replace existing Tool10 outputs.")
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=10_000,
        help="Print progress after approximately N validated points. Default: 10000.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        print("Repo root not found. Expected SPEC.md and src/ above this script.", file=sys.stderr)
        return 2
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from rcsd_topo_poc.modules.t08_preprocess import run_t08_trajectory_aggregation

    args = _parse_args(argv)
    try:
        artifacts = run_t08_trajectory_aggregation(
            patch_dir=Path(args.patch_dir),
            default_crs_text=args.default_crs,
            max_distance_gap_m=args.max_distance_gap_m,
            max_time_gap_s=args.max_time_gap_s,
            max_seq_gap=args.max_seq_gap,
            overwrite=args.overwrite,
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
