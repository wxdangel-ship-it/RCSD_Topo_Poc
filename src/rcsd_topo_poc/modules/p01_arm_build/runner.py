from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.p01_arm_build.io import load_dataset, normalise_id, write_csv, write_gpkg_layers, write_json
from rcsd_topo_poc.modules.p01_arm_build.models import DATASETS, DatasetInput, JunctionGroup, to_plain
from rcsd_topo_poc.modules.p01_arm_build.review import (
    build_compare_layers,
    build_dataset_review_layers,
    render_compare_png,
    render_dataset_review_png,
    render_trace_review_png,
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
    "initial_arm_count",
    "final_arm_count",
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p01-arm-build")
    parser.add_argument("--swsd-nodes", required=True)
    parser.add_argument("--swsd-roads", required=True)
    parser.add_argument("--rcsd-nodes", required=True)
    parser.add_argument("--rcsd-roads", required=True)
    parser.add_argument("--frcsd-nodes", required=True)
    parser.add_argument("--frcsd-roads", required=True)
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
        "SWSD": DatasetInput("SWSD", Path(args.swsd_nodes), Path(args.swsd_roads)),
        "RCSD": DatasetInput("RCSD", Path(args.rcsd_nodes), Path(args.rcsd_roads)),
        "FRCSD": DatasetInput("FRCSD", Path(args.frcsd_nodes), Path(args.frcsd_roads)),
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
            dataset: {"nodes": str(item.nodes_path), "roads": str(item.roads_path)}
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


def _write_trace_review_outputs(
    *,
    trace_dir: Path,
    loaded: Any,
    result: Any,
) -> list[str]:
    triggers = {
        "ambiguous_boundary",
        "loop_to_current_junction",
        "t_junction_uncertain",
        "seed_road_unassigned",
    }
    written: list[str] = []
    for trace in result.traces:
        should_write = bool(set(trace.issue_flags) & triggers)
        should_write = should_write or result.metrics["stable_arm_count"] == 0
        if should_write and result.review_priority in {"P0", "P1"}:
            path = trace_dir / f"{trace.trace_id}.png"
            render_trace_review_png(path, loaded, result, trace.trace_id)
            written.append(str(path))
    return written


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
        },
        "stable_rate": stable_total / arm_total if arm_total else 0.0,
        "unstable_rate": unstable_total / arm_total if arm_total else 0.0,
        "right_turn_exclusion_count": sum(int(row["excluded_right_turn_road_count"]) for row in rows),
        "ambiguous_boundary_count": sum(int(row["ambiguous_trace_count"]) for row in rows),
        "t_mainline_through_count": sum(int(row["t_mainline_through_count"]) for row in rows),
        "t_side_terminal_count": sum(int(row["t_side_terminal_count"]) for row in rows),
        "patch_boundary_count": sum(int(row["patch_boundary_count"]) for row in rows),
        "top_issue_types": dict(issue_counts),
        "p0_review_count": priority_counts.get("P0", 0),
        "p1_review_count": priority_counts.get("P1", 0),
        "failed_group_count": sum(1 for row in rows if str(row["review_priority"]) == "P0"),
        "duration_seconds": round(time.time() - started_at, 3),
    }


def run_p01_arm_build_from_args(argv: list[str]) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    run_id = args.run_id or "p01_arm_build_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = Path(args.out_root) / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    started_at = time.time()

    groups = _parse_junction_groups(args.junction_group)
    dataset_inputs = _dataset_inputs_from_args(args)
    loaded = {dataset: load_dataset(dataset_input) for dataset, dataset_input in dataset_inputs.items()}
    right_turn_formway_values = {normalise_id(value) for value in args.right_turn_formway_value if normalise_id(value)}

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
    for group in groups:
        case_dir = run_root / "cases" / group.group_id
        compare_dir = case_dir / "compare"
        trace_dir = case_dir / "trace_review"
        write_json(case_dir / "case_input.json", group)
        result_by_dataset: dict[str, Any] = {}
        dataset_output_paths: dict[str, dict[str, str]] = {}
        trace_review_paths: list[str] = []
        for dataset in DATASETS:
            junction_id = group.junction_id_for(dataset)
            result = build_dataset_arm_result(
                loaded[dataset],
                junction_id=junction_id,
                right_turn_formway_values=right_turn_formway_values,
            )
            result_by_dataset[dataset] = result
            dataset_dir = case_dir / dataset
            png_path, gpkg_path = _write_dataset_outputs(dataset_dir=dataset_dir, loaded=loaded[dataset], result=result)
            trace_review_paths.extend(_write_trace_review_outputs(trace_dir=trace_dir, loaded=loaded[dataset], result=result))
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

        compare_png = compare_dir / "p01_arm_compare.png"
        render_compare_png(compare_png, loaded, result_by_dataset)
        compare_gpkg = compare_dir / "p01_arm_compare_layers.gpkg"
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
            "trace_review_png_paths": trace_review_paths,
        }
        write_json(case_dir / "case_summary.json", case_summary)
        case_results.append(case_summary)

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
                dataset: {"nodes": str(item.nodes_path), "roads": str(item.roads_path)}
                for dataset, item in dataset_inputs.items()
            },
        ),
    )
    write_json(run_root / "case_results.json", case_results)
    return 0
