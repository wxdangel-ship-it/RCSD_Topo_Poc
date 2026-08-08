from __future__ import annotations

import json
from dataclasses import replace

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_firewall import (
    EvidenceStage,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_model import (
    JunctionGraphSetModel,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_overfit import (
    _anchor_result,
    build_cached_views,
    extract_exact_jsonl_rows,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorNodeRef,
    AnchorResult,
    AnchorState,
    CandidateBinding,
    CandidatePlan,
    JunctionEvidenceExample,
    NodeEquivalenceClass,
    ObjectTokenSpan,
    QualityState,
    RoadBreakOperation,
    Step1DriveZoneState,
    SurfaceMode,
    SurfacePlan,
    VirtualSurfaceRecipe,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)


SWSD = ObjectRef(EvidenceRole.SWSD_NODE, "S")
DRIVEZONE = ObjectRef(EvidenceRole.DRIVEZONE, "D")
NODE_1 = ObjectRef(EvidenceRole.RCSD_NODE, "N1")
NODE_2 = ObjectRef(EvidenceRole.RCSD_NODE, "N2")
ROAD = ObjectRef(EvidenceRole.RCSD_ROAD, "R")
REFS = (SWSD, DRIVEZONE, NODE_1, NODE_2, ROAD)


def _candidate_example() -> JunctionEvidenceExample:
    break_zero = AnchorNodeRef.road_break_point(ROAD, 0)
    break_one = AnchorNodeRef.road_break_point(ROAD, 1)
    source_one = AnchorNodeRef.source_node(NODE_1)
    anchor = AnchorResult(
        state=AnchorState.SUCCESS,
        associated_rcsd_node_refs=(NODE_1, NODE_2),
        associated_rcsd_road_refs=(ROAD,),
        selected_main_anchor=break_one,
        node_equivalence_classes=(
            NodeEquivalenceClass((break_zero, source_one)),
        ),
        road_break_operations=(RoadBreakOperation(ROAD, (0.3, 0.7)),),
    )
    surface = SurfacePlan(
        mode=SurfaceMode.VIRTUAL_SURFACE,
        virtual_member_refs=(NODE_1, ROAD),
        virtual_surface_recipe=VirtualSurfaceRecipe(
            "ASSOCIATED_OBJECT_BUFFER_HULL",
            (("buffer_m", 5.0),),
        ),
    )

    def plan(plan_id: str, selected_anchor: AnchorResult) -> CandidatePlan:
        return CandidatePlan(
            plan_id=plan_id,
            step1_drivezone_state=Step1DriveZoneState.EVIDENCE,
            surface_plan=surface,
            anchor_result=selected_anchor,
            quality_state=QualityState.NORMAL,
            review_reason="",
            planned_topology_signature=f"topology:{plan_id}",
        )

    plans = (
        plan("gold", anchor),
        plan("different-main", replace(anchor, selected_main_anchor=source_one)),
        plan(
            "different-equivalence",
            replace(
                anchor,
                node_equivalence_classes=(NodeEquivalenceClass((break_zero,)),),
            ),
        ),
    )
    return JunctionEvidenceExample(
        junction_key="T03:fixture|S",
        case_key="T03:fixture",
        semantic_junction_id="S",
        geometry_tokens=torch.arange(5 * 21, dtype=torch.float32).reshape(5, 21) / 100.0,
        object_spans=tuple(
            ObjectTokenSpan(ref, index, index + 1) for index, ref in enumerate(REFS)
        ),
        topology_edge_indices=torch.zeros((2, 0), dtype=torch.long),
        topology_edge_features=torch.zeros((0, 8), dtype=torch.float32),
        candidate_binding=CandidateBinding(
            junction_key="T03:fixture|S",
            allowed_object_refs=REFS,
            plans=plans,
        ),
    )


def test_exact_jsonl_extractor_does_not_decode_unrequested_rows(tmp_path) -> None:
    path = tmp_path / "mixed.jsonl"
    path.write_bytes(
        (json.dumps({"sample_id": "selected", "value": 7}) + "\n").encode()
        + b'{"sample_id":"blind",this-is-not-valid-json}\n'
    )

    assert extract_exact_jsonl_rows(path, ("selected",)) == {
        "selected": {"sample_id": "selected", "value": 7}
    }


def test_anchor_adapter_expresses_mixed_source_and_generated_break_nodes() -> None:
    result = _anchor_result(
        {
            "anchor_business_state": "SUCCESS",
            "normalized_junctionization_plan": {
                "applicable": True,
                "supervised": True,
                "state": "NORMALIZED_EXACT",
                "break_geometry_targets": [
                    {
                        "road_object_id": "ROAD:R1",
                        "break_rank": 0,
                        "fraction": 0.25,
                    },
                    {
                        "road_object_id": "ROAD:R1",
                        "break_rank": 1,
                        "fraction": 0.75,
                    },
                ],
                "canonical_topology": {
                    "source_rcsd_objects": ["NODE:N1", "ROAD:R1"],
                    "main_anchor": "BREAK:ROAD:R1#1",
                    "junction_node_equivalence_class": [
                        "NODE:N1",
                        "BREAK:ROAD:R1#0",
                        "BREAK:ROAD:R1#1",
                    ],
                },
            },
        }
    )

    assert result.selected_main_anchor == AnchorNodeRef.road_break_point(
        ObjectRef(EvidenceRole.RCSD_ROAD, "R1"), 1
    )
    assert {ref.kind.value for ref in result.node_equivalence_classes[0].node_refs} == {
        "SOURCE_RCSD_NODE",
        "ROAD_BREAK_POINT",
    }
    assert result.road_break_operations[0].fractions == (0.25, 0.75)


def test_complete_plan_scorer_observes_main_and_equivalence_business_fields() -> None:
    torch.manual_seed(91)
    model = JunctionGraphSetModel(hidden_dim=64, dropout=0.0).eval()
    example = _candidate_example()
    output = model((example,))

    assert output.complete_plan.plan_ids == (
        "gold",
        "different-main",
        "different-equivalence",
    )
    assert not torch.allclose(
        output.complete_plan.logits[0],
        output.complete_plan.logits[1],
    )
    assert not torch.allclose(
        output.complete_plan.logits[0],
        output.complete_plan.logits[2],
    )


def test_cached_firewall_views_match_regular_forward() -> None:
    torch.manual_seed(113)
    model = JunctionGraphSetModel(hidden_dim=64, dropout=0.0).eval()
    example = _candidate_example()
    regular = model((example,))
    views = build_cached_views(model, (example,), torch.device("cpu"))
    cached = model.forward_stage_views(
        step1_views=views.step1,
        surface_views=views.surface,
        anchor_views=views.anchor,
        candidate_bindings=(example.candidate_binding,),
    )

    assert torch.allclose(regular.step1_logits, cached.step1_logits)
    assert torch.allclose(regular.surface.mode_logits, cached.surface.mode_logits)
    assert torch.allclose(regular.anchor_state_logits, cached.anchor_state_logits)
    assert torch.allclose(regular.complete_plan.logits, cached.complete_plan.logits)


def test_encoder_preserves_road_identity_when_old_mean_pool_would_collide() -> None:
    road_left = ObjectRef(EvidenceRole.RCSD_ROAD, "RL")
    road_right = ObjectRef(EvidenceRole.RCSD_ROAD, "RR")
    refs = (SWSD, DRIVEZONE, road_left, road_right)
    tokens = torch.zeros((6, 21), dtype=torch.float32)
    tokens[2, 0] = 0.0
    tokens[3, 0] = 2.0
    tokens[4, 0] = 1.0
    tokens[5, 0] = 1.0
    assert torch.allclose(tokens[2:4].mean(dim=0), tokens[4:6].mean(dim=0))
    example = JunctionEvidenceExample(
        junction_key="T03:identity|S",
        case_key="T03:identity",
        semantic_junction_id="S",
        geometry_tokens=tokens,
        object_spans=(
            ObjectTokenSpan(SWSD, 0, 1),
            ObjectTokenSpan(DRIVEZONE, 1, 2),
            ObjectTokenSpan(road_left, 2, 4),
            ObjectTokenSpan(road_right, 4, 6),
        ),
        topology_edge_indices=torch.zeros((2, 0), dtype=torch.long),
        topology_edge_features=torch.zeros((0, 8), dtype=torch.float32),
        candidate_binding=CandidateBinding(
            junction_key="T03:identity|S",
            allowed_object_refs=refs,
            plans=(),
        ),
    )
    torch.manual_seed(127)
    model = JunctionGraphSetModel(hidden_dim=64, dropout=0.0).eval()
    view = model.firewall.build_view(example, EvidenceStage.ANCHOR)
    encoded = model.encoder((view,))
    embeddings = {
        ref: encoded.object_embeddings[index]
        for index, ref in enumerate(encoded.object_refs)
    }

    assert not torch.allclose(embeddings[road_left], embeddings[road_right])
