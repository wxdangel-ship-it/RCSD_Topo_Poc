from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation import (
    junction_graphset_v1_governance as governance,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_first_data import (
    STAGE1_OBJECT_INDICES as LEGACY_STAGE1_OBJECT_INDICES,
)


def _object_features() -> list[float]:
    return [0.0] * 64


def _feature_row(sample_id: str) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "anchor_id": f"anchor:{sample_id}",
        "input_fingerprint": "synthetic",
        "object_features": _object_features(),
        "candidate_ids": ["node:1", "road-bundle:1"],
        "candidate_vector_types": ["node_candidate64", "road_bundle64"],
        "candidate_features": [[0.0] * 64, [0.0] * 64],
    }


def test_t001_contract_hashes_are_frozen() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    freeze_path = (
        repo_root
        / "specs"
        / "p05-junction-graphset-v1-20260807"
        / "contracts"
        / "contract-freeze.json"
    )
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    for relative_path, expected_sha256 in freeze["contract_sha256"].items():
        actual_sha256 = hashlib.sha256(
            (repo_root / relative_path).read_bytes()
        ).hexdigest()
        assert actual_sha256 == expected_sha256


def test_t003_typed_feature_contract_is_complete() -> None:
    audit = governance.audit_feature_contract()
    assert audit["dimensions"] == {
        "object64": 64,
        "node_candidate64": 64,
        "road_bundle64": 64,
        "member12": 12,
    }
    assert audit["total_typed_dimensions"] == 204
    assert audit["source_counts"] == governance.EXPECTED_SOURCE_COUNTS


def test_t003_step1_is_drivezone_and_swsd_only() -> None:
    assert governance.STEP1_OBJECT_INDICES == LEGACY_STAGE1_OBJECT_INDICES
    object_features = [float(index) for index in range(64)]
    object_features[25:] = [0.0] * 39
    expected = tuple(
        object_features[index] for index in governance.STEP1_OBJECT_INDICES
    )
    assert governance.project_step1_object_features(object_features) == expected

    changed_post_step1 = list(object_features)
    for index in set(range(25)) - set(governance.STEP1_OBJECT_INDICES):
        changed_post_step1[index] += 10_000.0
    assert governance.project_step1_object_features(changed_post_step1) == expected

    assert all(
        spec.vector_type == "object64"
        and spec.index in governance.STEP1_OBJECT_INDICES
        for specs in governance.FEATURE_SPECS.values()
        for spec in specs
        if spec.visibility == governance.StageVisibility.STEP1
    )


def test_t003_candidate_64d_requires_explicit_type() -> None:
    values = [0.0] * 64
    governance.validate_compatibility_vector("node_candidate64", values)
    governance.validate_compatibility_vector("road_bundle64", values)
    with pytest.raises(governance.FeatureContractError, match="untyped"):
        governance.validate_compatibility_vector("candidate64", values)

    assert governance.NODE_CANDIDATE64_SPECS[7].name == "member_count"
    assert governance.ROAD_BUNDLE64_SPECS[7].name == "road_count"


def test_t003_forbidden_padding_must_remain_zero() -> None:
    values = [0.0] * 64
    values[63] = 1.0
    with pytest.raises(governance.FeatureContractError, match="forbidden"):
        governance.validate_compatibility_vector("object64", values)

    reserved_metadata = [0.0] * 64
    reserved_metadata[25] = 1.0
    with pytest.raises(governance.FeatureContractError, match="disabled"):
        governance.validate_compatibility_vector("road_bundle64", reserved_metadata)
    assert (
        governance.ROAD_BUNDLE64_SPECS[25].visibility
        == governance.StageVisibility.DISABLED
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"split": "train"},
        {"terminal_label": "SUCCESS"},
        {"debug": {"selected_candidate": "node:1"}},
    ],
)
def test_t004_feature_shard_rejects_terminal_and_unknown_fields(
    extra: dict[str, object],
) -> None:
    row = _feature_row("sample:1")
    row.update(extra)
    with pytest.raises(governance.DevelopmentIsolationError):
        governance.validate_inference_feature_row(row)


def test_t004_candidate_type_cannot_be_inferred_from_values() -> None:
    row = _feature_row("sample:1")
    del row["candidate_vector_types"]
    with pytest.raises(governance.DevelopmentIsolationError, match="must both"):
        governance.validate_inference_feature_row(row)


def test_t004_development_view_only_accepts_train_and_validation() -> None:
    feature_rows = [_feature_row("sample:b"), _feature_row("sample:a")]
    label_rows = [
        {"sample_id": "sample:a", "split": "train", "targets": {}},
        {"sample_id": "sample:b", "split": "validation", "targets": {}},
    ]
    examples = governance.build_development_view(feature_rows, label_rows)
    assert [(example.sample_id, example.split) for example in examples] == [
        ("sample:a", "train"),
        ("sample:b", "validation"),
    ]


def test_t004_development_view_rejects_test_and_identity_mismatch() -> None:
    with pytest.raises(governance.BlindTestAccessError):
        governance.build_development_view(
            [_feature_row("sample:test")],
            [{"sample_id": "sample:test", "split": "test", "targets": {}}],
        )
    with pytest.raises(governance.DevelopmentIsolationError, match="identities differ"):
        governance.build_development_view(
            [_feature_row("sample:feature")],
            [{"sample_id": "sample:label", "split": "train", "targets": {}}],
        )


def test_t004_duplicate_development_identity_is_rejected() -> None:
    with pytest.raises(governance.DevelopmentIsolationError, match="duplicate feature"):
        governance.build_development_view(
            [_feature_row("sample:1"), _feature_row("sample:1")],
            [{"sample_id": "sample:1", "split": "train", "targets": {}}],
        )


def test_t004_blind_test_seal_and_gate_are_frozen() -> None:
    seal = governance.FROZEN_BLIND_TEST_SEAL
    seal.validate()
    assert seal.sealed_test_count == 106
    assert seal.remaining_blind_count == 105
    assert (
        seal.schema_discovery_quarantine_sample_id
        == "junction-gold:POC_Data:T04_Error:1010449:6f546311f57ad6aa"
    )
    with pytest.raises(governance.BlindTestAccessError, match="until T029"):
        governance.open_blind_test_view()


def test_t004_identity_hash_is_sorted_and_deterministic() -> None:
    expected = hashlib.sha256(b"sample:a\nsample:b\n").hexdigest()
    assert governance.aggregate_identity_sha256(["sample:b", "sample:a"]) == expected
    with pytest.raises(ValueError, match="duplicate"):
        governance.aggregate_identity_sha256(["sample:a", "sample:a"])
