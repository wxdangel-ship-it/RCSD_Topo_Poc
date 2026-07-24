from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.inventory import scan_training_samples
from rcsd_topo_poc.modules.p05_neural_road_generation.models import M0Config, REGISTERED_FAMILIES


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture_root(root: Path) -> Path:
    for family in REGISTERED_FAMILIES:
        (root / family).mkdir(parents=True)
    _write_json(root / "T03" / "a" / "manifest.json", {"mainnodeid": "junction-x", "epsg": 3857})
    _write_json(root / "T03_Error" / "b" / "manifest.json", {"mainnodeid": "junction-x", "epsg": 3857, "variant": 2})
    _write_json(root / "T04" / "c" / "manifest.json", {"mainnodeid": "junction-y", "epsg": 3857})
    _write_json(root / "T04_Error" / "d" / "manifest.json", {"mainnodeid": "junction-z", "epsg": 3857})
    _write_json(root / "T10" / "case-1" / "t10_case_evidence_manifest.json", {"scope": {"case_id": "case-1"}})
    segment = {"scope": {"scope_type": "swsd_segment", "swsd_segment_id": "seg-1", "segment_properties": {"id": "seg-1"}}}
    _write_json(root / "T10-Error" / "seg-1" / "t10_case_evidence_manifest.json", segment)
    _write_json(root / "T10-Error-2" / "seg-1" / "t10_case_evidence_manifest.json", segment)
    return root


def test_inventory_applies_manual_truth_weights_and_grouping(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path / "POC_Data")
    config = M0Config(root, (), tmp_path / "out", "run", enforce_poc_scope=False)

    samples, anomalies = scan_training_samples(config)

    assert len(samples) == 7
    single_points = [sample for sample in samples if sample.family.startswith(("T03", "T04"))]
    assert all(sample.target_weight == 1.0 and sample.context_weight == 0.3 for sample in single_points)
    assert {sample.sample_group_id for sample in samples if sample.business_id == "junction-x"} == {"junction:junction-x"}
    assert {sample.sample_group_id for sample in samples if sample.business_id == "seg-1"} == {"segment:seg-1"}
    assert any(item.category == "multiple_archived_versions" for item in anomalies)


def test_inventory_rejects_wrong_strict_root(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path / "POC_Data")
    config = M0Config(root, (), tmp_path / "out", "run", enforce_poc_scope=True)

    try:
        scan_training_samples(config)
    except ValueError as exc:
        assert "scope violation" in str(exc)
    else:
        raise AssertionError("strict scope must reject a non-canonical root")


def test_inventory_records_missing_manifest_without_silent_drop(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path / "POC_Data")
    (root / "T03" / "missing-manifest").mkdir()
    config = M0Config(root, (), tmp_path / "out", "run", enforce_poc_scope=False)

    samples, anomalies = scan_training_samples(config)

    assert len(samples) == 7
    assert any(
        item.category == "invalid_case_manifest" and item.business_id == "missing-manifest"
        for item in anomalies
    )
