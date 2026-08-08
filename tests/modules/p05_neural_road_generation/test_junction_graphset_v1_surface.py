from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    JunctionPredictionError,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_surface import (
    ConstraintState,
    SurfaceBranchHeads,
    SurfaceConstraint,
    acceptable_set_cross_entropy,
    audit_frozen_surface_constraint_summary,
    masked_tristate_member_loss,
)


def test_surface_heads_keep_existing_and_virtual_object_roles_separate() -> None:
    head = SurfaceBranchHeads(hidden_dim=16)
    refs = (
        ObjectRef(EvidenceRole.RCSD_INTERSECTION, "I1"),
        ObjectRef(EvidenceRole.RCSD_NODE, "N1"),
        ObjectRef(EvidenceRole.RCSD_ROAD, "R1"),
        ObjectRef(EvidenceRole.DRIVEZONE, "D1"),
    )
    output = head(
        query_embeddings=torch.zeros((2, 16)),
        object_embeddings=torch.zeros((4, 16)),
        object_batch_indices=torch.tensor([0, 0, 1, 1], dtype=torch.long),
        object_refs=refs,
    )
    assert tuple(output.mode_logits.shape) == (2, 5)
    assert output.existing_object_refs == (refs[0],)
    assert output.virtual_member_refs == (refs[1], refs[2])
    assert output.virtual_member_batch_indices.tolist() == [0, 1]
    assert tuple(output.virtual_cardinality.shape) == (2,)
    assert torch.all(output.virtual_cardinality >= 0.0)


def test_acceptable_set_loss_accepts_multiple_correct_classes() -> None:
    logits = torch.tensor([[0.0, 3.0, 3.0]], requires_grad=True)
    loss = acceptable_set_cross_entropy(
        logits,
        acceptable_indices=((1, 2),),
        sample_weights=torch.tensor([1.0]),
    )
    assert float(loss.detach()) < 0.03
    loss.backward()
    assert logits.grad is not None


def test_unknown_and_review_constraints_have_zero_loss_and_gradient() -> None:
    refs = (
        ObjectRef(EvidenceRole.RCSD_NODE, "N1"),
        ObjectRef(EvidenceRole.RCSD_ROAD, "R1"),
    )
    logits = torch.tensor([2.0, -2.0], requires_grad=True)
    loss = masked_tristate_member_loss(
        logits,
        refs,
        (
            SurfaceConstraint(refs[0], ConstraintState.UNKNOWN, 0.0),
            SurfaceConstraint(refs[1], ConstraintState.REVIEW, 0.0),
        ),
    )
    assert float(loss.detach()) == 0.0
    loss.backward()
    assert torch.all(logits.grad == 0)


def test_required_and_forbidden_constraints_train_opposite_targets() -> None:
    refs = (
        ObjectRef(EvidenceRole.RCSD_NODE, "N1"),
        ObjectRef(EvidenceRole.RCSD_ROAD, "R1"),
    )
    good = masked_tristate_member_loss(
        torch.tensor([8.0, -8.0]),
        refs,
        (
            SurfaceConstraint(refs[0], ConstraintState.REQUIRED, 1.0),
            SurfaceConstraint(refs[1], ConstraintState.FORBIDDEN, 0.7),
        ),
    )
    bad = masked_tristate_member_loss(
        torch.tensor([-8.0, 8.0]),
        refs,
        (
            SurfaceConstraint(refs[0], ConstraintState.REQUIRED, 1.0),
            SurfaceConstraint(refs[1], ConstraintState.FORBIDDEN, 0.7),
        ),
    )
    assert float(good) < 0.001
    assert float(bad) > 7.9


def test_unknown_constraint_with_positive_weight_is_rejected() -> None:
    constraint = SurfaceConstraint(
        ObjectRef(EvidenceRole.RCSD_NODE, "N1"),
        ConstraintState.UNKNOWN,
        1.0,
    )
    with pytest.raises(JunctionPredictionError, match="zero weight"):
        constraint.validate()


def test_frozen_constraint_ledger_exact_counts(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    path.write_text(
        json.dumps(
            {
                "virtual_surface_constraint_scope_count": 1685,
                "constraint_supervised": {"count": 1680},
                "constraint_review_row_count": 5,
                "required_reachable": {"count": 1528, "denominator": 1528},
                "required_missing_object_count": 0,
                "no_evidence_reference_only_object_count": 6,
                "visible_hard_forbidden_object_count": 26858,
                "sealed_test_row_count": 106,
                "training_executed": False,
            }
        ),
        encoding="utf-8",
    )
    audit = audit_frozen_surface_constraint_summary(path)
    assert audit.scope_count == 1685
    assert audit.supervised_count == 1680
    assert audit.review_count == 5
    assert audit.required_reachable_count == 1528
