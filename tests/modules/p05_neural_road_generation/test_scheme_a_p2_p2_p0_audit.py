from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p0_audit import (
    SchemeAP2P2P0AuditConfig,
    _load_compatibility_edges,
    _load_effective_selections,
    build_scheme_a_p2_p2_p0_audit,
)


def test_audit_separates_segment_root_from_propagated_node(tmp_path: Path) -> None:
    dataset, oof_a, oof_b = _fixture(tmp_path)
    run = build_scheme_a_p2_p2_p0_audit(
        _config(tmp_path, dataset, oof_a, oof_b, "audit-pass")
    )
    summary = json.loads(
        (run / "scheme_a_p2_p2_p0_audit_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["decision"] == "P05_SCHEME_A_P2_P2_P0_CALIBRATION_EVIDENCE_GO"
    assert summary["error_summary"]["prior_accepted_wrong_counts"] == {
        "17": 2,
        "29": 0,
        "43": 0,
    }
    assert summary["error_summary"]["accepted_segment_root_error_counts"] == {
        "17": 1,
        "29": 0,
        "43": 0,
    }
    assert summary["error_summary"]["stable_false_use_count"] == 1
    assert summary["score_separability"]["best_zero_error_use_coverage"] == 1.0
    error_rows = list(_read_jsonl(run / "error_chains.jsonl"))
    assert {row["classification"] for row in error_rows} == {
        "SEGMENT_ACCEPTED_ROOT_ERROR",
        "NODE_PROPAGATED_ACCEPTED_SEGMENT_ERROR",
    }
    signal_rows = list(_read_jsonl(run / "safety_signals.jsonl"))
    assert all(row["feature_uses_truth"] is False for row in signal_rows)
    assert all(row["feature_uses_identifier"] is False for row in signal_rows)


def test_audit_rejects_truth_leak_in_signal_features(tmp_path: Path) -> None:
    dataset, oof_a, oof_b = _fixture(tmp_path, truth_feature=True)
    with pytest.raises(ValueError, match="truth or absolute coordinate leaked"):
        build_scheme_a_p2_p2_p0_audit(
            _config(tmp_path, dataset, oof_a, oof_b, "truth-leak")
        )


def test_audit_rejects_hash_mismatch(tmp_path: Path) -> None:
    dataset, oof_a, oof_b = _fixture(tmp_path)
    with (oof_b / "scores.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="artifact hash differs"):
        build_scheme_a_p2_p2_p0_audit(
            _config(tmp_path, dataset, oof_a, oof_b, "hash-mismatch")
        )


def test_effective_selection_rejects_missing_seed(tmp_path: Path) -> None:
    path = tmp_path / "effective.jsonl"
    _write_artifact(
        path,
        [
            _selection(
                seed,
                "segment-safe",
                "SEGMENT",
                "s1-use",
                "USE_RCSD",
                "s1-use",
                "USE_RCSD",
                True,
            )
            for seed in (17, 29)
        ],
    )
    labels = {
        "segment-safe": _label(
            "segment-safe", "SEGMENT", "s1-use", "USE_RCSD"
        )
    }
    with pytest.raises(ValueError, match="effective selection denominator differs"):
        _load_effective_selections(path, labels, (17, 29, 43))


def test_compatibility_edge_rejects_unknown_group(tmp_path: Path) -> None:
    path = tmp_path / "edges.jsonl"
    _write_artifact(
        path,
        [_edge("segment-safe", "s1-use", "missing-node", "PROPOSAL_NODE")],
    )
    labels = {
        "segment-safe": _label(
            "segment-safe", "SEGMENT", "s1-use", "USE_RCSD"
        )
    }
    with pytest.raises(ValueError, match="compatibility edge has unknown group"):
        _load_compatibility_edges(path, labels)


def _config(
    root: Path, dataset: Path, oof_a: Path, oof_b: Path, run_id: str
) -> SchemeAP2P2P0AuditConfig:
    return SchemeAP2P2P0AuditConfig(
        dataset_run_root=dataset,
        oof_run_root_a=oof_a,
        oof_run_root_b=oof_b,
        output_root=root / "outputs",
        run_id=run_id,
        expected_case_count=1,
        expected_segment_count=2,
        expected_node_count=1,
        expected_review_count=0,
    )


def _fixture(
    root: Path, *, truth_feature: bool = False
) -> tuple[Path, Path, Path]:
    dataset = root / "dataset"
    dataset.mkdir()
    labels = [
        _label("segment-safe", "SEGMENT", "s1-use", "USE_RCSD"),
        _label("segment-risk", "SEGMENT", "s2-keep", "KEEP_SWSD"),
        _label("node-1", "NODE", "n-t01", "T01_NODE"),
    ]
    features = [
        _feature("segment-safe", "s1-use", "USE_RCSD", 2.0, truth_feature),
        _feature("segment-safe", "s1-keep", "KEEP_SWSD", 1.0, truth_feature),
        _feature("segment-risk", "s2-use", "USE_RCSD", 4.0, truth_feature),
        _feature("segment-risk", "s2-keep", "KEEP_SWSD", 3.0, truth_feature),
    ]
    edges = [
        _edge("segment-risk", "s2-use", "node-1", "PROPOSAL_NODE"),
        _edge("segment-risk", "s2-keep", "node-1", "T01_NODE"),
    ]
    dataset_outputs = {
        "features": _write_artifact(dataset / "features.jsonl", features),
        "labels": _write_artifact(dataset / "labels.jsonl", labels),
        "compatibility_edges": _write_artifact(
            dataset / "compatibility_edges.jsonl", edges
        ),
        "summary": _write_json_artifact(dataset / "summary.json", {"gate_pass": True}),
    }
    write_json(
        dataset / "scheme_a_p2_p1_dataset_manifest.json",
        {"outputs": dataset_outputs},
    )

    scores: list[dict[str, Any]] = []
    effective: list[dict[str, Any]] = []
    roadgraphs: list[dict[str, Any]] = []
    seed_metrics: list[dict[str, Any]] = []
    for seed in (17, 29, 43):
        scores.extend(_score_rows(seed, "segment-safe", "s1-use", "s1-keep", 0.99))
        scores.extend(_score_rows(seed, "segment-risk", "s2-use", "s2-keep", 0.98))
        risk_accepted = seed == 17
        effective.extend(
            [
                _selection(
                    seed,
                    "segment-safe",
                    "SEGMENT",
                    "s1-use",
                    "USE_RCSD",
                    "s1-use",
                    "USE_RCSD",
                    True,
                ),
                _selection(
                    seed,
                    "segment-risk",
                    "SEGMENT",
                    "s2-use",
                    "USE_RCSD",
                    "s2-use" if risk_accepted else "s2-keep",
                    "USE_RCSD" if risk_accepted else "KEEP_SWSD",
                    risk_accepted,
                ),
                _selection(
                    seed,
                    "node-1",
                    "NODE",
                    "n-proposal" if risk_accepted else "n-t01",
                    "PROPOSAL_NODE" if risk_accepted else "T01_NODE",
                    "n-proposal" if risk_accepted else "n-t01",
                    "PROPOSAL_NODE" if risk_accepted else "T01_NODE",
                    True,
                ),
            ]
        )
        roadgraphs.append(
            {"seed": seed, "case_key": "T10:fixture", "terminal_state": "LEGAL"}
        )
        seed_metrics.append(
            {"seed": seed, "accepted_wrong_replacement_count": 2 if risk_accepted else 0}
        )
    oof_a = _oof_fixture(root / "oof-a", scores, effective, roadgraphs, seed_metrics)
    oof_b = _oof_fixture(root / "oof-b", scores, effective, roadgraphs, seed_metrics)
    return dataset, oof_a, oof_b


def _oof_fixture(
    root: Path,
    scores: Iterable[Mapping[str, Any]],
    effective: Iterable[Mapping[str, Any]],
    roadgraphs: Iterable[Mapping[str, Any]],
    seed_metrics: Iterable[Mapping[str, Any]],
) -> Path:
    root.mkdir()
    effective_rows = list(effective)
    outputs = {
        "scores": _write_artifact(root / "scores.jsonl", scores),
        "selections": _write_artifact(root / "selections.jsonl", effective_rows),
        "effective_selections": _write_artifact(
            root / "effective_selections.jsonl", effective_rows
        ),
        "roadgraphs": _write_artifact(root / "roadgraphs.jsonl", roadgraphs),
        "summary": _write_json_artifact(
            root / "summary.json", {"seed_metrics": list(seed_metrics)}
        ),
    }
    write_json(root / "scheme_a_p2_p1_oof_manifest.json", {"outputs": outputs})
    return root


def _label(
    group_id: str, object_type: str, truth_candidate_id: str, target: str
) -> dict[str, Any]:
    return {
        "case_key": "T10:fixture",
        "group_id": group_id,
        "object_id": group_id,
        "object_type": object_type,
        "truth_candidate_id": truth_candidate_id,
        "carrier_target": target,
    }


def _feature(
    group_id: str,
    candidate_id: str,
    target: str,
    numeric: float,
    truth_feature: bool,
) -> dict[str, Any]:
    return {
        "group_id": group_id,
        "object_type": "SEGMENT",
        "candidate_id": candidate_id,
        "candidate_target": target,
        "candidate_tokens": [f"OPTION:{target}"],
        "context_tokens": ["CONTEXT:fixture"],
        "hard_unsafe": False,
        "numeric_features": [numeric] * 8,
        "object_tokens": ["OBJECT:SEGMENT"],
        "feature_uses_truth": truth_feature,
        "absolute_coordinate_feature_count": 0,
    }


def _edge(
    segment_group: str,
    candidate_id: str,
    node_group: str,
    target: str,
) -> dict[str, Any]:
    return {
        "segment_group_id": segment_group,
        "segment_candidate_id": candidate_id,
        "node_group_id": node_group,
        "required_node_target": target,
        "feature_uses_truth": False,
    }


def _score_rows(
    seed: int, group_id: str, top_id: str, other_id: str, top_probability: float
) -> list[dict[str, Any]]:
    top_target = "USE_RCSD"
    return [
        {
            "seed": seed,
            "group_id": group_id,
            "object_type": "SEGMENT",
            "candidate_id": top_id,
            "candidate_target": top_target,
            "probability": top_probability,
            "anomaly_probability": 0.01,
        },
        {
            "seed": seed,
            "group_id": group_id,
            "object_type": "SEGMENT",
            "candidate_id": other_id,
            "candidate_target": "KEEP_SWSD",
            "probability": 1.0 - top_probability,
            "anomaly_probability": 0.01,
        },
    ]


def _selection(
    seed: int,
    group_id: str,
    object_type: str,
    selected_id: str,
    selected_target: str,
    effective_id: str,
    effective_target: str,
    accepted: bool,
) -> dict[str, Any]:
    return {
        "seed": seed,
        "case_key": "T10:fixture",
        "group_id": group_id,
        "object_id": group_id,
        "object_type": object_type,
        "selected_candidate_id": selected_id,
        "selected_target": selected_target,
        "effective_candidate_id": effective_id,
        "effective_target": effective_target,
        "raw_selected_candidate_id": selected_id,
        "raw_selected_target": selected_target,
        "accepted": accepted,
        "confidence": 0.99,
        "anomaly_probability": 0.01,
        "reason": "model_score_passed" if accepted else "confidence_threshold",
    }


def _write_artifact(
    path: Path, rows: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return output_record(path)


def _write_json_artifact(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    write_json(path, payload)
    return output_record(path)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)
