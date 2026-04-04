from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from rcsd_topo_poc.protocol.text_lint import lint_text
from rcsd_topo_poc.protocol.text_qc_bundle import build_demo_bundle, qc_bundle_template


REQUIRED_DOCS = [
    "SPEC.md",
    "docs/PROJECT_BRIEF.md",
    "docs/ARTIFACT_PROTOCOL.md",
    "docs/doc-governance/README.md",
    "docs/repository-metadata/README.md",
    "modules/_template/INTERFACE_CONTRACT.md",
]


def _find_repo_root(start: Path) -> Optional[Path]:
    p = start.resolve()
    for candidate in [p, *p.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "docs").is_dir():
            return candidate
    return None


def _cmd_doctor(_args: argparse.Namespace) -> int:
    root = _find_repo_root(Path.cwd())
    print("RCSD_Topo_Poc doctor")

    if root is None:
        print("RepoRoot: NOT_FOUND (need SPEC.md + docs/)")
        return 1

    print("RepoRoot: OK")

    missing = [rel for rel in REQUIRED_DOCS if not (root / rel).exists()]
    if missing:
        print("Docs: MISSING")
        for rel in missing:
            print(f"- {rel}")
        return 1

    print("Docs: OK")

    pyver = sys.version.split()[0]
    print(f"Python: {pyver}")

    try:
        import rcsd_topo_poc as pkg

        print(f"PackageImport: OK (version={pkg.__version__})")
    except Exception:
        print("PackageImport: FAIL")
        return 1

    return 0


def _cmd_qc_template(_args: argparse.Namespace) -> int:
    print(qc_bundle_template())
    return 0


def _cmd_qc_demo(_args: argparse.Namespace) -> int:
    print(build_demo_bundle())
    return 0


def _cmd_lint_text(args: argparse.Namespace) -> int:
    if args.text is not None:
        text = args.text
    else:
        text = sys.stdin.read()

    if not text.strip():
        print("No input text provided.", file=sys.stderr)
        return 2

    ok, violations = lint_text(text)
    if ok:
        print("OK")
        for v in violations:
            if v.startswith("LONG_LINE"):
                print(f"- {v}")
        return 0

    print("NOT_PASTEABLE")
    for v in violations:
        print(f"- {v}")
    return 2


