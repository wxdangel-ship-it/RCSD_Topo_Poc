from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.p01_arm_build.final_road_next_road import (
    build_frcsd_road_next_road,
    final_review_layers,
    render_final_review_png,
    write_final_geojson,
)
from rcsd_topo_poc.modules.p01_arm_build.io import load_dataset, normalise_id, write_csv, write_gpkg_layers, write_json
from rcsd_topo_poc.modules.p01_arm_build.models import DATASETS, DatasetInput, JunctionGroup, to_plain
from rcsd_topo_poc.modules.p01_arm_build.road_next_road import read_road_next_road
from rcsd_topo_poc.modules.p01_arm_build.review import (
    build_compare_layers,
    build_dataset_review_layers,
    render_compare_png,
    render_dataset_review_png,
)
from rcsd_topo_poc.modules.p01_arm_build.topology import build_dataset_arm_result


REVIEW_INDEX_FIELDS = [
    "run_id",
    "junction_group_id",
    "group_index",
    "dataset",
    "junction_id",
    "swsd_junction_id",
    "rcsd_junction_id",
    "frcsd_junction_id",
    "member_node_count",
    "internal_road_count",
    "seed_road_count",
    "excluded_right_turn_road_count",
    "advance_left_turn_road_count",
    "advance_right_turn_road_count",
    "advance_right_turn_relation_count",
    "advance_right_turn_unresolved_count",
    "trunk_complete_count",
    "trunk_partial_count",
    "trunk_none_count",
    "trunk_ambiguous_count",
    "formway_missing_count",
    "formway_unparseable_count",
    "arm_movement_count",
    "final_arm_validation_count",
    "final_arm_validated_count",
    "final_arm_weak_validated_count",
    "final_arm_unvalidated_count",
    "final_arm_validation_conflict_count",
    "arm_corridor_evidence_count",
    "arm_corridor_extended_count",
    "arm_corridor_seed_only_count",
    "arm_corridor_ambiguous_count",
    "road_movement_input_record_count",
    "road_movement_case_scoped_record_count",
    "road_movement_out_of_scope_skipped_count",
    "road_movement_evidence_count",
    "road_movement_mapped_count",
    "road_movement_unmapped_count",
    "straight_receiving_road_count",
    "advance_left_receiving_road_count",
    "trunk_correction_count",
    "trunk_correction_excluded_road_count",
    "trunk_correction_straight_evidence_missing_count",
    "corrected_trunk_complete_count",
    "corrected_trunk_partial_count",
    "corrected_trunk_none_count",
    "corrected_trunk_ambiguous_count",
    "frcsd_generated_road_next_road_count",
    "frcsd_source_geometry_match_missing_count",
    "frcsd_source_geometry_match_ambiguous_count",
    "frcsd_same_source_inherited_count",
    "frcsd_cross_source_generated_count",
    "frcsd_fallback_to_swsd_count",
    "frcsd_alternate_source_projected_count",
    "frcsd_swsd_basic_rule_count",
    "frcsd_rule_projected_count",
    "frcsd_data_error_partial_target_coverage_count",
    "frcsd_manual_review_required_count",
    "frcsd_parallel_branch_alignment_count",
    "frcsd_parallel_branch_count_matched_ordered_count",
    "frcsd_parallel_branch_manual_review_required_count",
    "initial_arm_count",
    "final_arm_count",
    "local_arm_candidate_count",
    "local_arm_fragmentation_gap",
    "stable_arm_count",
    "partial_arm_count",
    "unstable_arm_count",
    "ambiguous_trace_count",
    "t_mainline_through_count",
    "t_side_terminal_count",
    "patch_boundary_count",
    "dead_end_count",
    "loop_count",
    "seed_unassigned_count",
    "issue_count",
    "review_priority",
    "review_png_path",
    "review_gpkg_path",
]

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _progress(message: str) -> None:
    print(f"[p01] {message}", file=sys.stderr, flush=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p01-arm-build")
    parser.add_argument("--swsd-nodes", required=True)
    parser.add_argument("--swsd-roads", required=True)
    parser.add_argument("--rcsd-nodes", required=True)
    parser.add_argument("--rcsd-roads", required=True)
    parser.add_argument("--frcsd-nodes", required=True)
    parser.add_argument("--frcsd-roads", required=True)
    parser.add_argument("--swsd-road-next-road")
    parser.add_argument("--rcsd-road-next-road")
    parser.add_argument("--frcsd-road-next-road")
    parser.add_argument("--junction-group", action="append", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--right-turn-formway-value",
        action="append",
        default=[],
        help="Known formway value that explicitly identifies right-turn/channelized right-turn roads.",
    )
    return parser


def _parse_junction_groups(values: list[str]) -> list[JunctionGroup]:
    groups: list[JunctionGroup] = []
    for index, raw in enumerate(values, start=1):
        parts = [normalise_id(part) for part in raw.split(",")]
        if len(parts) != 3 or any(not part for part in parts):
            raise ValueError(f"Invalid --junction-group value: {raw}")
        groups.append(
            JunctionGroup(
                group_id=f"group_{index:04d}",
                group_index=index,
                swsd_junction_id=parts[0],
                rcsd_junction_id=parts[1],
                frcsd_junction_id=parts[2],
            )
        )
    return groups


def _priority_min(current: str, candidate: str) -> str:
    return candidate if PRIORITY_RANK[candidate] < PRIORITY_RANK[current] else current


def _dataset_inputs_from_args(args: argparse.Namespace) -> dict[str, DatasetInput]:
    return {
        "SWSD": DatasetInput("SWSD", Path(args.swsd_nodes), Path(args.swsd_roads), Path(args.swsd_road_next_road) if args.swsd_road_next_road else None),
        "RCSD": DatasetInput("RCSD", Path(args.rcsd_nodes), Path(args.rcsd_roads), Path(args.rcsd_road_next_road) if args.rcsd_road_next_road else None),
        "FRCSD": DatasetInput("FRCSD", Path(args.frcsd_nodes), Path(args.frcsd_roads), Path(args.frcsd_road_next_road) if args.frcsd_road_next_road else None),
    }


def _preflight_payload(
    *,
    run_id: str,
    dataset_inputs: dict[str, DatasetInput],
    loaded: dict[str, Any],
    groups: list[JunctionGroup],
    right_turn_formway_values: set[str],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "input_paths": {
            dataset: {
                "nodes": str(item.nodes_path),
                "roads": str(item.roads_path),
                "road_next_road": str(item.road_next_road_path) if item.road_next_road_path else None,
            }
            for dataset, item in dataset_inputs.items()
        },
        "right_turn_formway_values": sorted(right_turn_formway_values),
        "junction_groups": [to_plain(group) for group in groups],
        "datasets": {
            dataset: {
                "nodes_feature_count": data.node_layer.feature_count,
                "roads_feature_count": data.road_layer.feature_count,
                "nodes_crs": str(data.node_layer.crs or data.node_layer.crs_wkt or ""),
                "roads_crs": str(data.road_layer.crs or data.road_layer.crs_wkt or ""),
                "node_fields": data.node_layer.schema_properties,
                "road_fields": data.road_layer.schema_properties,
            }
            for dataset, data in loaded.items()
        },
    }


def _review_index_row(
    *,
    run_id: str,
    group: JunctionGroup,
    dataset: str,
    result: Any,
    review_png_path: Path,
    review_gpkg_path: Path,
) -> dict[str, Any]:
    metrics = result.metrics
    return {
        "run_id": run_id,
        "junction_group_id": group.group_id,
        "group_index": group.group_index,
        "dataset": dataset,
        "junction_id": group.junction_id_for(dataset),
        "swsd_junction_id": group.swsd_junction_id,
        "rcsd_junction_id": group.rcsd_junction_id,
        "frcsd_junction_id": group.frcsd_junction_id,
        "review_priority": result.review_priority,
        "review_png_path": str(review_png_path),
        "review_gpkg_path": str(review_gpkg_path),
        **metrics,
    }


def _apply_cross_dataset_priority(rows: list[dict[str, Any]]) -> None:
    by_group: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_group.setdefault(str(row["junction_group_id"]), []).append(row)
    for group_rows in by_group.values():
        by_dataset = {str(row["dataset"]): row for row in group_rows}
        swsd = by_dataset.get("SWSD")
        frcsd = by_dataset.get("FRCSD")
        if not swsd or not frcsd:
            continue
        arm_gap = abs(int(swsd["initial_arm_count"]) - int(frcsd["initial_arm_count"]))
        unstable_gap = int(frcsd["unstable_arm_count"]) - int(swsd["unstable_arm_count"])
        if arm_gap >= 2 or unstable_gap >= 2:
            for row in group_rows:
                row["review_priority"] = _priority_min(str(row["review_priority"]), "P0")


def _write_dataset_outputs(
    *,
    dataset_dir: Path,
    loaded: Any,
    result: Any,
) -> tuple[Path, Path]:
    write_json(dataset_dir / "junction_context.json", result.context)
    write_json(dataset_dir / "initial_arms.json", result.initial_arms)
    write_json(dataset_dir / "final_arms.json", result.final_arms)
    write_json(dataset_dir / "final_arm_validation.json", result.final_arm_validation)
    write_json(dataset_dir / "arm_corridor_evidence.json", result.arm_corridor_evidence)
    write_json(dataset_dir / "corrected_final_arms.json", result.corrected_final_arms)
    write_json(dataset_dir / "advance_right_turn_relations.json", result.advance_right_turn_relations)
    write_json(dataset_dir / "arm_movements.json", result.arm_movements)
    write_json(dataset_dir / "road_movement_evidence.json", result.road_movement_evidence)
    write_json(dataset_dir / "arm_receiving_road_roles.json", result.arm_receiving_road_roles)
    write_json(dataset_dir / "trunk_corrections.json", result.trunk_corrections)
    write_json(dataset_dir / "local_arm_candidates.json", result.local_arm_candidates)
    write_json(dataset_dir / "arm_traces.json", result.traces)
    write_json(dataset_dir / "through_decisions.json", result.decisions)
    write_json(dataset_dir / "issue_report.json", result.issue_report)
    gpkg_path = dataset_dir / "review_layers.gpkg"
    write_gpkg_layers(
        gpkg_path,
        layers=build_dataset_review_layers(loaded, result),
        crs=loaded.road_layer.crs or loaded.node_layer.crs,
        crs_wkt=loaded.road_layer.crs_wkt or loaded.node_layer.crs_wkt,
    )
    png_path = dataset_dir / "p01_arm_review.png"
    render_dataset_review_png(png_path, loaded, result)
    return png_path, gpkg_path


def _summary_payload(
    *,
    run_id: str,
    run_root: Path,
    started_at: float,
    rows: list[dict[str, Any]],
    groups: list[JunctionGroup],
    input_paths: dict[str, Any],
) -> dict[str, Any]:
    priority_counts = Counter(str(row["review_priority"]) for row in rows)
    issue_counts: Counter[str] = Counter()
    for row in rows:
        issue_counts[str(row["dataset"])] += int(row["issue_count"])
    total_dataset_count = len(rows)
    stable_total = sum(int(row["stable_arm_count"]) for row in rows)
    arm_total = sum(int(row["initial_arm_count"]) for row in rows)
    unstable_total = sum(int(row["unstable_arm_count"]) for row in rows)
    return {
        "run_id": run_id,
        "run_root": str(run_root),
        "input_paths": input_paths,
        "total_junction_group_count": len(groups),
        "total_dataset_junction_count": total_dataset_count,
        "dataset_distribution": dict(Counter(str(row["dataset"]) for row in rows)),
        "arm_count_distribution": {
            "total_initial_arms": arm_total,
            "total_final_arms": sum(int(row["final_arm_count"]) for row in rows),
            "total_local_arm_candidates": sum(int(row["local_arm_candidate_count"]) for row in rows),
        },
        "stable_rate": stable_total / arm_total if arm_total else 0.0,
        "unstable_rate": unstable_total / arm_total if arm_total else 0.0,
        "right_turn_exclusion_count": sum(int(row["excluded_right_turn_road_count"]) for row in rows),
        "advance_left_turn_road_count": sum(int(row["advance_left_turn_road_count"]) for row in rows),
        "advance_right_turn_road_count": sum(int(row["advance_right_turn_road_count"]) for row in rows),
        "advance_right_turn_relation_count": sum(int(row["advance_right_turn_relation_count"]) for row in rows),
        "advance_right_turn_unresolved_count": sum(int(row["advance_right_turn_unresolved_count"]) for row in rows),
        "trunk_complete_count": sum(int(row["trunk_complete_count"]) for row in rows),
        "trunk_partial_count": sum(int(row["trunk_partial_count"]) for row in rows),
        "trunk_none_count": sum(int(row["trunk_none_count"]) for row in rows),
        "trunk_ambiguous_count": sum(int(row["trunk_ambiguous_count"]) for row in rows),
        "formway_missing_count": sum(int(row["formway_missing_count"]) for row in rows),
        "formway_unparseable_count": sum(int(row["formway_unparseable_count"]) for row in rows),
        "arm_movement_count": sum(int(row["arm_movement_count"]) for row in rows),
        "final_arm_validation_count": sum(int(row["final_arm_validation_count"]) for row in rows),
        "final_arm_validated_count": sum(int(row["final_arm_validated_count"]) for row in rows),
        "final_arm_weak_validated_count": sum(int(row["final_arm_weak_validated_count"]) for row in rows),
        "final_arm_unvalidated_count": sum(int(row["final_arm_unvalidated_count"]) for row in rows),
        "final_arm_validation_conflict_count": sum(int(row["final_arm_validation_conflict_count"]) for row in rows),
        "arm_corridor_evidence_count": sum(int(row["arm_corridor_evidence_count"]) for row in rows),
        "arm_corridor_extended_count": sum(int(row["arm_corridor_extended_count"]) for row in rows),
        "arm_corridor_seed_only_count": sum(int(row["arm_corridor_seed_only_count"]) for row in rows),
        "arm_corridor_ambiguous_count": sum(int(row["arm_corridor_ambiguous_count"]) for row in rows),
        "road_movement_input_record_count": sum(int(row.get("road_movement_input_record_count") or 0) for row in rows),
        "road_movement_case_scoped_record_count": sum(
            int(row.get("road_movement_case_scoped_record_count") or 0) for row in rows
        ),
        "road_movement_out_of_scope_skipped_count": sum(
            int(row.get("road_movement_out_of_scope_skipped_count") or 0) for row in rows
        ),
        "road_movement_evidence_count": sum(int(row["road_movement_evidence_count"]) for row in rows),
        "road_movement_mapped_count": sum(int(row["road_movement_mapped_count"]) for row in rows),
        "road_movement_unmapped_count": sum(int(row["road_movement_unmapped_count"]) for row in rows),
        "straight_receiving_road_count": sum(int(row["straight_receiving_road_count"]) for row in rows),
        "advance_left_receiving_road_count": sum(int(row["advance_left_receiving_road_count"]) for row in rows),
        "trunk_correction_count": sum(int(row["trunk_correction_count"]) for row in rows),
        "trunk_correction_excluded_road_count": sum(int(row["trunk_correction_excluded_road_count"]) for row in rows),
        "trunk_correction_straight_evidence_missing_count": sum(int(row["trunk_correction_straight_evidence_missing_count"]) for row in rows),
        "corrected_trunk_complete_count": sum(int(row["corrected_trunk_complete_count"]) for row in rows),
        "corrected_trunk_partial_count": sum(int(row["corrected_trunk_partial_count"]) for row in rows),
        "corrected_trunk_none_count": sum(int(row["corrected_trunk_none_count"]) for row in rows),
        "corrected_trunk_ambiguous_count": sum(int(row["corrected_trunk_ambiguous_count"]) for row in rows),
        "frcsd_generated_road_next_road_count": sum(int(row.get("frcsd_generated_road_next_road_count") or 0) for row in rows),
        "frcsd_source_geometry_match_missing_count": sum(int(row.get("frcsd_source_geometry_match_missing_count") or 0) for row in rows),
        "frcsd_source_geometry_match_ambiguous_count": sum(int(row.get("frcsd_source_geometry_match_ambiguous_count") or 0) for row in rows),
        "frcsd_same_source_inherited_count": sum(int(row.get("frcsd_same_source_inherited_count") or 0) for row in rows),
        "frcsd_cross_source_generated_count": sum(int(row.get("frcsd_cross_source_generated_count") or 0) for row in rows),
        "frcsd_fallback_to_swsd_count": sum(int(row.get("frcsd_fallback_to_swsd_count") or 0) for row in rows),
        "frcsd_alternate_source_projected_count": sum(
            int(row.get("frcsd_alternate_source_projected_count") or 0) for row in rows
        ),
        "frcsd_swsd_basic_rule_count": sum(int(row.get("frcsd_swsd_basic_rule_count") or 0) for row in rows),
        "frcsd_rule_projected_count": sum(int(row.get("frcsd_rule_projected_count") or 0) for row in rows),
        "frcsd_data_error_partial_target_coverage_count": sum(
            int(row.get("frcsd_data_error_partial_target_coverage_count") or 0) for row in rows
        ),
        "frcsd_manual_review_required_count": sum(int(row.get("frcsd_manual_review_required_count") or 0) for row in rows),
        "frcsd_parallel_branch_alignment_count": sum(int(row.get("frcsd_parallel_branch_alignment_count") or 0) for row in rows),
        "frcsd_parallel_branch_count_matched_ordered_count": sum(
            int(row.get("frcsd_parallel_branch_count_matched_ordered_count") or 0) for row in rows
        ),
        "frcsd_parallel_branch_manual_review_required_count": sum(
            int(row.get("frcsd_parallel_branch_manual_review_required_count") or 0) for row in rows
        ),
        "ambiguous_boundary_count": sum(int(row["ambiguous_trace_count"]) for row in rows),
        "t_mainline_through_count": sum(int(row["t_mainline_through_count"]) for row in rows),
        "t_side_terminal_count": sum(int(row["t_side_terminal_count"]) for row in rows),
        "patch_boundary_count": sum(int(row["patch_boundary_count"]) for row in rows),
        "top_issue_types": dict(issue_counts),
        "p0_review_count": priority_counts.get("P0", 0),
        "p1_review_count": priority_counts.get("P1", 0),
        "failed_group_count": sum(1 for row in rows if str(row["review_priority"]) == "P0"),
        "duration_seconds": round(time.perf_counter() - started_at, 3),
    }


def run_p01_arm_build_from_args(argv: list[str]) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    run_id = args.run_id or "p01_arm_build_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = Path(args.out_root) / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    started_at = time.perf_counter()

    groups = _parse_junction_groups(args.junction_group)
    dataset_inputs = _dataset_inputs_from_args(args)
    right_turn_formway_values = {normalise_id(value) for value in args.right_turn_formway_value if normalise_id(value)}
    _progress(
        f"start run_id={run_id} groups={len(groups)} "
        f"out_root={Path(args.out_root)} right_turn_values={sorted(right_turn_formway_values) or '<none>'}"
    )
    loaded: dict[str, Any] = {}
    road_next_road_by_dataset: dict[str, Any] = {}
    for dataset_index, dataset in enumerate(DATASETS, start=1):
        dataset_input = dataset_inputs[dataset]
        load_started_at = time.perf_counter()
        _progress(
            f"load dataset {dataset_index}/{len(DATASETS)} {dataset} "
            f"nodes={dataset_input.nodes_path} roads={dataset_input.roads_path}"
        )
        loaded[dataset] = load_dataset(dataset_input)
        road_next_road_by_dataset[dataset] = read_road_next_road(dataset_input.road_next_road_path)
        _progress(
            f"loaded {dataset}: nodes={len(loaded[dataset].nodes)} roads={len(loaded[dataset].roads)} "
            f"road_next_road={len(road_next_road_by_dataset[dataset])} duration={time.perf_counter() - load_started_at:.1f}s"
        )

    _progress(f"write preflight {run_root / 'preflight.json'}")
    write_json(
        run_root / "preflight.json",
        _preflight_payload(
            run_id=run_id,
            dataset_inputs=dataset_inputs,
            loaded=loaded,
            groups=groups,
            right_turn_formway_values=right_turn_formway_values,
        ),
    )

    review_rows: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    for group_index, group in enumerate(groups, start=1):
        group_started_at = time.perf_counter()
        _progress(
            f"group {group_index}/{len(groups)} {group.group_id} "
            f"ids={group.swsd_junction_id},{group.rcsd_junction_id},{group.frcsd_junction_id}"
        )
        case_dir = run_root / "cases" / group.group_id
        compare_dir = case_dir / "compare"
        write_json(case_dir / "case_input.json", group)
        result_by_dataset: dict[str, Any] = {}
        dataset_output_paths: dict[str, dict[str, str]] = {}
        for dataset_index, dataset in enumerate(DATASETS, start=1):
            junction_id = group.junction_id_for(dataset)
            dataset_started_at = time.perf_counter()
            _progress(f"{group.group_id} dataset {dataset_index}/{len(DATASETS)} {dataset} build junction={junction_id}")
            result = build_dataset_arm_result(
                loaded[dataset],
                junction_id=junction_id,
                right_turn_formway_values=right_turn_formway_values,
                road_next_road_records=road_next_road_by_dataset[dataset],
                has_road_next_road_input=dataset_inputs[dataset].road_next_road_path is not None,
            )
            result_by_dataset[dataset] = result
            dataset_dir = case_dir / dataset
            _progress(
                f"{group.group_id} {dataset} built arms={result.metrics['initial_arm_count']} "
                f"local_candidates={result.metrics['local_arm_candidate_count']} "
                f"stable={result.metrics['stable_arm_count']} issues={result.metrics['issue_count']} "
                f"priority={result.review_priority}; writing outputs"
            )
            png_path, gpkg_path = _write_dataset_outputs(dataset_dir=dataset_dir, loaded=loaded[dataset], result=result)
            dataset_output_paths[dataset] = {"review_png_path": str(png_path), "review_gpkg_path": str(gpkg_path)}
            review_rows.append(
                _review_index_row(
                    run_id=run_id,
                    group=group,
                    dataset=dataset,
                    result=result,
                    review_png_path=png_path,
                    review_gpkg_path=gpkg_path,
                )
            )
            _progress(
                f"{group.group_id} {dataset} done duration={time.perf_counter() - dataset_started_at:.1f}s "
                f"png={png_path} gpkg={gpkg_path}"
            )

        frcsd_final = build_frcsd_road_next_road(
            loaded_by_dataset=loaded,
            result_by_dataset=result_by_dataset,
            road_next_road_by_dataset=road_next_road_by_dataset,
            junction_group_id=group.group_id,
        )
        frcsd_dir = case_dir / "FRCSD"
        _progress(
            f"{group.group_id} generate FRCSD RoadNextRoad "
            f"count={frcsd_final.metrics['frcsd_generated_road_next_road_count']} "
            f"manual_review={frcsd_final.metrics['frcsd_manual_review_required_count']}"
        )
        write_final_geojson(frcsd_dir / "frcsd_road_next_road.geojson", frcsd_final)
        write_json(frcsd_dir / "frcsd_source_road_map.json", frcsd_final.source_road_map)
        write_json(frcsd_dir / "source_movement_policy_swsd.json", frcsd_final.source_movement_policy_swsd)
        write_json(frcsd_dir / "source_movement_policy_rcsd.json", frcsd_final.source_movement_policy_rcsd)
        write_json(frcsd_dir / "arm_source_profiles.json", frcsd_final.arm_source_profiles)
        write_json(frcsd_dir / "source_arm_pass_rules_swsd.json", frcsd_final.source_arm_pass_rules_swsd)
        write_json(frcsd_dir / "source_arm_pass_rules_rcsd.json", frcsd_final.source_arm_pass_rules_rcsd)
        write_json(frcsd_dir / "final_generation_decisions.json", frcsd_final.final_generation_decisions)
        write_json(frcsd_dir / "parallel_branch_alignment.json", frcsd_final.parallel_branch_alignment)
        write_json(frcsd_dir / "frcsd_road_next_road_audit.json", frcsd_final.audit)
        write_json(frcsd_dir / "frcsd_road_next_road_issue_report.json", frcsd_final.issue_report)
        final_gpkg = frcsd_dir / "frcsd_road_next_road_review_layers.gpkg"
        write_gpkg_layers(
            final_gpkg,
            layers=final_review_layers(loaded_frcsd=loaded["FRCSD"], result=frcsd_final),
            crs=loaded["FRCSD"].road_layer.crs or loaded["FRCSD"].node_layer.crs,
            crs_wkt=loaded["FRCSD"].road_layer.crs_wkt or loaded["FRCSD"].node_layer.crs_wkt,
        )
        final_png = frcsd_dir / "frcsd_road_next_road_review.png"
        render_final_review_png(final_png, frcsd_final)
        dataset_output_paths.setdefault("FRCSD", {}).update(
            {
                "frcsd_road_next_road_geojson_path": str(frcsd_dir / "frcsd_road_next_road.geojson"),
                "frcsd_road_next_road_review_gpkg_path": str(final_gpkg),
                "frcsd_road_next_road_review_png_path": str(final_png),
            }
        )
        result_by_dataset["FRCSD"].metrics.update(frcsd_final.metrics)
        for row in reversed(review_rows):
            if row["junction_group_id"] == group.group_id and row["dataset"] == "FRCSD":
                row.update(frcsd_final.metrics)
                if frcsd_final.metrics["frcsd_source_geometry_match_missing_count"] or frcsd_final.metrics["frcsd_source_geometry_match_ambiguous_count"]:
                    row["review_priority"] = _priority_min(str(row["review_priority"]), "P0")
                elif frcsd_final.metrics["frcsd_manual_review_required_count"]:
                    row["review_priority"] = _priority_min(str(row["review_priority"]), "P1")
                break

        compare_png = compare_dir / "p01_arm_compare.png"
        _progress(f"{group.group_id} write compare png={compare_png}")
        render_compare_png(compare_png, loaded, result_by_dataset)
        compare_gpkg = compare_dir / "p01_arm_compare_layers.gpkg"
        _progress(f"{group.group_id} write compare gpkg={compare_gpkg}")
        write_gpkg_layers(
            compare_gpkg,
            layers=build_compare_layers(loaded, result_by_dataset),
            crs=loaded["SWSD"].road_layer.crs or loaded["SWSD"].node_layer.crs,
            crs_wkt=loaded["SWSD"].road_layer.crs_wkt or loaded["SWSD"].node_layer.crs_wkt,
        )
        compare_summary = {
            "group_id": group.group_id,
            "datasets": {dataset: result_by_dataset[dataset].metrics for dataset in DATASETS},
            "compare_png_path": str(compare_png),
            "compare_gpkg_path": str(compare_gpkg),
        }
        write_json(compare_dir / "p01_arm_compare_summary.json", compare_summary)
        case_summary = {
            "group": to_plain(group),
            "datasets": {dataset: result_by_dataset[dataset].metrics for dataset in DATASETS},
            "dataset_outputs": dataset_output_paths,
            "compare_outputs": compare_summary,
        }
        write_json(case_dir / "case_summary.json", case_summary)
        case_results.append(case_summary)
        _progress(f"group {group.group_id} complete duration={time.perf_counter() - group_started_at:.1f}s")

    _progress("finalize review priorities and summary")
    _apply_cross_dataset_priority(review_rows)
    write_csv(run_root / "p01_arm_build_review_index.csv", review_rows, REVIEW_INDEX_FIELDS)
    write_json(
        run_root / "p01_arm_build_summary.json",
        _summary_payload(
            run_id=run_id,
            run_root=run_root,
            started_at=started_at,
            rows=review_rows,
            groups=groups,
            input_paths={
                dataset: {
                    "nodes": str(item.nodes_path),
                    "roads": str(item.roads_path),
                    "road_next_road": str(item.road_next_road_path) if item.road_next_road_path else None,
                }
                for dataset, item in dataset_inputs.items()
            },
        ),
    )
    write_json(run_root / "case_results.json", case_results)
    _progress(f"complete run_id={run_id} duration={time.perf_counter() - started_at:.1f}s run_root={run_root}")
    return 0
