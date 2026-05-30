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
    parser = argparse.ArgumentParser(description="T08 Tool8: build explicit SW lane arrows from Laneinfo.")
    parser.add_argument("--lane-gpkg", required=True, help="Input SW Laneinfo GPKG.")
    parser.add_argument("--swnode-gpkg", required=True, help="Input SW Node GPKG, used for audit.")
    parser.add_argument("--swroad-gpkg", required=True, help="Input SW Road GPKG with road/link ids, directions and geometries.")
    parser.add_argument("--arrow-output", required=True, help="Output explicit lane arrow GPKG; name must end with _tool8.")
    parser.add_argument("--lane-layer", help="Optional Laneinfo layer/table name.")
    parser.add_argument("--swnode-layer", help="Optional SW Node layer name.")
    parser.add_argument("--swroad-layer", help="Optional SW Road layer name.")
    parser.add_argument("--summary-output", help="Optional summary JSON output path; name must end with _tool8.")
    parser.add_argument("--target-epsg", type=int, default=3857, help="Final target EPSG. Default: 3857.")
    parser.add_argument("--swnode-default-crs", help="Default CRS for SW Node input if missing.")
    parser.add_argument("--swroad-default-crs", help="Default CRS for SW Road input if missing.")
    parser.add_argument("--progress-interval", type=int, default=10000, help="Print progress every N output records. Default: 10000.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        print("Repo root not found. Expected SPEC.md and src/ above this script.", file=sys.stderr)
        return 2
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from rcsd_topo_poc.modules.t08_preprocess import run_t08_lane_arrow

    args = _parse_args(argv)
    try:
        artifacts = run_t08_lane_arrow(
            lane_gpkg=Path(args.lane_gpkg),
            swnode_gpkg=Path(args.swnode_gpkg),
            swroad_gpkg=Path(args.swroad_gpkg),
            arrow_output=Path(args.arrow_output),
            lane_layer=args.lane_layer,
            swnode_layer=args.swnode_layer,
            swroad_layer=args.swroad_layer,
            summary_output=Path(args.summary_output) if args.summary_output else None,
            target_epsg=args.target_epsg,
            swnode_default_crs_text=args.swnode_default_crs,
            swroad_default_crs_text=args.swroad_default_crs,
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
