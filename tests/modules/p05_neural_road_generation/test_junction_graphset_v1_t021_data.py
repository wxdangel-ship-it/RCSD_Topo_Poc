from __future__ import annotations

import json
from pathlib import Path

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_model import (
    JunctionGraphSetModel,
    compute_multitask_loss,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_surface import (
    ConstraintState,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_t021_data import (
    build_t021_record,
    iter_aligned_jsonl,
)


def _feature(sample_id: str = "sample:1") -> dict:
    object_ids = (
        (0, "SWSD_NODE:S1"),
        (2, "DRIVEZONE:D1"),
        (3, "NODE:N1"),
        (4, "ROAD:R1"),
        (6, "RCSD_INTERSECTION:I1"),
    )
    return {
        "sample_id": sample_id,
        "anchor_id": "S1",
        "input_fingerprint": "a" * 64,
        "object_features": [0.0] * 64,
        "candidate_ids": [],
        "candidate_features": [],
        "structural_member_ids": [],
        "swsd_arm_features": [],
        "member_arm_features": [],
        "member_local_features": [],
        "member_relation_edges": [],
        "geometry_token_features": [[float(index)] * 21 for index in range(5)],
        "geometry_object_spans": [
            {
                "role_index": role,
                "object_id": object_id,
                "token_start": index,
                "token_end": index + 1,
                "geometry_valid": True,
            }
            for index, (role, object_id) in enumerate(object_ids)
        ],
        "geometry_relation_edges": [],
        "drivezone_grid_indices": [1],
    }


def _label(
    sample_id: str = "sample:1",
    *,
    source_weight: float = 0.5,
    surface_mode: str = "VIRTUAL_SURFACE",
) -> dict:
    return {
        "sample_id": sample_id,
        "split": "train",
        "sample_weight": source_weight,
        "task_labels": {
            "final_state": "SUCCESS",
            "junctionization_action": "group_existing_rcsd_nodes",
            "relation_state": "success_required_rcsd_junction",
            "surface_mode": surface_mode,
            "surface_state": "accepted",
            "t07_step1": "yes",
            "t07_step2": "",
        },
        "task_masks": {
            "final_state": True,
            "junctionization_action": True,
            "relation_state": True,
            "surface_mode": True,
            "surface_state": True,
            "t07_step1": True,
            "t07_step2": False,
        },
        "surface_object_supervised": surface_mode == "EXISTING_RCSD_INTERSECTION",
        "surface_object_target_object_sets": (
            [["RCSD_INTERSECTION:I1"]]
            if surface_mode == "EXISTING_RCSD_INTERSECTION"
            else []
        ),
        "candidate_acceptable_indices": [0, 1],
    }


def _lineage(sample_id: str = "sample:1") -> dict:
    return {
        "sample_id": sample_id,
        "case_id": "C1",
        "family": "T03",
        "source_scope": "POC_Data",
        "input_fingerprint": "a" * 64,
        "split": "train",
    }


def _derived(sample_id: str = "sample:1") -> dict:
    return {
        "sample_id": sample_id,
        "source": "STRONG_GOLD",
        "split": "train",
        "anchor_business_state": "SUCCESS",
        "surface_mode": "VIRTUAL_SURFACE",
        "current_phase_result_oracle": {"measurable": True, "blockers": []},
        "normalized_junctionization_plan": {
            "applicable": True,
            "supervised": True,
            "state": "NORMALIZED_EXACT",
            "break_geometry_targets": [],
            "canonical_topology": {
                "source_rcsd_objects": ["NODE:N1", "ROAD:R1"],
                "main_anchor": "NODE:N1",
                "junction_node_equivalence_class": ["NODE:N1"],
            },
        },
    }


def _surface(sample_id: str = "sample:1") -> dict:
    return {
        "sample_id": sample_id,
        "split": "train",
        "supervised": True,
        "required_visible_object_ids": ["NODE:N1"],
        "forbidden_visible_object_ids": ["ROAD:R1"],
    }


def test_aligned_reader_skips_blind_prefix_without_decoding(tmp_path: Path) -> None:
    paths = tuple(tmp_path / f"store-{index}.jsonl" for index in range(3))
    row = {"sample_id": "development:1", "value": 1}
    for path in paths:
        path.write_text(
            "THIS SEALED ROW MUST NOT BE JSON-DECODED\n"
            + json.dumps(row)
            + "\n",
            encoding="utf-8",
        )

    aligned = tuple(iter_aligned_jsonl(paths, raw_prefix_skip=1))

    assert len(aligned) == 1
    assert {part["sample_id"] for part in aligned[0]} == {"development:1"}


def test_strong_record_normalizes_weight_and_keeps_teacher_truth_separate() -> None:
    record = build_t021_record(
        feature=_feature(),
        label=_label(),
        lineage=_lineage(),
        derived=_derived(),
        surface_row=_surface(),
        source="STRONG_GOLD",
    )

    assert record.label.old_source_weight == 0.5
    assert record.label.source_weight_normalized is True
    assert record.label.overlay.source_weight == 1.0
    assert record.feature.example.candidate_binding.plan("safe:abstain")
    assert record.feature.example.candidate_binding.plans == (
        record.feature.example.candidate_binding.plan("safe:abstain"),
    )
    assert record.label.teacher_candidate_binding.plan("gold")
    assert record.label.overlay.acceptable_complete_plan_ids == ("gold",)
    assert record.label.legacy_candidate_acceptable_count == 2
    assert record.label.overlay.virtual_surface_acceptable_cardinalities == (1,)
    states = {
        constraint.object_ref.object_id: constraint.state
        for constraint in record.label.overlay.virtual_surface_constraints
    }
    assert states == {
        "N1": ConstraintState.REQUIRED,
        "R1": ConstraintState.FORBIDDEN,
    }
    assert "STRONG_GOLD" not in repr(record.feature.example)


def test_existing_surface_object_is_a_real_training_target() -> None:
    label = _label(source_weight=0.7, surface_mode="EXISTING_RCSD_INTERSECTION")
    lineage = {
        **_lineage(),
        "case_key": "T10:C1",
    }
    derived = {
        **_derived(),
        "source": "T10_WEAK",
        "surface_mode": "EXISTING_RCSD_INTERSECTION",
    }
    record = build_t021_record(
        feature=_feature(),
        label=label,
        lineage=lineage,
        derived=derived,
        surface_row=None,
        source="T10_WEAK",
    )

    constraints = record.label.overlay.existing_surface_constraints
    assert len(constraints) == 1
    assert constraints[0].object_ref.role == EvidenceRole.RCSD_INTERSECTION
    assert constraints[0].state == ConstraintState.REQUIRED
    assert record.label.overlay.source_weight == 0.7


def test_real_record_supports_finite_teacher_forced_loss() -> None:
    record = build_t021_record(
        feature=_feature(),
        label=_label(),
        lineage=_lineage(),
        derived=_derived(),
        surface_row=_surface(),
        source="STRONG_GOLD",
    )
    model = JunctionGraphSetModel(hidden_dim=32, dropout=0.0)
    teacher_example = record.teacher_example
    output = model(
        (teacher_example,),
        step1_state_indices=torch.tensor((record.label.teacher_step1_index,)),
        surface_mode_indices=torch.tensor((record.label.teacher_surface_index,)),
    )
    losses = compute_multitask_loss(output, (record.label.overlay,))

    assert all(torch.isfinite(loss).item() for loss in losses.values())
    assert float(losses["existing_surface_object"].detach()) == 0.0
    assert output.complete_plan.plan_ids == (
        "gold",
        "safe:abstain",
        "decoy:alternate-state",
    )
