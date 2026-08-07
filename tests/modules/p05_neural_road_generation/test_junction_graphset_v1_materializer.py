from __future__ import annotations

from dataclasses import replace

from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_materializer import (
    GeometryAsset,
    SelectedPlanMaterializer,
    business_topology_signature,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorResult,
    AnchorState,
    CandidateBinding,
    CandidatePlan,
    JunctionResultPrediction,
    NodeEquivalenceClass,
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


NODE_1 = ObjectRef(EvidenceRole.RCSD_NODE, "N1")
NODE_2 = ObjectRef(EvidenceRole.RCSD_NODE, "N2")
ROAD_1 = ObjectRef(EvidenceRole.RCSD_ROAD, "R1")
SURFACE_1 = ObjectRef(EvidenceRole.RCSD_INTERSECTION, "I1")
JUNCTION_KEY = "T03:fixture|S1"


def _anchor() -> AnchorResult:
    return AnchorResult(
        state=AnchorState.SUCCESS,
        associated_rcsd_node_refs=(NODE_1, NODE_2),
        associated_rcsd_road_refs=(ROAD_1,),
        selected_main_anchor=NODE_1,
        node_equivalence_classes=(NodeEquivalenceClass((NODE_1, NODE_2)),),
        road_break_operations=(RoadBreakOperation(ROAD_1, (0.5,)),),
    )


def _plan(*, virtual: bool = False) -> CandidatePlan:
    anchor = _anchor()
    surface = (
        SurfacePlan(
            mode=SurfaceMode.VIRTUAL_SURFACE,
            virtual_surface_recipe=VirtualSurfaceRecipe(
                recipe_type=SelectedPlanMaterializer.VIRTUAL_RECIPE,
                parameters=(("buffer_m", 2.0),),
            ),
        )
        if virtual
        else SurfacePlan(
            mode=SurfaceMode.EXISTING_RCSD_INTERSECTION,
            selected_rcsdintersection_refs=(SURFACE_1,),
        )
    )
    return CandidatePlan(
        plan_id="virtual" if virtual else "existing",
        step1_drivezone_state=Step1DriveZoneState.EVIDENCE,
        surface_plan=surface,
        anchor_result=anchor,
        quality_state=QualityState.NORMAL,
        review_reason="",
        planned_topology_signature=business_topology_signature(anchor),
    )


def _prediction_and_binding(*, virtual: bool = False):
    plan = _plan(virtual=virtual)
    binding = CandidateBinding(
        junction_key=JUNCTION_KEY,
        allowed_object_refs=(NODE_1, NODE_2, ROAD_1, SURFACE_1),
        plans=(plan,),
    )
    prediction = JunctionResultPrediction.from_candidate(
        junction_key=JUNCTION_KEY,
        candidate=plan,
        complete_plan_confidence=0.9,
        component_confidences={"anchor": 0.95},
    )
    return prediction, binding


def _assets():
    return {
        NODE_1: GeometryAsset(NODE_1, "EPSG:3857", Point(0, 0)),
        NODE_2: GeometryAsset(NODE_2, "EPSG:3857", Point(10, 0)),
        ROAD_1: GeometryAsset(
            ROAD_1,
            "EPSG:3857",
            LineString(((0, 0), (10, 0))),
        ),
        SURFACE_1: GeometryAsset(
            SURFACE_1,
            "EPSG:3857",
            Polygon(((-1, -1), (11, -1), (11, 1), (-1, 1), (-1, -1))),
        ),
    }


def test_existing_surface_and_selected_road_break_materialize_deterministically() -> None:
    prediction, binding = _prediction_and_binding()
    materializer = SelectedPlanMaterializer()
    first = materializer.materialize(
        prediction=prediction,
        binding=binding,
        geometry_assets=_assets(),
    )
    second = materializer.materialize(
        prediction=prediction,
        binding=binding,
        geometry_assets=dict(reversed(tuple(_assets().items()))),
    )

    assert not first.fallback
    assert first.ledger.topology_valid
    assert first.ledger.silent_fix_count == 0
    assert first.surface_geometry is not None and first.surface_geometry.area == 24.0
    assert len(first.generated_road_fragments) == 2
    assert len(first.generated_break_nodes) == 1
    assert [item.generated_id for item in first.generated_road_fragments] == [
        item.generated_id for item in second.generated_road_fragments
    ]
    assert first.generated_road_fragments[0].geometry.length == 5.0
    assert first.generated_break_nodes[0].geometry.equals(Point(5, 0))


def test_virtual_surface_is_only_the_predeclared_selected_member_recipe() -> None:
    prediction, binding = _prediction_and_binding(virtual=True)
    result = SelectedPlanMaterializer().materialize(
        prediction=prediction,
        binding=binding,
        geometry_assets=_assets(),
    )
    assert not result.fallback
    assert result.surface_geometry is not None
    assert result.surface_geometry.covers(Point(0, 0))
    assert result.surface_geometry.covers(Point(10, 0))
    assert result.ledger.executed_operations[0].startswith(
        SelectedPlanMaterializer.VIRTUAL_RECIPE
    )


def test_crs_mismatch_is_junction_fallback_without_silent_fix() -> None:
    prediction, binding = _prediction_and_binding()
    assets = _assets()
    assets[ROAD_1] = replace(assets[ROAD_1], crs="EPSG:4326")
    result = SelectedPlanMaterializer().materialize(
        prediction=prediction,
        binding=binding,
        geometry_assets=assets,
    )
    assert result.fallback
    assert result.ledger.fallback_scope == "JUNCTION"
    assert result.ledger.failure_reason == f"CRS_MISMATCH:{ROAD_1.key}"
    assert result.ledger.silent_fix_count == 0


def test_disconnected_selected_topology_falls_back_without_reselecting() -> None:
    anchor = replace(_anchor(), node_equivalence_classes=())
    plan = replace(
        _plan(),
        anchor_result=anchor,
        planned_topology_signature=business_topology_signature(anchor),
    )
    binding = CandidateBinding(
        junction_key=JUNCTION_KEY,
        allowed_object_refs=(NODE_1, NODE_2, ROAD_1, SURFACE_1),
        plans=(plan,),
    )
    prediction = JunctionResultPrediction.from_candidate(
        junction_key=JUNCTION_KEY,
        candidate=plan,
        complete_plan_confidence=0.9,
        component_confidences={},
    )
    assets = _assets()
    assets[NODE_2] = replace(assets[NODE_2], geometry=Point(5, 0.5))
    result = SelectedPlanMaterializer(connectivity_tolerance_m=0.01).materialize(
        prediction=prediction,
        binding=binding,
        geometry_assets=assets,
    )
    assert result.fallback
    assert result.ledger.failure_reason == "SELECTED_TOPOLOGY_DISCONNECTED"
    assert result.associated_node_refs == ()
    assert result.ledger.selected_object_keys == tuple(
        sorted(ref.key for ref in plan.referenced_objects)
    )


def test_topology_signature_mismatch_cannot_be_hidden_by_geometry() -> None:
    plan = replace(_plan(), planned_topology_signature="invented-topology")
    binding = CandidateBinding(
        junction_key=JUNCTION_KEY,
        allowed_object_refs=(NODE_1, NODE_2, ROAD_1, SURFACE_1),
        plans=(plan,),
    )
    prediction = JunctionResultPrediction.from_candidate(
        junction_key=JUNCTION_KEY,
        candidate=plan,
        complete_plan_confidence=0.9,
        component_confidences={},
    )
    result = SelectedPlanMaterializer().materialize(
        prediction=prediction,
        binding=binding,
        geometry_assets=_assets(),
    )
    assert result.fallback
    assert result.ledger.failure_reason == "TOPOLOGY_SIGNATURE_MISMATCH"


def test_model_abstain_stops_at_junction_scope() -> None:
    _, binding = _prediction_and_binding()
    prediction = JunctionResultPrediction.abstained(
        junction_key=JUNCTION_KEY,
        review_reason="MODEL_UNCERTAIN",
    )
    result = SelectedPlanMaterializer().materialize(
        prediction=prediction,
        binding=binding,
        geometry_assets=_assets(),
    )
    assert result.fallback
    assert result.ledger.fallback_scope == "JUNCTION"
    assert result.ledger.failure_reason == "MODEL_ABSTAIN"
