from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_member_supervision import (
    apply_anchor_member_supervision,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)


def _road_anchor(
    anchor_id: str,
    *,
    candidate_acceptable_indices: tuple[int, ...] = (),
) -> AnchorPretrainExample:
    road_features = [0.0] * 64
    road_features[27] = 1.0
    return AnchorPretrainExample(
        sample_id=f"anchor:{anchor_id}",
        case_key="T10:case",
        anchor_id=anchor_id,
        fold=0,
        object_features=(0.0,) * 64,
        candidate_ids=("ROAD:r1", "ROAD:r1|r2"),
        candidate_features=(
            tuple(road_features),
            tuple(road_features),
        ),
        status_label=ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS],
        candidate_acceptable_indices=candidate_acceptable_indices,
        preferred_candidate_index=(
            candidate_acceptable_indices[0]
            if candidate_acceptable_indices
            else -1
        ),
        candidate_supervised=bool(candidate_acceptable_indices),
        sample_weight=0.7,
        input_hashes=(("input", "hash"),),
        label_reason=(
            "t05:road_only_split:t03_b2_road_only_support:"
            "object_selection_masked"
        ),
        dependency_anchor_ids=(anchor_id,),
        status_supervised=True,
        gate_label=1,
        gate_supervised=True,
        structural_member_ids=("ROAD:r1", "ROAD:r2"),
        member_arm_features=((), ()),
    )


def test_exact_member_truth_recovers_unenumerated_road_bundle() -> None:
    row = _road_anchor("member-only")

    transformed, counts = apply_anchor_member_supervision(
        [row],
        explicit_member_options={
            ("T10:case", "member-only"): (("ROAD:r1", "ROAD:r2"),),
        },
    )

    result = transformed[0]
    assert result.member_supervised
    assert result.member_acceptable_sets == ((0, 1),)
    assert not result.candidate_supervised
    assert counts["explicit_member_set_reachable"] == 1
    assert counts["member_only_supervised"] == 1


def test_candidate_truth_is_also_available_to_member_decoder() -> None:
    row = _road_anchor(
        "candidate",
        candidate_acceptable_indices=(1,),
    )

    transformed, counts = apply_anchor_member_supervision([row])

    assert transformed[0].member_acceptable_sets == ((0, 1),)
    assert counts["candidate_derived_member_set"] == 1


def test_truth_never_adds_a_missing_inference_member() -> None:
    row = _road_anchor("missing")

    transformed, counts = apply_anchor_member_supervision(
        [row],
        explicit_member_options={
            ("T10:case", "missing"): (("ROAD:r3",),),
        },
    )

    assert not transformed[0].member_supervised
    assert counts["explicit_member_set_unreachable"] == 1
