from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.p01_arm_build.alignment import build_case_alignment
from rcsd_topo_poc.modules.p01_arm_build.alignment_io import load_datasets_from_a1_preflight, read_a1_run_root
from rcsd_topo_poc.modules.p01_arm_build.alignment_models import SOURCE_DATASETS
from rcsd_topo_poc.modules.p01_arm_build.alignment_review import (
    build_alignment_layers,
    render_compare_alignment_png,
    render_source_alignment_png,
)
from rcsd_topo_poc.modules.p01_arm_build.io import write_csv, write_gpkg_layers, write_json
from rcsd_topo_poc.modules.p01_arm_build.models import DATASETS, to_plain


REVIEW_INDEX_FIELDS = [
    "run_id",
    "junction_group_id",
    "dataset",
    "logical_arm_group_count",
    "acceptable_logical_arm_group_count",
    "candidate_count",
    "feedback_count",
    "source_extra_count",
    "missing_count",
    "partial_count",
    "conflict_count",
    "uncertain_count",
    "review_priority",
    "review_png_path",
    "review_gpkg_path",
]


def _progress(message: str) -> None:
    print(f"[p01-a2] {message}", file=sys.stderr, flush=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p01-arm-alignment")
    parser.add_argument("--arm-build-run-root", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--run-id")
    return parser


def run_p01_arm_alignment_from_args(argv: list[str]) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    started_at = time.perf_counter()
    run_id = args.run_id or "p01_arm_alignment_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    arm_build_run_root = Path(args.arm_build_run_root)
    run_root = Path(args.out_root) / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    _progress(f"start run_id={run_id} arm_build_run_root={arm_build_run_root} out_root={Path(args.out_root)}")
    a1 = read_a1_run_root(arm_build_run_root)
    _progress(f"read A1 run root cases={len(a1.cases)}")
    loaded_by_dataset, load_errors = load_datasets_from_a1_preflight(a1.preflight)
    for dataset in DATASETS:
        if dataset in loaded_by_dataset:
            _progress(
                f"loaded source geometry {dataset}: "
                f"nodes={len(loaded_by_dataset[dataset].nodes)} roads={len(loaded_by_dataset[dataset].roads)}"
            )
        else:
            _progress(f"source geometry unavailable {dataset}: {load_errors.get(dataset, 'unknown error')}")

    write_json(
        run_root / "preflight.json",
        {
            "run_id": run_id,
            "arm_build_run_root": str(arm_build_run_root),
            "a1_run_id": a1.preflight.get("run_id"),
            "a1_input_paths": a1.preflight.get("input_paths", {}),
            "source_geometry_load_errors": load_errors,
            "case_count": len(a1.cases),
        },
    )

    review_rows: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    for case_index, case in enumerate(a1.cases, start=1):
        case_started_at = time.perf_counter()
        _progress(f"case {case_index}/{len(a1.cases)} {case.group_id} build alignment")
        result = build_case_alignment(case, loaded_by_dataset)
        case_dir = run_root / "cases" / case.group_id
        compare_dir = case_dir / "compare"

        write_json(case_dir / "arm_profiles.json", result.profiles_by_dataset)
        write_json(case_dir / "logical_arm_groups.json", result.logical_arm_groups)
        write_json(case_dir / "arm_build_feedback.json", result.feedback)
        write_json(case_dir / "source_extra_arms.json", result.source_extra_arms)
        write_json(case_dir / "arm_alignment_candidates.json", result.candidates)

        layers = build_alignment_layers(result, loaded_by_dataset)
        for source_dataset in SOURCE_DATASETS:
            dataset_dir = case_dir / source_dataset
            raw_path = dataset_dir / "raw_arm_alignment.json"
            issue_path = dataset_dir / "arm_alignment_issue_report.json"
            png_path = dataset_dir / "p01_arm_alignment_review.png"
            gpkg_path = dataset_dir / "arm_alignment_review_layers.gpkg"
            write_json(raw_path, result.raw_alignments_by_source[source_dataset])
            write_json(issue_path, result.issue_reports_by_source[source_dataset])
            _progress(f"{case.group_id} {source_dataset} write review png/gpkg")
            render_source_alignment_png(
                png_path,
                source_dataset=source_dataset,
                loaded_by_dataset=loaded_by_dataset,
                result=result,
            )
            write_gpkg_layers(
                gpkg_path,
                layers=layers,
                crs=_preferred_crs(loaded_by_dataset, source_dataset),
                crs_wkt=_preferred_crs_wkt(loaded_by_dataset, source_dataset),
            )
            review_rows.append(_review_row(run_id, case.group_id, source_dataset, result, png_path, gpkg_path))

        compare_png = compare_dir / "p01_arm_alignment_compare.png"
        compare_gpkg = compare_dir / "p01_arm_alignment_compare_layers.gpkg"
        render_compare_alignment_png(compare_png, loaded_by_dataset=loaded_by_dataset, result=result)
        write_gpkg_layers(
            compare_gpkg,
            layers=layers,
            crs=_preferred_crs(loaded_by_dataset, "FRCSD"),
            crs_wkt=_preferred_crs_wkt(loaded_by_dataset, "FRCSD"),
        )
        compare_summary = {
            "group_id": case.group_id,
            "metrics": result.metrics,
            "review_priority": result.review_priority,
            "compare_png_path": str(compare_png),
            "compare_gpkg_path": str(compare_gpkg),
        }
        write_json(compare_dir / "p01_arm_alignment_compare_summary.json", compare_summary)
        alignment_summary = {
            "group_id": case.group_id,
            "metrics": result.metrics,
            "review_priority": result.review_priority,
            "compare_outputs": compare_summary,
            "duration_seconds": round(time.perf_counter() - case_started_at, 3),
        }
        write_json(case_dir / "alignment_summary.json", alignment_summary)
        case_results.append(alignment_summary)
        _progress(
            f"case {case.group_id} complete logical_groups={result.metrics['logical_arm_group_count']} "
            f"feedback={result.metrics['feedback_count']} source_extra={result.metrics['source_extra_count']} "
            f"priority={result.review_priority} duration={time.perf_counter() - case_started_at:.1f}s"
        )

    write_csv(run_root / "p01_arm_alignment_review_index.csv", review_rows, REVIEW_INDEX_FIELDS)
    write_json(
        run_root / "p01_arm_alignment_summary.json",
        _summary_payload(
            run_id=run_id,
            run_root=run_root,
            a1_run_root=arm_build_run_root,
            started_at=started_at,
            review_rows=review_rows,
            case_results=case_results,
        ),
    )
    _progress(f"complete run_id={run_id} duration={time.perf_counter() - started_at:.1f}s run_root={run_root}")
    return 0


def _preferred_crs(loaded_by_dataset: dict[str, Any], dataset: str) -> Any:
    loaded = loaded_by_dataset.get(dataset) or loaded_by_dataset.get("FRCSD") or next(iter(loaded_by_dataset.values()), None)
    return loaded.road_layer.crs if loaded else None


def _preferred_crs_wkt(loaded_by_dataset: dict[str, Any], dataset: str) -> str | None:
    loaded = loaded_by_dataset.get(dataset) or loaded_by_dataset.get("FRCSD") or next(iter(loaded_by_dataset.values()), None)
    return loaded.road_layer.crs_wkt if loaded else None


def _review_row(
    run_id: str,
    group_id: str,
    dataset: str,
    result: Any,
    png_path: Path,
    gpkg_path: Path,
) -> dict[str, Any]:
    status_counts = result.metrics.get("status_counts", {})
    return {
        "run_id": run_id,
        "junction_group_id": group_id,
        "dataset": dataset,
        "logical_arm_group_count": result.metrics["logical_arm_group_count"],
        "acceptable_logical_arm_group_count": result.metrics["acceptable_logical_arm_group_count"],
        "candidate_count": result.metrics["candidate_count"],
        "feedback_count": result.metrics["feedback_count"],
        "source_extra_count": result.metrics["source_extra_count"],
        "missing_count": status_counts.get("source_missing", 0),
        "partial_count": status_counts.get("source_partial", 0),
        "conflict_count": status_counts.get("conflict", 0),
        "uncertain_count": status_counts.get("uncertain", 0),
        "review_priority": result.review_priority,
        "review_png_path": str(png_path),
        "review_gpkg_path": str(gpkg_path),
    }


def _summary_payload(
    *,
    run_id: str,
    run_root: Path,
    a1_run_root: Path,
    started_at: float,
    review_rows: list[dict[str, Any]],
    case_results: list[dict[str, Any]],
) -> dict[str, Any]:
    priority_counts = Counter(str(row["review_priority"]) for row in review_rows)
    total_groups = sum(int(item["metrics"]["logical_arm_group_count"]) for item in case_results)
    acceptable = sum(int(item["metrics"]["acceptable_logical_arm_group_count"]) for item in case_results)
    return {
        "run_id": run_id,
        "run_root": str(run_root),
        "arm_build_run_root": str(a1_run_root),
        "case_count": len(case_results),
        "logical_arm_group_count": total_groups,
        "acceptable_logical_arm_group_count": acceptable,
        "candidate_count": sum(int(item["metrics"]["candidate_count"]) for item in case_results),
        "feedback_count": sum(int(item["metrics"]["feedback_count"]) for item in case_results),
        "source_extra_count": sum(int(item["metrics"]["source_extra_count"]) for item in case_results),
        "priority_counts": dict(priority_counts),
        "duration_seconds": round(time.perf_counter() - started_at, 3),
    }
