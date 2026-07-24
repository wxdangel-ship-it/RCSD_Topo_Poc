from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_historical import (
    audit_historical_surface_outputs,
)


def _json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_historical_surface_requires_exact_manifest_and_terminal_state(tmp_path: Path) -> None:
    case_root = tmp_path / "cases_in"
    run_root = tmp_path / "run"
    manifest = case_root / "42" / "manifest.json"
    _json(manifest, {"mainnodeid": "42", "epsg": 3857, "checksum": {"nodes.gpkg": "abc"}})
    _json(run_root / "preflight.json", {"case_root": str(case_root), "selected_case_ids": ["42"]})
    _json(run_root / "cases" / "42" / "step7_status.json", {"step7_state": "accepted"})
    geometry = run_root / "cases" / "42" / "step7_final_polygon.gpkg"
    geometry.write_bytes(b"surface")
    samples = [
        {
            "sample_id": "T03:42:sample",
            "family": "T03",
            "business_id": "42",
            "manifest_path": str(manifest),
            "manifest_sha256": _sha(manifest),
        }
    ]

    targets, anomalies, documents, summary = audit_historical_surface_outputs(
        samples,
        [run_root],
        label_root=tmp_path / "normalized",
        user_confirmed_strategy_replay=True,
    )

    assert anomalies == []
    assert summary["accepted_label_count"] == 1
    assert [(item.task_name, item.target_kind, item.target_selector) for item in targets] == [
        ("T03", "surface", "42")
    ]
    payload = next(iter(documents.values()))
    assert hashlib.sha256(payload).hexdigest() == targets[0].artifact_sha256
    assert json.loads(payload)["lineage_gate"]["input_manifest_sha256_exact_match"] is True


def test_historical_surface_rejects_missing_source_root(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    _json(
        run_root / "preflight.json",
        {"case_root": str(tmp_path / "gone"), "selected_case_ids": ["42"]},
    )
    (run_root / "cases" / "42").mkdir(parents=True)
    (run_root / "cases" / "42" / "step7_final_polygon.gpkg").write_bytes(b"surface")

    targets, anomalies, documents, summary = audit_historical_surface_outputs(
        [],
        [run_root],
        label_root=tmp_path / "normalized",
        user_confirmed_strategy_replay=True,
    )

    assert targets == []
    assert documents == {}
    assert summary["accepted_label_count"] == 0
    assert anomalies[0]["category"] == "historical_source_case_root_missing"


def test_historical_t03_relation_is_registered_only_from_explicit_association_class(tmp_path: Path) -> None:
    case_root = tmp_path / "cases_in"
    run_root = tmp_path / "run"
    manifest = case_root / "42" / "manifest.json"
    _json(manifest, {"mainnodeid": "42", "epsg": 3857})
    _json(run_root / "preflight.json", {"case_root": str(case_root), "selected_case_ids": ["42"]})
    _json(
        run_root / "cases" / "42" / "step7_status.json",
        {"step7_state": "rejected", "association_class": "C", "association_state": "not_established"},
    )
    samples = [{
        "sample_id": "T03:42:sample",
        "family": "T03",
        "business_id": "42",
        "manifest_path": str(manifest),
        "manifest_sha256": _sha(manifest),
    }]

    targets, anomalies, documents, summary = audit_historical_surface_outputs(
        samples, [run_root], label_root=tmp_path / "normalized", user_confirmed_strategy_replay=True
    )

    assert anomalies == []
    assert summary["accepted_label_count"] == 2
    assert {item.target_kind for item in targets} == {"surface", "relation"}
    relation = next(json.loads(payload) for path, payload in documents.items() if path.name.endswith("_relation.json"))
    assert relation["relation_evidence"]["label"] == {"association_class": "C", "class_index": 2}
