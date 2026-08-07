from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_independent_gate import (
    INDEPENDENT_GATE_FEATURE_DIM,
    IndependentAnchorGate,
    IndependentAnchorGateConfig,
    build_independent_anchor_gate_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
)


def _example(
    *,
    sample_id: str,
    case_key: str,
    anchor_id: str,
    candidate_id: str,
    status_label: int,
    gate_label: int,
) -> AnchorPretrainExample:
    object_features = [0.0] * 64
    object_features[4] = 0.5
    candidate_features = [0.0] * 64
    candidate_features[12] = 0.25
    return AnchorPretrainExample(
        sample_id=sample_id,
        case_key=case_key,
        anchor_id=anchor_id,
        fold=0,
        object_features=tuple(object_features),
        candidate_ids=(candidate_id,),
        candidate_features=(tuple(candidate_features),),
        status_label=status_label,
        candidate_acceptable_indices=(),
        preferred_candidate_index=-1,
        candidate_supervised=False,
        sample_weight=0.7,
        input_hashes=(("input", sample_id),),
        label_reason="must-not-enter-feature",
        dependency_anchor_ids=(anchor_id,),
        gate_label=gate_label,
        gate_supervised=True,
    )


def test_independent_gate_features_exclude_labels_and_raw_ids() -> None:
    first = _example(
        sample_id="first",
        case_key="T10:first",
        anchor_id="raw-anchor-a",
        candidate_id="NODE:raw-a|raw-b",
        status_label=3,
        gate_label=0,
    )
    second = _example(
        sample_id="second",
        case_key="T10:second",
        anchor_id="raw-anchor-z",
        candidate_id="NODE:raw-y|raw-z",
        status_label=0,
        gate_label=1,
    )

    features = build_independent_anchor_gate_features((first, second))

    assert features.shape == (2, INDEPENDENT_GATE_FEATURE_DIM)
    assert torch.equal(features[0], features[1])


def test_independent_gate_has_expected_output_shape() -> None:
    config = IndependentAnchorGateConfig()
    model = IndependentAnchorGate(config)

    output = model(torch.zeros((3, INDEPENDENT_GATE_FEATURE_DIM)))

    assert output.shape == (3, 2)
    assert torch.isfinite(output).all()
