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
    parser = argparse.ArgumentParser(description="T08 Tool2: preprocess Road GPKG with patch_id and raw kind.")
    parser.add_argument("--road-gpkg", required=True, help="Input Road GPKG with id field.")
    parser.add_argument("--patch-road-gpkg", required=True, help="Input Patch Road GPKG with road_id and patch_id fields.")
    parser.add_argument("--raw-kind-road-gpkg", required=True, help="Input raw Road GPKG with Kind/kind field.")
    parser.add_argument("--road-layer", help="Optional Road input layer name.")
    parser.add_argument("--patch-road-layer", help="Optional Patch Road input layer name.")
    parser.add_argument("--raw-kind-road-layer", help="Optional raw Kind Road input layer name.")
    parser.add_argument("--road-patch-output", required=True, help="Output GPKG for Road with patch_id.")
    parser.add_argument("--road-patch-unmatched-output", required=True, help="Output GPKG for unmatched Road records.")
    parser.add_argument("--road-patch-kind-output", required=True, help="Output GPKG for Road with patch_id and kind.")
    parser.add_argument(
        "--event-road-0a-output",
        required=True,
        help="Output GPKG for removed Road records whose kind contains 17 road type attribute.",
    )
    parser.add_argument("--patch-summary-output", help="Optional patch join summary JSON path.")
    parser.add_argument("--kind-summary-output", help="Optional kind enrich summary JSON path.")
    parser.add_argument("--summary-output", help="Optional combined summary JSON path.")
    parser.add_argument("--target-epsg", type=int, default=3857, help="Final target EPSG. Default: 3857.")
    parser.add_argument("--road-default-crs", help="Default CRS for Road input if missing.")
    parser.add_argument("--patch-road-default-crs", help="Default CRS for Patch Road input if missing.")
    parser.add_argument("--raw-kind-road-default-crs", help="Default CRS for raw Kind Road input if missing.")
    parser.add_argument("--buffer-distance-meters", type=float, default=1.0, help="Spatial match buffer distance.")
    parser.add_argument("--spatial-predicate", default="covers", help="STRtree spatial predicate. Default: covers.")
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

    from rcsd_topo_poc.modules.t08_preprocess import run_t08_road_preprocess

    args = _parse_args(argv)
    try:
        artifacts = run_t08_road_preprocess(
            road_gpkg=Path(args.road_gpkg),
            patch_road_gpkg=Path(args.patch_road_gpkg),
            raw_kind_road_gpkg=Path(args.raw_kind_road_gpkg),
            road_patch_output=Path(args.road_patch_output),
            road_patch_unmatched_output=Path(args.road_patch_unmatched_output),
            road_patch_kind_output=Path(args.road_patch_kind_output),
            event_road_0a_output=Path(args.event_road_0a_output),
            road_layer=args.road_layer,
            patch_road_layer=args.patch_road_layer,
            raw_kind_road_layer=args.raw_kind_road_layer,
            patch_summary_output=Path(args.patch_summary_output) if args.patch_summary_output else None,
            kind_summary_output=Path(args.kind_summary_output) if args.kind_summary_output else None,
            summary_output=Path(args.summary_output) if args.summary_output else None,
            target_epsg=args.target_epsg,
            road_default_crs_text=args.road_default_crs,
            patch_road_default_crs_text=args.patch_road_default_crs,
            raw_kind_road_default_crs_text=args.raw_kind_road_default_crs,
            buffer_distance_meters=args.buffer_distance_meters,
            spatial_predicate=args.spatial_predicate,
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