def _cmd_t01_step1_pair_poc(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import run_step1_pair_poc_cli

    return run_step1_pair_poc_cli(args)


def _cmd_t01_step2_segment_poc(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t01_data_preprocess.step2_segment_poc import run_step2_segment_poc_cli

    return run_step2_segment_poc_cli(args)


def _cmd_t01_build_validation_slices(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t01_data_preprocess.slice_builder import run_slice_builder_cli

    return run_slice_builder_cli(args)


def _cmd_t01_s2_refresh_node_road(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import run_s2_baseline_refresh_cli

    return run_s2_baseline_refresh_cli(args)


def _cmd_t01_step4_residual_graph(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t01_data_preprocess.step4_residual_graph import run_step4_residual_graph_cli

    return run_step4_residual_graph_cli(args)


def _cmd_t01_step5_staged_residual_graph(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t01_data_preprocess.step5_staged_residual_graph import (
        run_step5_staged_residual_graph_cli,
    )

    return run_step5_staged_residual_graph_cli(args)


def _cmd_t01_run_skill_v1(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t01_data_preprocess.skill_v1 import run_t01_skill_v1_cli

    return run_t01_skill_v1_cli(args)


def _cmd_t01_continue_oneway_segment(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t01_data_preprocess.skill_v1 import run_t01_skill_v1_continue_oneway_cli

    return run_t01_skill_v1_continue_oneway_cli(args)


def _cmd_t01_step6_segment_aggregation(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t01_data_preprocess.step6_segment_aggregation import (
        run_step6_segment_aggregation_cli,
    )

    return run_step6_segment_aggregation_cli(args)


def _cmd_t01_compare_freeze(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t01_data_preprocess.freeze_compare import run_compare_t01_freeze_cli

    return run_compare_t01_freeze_cli(args)


def _cmd_t02_stage1_drivezone_gate(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t02_junction_anchor.stage1_drivezone_gate import (
        run_t02_stage1_drivezone_gate_cli,
    )

    return run_t02_stage1_drivezone_gate_cli(args)


def _cmd_t02_virtual_intersection_poc(args: argparse.Namespace) -> int:
    if args.input_mode == "full-input":
        from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_full_input_poc import (
            run_t02_virtual_intersection_full_input_poc_cli,
        )

        return run_t02_virtual_intersection_full_input_poc_cli(args)

    if not args.mainnodeid:
        print("--mainnodeid is required when --input-mode case-package.", file=sys.stderr)
        return 2

    from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
        run_t02_virtual_intersection_poc_cli,
    )

    return run_t02_virtual_intersection_poc_cli(args)


def _cmd_t02_export_text_bundle(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t02_junction_anchor.text_bundle import run_t02_export_text_bundle_cli

    return run_t02_export_text_bundle_cli(args)


def _cmd_t02_decode_text_bundle(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t02_junction_anchor.text_bundle import run_t02_decode_text_bundle_cli

    return run_t02_decode_text_bundle_cli(args)


def _cmd_t02_stage2_anchor_recognition(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t02_junction_anchor.stage2_anchor_recognition import (
        run_t02_stage2_anchor_recognition_cli,
    )

    return run_t02_stage2_anchor_recognition_cli(args)


def _cmd_t02_fix_node_error_2(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t02_junction_anchor.fix_node_error_2 import run_t02_fix_node_error_2_cli

    return run_t02_fix_node_error_2_cli(args)


def _cmd_t02_stage4_divmerge_virtual_polygon(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t02_junction_anchor.stage4_divmerge_virtual_polygon import (
        run_t02_stage4_divmerge_virtual_polygon_cli,
    )

    return run_t02_stage4_divmerge_virtual_polygon_cli(args)


def _add_debug_flag(parser: argparse.ArgumentParser, *, default: bool) -> None:
    parser.add_argument(
        "--debug",
        action=argparse.BooleanOptionalAction,
        default=default,
        help="Whether to preserve step-by-step intermediate outputs. Does not change final business results.",
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="rcsd_topo_poc")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Check repo/docs/python environment.")
    p_doctor.set_defaults(func=_cmd_doctor)

    p_tpl = sub.add_parser("qc-template", help="Print TEXT_QC_BUNDLE v1 template.")
    p_tpl.set_defaults(func=_cmd_qc_template)

    p_demo = sub.add_parser("qc-demo", help="Print a demo TEXT_QC_BUNDLE (pasteable + truncated).")
    p_demo.set_defaults(func=_cmd_qc_demo)

    p_lint = sub.add_parser("lint-text", help="Check text pasteability (size/lines/long lines).")
    p_lint.add_argument("--text", help="Text to lint (if omitted, read stdin).")
    p_lint.set_defaults(func=_cmd_lint_text)

    p_t01 = sub.add_parser(
        "t01-step1-pair-poc",
        help="Run T01 Step1 pair-candidate prototype and write QGIS-reviewable outputs.",
    )
    p_t01.add_argument("--road-path", required=True, help="Path to Road GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.")
    p_t01.add_argument("--road-layer", help="Optional road layer name.")
    p_t01.add_argument("--road-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_t01.add_argument("--node-path", required=True, help="Path to Node GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.")
    p_t01.add_argument("--node-layer", help="Optional node layer name.")
    p_t01.add_argument("--node-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_t01.add_argument(
        "--strategy-config",
        action="append",
        required=True,
        help="Strategy config path. Repeat the option to run multiple strategies.",
    )
    p_t01.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t01_step1_pair_poc_YYYYMMDD_HHMMSS.",
    )
    p_t01.add_argument(
        "--out-root",
        help="Optional output root override. If omitted, write to outputs/_work/t01_step1_pair_poc/<run_id>.",
    )
    _add_debug_flag(p_t01, default=True)
    p_t01.set_defaults(func=_cmd_t01_step1_pair_poc)

    p_t02 = sub.add_parser(
        "t01-step2-segment-poc",
        help="Run T01 Step2 Segment POC: validate pair candidates and build reviewable segment outputs.",
    )
    p_t02.add_argument("--road-path", required=True, help="Path to Road GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.")
    p_t02.add_argument("--road-layer", help="Optional road layer name.")
    p_t02.add_argument("--road-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_t02.add_argument("--node-path", required=True, help="Path to Node GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.")
    p_t02.add_argument("--node-layer", help="Optional node layer name.")
    p_t02.add_argument("--node-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_t02.add_argument(
        "--strategy-config",
        action="append",
        required=True,
        help="Step1 strategy config path. Repeat the option to run multiple strategies.",
    )
    p_t02.add_argument(
        "--formway-mode",
        choices=["strict", "audit_only", "off"],
        default="strict",
        help="How Step2 should treat left-turn-only roads when validating trunk roads.",
    )
    p_t02.add_argument(
        "--left-turn-formway-bit",
        type=int,
        default=8,
        help="formway bit index used as left-turn-only lane indicator. Default: 8.",
    )
    p_t02.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t01_step2_segment_poc_YYYYMMDD_HHMMSS.",
    )
    p_t02.add_argument(
        "--trace-validation-pair",
        action="append",
        dest="trace_validation_pair_ids",
        help="Optional Step2 validation pair_id trace filter. Repeat to trace multiple pairs in perf markers.",
    )
    p_t02.add_argument(
        "--only-validation-pair",
        action="append",
        dest="only_validation_pair_ids",
        help="Optional Step2 validation pair_id filter. Repeat to validate only selected pairs after full candidate search.",
    )
    p_t02.add_argument(
        "--validation-pair-index-start",
        type=int,
        help="Optional 1-based Step2 validation pair index start filter, applied after full candidate search.",
    )
    p_t02.add_argument(
        "--validation-pair-index-end",
        type=int,
        help="Optional 1-based Step2 validation pair index end filter, applied after full candidate search.",
    )
    p_t02.add_argument(
        "--assume-working-layers",
        action="store_true",
        help="Treat the provided node/road inputs as already initialized working layers and skip bootstrap initialization.",
    )
    p_t02.add_argument(
        "--out-root",
        help="Optional output root override. If omitted, write to outputs/_work/t01_step2_segment_poc/<run_id>.",
    )
    _add_debug_flag(p_t02, default=True)
    p_t02.set_defaults(func=_cmd_t01_step2_segment_poc)

    p_slice = sub.add_parser(
        "t01-build-validation-slices",
        help="Build T01 validation slice outputs for later Step1/Step2 review runs.",
    )
    p_slice.add_argument("--road-path", required=True, help="Path to Road GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.")
    p_slice.add_argument("--road-layer", help="Optional road layer name.")
    p_slice.add_argument("--road-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_slice.add_argument("--node-path", required=True, help="Path to Node GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.")
    p_slice.add_argument("--node-layer", help="Optional node layer name.")
    p_slice.add_argument("--node-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_slice.add_argument(
        "--profile-config",
        help="Optional slice profile config path. If omitted, use configs/t01_data_preprocess/slice_profiles.json.",
    )
    p_slice.add_argument(
        "--profile-id",
        action="append",
        help="Optional profile id filter. Repeat to run multiple profiles, e.g. --profile-id XS --profile-id S.",
    )
    p_slice.add_argument("--center-x", type=float, help="Optional center x in EPSG:3857 for semantic slice ranking.")
    p_slice.add_argument("--center-y", type=float, help="Optional center y in EPSG:3857 for semantic slice ranking.")
    p_slice.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t01_validation_slices_YYYYMMDD_HHMMSS.",
    )
    p_slice.add_argument(
        "--out-root",
        help="Optional output root override. If omitted, write to outputs/_work/t01_validation_slices/<run_id>.",
    )
    p_slice.set_defaults(func=_cmd_t01_build_validation_slices)

    p_refresh = sub.add_parser(
        "t01-s2-refresh-node-road",
        help="Refresh Node/Road derived fields from the passed Step2 S2 baseline outputs.",
    )
    p_refresh.add_argument(
        "--road-path",
        required=True,
        help="Path to original Road GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_refresh.add_argument("--road-layer", help="Optional road layer name.")
    p_refresh.add_argument("--road-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_refresh.add_argument(
        "--node-path",
        required=True,
        help="Path to original Node GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_refresh.add_argument("--node-layer", help="Optional node layer name.")
    p_refresh.add_argument("--node-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_refresh.add_argument(
        "--s2-path",
        required=True,
        help="Path to the passed Step2 S2 baseline. Can point to the run root or directly to the S2 directory.",
    )
    p_refresh.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t01_s2_refresh_node_road_YYYYMMDD_HHMMSS.",
    )
    p_refresh.add_argument(
        "--out-root",
        help="Optional output root override. If omitted, write to outputs/_work/t01_s2_refresh_node_road/<run_id>.",
    )
    _add_debug_flag(p_refresh, default=True)
    p_refresh.set_defaults(func=_cmd_t01_s2_refresh_node_road)

    p_step4 = sub.add_parser(
        "t01-step4-residual-graph",
        help="Run Step4 residual-graph segment construction on refreshed Node/Road inputs.",
    )
    p_step4.add_argument(
        "--road-path",
        required=True,
        help="Path to refreshed Road GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_step4.add_argument("--road-layer", help="Optional road layer name.")
    p_step4.add_argument("--road-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_step4.add_argument(
        "--node-path",
        required=True,
        help="Path to refreshed Node GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_step4.add_argument("--node-layer", help="Optional node layer name.")
    p_step4.add_argument("--node-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_step4.add_argument(
        "--formway-mode",
        choices=["strict", "audit_only", "off"],
        default="strict",
        help="How Step4 should treat left-turn-only roads when validating trunk roads.",
    )
    p_step4.add_argument(
        "--left-turn-formway-bit",
        type=int,
        default=8,
        help="formway bit index used as left-turn-only lane indicator. Default: 8.",
    )
    p_step4.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t01_step4_residual_graph_YYYYMMDD_HHMMSS.",
    )
    p_step4.add_argument(
        "--out-root",
        help="Optional output root override. If omitted, write to outputs/_work/t01_step4_residual_graph/<run_id>.",
    )
    _add_debug_flag(p_step4, default=True)
    p_step4.set_defaults(func=_cmd_t01_step4_residual_graph)

    p_step5 = sub.add_parser(
        "t01-step5-staged-residual-graph",
        help="Run Step5A/Step5B/Step5C staged residual-graph segment construction on Step4 refreshed inputs.",
    )
    p_step5.add_argument(
        "--road-path",
        required=True,
        help="Path to Step4 refreshed Road GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_step5.add_argument("--road-layer", help="Optional road layer name.")
    p_step5.add_argument("--road-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_step5.add_argument(
        "--node-path",
        required=True,
        help="Path to Step4 refreshed Node GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_step5.add_argument("--node-layer", help="Optional node layer name.")
    p_step5.add_argument("--node-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_step5.add_argument(
        "--formway-mode",
        choices=["strict", "audit_only", "off"],
        default="strict",
        help="How Step5 should treat left-turn-only roads when validating trunk roads.",
    )
    p_step5.add_argument(
        "--left-turn-formway-bit",
        type=int,
        default=8,
        help="formway bit index used as left-turn-only lane indicator. Default: 8.",
    )
    p_step5.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t01_step5_staged_residual_graph_YYYYMMDD_HHMMSS.",
    )
    p_step5.add_argument(
        "--out-root",
        help="Optional output root override. If omitted, write to outputs/_work/t01_step5_staged_residual_graph/<run_id>.",
    )
    _add_debug_flag(p_step5, default=True)
    p_step5.set_defaults(func=_cmd_t01_step5_staged_residual_graph)

    p_skill = sub.add_parser(
        "t01-run-skill-v1",
        help="Run the accepted Step1-Step6 T01 skill pipeline end-to-end with the official debug-aware runner.",
    )
    p_skill.add_argument(
        "--road-path",
        required=True,
        help="Path to input Road GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_skill.add_argument("--road-layer", help="Optional road layer name.")
    p_skill.add_argument("--road-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_skill.add_argument(
        "--node-path",
        required=True,
        help="Path to input Node GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_skill.add_argument("--node-layer", help="Optional node layer name.")
    p_skill.add_argument("--node-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_skill.add_argument(
        "--strategy-config",
        help="Optional Step1/Step2 strategy config path. If omitted, use configs/t01_data_preprocess/step1_pair_s2.json.",
    )
    p_skill.add_argument(
        "--formway-mode",
        choices=["strict", "audit_only", "off"],
        default="strict",
        help="How T01 Skill v1 should treat left-turn-only roads when validating trunk roads.",
    )
    p_skill.add_argument(
        "--left-turn-formway-bit",
        type=int,
        default=8,
        help="formway bit index used as left-turn-only lane indicator. Default: 8.",
    )
    p_skill.add_argument("--compare-freeze-dir", help="Optional frozen baseline package directory for PASS/FAIL compare.")
    p_skill.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t01_skill_v1_YYYYMMDD_HHMMSS.",
    )
    p_skill.add_argument(
        "--trace-validation-pair",
        action="append",
        dest="trace_validation_pair_ids",
        help="Optional Step2 validation pair_id trace filter. Repeat to trace multiple pairs in perf markers.",
    )
    p_skill.add_argument(
        "--stop-after-step2-validation-pair-index",
        type=int,
        dest="stop_after_step2_validation_pair_index",
        help=(
            "Optional diagnostic stop point for the full Skill v1 runner. "
            "Runs the normal full-data path through Step2 validation and stops cleanly "
            "after validating pairs up to the specified 1-based index."
        ),
    )
    p_skill.add_argument(
        "--out-root",
        help="Optional output root override. If omitted, write to outputs/_work/t01_skill_eval/<run_id>.",
    )
    _add_debug_flag(p_skill, default=False)
    p_skill.set_defaults(func=_cmd_t01_run_skill_v1)

    p_continue_oneway = sub.add_parser(
        "t01-continue-oneway-segment",
        help="Continue from an existing Step5 refreshed output directory and run only oneway completion plus Step6.",
    )
    p_continue_oneway.add_argument(
        "--continue-from-dir",
        required=True,
        help=(
            "Path to a previous T01 Skill v1 debug out_root containing debug/step5, a direct debug dir with step2/step4/step5, "
            "or a direct Step5 refreshed output dir that already has Step5 markers plus nodes.gpkg/roads.gpkg."
        ),
    )
    p_continue_oneway.add_argument(
        "--compare-freeze-dir",
        help=(
            "Optional frozen baseline package directory for PASS/FAIL compare. "
            "Only valid when --continue-from-dir points to a previous full Skill v1 out_root."
        ),
    )
    p_continue_oneway.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t01_skill_v1_YYYYMMDD_HHMMSS.",
    )
    p_continue_oneway.add_argument(
        "--out-root",
        help="Output directory for continuation results. Must not overlap the continuation source directory.",
    )
    _add_debug_flag(p_continue_oneway, default=False)
    p_continue_oneway.set_defaults(func=_cmd_t01_continue_oneway_segment)

    p_step6 = sub.add_parser(
        "t01-step6-segment-aggregation-poc",
        help="Build segment.gpkg, inner_nodes.gpkg, and segment_error.gpkg from refreshed Step1-Step6-aligned vector outputs.",
    )
    p_step6.add_argument(
        "--road-path",
        required=True,
        help="Path to refreshed Road GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_step6.add_argument("--road-layer", help="Optional road layer name.")
    p_step6.add_argument("--road-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_step6.add_argument(
        "--node-path",
        required=True,
        help="Path to refreshed Node GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_step6.add_argument("--node-layer", help="Optional node layer name.")
    p_step6.add_argument("--node-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_step6.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t01_step6_segment_aggregation_YYYYMMDD_HHMMSS.",
    )
    p_step6.add_argument(
        "--out-root",
        help="Optional output root override. If omitted, write to outputs/_work/t01_step6_segment_aggregation/<run_id>.",
    )
    _add_debug_flag(p_step6, default=False)
    p_step6.set_defaults(func=_cmd_t01_step6_segment_aggregation)

    p_compare = sub.add_parser(
        "t01-compare-freeze",
        help="Compare a T01 Skill v1 current run output with the frozen XXXS baseline package.",
    )
    p_compare.add_argument("--current-dir", required=True, help="Directory of current T01 Skill v1 run output.")
    p_compare.add_argument("--freeze-dir", required=True, help="Directory of frozen baseline audit package.")
    p_compare.add_argument(
        "--run-id",
        help="Optional compare run id. If omitted, use t01_compare_freeze_YYYYMMDD_HHMMSS.",
    )
    p_compare.add_argument(
        "--out-root",
        help="Optional compare output root override. If omitted, write to outputs/_work/t01_compare_freeze/<run_id>.",
    )
    p_compare.set_defaults(func=_cmd_t01_compare_freeze)

    p_t02_stage1 = sub.add_parser(
        "t02-stage1-drivezone-gate",
        help="Run T02 stage1 DriveZone/has_evd gate and write auditable node/segment outputs.",
    )
    p_t02_stage1.add_argument(
        "--segment-path",
        "--segment_path",
        required=True,
        dest="segment_path",
        help="Path to T01 segment GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage1.add_argument("--segment-layer", help="Optional segment layer name.")
    p_t02_stage1.add_argument("--segment-crs", help="Optional segment CRS override, e.g. EPSG:4326.")
    p_t02_stage1.add_argument(
        "--nodes-path",
        "--nodes_path",
        required=True,
        dest="nodes_path",
        help="Path to T01 nodes GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage1.add_argument("--nodes-layer", help="Optional nodes layer name.")
    p_t02_stage1.add_argument("--nodes-crs", help="Optional nodes CRS override, e.g. EPSG:4326.")
    p_t02_stage1.add_argument(
        "--drivezone-path",
        "--drivezone_path",
        required=True,
        dest="drivezone_path",
        help="Path to DriveZone GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage1.add_argument("--drivezone-layer", help="Optional DriveZone layer name.")
    p_t02_stage1.add_argument("--drivezone-crs", help="Optional DriveZone CRS override, e.g. EPSG:4326.")
    p_t02_stage1.add_argument(
        "--out-root",
        "--out-dir",
        "--out_dir",
        dest="out_root",
        help="Optional output root override. If omitted, write to outputs/_work/t02_stage1_drivezone_gate/<run_id>.",
    )
    p_t02_stage1.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t02_stage1_drivezone_gate_YYYYMMDD_HHMMSS.",
    )
    p_t02_stage1.set_defaults(func=_cmd_t02_stage1_drivezone_gate)

    p_t02_stage2 = sub.add_parser(
        "t02-stage2-anchor-recognition",
        help="Run T02 stage2 anchor recognition on stage1 node outputs and RCSDIntersection inputs.",
    )
    p_t02_stage2.add_argument(
        "--segment-path",
        "--segment_path",
        required=True,
        dest="segment_path",
        help="Path to T01/T02 segment GeoPackage/GeoJSON/Shapefile used for stage2 summary. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage2.add_argument("--segment-crs", help="Optional segment CRS override, e.g. EPSG:4326.")
    p_t02_stage2.add_argument(
        "--nodes-path",
        "--nodes_path",
        required=True,
        dest="nodes_path",
        help="Path to T02 stage1 nodes GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage2.add_argument("--nodes-layer", help="Optional nodes layer name.")
    p_t02_stage2.add_argument("--nodes-crs", help="Optional nodes CRS override, e.g. EPSG:4326.")
    p_t02_stage2.add_argument(
        "--intersection-path",
        "--intersection_path",
        required=True,
        dest="intersection_path",
        help="Path to RCSDIntersection GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage2.add_argument("--intersection-layer", help="Optional RCSDIntersection layer name.")
    p_t02_stage2.add_argument("--intersection-crs", help="Optional RCSDIntersection CRS override, e.g. EPSG:4326.")
    p_t02_stage2.add_argument(
        "--out-root",
        "--out-dir",
        "--out_dir",
        dest="out_root",
        help="Optional output root override. If omitted, write to outputs/_work/t02_stage2_anchor_recognition/<run_id>.",
    )
    p_t02_stage2.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t02_stage2_anchor_recognition_YYYYMMDD_HHMMSS.",
    )
    p_t02_stage2.set_defaults(func=_cmd_t02_stage2_anchor_recognition)

    p_t02_fix_node_error_2 = sub.add_parser(
        "t02-fix-node-error-2",
        help="Run the standalone T02 node_error_2 offline repair tool and write nodes_fix/roads_fix outputs.",
    )
    p_t02_fix_node_error_2.add_argument(
        "--node-error2-path",
        "--node_error2_path",
        required=True,
        dest="node_error2_path",
        help="Path to node_error_2 GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_fix_node_error_2.add_argument("--node-error2-layer", "--node_error2_layer", dest="node_error2_layer", help="Optional node_error_2 layer name.")
    p_t02_fix_node_error_2.add_argument("--node-error2-crs", "--node_error2_crs", dest="node_error2_crs", help="Optional node_error_2 CRS override, e.g. EPSG:4326.")
    p_t02_fix_node_error_2.add_argument(
        "--nodes-path",
        "--nodes_path",
        required=True,
        dest="nodes_path",
        help="Path to nodes GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_fix_node_error_2.add_argument("--nodes-layer", help="Optional nodes layer name.")
    p_t02_fix_node_error_2.add_argument("--nodes-crs", help="Optional nodes CRS override, e.g. EPSG:4326.")
    p_t02_fix_node_error_2.add_argument(
        "--roads-path",
        "--roads_path",
        required=True,
        dest="roads_path",
        help="Path to roads GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_fix_node_error_2.add_argument("--roads-layer", help="Optional roads layer name.")
    p_t02_fix_node_error_2.add_argument("--roads-crs", help="Optional roads CRS override, e.g. EPSG:4326.")
    p_t02_fix_node_error_2.add_argument(
        "--intersection-path",
        "--intersection_path",
        required=True,
        dest="intersection_path",
        help="Path to RCSDIntersection GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_fix_node_error_2.add_argument("--intersection-layer", help="Optional RCSDIntersection layer name.")
    p_t02_fix_node_error_2.add_argument("--intersection-crs", help="Optional RCSDIntersection CRS override, e.g. EPSG:4326.")
    p_t02_fix_node_error_2.add_argument(
        "--nodes-fix-path",
        "--nodes_fix_path",
        required=True,
        dest="nodes_fix_path",
        help="Output path for repaired nodes GeoPackage.",
    )
    p_t02_fix_node_error_2.add_argument(
        "--roads-fix-path",
        "--roads_fix_path",
        required=True,
        dest="roads_fix_path",
        help="Output path for repaired roads GeoPackage.",
    )
    p_t02_fix_node_error_2.add_argument(
        "--report-path",
        "--report_path",
        dest="report_path",
        help="Optional audit JSON output path. Defaults to sibling fix_report.json next to nodes_fix.",
    )
    p_t02_fix_node_error_2.set_defaults(func=_cmd_t02_fix_node_error_2)

    p_t02_stage4 = sub.add_parser(
        "t02-stage4-divmerge-virtual-polygon",
        help="Run T02 stage4 div/merge virtual polygon baseline and write independent polygon/link outputs.",
    )
    p_t02_stage4.add_argument(
        "--nodes-path",
        "--nodes_path",
        required=True,
        dest="nodes_path",
        help="Path to T02 stage2 nodes GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage4.add_argument("--nodes-layer", help="Optional nodes layer name.")
    p_t02_stage4.add_argument("--nodes-crs", help="Optional nodes CRS override, e.g. EPSG:4326.")
    p_t02_stage4.add_argument(
        "--roads-path",
        "--roads_path",
        required=True,
        dest="roads_path",
        help="Path to roads GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage4.add_argument("--roads-layer", help="Optional roads layer name.")
    p_t02_stage4.add_argument("--roads-crs", help="Optional roads CRS override, e.g. EPSG:4326.")
    p_t02_stage4.add_argument(
        "--drivezone-path",
        "--drivezone_path",
        required=True,
        dest="drivezone_path",
        help="Path to DriveZone GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage4.add_argument("--drivezone-layer", help="Optional DriveZone layer name.")
    p_t02_stage4.add_argument("--drivezone-crs", help="Optional DriveZone CRS override, e.g. EPSG:4326.")
    p_t02_stage4.add_argument(
        "--divstripzone-path",
        "--divstripzone_path",
        dest="divstripzone_path",
        help="Optional DivStripZone GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage4.add_argument("--divstripzone-layer", help="Optional DivStripZone layer name.")
    p_t02_stage4.add_argument("--divstripzone-crs", help="Optional DivStripZone CRS override, e.g. EPSG:4326.")
    p_t02_stage4.add_argument(
        "--rcsdroad-path",
        "--rcsdroad_path",
        required=True,
        dest="rcsdroad_path",
        help="Path to RCSDRoad GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage4.add_argument("--rcsdroad-layer", help="Optional RCSDRoad layer name.")
    p_t02_stage4.add_argument("--rcsdroad-crs", help="Optional RCSDRoad CRS override, e.g. EPSG:4326.")
    p_t02_stage4.add_argument(
        "--rcsdnode-path",
        "--rcsdnode_path",
        required=True,
        dest="rcsdnode_path",
        help="Path to RCSDNode GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_stage4.add_argument("--rcsdnode-layer", help="Optional RCSDNode layer name.")
    p_t02_stage4.add_argument("--rcsdnode-crs", help="Optional RCSDNode CRS override, e.g. EPSG:4326.")
    p_t02_stage4.add_argument(
        "--mainnodeid",
        required=True,
        help="Target mainnodeid for the Stage4 div/merge virtual polygon baseline.",
    )
    p_t02_stage4.add_argument(
        "--out-root",
        "--out-dir",
        "--out_dir",
        dest="out_root",
        help="Optional output root override. If omitted, write to outputs/_work/t02_stage4_divmerge_virtual_polygon/<run_id>.",
    )
    p_t02_stage4.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t02_stage4_divmerge_virtual_polygon_YYYYMMDD_HHMMSS.",
    )
    _add_debug_flag(p_t02_stage4, default=False)
    p_t02_stage4.set_defaults(func=_cmd_t02_stage4_divmerge_virtual_polygon)

    p_t02_poc = sub.add_parser(
        "t02-virtual-intersection-poc",
        help="Run T02 virtual intersection POC in case-package mode or unified full-input mode.",
    )
    p_t02_poc.add_argument(
        "--input-mode",
        choices=("case-package", "full-input"),
        default="case-package",
        help="case-package keeps existing single-mainnodeid baseline behavior; full-input unifies shared full-data specified-mainnodeid and auto-discovery modes.",
    )
    p_t02_poc.add_argument("--nodes-path", "--nodes_path", required=True, dest="nodes_path", help="Path to nodes GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.")
    p_t02_poc.add_argument("--nodes-layer", help="Optional nodes layer name.")
    p_t02_poc.add_argument("--nodes-crs", help="Optional nodes CRS override, e.g. EPSG:4326.")
    p_t02_poc.add_argument("--roads-path", "--roads_path", required=True, dest="roads_path", help="Path to roads GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.")
    p_t02_poc.add_argument("--roads-layer", help="Optional roads layer name.")
    p_t02_poc.add_argument("--roads-crs", help="Optional roads CRS override, e.g. EPSG:4326.")
    p_t02_poc.add_argument(
        "--drivezone-path",
        "--drivezone_path",
        required=True,
        dest="drivezone_path",
        help="Path to DriveZone GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_poc.add_argument("--drivezone-layer", help="Optional DriveZone layer name.")
    p_t02_poc.add_argument("--drivezone-crs", help="Optional DriveZone CRS override, e.g. EPSG:4326.")
    p_t02_poc.add_argument(
        "--rcsdroad-path",
        "--rcsdroad_path",
        required=True,
        dest="rcsdroad_path",
        help="Path to RCSDRoad GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_poc.add_argument("--rcsdroad-layer", help="Optional RCSDRoad layer name.")
    p_t02_poc.add_argument("--rcsdroad-crs", help="Optional RCSDRoad CRS override, e.g. EPSG:4326.")
    p_t02_poc.add_argument(
        "--rcsdnode-path",
        "--rcsdnode_path",
        required=True,
        dest="rcsdnode_path",
        help="Path to RCSDNode GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_poc.add_argument("--rcsdnode-layer", help="Optional RCSDNode layer name.")
    p_t02_poc.add_argument("--rcsdnode-crs", help="Optional RCSDNode CRS override, e.g. EPSG:4326.")
    p_t02_poc.add_argument(
        "--mainnodeid",
        help="Single target mainnodeid. Required in case-package mode; optional in full-input mode where omission triggers auto-discovery.",
    )
    p_t02_poc.add_argument(
        "--out-root",
        "--out-dir",
        "--out_dir",
        dest="out_root",
        help="Optional output root override. If omitted, write to outputs/_work/t02_virtual_intersection_poc/<run_id>.",
    )
    p_t02_poc.add_argument("--run-id", help="Optional run id. If omitted, use t02_virtual_intersection_poc_YYYYMMDD_HHMMSS.")
    p_t02_poc.add_argument(
        "--max-cases",
        type=int,
        help="Full-input mode only. Maximum number of auto-discovered mainnodeids to process after stable sorting.",
    )
    p_t02_poc.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Full-input mode only. Number of parallel case workers. Default: 1.",
    )
    p_t02_poc.add_argument("--buffer-m", type=float, default=100.0, help="Local query buffer in meters. Default: 100.")
    p_t02_poc.add_argument("--patch-size-m", type=float, default=200.0, help="North-up patch size in meters. Default: 200.")
    p_t02_poc.add_argument("--resolution-m", type=float, default=0.2, help="Raster resolution in meters. Default: 0.2.")
    p_t02_poc.add_argument(
        "--debug-render-root",
        help="Optional debug render output root. When set with --debug, all rendered PNGs are written under this directory instead of the default sibling _rendered_maps folder.",
    )
    p_t02_poc.add_argument(
        "--review-mode",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Review-only mode for case analysis. Keeps strict defaults unless enabled, then bypasses anchor gate and soft-excludes RC features outside DriveZone.",
    )
    _add_debug_flag(p_t02_poc, default=False)
    p_t02_poc.set_defaults(func=_cmd_t02_virtual_intersection_poc)

    p_t02_export = sub.add_parser(
        "t02-export-text-bundle",
        help="Export a single- or multi-mainnodeid T02 text bundle for external reproduction.",
    )
    p_t02_export.add_argument("--nodes-path", "--nodes_path", required=True, dest="nodes_path", help="Path to nodes GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.")
    p_t02_export.add_argument("--nodes-layer", help="Optional nodes layer name.")
    p_t02_export.add_argument("--nodes-crs", help="Optional nodes CRS override, e.g. EPSG:4326.")
    p_t02_export.add_argument("--roads-path", "--roads_path", required=True, dest="roads_path", help="Path to roads GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.")
    p_t02_export.add_argument("--roads-layer", help="Optional roads layer name.")
    p_t02_export.add_argument("--roads-crs", help="Optional roads CRS override, e.g. EPSG:4326.")
    p_t02_export.add_argument(
        "--drivezone-path",
        "--drivezone_path",
        required=True,
        dest="drivezone_path",
        help="Path to DriveZone GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_export.add_argument("--drivezone-layer", help="Optional DriveZone layer name.")
    p_t02_export.add_argument("--drivezone-crs", help="Optional DriveZone CRS override, e.g. EPSG:4326.")
    p_t02_export.add_argument(
        "--divstripzone-path",
        "--divstripzone_path",
        dest="divstripzone_path",
        help="Optional DivStripZone GeoPackage/GeoJSON/Shapefile to include in the text bundle. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_export.add_argument("--divstripzone-layer", help="Optional DivStripZone layer name.")
    p_t02_export.add_argument("--divstripzone-crs", help="Optional DivStripZone CRS override, e.g. EPSG:4326.")
    p_t02_export.add_argument(
        "--rcsdroad-path",
        "--rcsdroad_path",
        required=True,
        dest="rcsdroad_path",
        help="Path to RCSDRoad GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_export.add_argument("--rcsdroad-layer", help="Optional RCSDRoad layer name.")
    p_t02_export.add_argument("--rcsdroad-crs", help="Optional RCSDRoad CRS override, e.g. EPSG:4326.")
    p_t02_export.add_argument(
        "--rcsdnode-path",
        "--rcsdnode_path",
        required=True,
        dest="rcsdnode_path",
        help="Path to RCSDNode GeoPackage/GeoJSON/Shapefile. Same-name .gpkg is preferred; legacy .gpkt is still accepted.",
    )
    p_t02_export.add_argument("--rcsdnode-layer", help="Optional RCSDNode layer name.")
    p_t02_export.add_argument("--rcsdnode-crs", help="Optional RCSDNode CRS override, e.g. EPSG:4326.")
    p_t02_export.add_argument("--mainnodeid", required=True, nargs="+", help="One or more target mainnodeids for the text bundle.")
    p_t02_export.add_argument("--out-txt", "--out_txt", required=True, dest="out_txt", help="Single text bundle output path.")
    p_t02_export.add_argument("--buffer-m", type=float, default=100.0, help="Local query buffer in meters. Default: 100.")
    p_t02_export.add_argument("--patch-size-m", type=float, default=200.0, help="North-up patch size in meters. Default: 200.")
    p_t02_export.add_argument("--resolution-m", type=float, default=0.2, help="Raster resolution in meters. Default: 0.2.")
    p_t02_export.set_defaults(func=_cmd_t02_export_text_bundle)

    p_t02_decode = sub.add_parser(
        "t02-decode-text-bundle",
        help="Decode a single- or multi-mainnodeid T02 text bundle into local directories.",
    )
    p_t02_decode.add_argument("--bundle-txt", "--bundle_txt", required=True, dest="bundle_txt", help="Input bundle txt path.")
    p_t02_decode.add_argument("--out-dir", "--out_dir", dest="out_dir", help="Optional output directory for decoded bundle files. If omitted, single-case bundles decode to a sibling directory named after the bundle file, while multi-case bundles decode into the current working directory.")
    p_t02_decode.set_defaults(func=_cmd_t02_decode_text_bundle)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as e:
        if isinstance(e, ValueError) and str(e):
            print(f"ERROR: {e}", file=sys.stderr)
        else:
            print(f"ERROR: {type(e).__name__}", file=sys.stderr)
        return 1
