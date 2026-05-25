#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rcsd_topo_poc.modules.t06_segment_fusion_precheck import (  # noqa: E402
    run_t06_segment_fusion_precheck,
)


DEFAULT_SWSD_SEGMENT = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg"
DEFAULT_SWSD_ROADS = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg"
DEFAULT_SWSD_NODES = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg"
DEFAULT_T05_PHASE2_ROOT = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet"
DEFAULT_OUT_ROOT = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck"


def main() -> int:
    args = _parse_args()
    t05_phase2_root = Path(args.t05_phase2_root)
    intersection_match = _resolve_file(args.intersection_match, t05_phase2_root, "intersection_match_all.geojson")
    rcsdroad = _resolve_file(args.rcsdroad, t05_phase2_root, "rcsdroad_out.gpkg")
    rcsdnode = _resolve_file(args.rcsdnode, t05_phase2_root, "rcsdnode_out.gpkg")

    inputs = {
        "swsd_segment_path": _require_file(args.swsd_segment),
        "swsd_roads_path": _require_file(args.swsd_roads),
        "swsd_nodes_path": _require_file(args.swsd_nodes),
        "intersection_match_path": intersection_match,
        "rcsdroad_path": rcsdroad,
        "rcsdnode_path": rcsdnode,
    }

    print("[T06 innernet] run Step1 + Step2 segment fusion precheck", flush=True)
    artifacts = run_t06_segment_fusion_precheck(
        swsd_segment_path=inputs["swsd_segment_path"],
        swsd_roads_path=inputs["swsd_roads_path"],
        swsd_nodes_path=inputs["swsd_nodes_path"],
        intersection_match_path=inputs["intersection_match_path"],
        rcsdroad_path=inputs["rcsdroad_path"],
        rcsdnode_path=inputs["rcsdnode_path"],
        out_root=args.out_root,
        run_id=args.run_id,
        max_main_axis_angle_diff_deg=args.max_main_axis_angle_diff_deg,
        min_coarse_length_ratio=args.min_coarse_length_ratio,
        max_coarse_length_ratio=args.max_coarse_length_ratio,
        buffer_distance_m=args.buffer_distance_m,
        min_buffer_road_overlap_ratio=args.min_buffer_road_overlap_ratio,
        min_buffer_road_overlap_length_m=args.min_buffer_road_overlap_length_m,
        advance_right_formway_bit=args.advance_right_formway_bit,
        progress=args.progress,
    )

    step1_summary = _read_json(artifacts.step1.summary_path)
    step2_summary = _read_json(artifacts.step2.summary_path)
    print(
        json.dumps(
            {
                "inputs": {key: str(value) for key, value in inputs.items()},
                "run_id": artifacts.run_id,
                "run_root": str(artifacts.run_root),
                "step1": {
                    "run_root": str(artifacts.step1.step_root),
                    "fusion_units": str(artifacts.step1.fusion_units_gpkg_path),
                    "rejected": str(artifacts.step1.rejected_gpkg_path),
                    "summary": str(artifacts.step1.summary_path),
                    "input_segment_count": step1_summary.get("input_segment_count"),
                    "evd_candidate_count": step1_summary.get("evd_candidate_count"),
                    "final_fusion_unit_count": step1_summary.get("final_fusion_unit_count"),
                    "reject_reason_counts": step1_summary.get("reject_reason_counts"),
                },
                "step2": {
                    "run_root": str(artifacts.step2.step_root),
                    "candidates": str(artifacts.step2.candidates_gpkg_path),
                    "replaceable": str(artifacts.step2.replaceable_gpkg_path),
                    "rejected": str(artifacts.step2.rejected_gpkg_path),
                    "summary": str(artifacts.step2.summary_path),
                    "input_fusion_unit_count": step2_summary.get("input_fusion_unit_count"),
                    "rcsd_candidate_count": step2_summary.get("rcsd_candidate_count"),
                    "replaceable_count": step2_summary.get("replaceable_count"),
                    "rejected_count": step2_summary.get("rejected_count"),
                    "reject_reason_counts": step2_summary.get("reject_reason_counts"),
                    "buffer_segments": step2_summary.get("outputs", {}).get("buffer_segments_gpkg"),
                    "buffer_rejected": step2_summary.get("outputs", {}).get("buffer_rejected_gpkg"),
                    "buffer_segment_count": step2_summary.get("buffer_segment_count"),
                    "buffer_rejected_count": step2_summary.get("buffer_rejected_count"),
                    "buffer_reject_reason_counts": step2_summary.get("buffer_reject_reason_counts"),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run T06 Step1 + Step2 segment fusion precheck on innernet outputs.")
    parser.add_argument("--swsd-segment", default=DEFAULT_SWSD_SEGMENT, help="T01 segment.gpkg path.")
    parser.add_argument("--swsd-roads", default=DEFAULT_SWSD_ROADS, help="SWSD roads.gpkg path used for oneway direction inference.")
    parser.add_argument("--swsd-nodes", default=DEFAULT_SWSD_NODES, help="Final SWSD nodes.gpkg path with has_evd/is_anchor.")
    parser.add_argument("--t05-phase2-root", default=DEFAULT_T05_PHASE2_ROOT, help="T05 Phase 2 run root containing relation and copy-on-write RCSD outputs.")
    parser.add_argument("--intersection-match", default=None, help="Explicit intersection_match_all.geojson path.")
    parser.add_argument("--rcsdroad", default=None, help="Explicit rcsdroad_out.gpkg path.")
    parser.add_argument("--rcsdnode", default=None, help="Explicit rcsdnode_out.gpkg path.")
    parser.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    parser.add_argument("--run-id", default="t06_innernet_precheck")
    parser.add_argument("--max-main-axis-angle-diff-deg", type=float, default=60.0)
    parser.add_argument("--min-coarse-length-ratio", type=float, default=0.4)
    parser.add_argument("--max-coarse-length-ratio", type=float, default=2.5)
    parser.add_argument("--buffer-distance-m", type=float, default=50.0)
    parser.add_argument("--min-buffer-road-overlap-ratio", type=float, default=0.2)
    parser.add_argument("--min-buffer-road-overlap-length-m", type=float, default=1.0)
    parser.add_argument("--advance-right-formway-bit", type=int, default=128)
    parser.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def _resolve_file(explicit_path: str | None, root: Path, filename: str) -> Path:
    if explicit_path:
        return _require_file(explicit_path)
    direct = root / filename
    if direct.is_file():
        return direct
    matches = sorted(root.rglob(filename)) if root.is_dir() else []
    if matches:
        return matches[0]
    raise FileNotFoundError(f"missing {filename} under {root}")


def _require_file(path: str | Path) -> Path:
    resolved = Path(path)
    if resolved.is_file():
        return resolved
    raise FileNotFoundError(f"input file does not exist: {resolved}")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
