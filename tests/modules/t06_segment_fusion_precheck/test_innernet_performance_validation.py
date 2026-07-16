from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

from shapely.geometry import Point

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_vector


REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR_PATH = (
    REPO_ROOT
    / "specs/t06-innernet-performance-50pct-20260716/validation/validate_innernet_candidate.py"
)
COLLECTOR_PATH = (
    REPO_ROOT
    / "specs/t06-innernet-performance-50pct-20260716/validation/collect_innernet_validation.py"
)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_validator() -> ModuleType:
    return _load_module("t06_innernet_candidate_validator", VALIDATOR_PATH)


def _write_time(path: Path, *, elapsed: str, peak: int, swaps: int = 0, status: int = 0) -> None:
    path.write_text(
        "\n".join(
            [
                "User time (seconds): 10.0",
                "System time (seconds): 1.0",
                f"Elapsed (wall clock) time (h:mm:ss or m:ss): {elapsed}",
                f"Maximum resident set size (kbytes): {peak}",
                f"Swaps: {swaps}",
                f"Exit status: {status}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_parse_elapsed_seconds_supports_gnu_time_formats() -> None:
    validator = _load_validator()
    assert validator.parse_elapsed_seconds("05:30") == 330.0
    assert validator.parse_elapsed_seconds("1:02:03") == 3723.0
    assert validator.parse_elapsed_seconds("1-01:00:00") == 90000.0


def test_performance_summary_passes_only_all_formal_gates(tmp_path: Path) -> None:
    validator = _load_validator()
    step12 = tmp_path / "t06_step12.time.txt"
    step3 = tmp_path / "t06_step3.time.txt"
    step3_log = tmp_path / "t06_step3.log"
    _write_time(step12, elapsed="1:00:00", peak=2_000_000)
    _write_time(step3, elapsed="4:30:00", peak=8_000_000)
    step3_log.write_text("[T06 Step3] stage=read_summary elapsed=15000.000s\n", encoding="utf-8")

    summary = validator.build_performance_summary(
        step12_time_path=step12,
        step3_time_path=step3,
        step3_log_path=step3_log,
    )

    assert summary["passed"] is True
    assert summary["candidate"]["t06_group_wall_sum_seconds"] == 19800.0
    assert summary["candidate"]["peak_rss_kb"] == 8_000_000


def test_performance_summary_rejects_time_memory_swap_and_exit_regression(tmp_path: Path) -> None:
    validator = _load_validator()
    step12 = tmp_path / "t06_step12.time.txt"
    step3 = tmp_path / "t06_step3.time.txt"
    step3_log = tmp_path / "t06_step3.log"
    _write_time(step12, elapsed="2:00:00", peak=2_000_000, swaps=1)
    _write_time(step3, elapsed="5:00:00", peak=9_500_000, status=1)
    step3_log.write_text("[T06 Step3] stage=read_summary elapsed=17000.000s\n", encoding="utf-8")

    summary = validator.build_performance_summary(
        step12_time_path=step12,
        step3_time_path=step3,
        step3_log_path=step3_log,
    )

    assert summary["passed"] is False
    assert not all(summary["checks"].values())


def test_business_comparison_normalizes_run_roots(tmp_path: Path) -> None:
    validator = _load_validator()
    baseline_run = tmp_path / "baseline"
    candidate_run = tmp_path / "candidate"
    relative = validator.T06_RELATIVE_ROOT
    baseline_t06 = baseline_run / relative
    candidate_t06 = candidate_run / relative
    baseline_t06.mkdir(parents=True)
    candidate_t06.mkdir(parents=True)
    (baseline_t06 / "summary.json").write_text(
        '{"status":"passed","artifact":"'
        + str(baseline_t06 / "step1_identify_fusion_units/result.gpkg")
        + '"}',
        encoding="utf-8",
    )
    (candidate_t06 / "summary.json").write_text(
        '{"status":"passed","artifact":"'
        + str(tmp_path / "stale_candidate_v7/step1_identify_fusion_units/result.gpkg")
        + '"}',
        encoding="utf-8",
    )
    (baseline_t06 / "audit.csv").write_text("id,status\n1,ok\n2,review\n", encoding="utf-8")
    (candidate_t06 / "audit.csv").write_text("id,status\n2,review\n1,ok\n", encoding="utf-8")
    write_vector(
        baseline_t06 / "result.gpkg",
        [{"properties": {"id": "1"}, "geometry": Point(1.0, 2.0)}],
    )
    write_vector(
        candidate_t06 / "result.gpkg",
        [{"properties": {"id": "1"}, "geometry": Point(1.0, 2.0)}],
    )

    comparison = validator.compare_business_outputs(
        baseline_run_root=baseline_run,
        candidate_run_root=candidate_run,
        out_dir=tmp_path / "compare",
    )

    assert comparison["passed"] is True
    assert comparison["reference_artifact_count"] == 3

    validator.semantic_fingerprint = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("valid checkpoint should avoid recomputing semantic fingerprints")
    )
    resumed = validator.compare_business_outputs(
        baseline_run_root=baseline_run,
        candidate_run_root=candidate_run,
        out_dir=tmp_path / "compare",
    )
    assert resumed["passed"] is True


def test_collector_exports_and_verifies_250kib_text_bundle(tmp_path: Path) -> None:
    collector = _load_module("t06_innernet_validation_collector", COLLECTOR_PATH)
    candidate = tmp_path / "candidate"
    evidence = candidate / "logs/t06_perf_validation"
    t06_root = candidate / "t06_segment_fusion_precheck/t06_innernet_precheck"
    evidence.mkdir(parents=True)
    t06_root.mkdir(parents=True)
    (t06_root / "summary.json").write_text('{"status":"passed"}', encoding="utf-8")
    (evidence / "t06_innernet_validation_summary.json").write_text(
        '{"overall_passed":true}', encoding="utf-8"
    )
    (candidate / "t06_perf_validation.status").write_text("STATUS=PASSED\n", encoding="utf-8")
    (candidate / "t10_innernet_full_pipeline_manifest.json").write_text(
        '{"pipeline_status":"passed"}', encoding="utf-8"
    )
    collector._environment = lambda _repo: {"repo_head": "candidate"}

    parts = collector.collect(
        SimpleNamespace(repo=REPO_ROOT, candidate_run_root=candidate, evidence_dir=evidence)
    )

    assert parts
    assert all(path.is_file() and path.stat().st_size <= 250 * 1024 for path in parts)


def test_summary_consistency_rejects_audit_or_compat_business_drift(tmp_path: Path) -> None:
    validator = _load_validator()
    baseline_t06 = tmp_path / "baseline_t06"
    candidate_t06 = tmp_path / "candidate_t06"
    baseline_step3 = baseline_t06 / "step3_segment_replacement"
    candidate_step3 = candidate_t06 / "step3_segment_replacement"
    baseline_step3.mkdir(parents=True)
    candidate_step3.mkdir(parents=True)
    baseline_summary = {"replacement_unit_count": 1}
    summary = {
        "summary_schema": "t06_step3_summary_compact_v1",
        "replacement_unit_count": 1,
        "topology_connectivity_fail_count": 0,
        "topology_connectivity_warn_count": 0,
        "topology_connectivity_pass_count": 1,
        "topology_audit_fail_row_count": 0,
        "final_frcsd_topology_fail_row_count": 0,
        "final_frcsd_topology_fail_count": 0,
        "final_frcsd_segment_transition_fail_count": 0,
        "final_frcsd_independent_attachment_fail_count": 0,
        "topology": {
            "audit_row_count": 1,
            "fail_count": 0,
            "warn_count": 0,
            "pass_count": 1,
            "segment_internal_connectivity_pass_count": 1,
        },
    }
    detail = {
        "replacement_unit_count": 1,
        "topology_connectivity_audit_row_count": 1,
        "topology_connectivity_fail_count": 0,
        "topology_connectivity_warn_count": 0,
        "topology_connectivity_pass_count": 1,
        "topology_connectivity_segment_internal_connectivity_pass_count": 1,
        "topology_audit_fail_row_count": 0,
        "final_frcsd_topology_fail_row_count": 0,
        "final_frcsd_topology_fail_count": 0,
        "final_frcsd_segment_transition_fail_count": 0,
        "final_frcsd_independent_attachment_fail_count": 0,
    }
    (baseline_step3 / "t06_step3_summary.json").write_text(
        json.dumps(baseline_summary), encoding="utf-8"
    )
    summary_path = candidate_step3 / "t06_step3_summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    (candidate_step3 / "t06_step3_detail_metrics.json").write_text(
        json.dumps(detail), encoding="utf-8"
    )
    (candidate_step3 / "t06_step3_topology_connectivity_audit.csv").write_text(
        "audit_layer,audit_status,counts_in_final_frcsd_topology_fail,"
        "final_topology_category,final_topology_object_key\n"
        "segment_internal_connectivity,pass,False,,,\n",
        encoding="utf-8",
    )

    assert validator._validate_candidate_step3_summaries(baseline_t06, candidate_t06)["passed"]

    summary["replacement_unit_count"] = 2
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    business_drift = validator._validate_candidate_step3_summaries(baseline_t06, candidate_t06)
    assert business_drift["passed"] is False
    assert "summary_compat_business::replacement_unit_count" in business_drift["failed_checks"]

    summary["replacement_unit_count"] = 1
    summary["topology"]["pass_count"] = 0
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    audit_drift = validator._validate_candidate_step3_summaries(baseline_t06, candidate_t06)
    assert audit_drift["passed"] is False
    assert "summary_pass_count" in audit_drift["failed_checks"]
