from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.labels import discover_label_artifacts
from rcsd_topo_poc.modules.p05_neural_road_generation.models import M0Config, TrainingSample
from rcsd_topo_poc.modules.p05_neural_road_generation.splits import build_grouped_split


def _cross_runtime_path(path: Path) -> str:
    resolved = path.resolve()
    if resolved.drive:
        tail = resolved.as_posix().split(":", 1)[1].lstrip("/")
        return f"/mnt/{resolved.drive[0].lower()}/{tail}"
    return str(resolved)


def _sample(sample_id: str, group: str, *, family: str = "T10", business_id: str = "case-1") -> TrainingSample:
    return TrainingSample(
        sample_id=sample_id,
        family=family,
        business_id=business_id,
        sample_group_id=group,
        scope_type="t10_case",
        case_root="case",
        manifest_path="manifest",
        manifest_sha256="a" * 64,
        target_weight=0.7,
        context_weight=0.7,
        task_mask={"road_graph": False},
        task_mask_reasons={"road_graph": "pending"},
    )


def test_label_lineage_uses_explicit_passed_handoffs(tmp_path: Path) -> None:
    poc_root = tmp_path / "POC_Data"
    source_root = poc_root / "T10"
    source_root.mkdir(parents=True)
    for family in ("T03", "T03_Error", "T04", "T04_Error", "T10-Error", "T10-Error-2"):
        (poc_root / family).mkdir()
    baseline = tmp_path / "baseline"
    case_dir = baseline / "t10" / "e2e_full" / "cases" / "case-1"
    case_dir.mkdir(parents=True)
    road = case_dir / "road.gpkg"
    node = case_dir / "node.gpkg"
    road.write_bytes(b"road")
    node.write_bytes(b"node")
    (baseline / "baseline_summary.json").write_text(
        json.dumps(
            {
                "baseline_id": "b1",
                "repo_head": "abc",
                "source_root": _cross_runtime_path(source_root),
                "run_root": _cross_runtime_path(baseline / "t10" / "e2e_full"),
            }
        ),
        encoding="utf-8",
    )
    (case_dir / "t10_e2e_case_run_summary.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "t06_funnel": {"handoffs": {"t06_frcsd_road": _cross_runtime_path(road), "t06_frcsd_node": _cross_runtime_path(node)}},
            }
        ),
        encoding="utf-8",
    )
    config = M0Config(poc_root, (baseline,), tmp_path / "out", "run", enforce_poc_scope=False)

    updated, artifacts, anomalies = discover_label_artifacts(config, [_sample("s1", "case:case-1")])

    assert {artifact.role for artifact in artifacts} == {"t06_frcsd_road", "t06_frcsd_node"}
    assert updated[0].task_mask["road_graph"] is True
    assert not [item for item in anomalies if item.severity == "error"]


def test_label_lineage_masks_missing_truth_and_rejects_wrong_source(tmp_path: Path) -> None:
    poc_root = tmp_path / "POC_Data"
    source_root = poc_root / "T10"
    source_root.mkdir(parents=True)
    baseline = tmp_path / "baseline"
    case_dir = baseline / "run" / "cases" / "case-1"
    case_dir.mkdir(parents=True)
    road = case_dir / "road.gpkg"
    road.write_bytes(b"road")
    (baseline / "baseline_summary.json").write_text(
        json.dumps({"baseline_id": "b1", "source_root": str(source_root), "run_root": str(baseline / "run")}),
        encoding="utf-8",
    )
    (case_dir / "t10_e2e_case_run_summary.json").write_text(
        json.dumps({"passed": True, "t06_funnel": {"handoffs": {"t06_frcsd_road": str(road)}}}),
        encoding="utf-8",
    )
    config = M0Config(poc_root, (baseline,), tmp_path / "out", "run", enforce_poc_scope=False)

    updated, _, anomalies = discover_label_artifacts(config, [_sample("s1", "case:case-1")])

    assert updated[0].task_mask["road_graph"] is False
    assert any(item.category == "road_graph_label_incomplete" for item in anomalies)

    wrong_baseline = tmp_path / "wrong-baseline"
    wrong_baseline.mkdir()
    (wrong_baseline / "baseline_summary.json").write_text(
        json.dumps({"source_root": str(tmp_path / "outside" / "T10"), "run_root": str(baseline / "run")}),
        encoding="utf-8",
    )
    wrong_config = M0Config(poc_root, (wrong_baseline,), tmp_path / "out", "wrong", enforce_poc_scope=False)
    _, _, wrong_anomalies = discover_label_artifacts(wrong_config, [_sample("s1", "case:case-1")])
    assert any(item.category == "baseline_scope_violation" for item in wrong_anomalies)


def test_grouped_split_is_deterministic_and_leak_free() -> None:
    samples = [_sample("s1", "segment:x"), _sample("s2", "segment:x"), _sample("s3", "segment:y")]

    first = build_grouped_split(samples, "seed")
    second = build_grouped_split(samples, "seed")

    assert first == second
    x_splits = {item.split for item in first if item.sample_group_id == "segment:x"}
    x_folds = {item.fold for item in first if item.sample_group_id == "segment:x"}
    assert len(x_splits) == 1
    assert len(x_folds) == 1
