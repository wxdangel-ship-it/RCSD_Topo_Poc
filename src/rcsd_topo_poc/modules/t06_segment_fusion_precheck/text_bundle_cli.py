from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import shlex
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from shapely.geometry import box, mapping
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.io import read_features
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.parsing import (
    ParseError,
    normalize_id,
    parse_id_list,
    parse_positive_int,
    unique_preserve_order,
)

from .schemas import (
    STEP1_CANDIDATES_STEM,
    STEP1_DIR,
    STEP1_FINAL_FUSION_STEM,
    STEP1_REJECTED_STEM,
    STEP1_STATS_CSV,
    STEP1_SUMMARY,
    STEP2_BUFFER_REJECTED_STEM,
    STEP2_BUFFER_SEGMENTS_STEM,
    STEP2_CANDIDATES_STEM,
    STEP2_DIR,
    STEP2_REJECTED_STEM,
    STEP2_REPLACEABLE_STEM,
    STEP2_SUMMARY,
)


T06_TEXT_BUNDLE_VERSION = "1"
T06_TEXT_BUNDLE_TYPE = "t06_segment_fusion_precheck_evidence"
T06_TEXT_BUNDLE_BEGIN = "BEGIN_T06_SEGMENT_FUSION_PRECHECK_BUNDLE"
T06_TEXT_BUNDLE_PAYLOAD = "payload:"
T06_TEXT_BUNDLE_META = "meta: "
T06_TEXT_BUNDLE_CHECKSUM = "checksum: "
T06_TEXT_BUNDLE_END = "END_T06_SEGMENT_FUSION_PRECHECK_BUNDLE"
T06_TEXT_BUNDLE_LINE_WIDTH = 120
T06_TEXT_BUNDLE_LIMIT_BYTES = 250 * 1024

T06_TEXT_BUNDLE_NAME = "t06_segment_fusion_precheck_evidence_bundle.txt"
T06_TEXT_BUNDLE_SIZE_REPORT_NAME = "t06_segment_fusion_precheck_evidence_bundle_size_report.json"
T06_INTERNAL_MANIFEST_NAME = "t06_evidence_manifest.json"
T06_INTERNAL_SIZE_REPORT_NAME = "t06_evidence_size_report.json"
T06_INPUT_MANIFEST_NAME = "t06_input_manifest.json"
T06_REPLAY_COMMAND_NAME = "replay_t06_run_innernet_precheck.sh"
T06_LOCAL_REPLAY_PRECHECK_NAME = "replay_t06_decoded_precheck.sh"
T06_LOCAL_REPLAY_STEP3_NAME = "replay_t06_decoded_step3_segment_replacement.sh"
T06_LOCAL_CASE_MANIFEST_NAME = "t06_local_case_manifest.json"
T06_LOCAL_CASE_README_NAME = "README_t06_local_case.md"
T06_INPUT_SLICE_SUMMARY_NAME = "t06_input_slice_summary.json"
T06_INPUT_SLICE_BUNDLE_NAME = "t06_input_slice_bundle.txt"
T06_INPUT_SLICE_SIZE_REPORT_NAME = "t06_input_slice_bundle_size_report.json"

DEFAULT_RUN_ID = "t06_innernet_precheck"
DEFAULT_SWSD_SEGMENT = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg"
DEFAULT_SWSD_ROADS = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg"
DEFAULT_SWSD_NODES = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg"
DEFAULT_T05_PHASE2_ROOT = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet"
DEFAULT_OUT_ROOT = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck"
T06_INPUT_SLICE_PROFILE_RADII_M = {
    "XXXS": 250.0,
    "XXS": 500.0,
    "XS": 1000.0,
    "S": 2000.0,
    "M": 5000.0,
}
T06_INPUT_SLICE_DEFAULT_PROFILE_ID = "XS"
T06_INPUT_SLICE_CRS_TEXT = "EPSG:3857"

