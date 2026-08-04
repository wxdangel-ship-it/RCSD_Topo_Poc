from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


GIB = 1024**3
REQUIRED_OUTPUTS = (
    "p04_segment_first_rcsd.gpkg",
    "p04_segment_first_audit.gpkg",
    "p04_segment_first_relations.gpkg",
    "p04_segment_first_comparison.gpkg",
    "p04_segment_first_independent_quality.gpkg",
    "p04_segment_first_independent_quality.json",
    "p04_segment_first_input_manifest.json",
    "p04_segment_first_report.md",
    "p04_segment_first_summary.json",
    "p04_segment_first_comparison.qgz",
    "p04_progress.jsonl",
)
BUSINESS_EQUIVALENCE_ARTIFACTS = (
    "p04_segment_first_rcsd.gpkg",
    "p04_segment_first_audit.gpkg",
    "p04_segment_first_relations.gpkg",
    "p04_segment_first_comparison.gpkg",
    "p04_segment_first_independent_quality.gpkg",
    "p04_segment_first_independent_quality.json",
    "p04_segment_first_summary.json",
)
NATIVE_THREAD_LIMITS = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "NUMEXPR_MAX_THREADS",
    "GDAL_NUM_THREADS",
)
REQUIRED_PROGRESS_STAGE_GROUPS = {
    "patch": {"input_patch_layer"},
    "manifest": {"input_manifest"},
    "skeleton": {"segment_skeleton_access"},
    "evidence": {"patch_road_center", "target_fragment_assignment"},
    "access_recovery": {"access_surface_recovery"},
    "segment": {"segment_carrier"},
    "junction_unit": {"junction_unit_retained_groups"},
    "junction": {"junction_portal"},
    "node": {"node_topology_pairs", "node_materialization"},
    "topology": {
        "topology_shared_nodes",
        "topology_semantic_junctions",
        "topology_advance_right",
    },
    "qa": {"independent_qa_objects"},
    "output": {
        "output_gpkg_layers",
        "qgis_layer_discovery",
        "qgis_project_layers",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "只读核验P04约1500 Patch内网运行的时限、资源、QA和业务等价证据。"
        )
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--expected-patch-count-min", type=int, default=1400)
    parser.add_argument("--expected-patch-count-max", type=int, default=1600)
    parser.add_argument("--expected-logical-cpu-count", type=int, default=8)
    parser.add_argument("--expected-analysis-crs", default="EPSG:32650")
    parser.add_argument("--wall-target-hours", type=float, default=6.0)
    parser.add_argument("--wall-hard-hours", type=float, default=8.0)
    parser.add_argument(
        "--baseline-wall-seconds",
        type=float,
        default=45759.2,
        help=(
            "异常终止运行在中间日志中已观测的墙钟下界秒数；"
            "候选必须不超过其50%%。"
        ),
    )
    parser.add_argument("--rss-target-gib", type=float, default=8.0)
    parser.add_argument("--rss-hard-gib", type=float, default=16.0)
    parser.add_argument(
        "--over-target-note",
        default="",
        help="兼容保留参数；第三轮中超过6小时仍判定失败，说明不能绕过门槛。",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def gate(
    name: str,
    passed: bool,
    *,
    actual: Any = None,
    expected: Any = None,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "actual": actual,
        "expected": expected,
        "detail": detail,
    }


def manifest_input_identity(manifest: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in manifest.get("files", []):
        rows.append(
            [
                item.get("role"),
                item.get("patch_id"),
                item.get("size_bytes"),
                item.get("sha256"),
            ]
        )
    rows.sort(key=lambda item: json.dumps(item, ensure_ascii=False))
    return rows


def patch_count_from_manifest(manifest: dict[str, Any]) -> int:
    return len(
        {
            str(item["patch_id"])
            for item in manifest.get("files", [])
            if item.get("role") == "patch_vector"
            and item.get("patch_id") is not None
        }
    )


def timeline_assessment(
    performance: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    timeline = list(performance.get("resource_timeline") or [])
    wall_seconds = float(performance.get("wall_seconds") or 0.0)
    expected_minimum = max(2, int(math.floor(wall_seconds / 30.0)))
    final_wall = (
        float(timeline[-1].get("wall_seconds") or 0.0)
        if timeline
        else 0.0
    )
    rss_values = [
        int(item["rss_bytes"])
        for item in timeline
        if item.get("rss_bytes") is not None
    ]
    peak_values = [
        int(item["peak_rss_bytes"])
        for item in timeline
        if item.get("peak_rss_bytes") is not None
    ]
    gates = [
        gate(
            "resource_timeline_present",
            len(timeline) >= expected_minimum,
            actual=len(timeline),
            expected=f">={expected_minimum}",
        ),
        gate(
            "resource_timeline_reaches_completion",
            bool(timeline) and abs(wall_seconds - final_wall) <= 35.0,
            actual=final_wall,
            expected=f"within 35s of {wall_seconds}",
        ),
        gate(
            "resource_timeline_rss_complete",
            len(rss_values) == len(timeline) and bool(rss_values),
            actual=len(rss_values),
            expected=len(timeline),
        ),
        gate(
            "resource_timeline_peak_complete",
            len(peak_values) == len(timeline) and bool(peak_values),
            actual=len(peak_values),
            expected=len(timeline),
        ),
    ]

    tail = rss_values[max(0, len(rss_values) * 2 // 3) :]
    positive_steps = sum(
        current > previous
        for previous, current in zip(tail, tail[1:])
    )
    step_count = max(0, len(tail) - 1)
    tail_growth_bytes = tail[-1] - tail[0] if len(tail) >= 2 else 0
    positive_ratio = positive_steps / step_count if step_count else 0.0
    review_required = (
        len(tail) >= 6
        and tail_growth_bytes > 0.5 * GIB
        and positive_ratio >= 0.8
    )
    advisory = {
        "tail_sample_count": len(tail),
        "tail_growth_bytes": tail_growth_bytes,
        "positive_step_ratio": positive_ratio,
        "review_required": review_required,
        "rule": (
            "advisory only: last third has >=6 samples, grows >0.5GiB, "
            "and >=80% of steps increase"
        ),
    }
    return gates, advisory


def progress_assessment(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    if path.is_file():
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError as error:
                parse_errors.append(f"line {line_number}: {error}")
                continue
            if isinstance(event, dict):
                events.append(event)
            else:
                parse_errors.append(f"line {line_number}: not an object")

    completed_stages = {
        str(event.get("stage"))
        for event in events
        if event.get("event_type") == "stage_completed"
        and int(event.get("completed") or 0) == int(event.get("total") or 0)
    }
    missing_stage_groups = sorted(
        group
        for group, stages in REQUIRED_PROGRESS_STAGE_GROUPS.items()
        if not completed_stages.intersection(stages)
    )
    monotonic = True
    previous: dict[tuple[str, int], tuple[int, int]] = {}
    for event in events:
        stage = str(event.get("stage") or "")
        invocation = int(event.get("stage_invocation") or 0)
        completed = int(event.get("completed") or 0)
        total = int(event.get("total") or 0)
        key = (stage, invocation)
        prior = previous.get(key)
        if completed < 0 or total < 0 or completed > total:
            monotonic = False
        if prior is not None and (
            completed < prior[0] or total != prior[1]
        ):
            monotonic = False
        previous[key] = (completed, total)
    terminal_completed = any(
        event.get("event_type") == "run_completed" for event in events
    )
    movement_cache_rows: list[dict[str, Any]] = []
    movement_cache_violations: list[dict[str, Any]] = []
    for event in events:
        if (
            event.get("event_type") != "stage_completed"
            or event.get("stage") != "movement_anchor_split"
        ):
            continue
        counters = dict(event.get("counters") or {})
        row = {
            "stage_invocation": int(event.get("stage_invocation") or 0),
            "entry_count": counters.get(
                "carrier_selection_cache_entries"
            ),
            "entry_count_max": counters.get(
                "carrier_selection_cache_entries_max"
            ),
            "eviction_count": counters.get(
                "carrier_selection_cache_evictions"
            ),
        }
        movement_cache_rows.append(row)
        try:
            bounded = (
                0 <= int(row["entry_count"]) <= int(row["entry_count_max"])
                and int(row["entry_count_max"]) > 0
                and int(row["eviction_count"]) >= 0
            )
        except (TypeError, ValueError):
            bounded = False
        if not bounded:
            movement_cache_violations.append(row)
    gates = [
        gate(
            "progress_jsonl_valid",
            bool(events) and not parse_errors,
            actual={"event_count": len(events), "errors": parse_errors},
            expected="non-empty valid JSONL",
        ),
        gate(
            "progress_units_monotonic",
            monotonic,
            actual=monotonic,
            expected=True,
        ),
        gate(
            "progress_stage_groups_complete",
            not missing_stage_groups,
            actual=missing_stage_groups,
            expected=[],
        ),
        gate(
            "progress_terminal_event_present",
            terminal_completed,
            actual=terminal_completed,
            expected=True,
        ),
        gate(
            "movement_carrier_selection_cache_bounded",
            not movement_cache_violations,
            actual={
                "invocation_count": len(movement_cache_rows),
                "violations": movement_cache_violations,
            },
            expected="each emitted invocation satisfies 0 <= entries <= max",
        ),
    ]
    return gates, {
        "event_count": len(events),
        "completed_stages": sorted(completed_stages),
        "missing_stage_groups": missing_stage_groups,
        "parse_errors": parse_errors,
        "terminal_completed": terminal_completed,
        "movement_carrier_selection_cache": movement_cache_rows,
    }


def compare_business_artifacts(
    *,
    repo_root: Path,
    reference_root: Path,
    candidate_root: Path,
) -> dict[str, Any]:
    sys.path.insert(0, str(repo_root))
    from tests.modules.t10_e2e_orchestration.artifact_equivalence import (
        semantic_fingerprint,
    )

    rows = []
    for filename in BUSINESS_EQUIVALENCE_ARTIFACTS:
        reference_path = reference_root / filename
        candidate_path = candidate_root / filename
        if not reference_path.is_file() or not candidate_path.is_file():
            rows.append(
                {
                    "artifact": filename,
                    "passed": False,
                    "reference_exists": reference_path.is_file(),
                    "candidate_exists": candidate_path.is_file(),
                }
            )
            continue
        reference = semantic_fingerprint(
            reference_path,
            root=reference_root,
        )
        candidate = semantic_fingerprint(
            candidate_path,
            root=candidate_root,
        )
        rows.append(
            {
                "artifact": filename,
                "passed": reference["sha256"] == candidate["sha256"],
                "reference_sha256": reference["sha256"],
                "candidate_sha256": candidate["sha256"],
            }
        )
    return {
        "passed": all(row["passed"] for row in rows),
        "rows": rows,
    }


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    run_root = args.run_root.resolve()
    reference_root = (
        args.reference_root.resolve()
        if args.reference_root is not None
        else None
    )
    summary_path = run_root / "p04_segment_first_summary.json"
    quality_path = run_root / "p04_segment_first_independent_quality.json"
    manifest_path = run_root / "p04_segment_first_input_manifest.json"

    summary = load_json(summary_path)
    quality = load_json(quality_path)
    manifest = load_json(manifest_path)
    performance = dict(summary.get("performance") or {})
    runtime_resources = dict(performance.get("runtime_resources") or {})
    native_limits = dict(runtime_resources.get("native_thread_limits") or {})
    surface_coverage_stats = dict(
        performance.get("surface_coverage") or {}
    )
    corridor_cache_stats = dict(
        performance.get("corridor_assembly_cache") or {}
    )
    target_path_cache_stats = dict(
        performance.get("target_path_cache") or {}
    )
    carrier_planner_stats = dict(
        performance.get("incremental_carrier_planner") or {}
    )
    interior_target_cache_stats = dict(
        performance.get("interior_target_cache") or {}
    )

    from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_inputs import (
        SEGMENT_FIRST_PATCH_LAYER_FAMILIES,
    )

    patch_count = patch_count_from_manifest(manifest)
    patch_vector_count = sum(
        item.get("role") == "patch_vector"
        for item in manifest.get("files", [])
    )
    wall_seconds = float(performance.get("wall_seconds") or 0.0)
    peak_rss_bytes = int(performance.get("peak_rss_bytes") or 0)
    wall_target_seconds = args.wall_target_hours * 3600.0
    wall_hard_seconds = args.wall_hard_hours * 3600.0
    baseline_wall_seconds = float(args.baseline_wall_seconds)
    wall_reduction_ratio = (
        wall_seconds / baseline_wall_seconds
        if baseline_wall_seconds > 0.0
        else math.inf
    )
    rss_target_bytes = args.rss_target_gib * GIB
    rss_hard_bytes = args.rss_hard_gib * GIB

    hard_gates = [
        gate(
            "required_outputs_present",
            all((run_root / name).is_file() for name in REQUIRED_OUTPUTS),
            actual=[
                name
                for name in REQUIRED_OUTPUTS
                if not (run_root / name).is_file()
            ],
            expected=[],
        ),
        gate(
            "patch_count_in_expected_range",
            args.expected_patch_count_min
            <= patch_count
            <= args.expected_patch_count_max,
            actual=patch_count,
            expected=(
                f"{args.expected_patch_count_min}.."
                f"{args.expected_patch_count_max}"
            ),
        ),
        gate(
            "eight_consumed_patch_layers_each",
            patch_vector_count
            == patch_count * len(SEGMENT_FIRST_PATCH_LAYER_FAMILIES),
            actual=patch_vector_count,
            expected=patch_count
            * len(SEGMENT_FIRST_PATCH_LAYER_FAMILIES),
        ),
        gate(
            "analysis_crs_expected",
            summary.get("analysis_crs") == args.expected_analysis_crs
            and quality.get("expected_crs") == args.expected_analysis_crs,
            actual={
                "summary": summary.get("analysis_crs"),
                "quality": quality.get("expected_crs"),
            },
            expected=args.expected_analysis_crs,
        ),
        gate(
            "wall_target_limit",
            0.0 < wall_seconds <= wall_target_seconds,
            actual=wall_seconds,
            expected=f"(0, {wall_target_seconds}]",
        ),
        gate(
            "wall_reduction_at_least_50_percent",
            0.0 < wall_reduction_ratio <= 0.5,
            actual=wall_reduction_ratio,
            expected="(0, 0.5]",
        ),
        gate(
            "wall_hard_limit",
            0.0 < wall_seconds <= wall_hard_seconds,
            actual=wall_seconds,
            expected=f"(0, {wall_hard_seconds}]",
        ),
        gate(
            "rss_hard_limit",
            0 < peak_rss_bytes < rss_hard_bytes,
            actual=peak_rss_bytes,
            expected=f"(0, {rss_hard_bytes})",
        ),
        gate(
            "rss_target_budget",
            0 < peak_rss_bytes <= rss_target_bytes,
            actual=peak_rss_bytes,
            expected=f"(0, {rss_target_bytes}]",
        ),
        gate(
            "logical_cpu_count_expected",
            runtime_resources.get("logical_cpu_count")
            == args.expected_logical_cpu_count,
            actual=runtime_resources.get("logical_cpu_count"),
            expected=args.expected_logical_cpu_count,
        ),
        gate(
            "patch_io_workers_bounded",
            runtime_resources.get("patch_io_workers_max") == 6,
            actual=runtime_resources.get("patch_io_workers_max"),
            expected=6,
        ),
        gate(
            "native_threads_bounded",
            all(native_limits.get(name) == "1" for name in NATIVE_THREAD_LIMITS),
            actual={
                name: native_limits.get(name)
                for name in NATIVE_THREAD_LIMITS
            },
            expected={name: "1" for name in NATIVE_THREAD_LIMITS},
        ),
        gate(
            "warning_volume_bounded",
            native_limits.get("CPL_MAX_ERROR_REPORTS") == "100",
            actual=native_limits.get("CPL_MAX_ERROR_REPORTS"),
            expected="100",
        ),
        gate(
            "surface_coverage_exactness_preserved",
            performance.get("surface_coverage_exactness_pass") is True
            and int(
                surface_coverage_stats.get(
                    "unsafe_local_reconstruction_count",
                    -1,
                    )
                )
                == 0,
            actual={
                "gate": performance.get(
                    "surface_coverage_exactness_pass"
                ),
                "unsafe_local_reconstruction_count": surface_coverage_stats.get(
                    "unsafe_local_reconstruction_count"
                ),
            },
            expected={
                "gate": True,
                "unsafe_local_reconstruction_count": 0,
            },
        ),
        gate(
            "corridor_assembly_cache_bounded",
            0
            <= int(corridor_cache_stats.get("entry_count", -1))
            <= int(corridor_cache_stats.get("entry_count_max", -2))
            and 0
            <= int(corridor_cache_stats.get("key_bytes", -1))
            <= int(corridor_cache_stats.get("key_bytes_max", -2)),
            actual={
                "entry_count": corridor_cache_stats.get("entry_count"),
                "entry_count_max": corridor_cache_stats.get(
                    "entry_count_max"
                ),
                "key_bytes": corridor_cache_stats.get("key_bytes"),
                "key_bytes_max": corridor_cache_stats.get("key_bytes_max"),
                "eviction_count": corridor_cache_stats.get(
                    "eviction_count"
                ),
            },
            expected="0 <= current <= configured bound",
        ),
        gate(
            "target_path_cache_bounded",
            0
            <= int(target_path_cache_stats.get("entry_count", -1))
            <= int(target_path_cache_stats.get("entry_count_max", -2))
            and 0
            <= int(target_path_cache_stats.get("key_bytes", -1))
            <= int(target_path_cache_stats.get("key_bytes_max", -2)),
            actual={
                "entry_count": target_path_cache_stats.get("entry_count"),
                "entry_count_max": target_path_cache_stats.get(
                    "entry_count_max"
                ),
                "key_bytes": target_path_cache_stats.get("key_bytes"),
                "key_bytes_max": target_path_cache_stats.get(
                    "key_bytes_max"
                ),
                "eviction_count": target_path_cache_stats.get(
                    "eviction_count"
                ),
            },
            expected="0 <= current <= configured bound",
        ),
        gate(
            "interior_target_cache_bounded",
            0
            <= int(interior_target_cache_stats.get("entry_count", -1))
            <= int(
                interior_target_cache_stats.get("entry_count_max", -2)
            )
            and 0
            <= int(interior_target_cache_stats.get("key_bytes", -1))
            <= int(
                interior_target_cache_stats.get("key_bytes_max", -2)
            ),
            actual={
                "entry_count": interior_target_cache_stats.get(
                    "entry_count"
                ),
                "entry_count_max": interior_target_cache_stats.get(
                    "entry_count_max"
                ),
                "key_bytes": interior_target_cache_stats.get("key_bytes"),
                "key_bytes_max": interior_target_cache_stats.get(
                    "key_bytes_max"
                ),
                "eviction_count": interior_target_cache_stats.get(
                    "eviction_count"
                ),
            },
            expected="0 <= current <= configured bound",
        ),
        gate(
            "incremental_carrier_reuse_active",
            int(carrier_planner_stats.get("invocation_count", 0)) >= 2
            and 1
            <= int(
                carrier_planner_stats.get(
                    "full_recompute_invocation_count",
                    0,
                )
            )
            < int(carrier_planner_stats.get("invocation_count", 0))
            and int(carrier_planner_stats.get("segment_units_reused", 0)) > 0
            and int(carrier_planner_stats.get("segment_units_seen", -1))
            == int(
                carrier_planner_stats.get("segment_units_recomputed", -2)
            )
            + int(carrier_planner_stats.get("segment_units_reused", -3)),
            actual=carrier_planner_stats,
            expected=(
                "invocations>=2, full recomputes below invocations, reused>0, "
                "seen=recomputed+reused"
            ),
        ),
        gate(
            "carrier_static_context_cache_active",
            int(
                carrier_planner_stats.get(
                    "carrier_context_cache_hit_count",
                    0,
                )
            )
            > 0
            and int(
                carrier_planner_stats.get(
                    "carrier_context_cache_miss_count",
                    0,
                )
            )
            > 0
            and float(
                carrier_planner_stats.get(
                    "carrier_context_prepare_seconds",
                    -1.0,
                )
            )
            >= 0.0
            and 0
            <= int(
                carrier_planner_stats.get(
                    "carrier_context_cache_entry_count",
                    -1,
                )
            )
            <= 5,
            actual={
                "hit_count": carrier_planner_stats.get(
                    "carrier_context_cache_hit_count"
                ),
                "miss_count": carrier_planner_stats.get(
                    "carrier_context_cache_miss_count"
                ),
                "prepare_seconds": carrier_planner_stats.get(
                    "carrier_context_prepare_seconds"
                ),
                "entry_count": carrier_planner_stats.get(
                    "carrier_context_cache_entry_count"
                ),
            },
            expected="hits>0, misses>0, prepare>=0, 0<=live entries<=5",
        ),
        gate(
            "independent_quality_pass",
            quality.get("gate_pass") is True
            and int((quality.get("counts") or {}).get("violation", -1)) == 0
            and all((quality.get("gates") or {}).values()),
            actual={
                "gate_pass": quality.get("gate_pass"),
                "violation": (quality.get("counts") or {}).get("violation"),
                "failed_gates": [
                    name
                    for name, value in (quality.get("gates") or {}).items()
                    if not value
                ],
            },
            expected={
                "gate_pass": True,
                "violation": 0,
                "failed_gates": [],
            },
        ),
        gate(
            "qgis_readback_pass",
            (summary.get("qgis") or {}).get("readback_pass") is True
            and not (summary.get("qgis") or {}).get("missing_layers")
            and int((summary.get("qgis") or {}).get("layer_count") or 0) > 0,
            actual=summary.get("qgis"),
            expected={
                "readback_pass": True,
                "missing_layers": [],
                "layer_count": ">0",
            },
        ),
    ]
    timeline_gates, rss_trend = timeline_assessment(performance)
    hard_gates.extend(timeline_gates)
    progress_gates, progress_evidence = progress_assessment(
        run_root / "p04_progress.jsonl"
    )
    hard_gates.extend(progress_gates)

    wall_target_pass = wall_seconds <= wall_target_seconds
    time_acceptance = {
        "target_pass": wall_target_pass,
        "reduction_50_percent_pass": wall_reduction_ratio <= 0.5,
        "baseline_wall_seconds": baseline_wall_seconds,
        "baseline_evidence_role": (
            "observed_lower_bound_before_abnormal_termination"
        ),
        "reduction_ratio": wall_reduction_ratio,
        "hard_pass": 0.0 < wall_seconds <= wall_hard_seconds,
        "eight_hour_role": "failure_diagnostic_line_only",
    }

    reference_evidence: dict[str, Any]
    if reference_root is None:
        reference_evidence = {
            "provided": False,
            "passed": None,
            "detail": (
                "没有同输入参考结果，自动验证不能单独证明业务零回退。"
            ),
        }
    else:
        reference_manifest = load_json(
            reference_root / "p04_segment_first_input_manifest.json"
        )
        input_identity_pass = (
            manifest_input_identity(reference_manifest)
            == manifest_input_identity(manifest)
        )
        artifact_result = compare_business_artifacts(
            repo_root=repo_root,
            reference_root=reference_root,
            candidate_root=run_root,
        )
        reference_evidence = {
            "provided": True,
            "passed": input_identity_pass and artifact_result["passed"],
            "same_input_identity": input_identity_pass,
            "business_artifacts": artifact_result,
        }
        hard_gates.append(
            gate(
                "business_zero_regression",
                bool(reference_evidence["passed"]),
                actual=reference_evidence,
                expected="same inputs and all business fingerprints equal",
            )
        )

    failed_gates = [item for item in hard_gates if not item["passed"]]
    core_gate_pass = summary.get("core_gate_pass") is True
    core_gate_review = {
        "core_gate_pass": core_gate_pass,
        "failed_core_gates": [
            name
            for name, value in (summary.get("core_gates") or {}).items()
            if not value
        ],
        "reference_comparison_provided": reference_root is not None,
        "review_required": not core_gate_pass and reference_root is None,
    }

    if failed_gates:
        status = "FAILED"
        exit_code = 2
    elif rss_trend["review_required"]:
        status = "REVIEW_REQUIRED"
        exit_code = 3
    elif reference_root is None:
        status = "EVIDENCE_READY"
        exit_code = 0
    elif wall_target_pass and wall_reduction_ratio <= 0.5:
        status = "ACCEPTED"
        exit_code = 0
    else:
        status = "FAILED"
        exit_code = 2

    return {
        "validator_version": "p04-innernet-acceptance-v3",
        "status": status,
        "exit_code": exit_code,
        "run_root": str(run_root),
        "reference_root": (
            str(reference_root) if reference_root is not None else None
        ),
        "patch_count": patch_count,
        "wall_seconds": wall_seconds,
        "peak_rss_bytes": peak_rss_bytes,
        "hard_gates": hard_gates,
        "failed_gate_names": [item["name"] for item in failed_gates],
        "time_acceptance": time_acceptance,
        "progress_evidence": progress_evidence,
        "surface_coverage_evidence": surface_coverage_stats,
        "rss_trend_advisory": rss_trend,
        "core_gate_review": core_gate_review,
        "business_reference_evidence": reference_evidence,
        "acceptance_rule": (
            "ACCEPTED requires <=6h, <=50% of the observed lower bound "
            "before abnormal termination, all "
            "automated gates, and same-input business reference equivalence; "
            "8h is failure diagnostics only and EVIDENCE_READY is not final "
            "acceptance."
        ),
    }


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    sys.path.insert(0, str(repo_root / "src"))
    report_path = args.report_path.resolve()
    report = evaluate(args)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print(f"[P04 acceptance] report={report_path}", file=sys.stderr)
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
