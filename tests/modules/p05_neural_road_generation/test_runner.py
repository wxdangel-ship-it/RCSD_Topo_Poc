from __future__ import annotations

import json
from pathlib import Path

import fiona
import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation import M0Config, build_m0_benchmark
from rcsd_topo_poc.modules.p05_neural_road_generation.models import ApprovedExclusion, LabelArtifact, REGISTERED_FAMILIES
from rcsd_topo_poc.modules.p05_neural_road_generation.runner import _oracle_evaluation


def _json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _road_graph(root: Path, *, end_node_id: str = "n2") -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    road = root / "road.gpkg"
    node = root / "node.gpkg"
    with fiona.open(road, "w", driver="GPKG", layer="road", crs="EPSG:3857", schema={"geometry": "LineString", "properties": {"id": "str", "snodeid": "str", "enodeid": "str", "direction": "int", "source": "int"}}) as sink:
        sink.write({"geometry": {"type": "LineString", "coordinates": ((0.0, 0.0), (1.0, 0.0))}, "properties": {"id": "r", "snodeid": "n1", "enodeid": end_node_id, "direction": 2, "source": 1}})
    with fiona.open(node, "w", driver="GPKG", layer="node", crs="EPSG:3857", schema={"geometry": "Point", "properties": {"id": "str", "source": "int"}}) as sink:
        sink.write({"geometry": {"type": "Point", "coordinates": (0.0, 0.0)}, "properties": {"id": "n1", "source": 1}})
        sink.write({"geometry": {"type": "Point", "coordinates": (1.0, 0.0)}, "properties": {"id": "n2", "source": 1}})
    return road, node


def _full_fixture(tmp_path: Path) -> tuple[Path, Path]:
    poc_root = tmp_path / "POC_Data"
    for family in REGISTERED_FAMILIES:
        (poc_root / family).mkdir(parents=True)
    _json(poc_root / "T03" / "a" / "manifest.json", {"mainnodeid": "j1", "epsg": 3857})
    _json(poc_root / "T03_Error" / "b" / "manifest.json", {"mainnodeid": "j2", "epsg": 3857})
    _json(poc_root / "T04" / "c" / "manifest.json", {"mainnodeid": "j3", "epsg": 3857})
    _json(poc_root / "T04_Error" / "d" / "manifest.json", {"mainnodeid": "j4", "epsg": 3857})
    _json(poc_root / "T10" / "case1" / "t10_case_evidence_manifest.json", {"scope": {"case_id": "case1"}})
    segment = lambda value: {"scope": {"scope_type": "swsd_segment", "swsd_segment_id": value, "segment_properties": {"id": value}}}
    _json(poc_root / "T10-Error" / "seg1" / "t10_case_evidence_manifest.json", segment("seg1"))
    _json(poc_root / "T10-Error-2" / "seg2" / "t10_case_evidence_manifest.json", segment("seg2"))

    baseline = tmp_path / "baseline"
    packages = []
    for key, family, case_id in (("t10", "T10", "case1"), ("t10_error", "T10-Error", "segment_seg1"), ("t10_error2", "T10-Error-2", "segment_seg2")):
        run_root = baseline / key / "e2e_full"
        case_root = run_root / "cases" / case_id
        road, node = _road_graph(case_root)
        _json(case_root / "t10_e2e_case_run_summary.json", {"passed": True, "t06_funnel": {"handoffs": {"t06_frcsd_road": str(road), "t06_frcsd_node": str(node)}}})
        packages.append({"source_root": str(poc_root / family), "run_root": str(run_root)})
    _json(baseline / "baseline_summary.json", {"baseline_id": "fixture", "repo_head": "abc", "package_summaries": packages})
    return poc_root, baseline


def test_runner_writes_complete_immutable_m0_bundle(tmp_path: Path) -> None:
    poc_root, baseline = _full_fixture(tmp_path)
    config = M0Config(
        poc_root,
        (baseline,),
        tmp_path / "outputs",
        "m0",
        enforce_poc_scope=False,
        approved_exclusions=(ApprovedExclusion("T10-Error", "seg1", "user approved fixture exclusion"),),
    )

    run_root = build_m0_benchmark(config)

    expected = {
        "p05_m0_manifest.json",
        "p05_training_samples.csv",
        "p05_label_artifacts.csv",
        "p05_grouped_split.csv",
        "p05_data_anomalies.csv",
        "p05_oracle_evaluation.json",
        "p05_m0_summary.json",
        "p05_m0_report.md",
    }
    assert expected.issubset({path.name for path in run_root.iterdir()})
    summary = json.loads((run_root / "p05_m0_summary.json").read_text(encoding="utf-8"))
    assert summary["sample_count"] == 7
    assert summary["road_graph_training_sample_count"] == 2
    assert summary["usable_sample_count"] == 6
    assert summary["oracle_all_passed"] is True
    assert summary["approved_exclusion_count"] == 1
    assert summary["oracle_quarantined_count"] == 0
    assert summary["corruption_suite_all_detected"] is True
    with pytest.raises(FileExistsError):
        build_m0_benchmark(config)


def test_oracle_quarantines_truth_with_missing_endpoint(tmp_path: Path) -> None:
    road, node = _road_graph(tmp_path / "broken", end_node_id="missing")
    common = {
        "sample_id": "sample",
        "family": "T10-Error",
        "business_id": "seg",
        "artifact_sha256": "a" * 64,
        "baseline_id": "baseline",
        "repo_head": "head",
        "baseline_summary_path": "summary",
        "case_run_summary_path": "case-summary",
        "source_case_root": "case",
        "target_selector": "seg",
        "target_weight": 0.7,
        "context_weight": 0.3,
    }
    artifacts = [
        LabelArtifact(role="t06_frcsd_road", artifact_path=str(road), **common),
        LabelArtifact(role="t06_frcsd_node", artifact_path=str(node), **common),
    ]

    oracle = _oracle_evaluation(artifacts, tmp_path / "oracle")

    assert oracle["evaluated_case_count"] == 1
    assert oracle["case_count"] == 0
    assert oracle["quarantined_count"] == 1
    assert oracle["quarantined_sample_ids"] == ["sample"]

    approved = _oracle_evaluation(
        artifacts,
        tmp_path / "oracle-approved",
        approved_exclusion_keys=frozenset({("T10-Error", "seg")}),
    )
    assert approved["approved_exclusion_count"] == 1
    assert approved["quarantined_count"] == 0
    assert approved["approved_exclusion_sample_ids"] == ["sample"]