_OUTPUT_STEMS_BY_STEP_DIR = {
    STEP1_DIR: (STEP1_CANDIDATES_STEM, STEP1_FINAL_FUSION_STEM, STEP1_REJECTED_STEM),
    STEP2_DIR: (
        STEP2_CANDIDATES_STEM,
        STEP2_REPLACEABLE_STEM,
        STEP2_REJECTED_STEM,
        STEP2_BUFFER_SEGMENTS_STEM,
        STEP2_BUFFER_REJECTED_STEM,
    ),
}
_SUMMARY_BY_STEP_DIR = {
    STEP1_DIR: STEP1_SUMMARY,
    STEP2_DIR: STEP2_SUMMARY,
}
_OUTPUT_FILES_BY_STEP_DIR = {
    STEP1_DIR: (STEP1_STATS_CSV,),
}
_COMPACT_OUTPUT_SUFFIXES = (".json", ".csv")
_VECTOR_OUTPUT_SUFFIXES = (".gpkg",)
_INPUT_ARCHIVE_NAMES = {
    "swsd_segment_path": "inputs/swsd/segment.gpkg",
    "swsd_roads_path": "inputs/swsd/roads.gpkg",
    "swsd_nodes_path": "inputs/swsd/nodes.gpkg",
    "intersection_match_path": "inputs/t05_phase2/intersection_match_all.geojson",
    "rcsdroad_path": "inputs/t05_phase2/rcsdroad_out.gpkg",
    "rcsdnode_path": "inputs/t05_phase2/rcsdnode_out.gpkg",
}


from .text_bundle import (
    run_t06_decode_text_bundle,
    run_t06_export_input_text_bundle,
    run_t06_export_text_bundle,
)

def _build_export_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t06-export-text-bundle-dev")
    parser.add_argument("--swsd-segment", default=DEFAULT_SWSD_SEGMENT)
    parser.add_argument("--swsd-roads", default=DEFAULT_SWSD_ROADS)
    parser.add_argument("--swsd-nodes", default=DEFAULT_SWSD_NODES)
    parser.add_argument("--t05-phase2-root", default=DEFAULT_T05_PHASE2_ROOT)
    parser.add_argument("--intersection-match", default=None)
    parser.add_argument("--rcsdroad", default=None)
    parser.add_argument("--rcsdnode", default=None)
    parser.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--out-txt")
    parser.add_argument("--max-main-axis-angle-diff-deg", type=float, default=60.0)
    parser.add_argument("--min-coarse-length-ratio", type=float, default=0.4)
    parser.add_argument("--max-coarse-length-ratio", type=float, default=2.5)
    parser.add_argument("--buffer-distance-m", type=float, default=50.0)
    parser.add_argument("--min-buffer-road-overlap-ratio", type=float, default=0.2)
    parser.add_argument("--min-buffer-road-overlap-length-m", type=float, default=1.0)
    parser.add_argument("--advance-right-formway-bit", type=int, default=128)
    parser.add_argument("--include-output-vectors", action="store_true")
    parser.add_argument("--include-input-files", action="store_true")
    parser.add_argument("--extra-path", action="append", default=[])
    parser.add_argument("--max-text-size-bytes", type=int, default=T06_TEXT_BUNDLE_LIMIT_BYTES)
    return parser


def _build_decode_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t06-decode-text-bundle-dev")
    parser.add_argument("--bundle-txt", required=True)
    parser.add_argument("--out-dir")
    return parser


def _build_input_export_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t06-export-input-text-bundle-dev")
    parser.add_argument("--swsd-segment", default=DEFAULT_SWSD_SEGMENT)
    parser.add_argument("--swsd-roads", default=DEFAULT_SWSD_ROADS)
    parser.add_argument("--swsd-nodes", default=DEFAULT_SWSD_NODES)
    parser.add_argument("--t05-phase2-root", default=DEFAULT_T05_PHASE2_ROOT)
    parser.add_argument("--intersection-match", default=None)
    parser.add_argument("--rcsdroad", default=None)
    parser.add_argument("--rcsdnode", default=None)
    parser.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--out-txt")
    parser.add_argument("--center-x", required=True, type=float)
    parser.add_argument("--center-y", required=True, type=float)
    parser.add_argument("--profile-id", default=T06_INPUT_SLICE_DEFAULT_PROFILE_ID)
    parser.add_argument("--size-m", type=float)
    parser.add_argument("--radius-m", type=float)
    parser.add_argument("--max-main-axis-angle-diff-deg", type=float, default=60.0)
    parser.add_argument("--min-coarse-length-ratio", type=float, default=0.4)
    parser.add_argument("--max-coarse-length-ratio", type=float, default=2.5)
    parser.add_argument("--buffer-distance-m", type=float, default=50.0)
    parser.add_argument("--min-buffer-road-overlap-ratio", type=float, default=0.2)
    parser.add_argument("--min-buffer-road-overlap-length-m", type=float, default=1.0)
    parser.add_argument("--advance-right-formway-bit", type=int, default=128)
    parser.add_argument("--include-input-files", action="store_true")
    parser.add_argument("--max-text-size-bytes", type=int, default=T06_TEXT_BUNDLE_LIMIT_BYTES)
    return parser


def run_t06_export_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_export_arg_parser().parse_args(argv)
    artifacts = run_t06_export_text_bundle(
        swsd_segment_path=args.swsd_segment,
        swsd_roads_path=args.swsd_roads,
        swsd_nodes_path=args.swsd_nodes,
        t05_phase2_root=args.t05_phase2_root,
        intersection_match_path=args.intersection_match,
        rcsdroad_path=args.rcsdroad,
        rcsdnode_path=args.rcsdnode,
        out_root=args.out_root,
        run_id=args.run_id,
        out_txt=args.out_txt,
        max_main_axis_angle_diff_deg=args.max_main_axis_angle_diff_deg,
        min_coarse_length_ratio=args.min_coarse_length_ratio,
        max_coarse_length_ratio=args.max_coarse_length_ratio,
        buffer_distance_m=args.buffer_distance_m,
        min_buffer_road_overlap_ratio=args.min_buffer_road_overlap_ratio,
        min_buffer_road_overlap_length_m=args.min_buffer_road_overlap_length_m,
        advance_right_formway_bit=args.advance_right_formway_bit,
        include_output_vectors=args.include_output_vectors,
        include_input_files=args.include_input_files,
        extra_relative_paths=tuple(args.extra_path or ()),
        max_text_size_bytes=args.max_text_size_bytes,
    )
    if not artifacts.success:
        print(f"T06 text bundle export failed: {artifacts.failure_detail}", file=sys.stderr)
        if artifacts.size_report_path is not None:
            print(f"size_report={artifacts.size_report_path}", file=sys.stderr)
        return 1
    print(f"T06 text bundle written to: {artifacts.bundle_txt_path}")
    print(f"bundle_size_bytes={artifacts.bundle_size_bytes}")
    print(f"included_file_count={artifacts.included_file_count}")
    if artifacts.part_txt_paths:
        print(f"bundle_part_count={len(artifacts.part_txt_paths)}")
        print(f"max_part_size_bytes={artifacts.max_part_size_bytes}")
        for path in artifacts.part_txt_paths:
            print(f"bundle_part={path}")
    if artifacts.size_report_path is not None:
        print(f"size_report={artifacts.size_report_path}")
    return 0


def run_t06_decode_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_decode_arg_parser().parse_args(argv)
    artifacts = run_t06_decode_text_bundle(bundle_txt=args.bundle_txt, out_dir=args.out_dir)
    print(f"T06 text bundle decoded to: {artifacts.out_dir}")
    print(f"manifest={artifacts.manifest_path}")
    return 0


def run_t06_export_input_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_input_export_arg_parser().parse_args(argv)
    artifacts = run_t06_export_input_text_bundle(
        swsd_segment_path=args.swsd_segment,
        swsd_roads_path=args.swsd_roads,
        swsd_nodes_path=args.swsd_nodes,
        t05_phase2_root=args.t05_phase2_root,
        intersection_match_path=args.intersection_match,
        rcsdroad_path=args.rcsdroad,
        rcsdnode_path=args.rcsdnode,
        out_root=args.out_root,
        run_id=args.run_id,
        out_txt=args.out_txt,
        center_x=args.center_x,
        center_y=args.center_y,
        profile_id=args.profile_id,
        size_m=args.size_m,
        radius_m=args.radius_m,
        max_main_axis_angle_diff_deg=args.max_main_axis_angle_diff_deg,
        min_coarse_length_ratio=args.min_coarse_length_ratio,
        max_coarse_length_ratio=args.max_coarse_length_ratio,
        buffer_distance_m=args.buffer_distance_m,
        min_buffer_road_overlap_ratio=args.min_buffer_road_overlap_ratio,
        min_buffer_road_overlap_length_m=args.min_buffer_road_overlap_length_m,
        advance_right_formway_bit=args.advance_right_formway_bit,
        include_input_files=args.include_input_files,
        max_text_size_bytes=args.max_text_size_bytes,
    )
    if not artifacts.success:
        print(f"T06 input text bundle export failed: {artifacts.failure_detail}", file=sys.stderr)
        if artifacts.size_report_path is not None:
            print(f"size_report={artifacts.size_report_path}", file=sys.stderr)
        return 1
    print(f"T06 input text bundle written to: {artifacts.bundle_txt_path}")
    print(f"bundle_size_bytes={artifacts.bundle_size_bytes}")
    print(f"included_file_count={artifacts.included_file_count}")
    if artifacts.part_txt_paths:
        print(f"bundle_part_count={len(artifacts.part_txt_paths)}")
        print(f"max_part_size_bytes={artifacts.max_part_size_bytes}")
        for path in artifacts.part_txt_paths:
            print(f"bundle_part={path}")
    if artifacts.size_report_path is not None:
        print(f"size_report={artifacts.size_report_path}")
    return 0
