from __future__ import annotations

from dataclasses import replace

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_evaluation import (
    CompleteResultSignature,
    JunctionEvaluationGold,
    JunctionEvaluationItem,
    evaluate_junction_results,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_materializer import (
    MaterializationLedger,
    MaterializedJunctionResult,
    business_topology_signature,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorNodeRef,
    AnchorResult,
    AnchorState,
    CandidatePlan,
    JunctionResultPrediction,
    QualityState,
    RoadBreakOperation,
    Step1DriveZoneState,
    SurfaceMode,
    SurfacePlan,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)


NODE = ObjectRef(EvidenceRole.RCSD_NODE, "N1")
ROAD = ObjectRef(EvidenceRole.RCSD_ROAD, "R1")
SURFACE = ObjectRef(EvidenceRole.RCSD_INTERSECTION, "I1")


def _prediction(junction_key: str, *, fraction: float = 0.5) -> JunctionResultPrediction:
    anchor = AnchorResult(
        state=AnchorState.SUCCESS,
        associated_rcsd_node_refs=(NODE,),
        associated_rcsd_road_refs=(ROAD,),
        selected_main_anchor=AnchorNodeRef.source_node(NODE),
        road_break_operations=(RoadBreakOperation(ROAD, (fraction,)),),
    )
    candidate = CandidatePlan(
        plan_id="complete",
        step1_drivezone_state=Step1DriveZoneState.EVIDENCE,
        surface_plan=SurfacePlan(
            mode=SurfaceMode.EXISTING_RCSD_INTERSECTION,
            selected_rcsdintersection_refs=(SURFACE,),
        ),
        anchor_result=anchor,
        quality_state=QualityState.NORMAL,
        review_reason="",
        planned_topology_signature=business_topology_signature(anchor),
    )
    return JunctionResultPrediction.from_candidate(
        junction_key=junction_key,
        candidate=candidate,
        complete_plan_confidence=0.9,
        component_confidences={"anchor": 0.95},
    )


def _automatic_materialization(prediction: JunctionResultPrediction):
    ledger = MaterializationLedger(
        junction_key=prediction.junction_key,
        selected_plan_id=prediction.selected_plan_id,
        selected_object_keys=(NODE.key, ROAD.key, SURFACE.key),
        executed_operations=("MODEL_SELECTED_ONLY",),
        generated_ids=("ignored-generated-id",),
        planned_topology_signature=prediction.post_materialization_topology_signature,
        actual_topology_signature=prediction.post_materialization_topology_signature,
        topology_valid=True,
        fallback_scope=None,
        failure_reason="",
        silent_fix_count=0,
    )
    return MaterializedJunctionResult(
        junction_key=prediction.junction_key,
        surface_geometry=None,
        associated_node_refs=(NODE,),
        associated_road_refs=(ROAD,),
        generated_road_fragments=(),
        generated_break_nodes=(),
        node_equivalence_keys=(),
        materialized_main_node_id=NODE.object_id,
        topology_signature=prediction.post_materialization_topology_signature,
        fallback=False,
        ledger=ledger,
    )


def _fallback_materialization(prediction: JunctionResultPrediction):
    ledger = MaterializationLedger(
        junction_key=prediction.junction_key,
        selected_plan_id=None,
        selected_object_keys=(),
        executed_operations=(),
        generated_ids=(),
        planned_topology_signature=None,
        actual_topology_signature=None,
        topology_valid=False,
        fallback_scope="JUNCTION",
        failure_reason="MODEL_ABSTAIN",
        silent_fix_count=0,
    )
    return MaterializedJunctionResult(
        junction_key=prediction.junction_key,
        surface_geometry=None,
        associated_node_refs=(),
        associated_road_refs=(),
        generated_road_fragments=(),
        generated_break_nodes=(),
        node_equivalence_keys=(),
        materialized_main_node_id=None,
        topology_signature=None,
        fallback=True,
        ledger=ledger,
    )


def test_multiple_acceptable_results_and_break_tolerance_count_as_exact() -> None:
    prediction = _prediction("T03:A|J1", fraction=0.5005)
    actual = CompleteResultSignature.from_prediction(prediction)
    expected = replace(actual, road_breaks=((ROAD.key, (0.5,)),))
    nonpreferred = replace(actual, associated_road_keys=("RCSD_ROAD:another",))
    report = evaluate_junction_results(
        (
            JunctionEvaluationItem(
                case_key="T03:A",
                prediction=prediction,
                materialized=_automatic_materialization(prediction),
                gold=JunctionEvaluationGold(
                    truth_known=True,
                    acceptable_automatic_results=(nonpreferred, expected),
                ),
            ),
        ),
        break_fraction_tolerance=0.001,
    )
    assert report.automatic_accepted == 1
    assert report.automatic_exact == 1
    assert report.final_exact == 1
    assert report.dangerous_automatic == 0
    assert report.release_enabled


def test_known_wrong_and_unknown_auto_acceptance_are_separate_hard_failures() -> None:
    wrong_prediction = _prediction("T03:B|J1")
    unknown_prediction = _prediction("T10:U|J1")
    actual = CompleteResultSignature.from_prediction(wrong_prediction)
    wrong_gold = replace(actual, main_anchor_key="RCSD_NODE:wrong")
    report = evaluate_junction_results(
        (
            JunctionEvaluationItem(
                case_key="T03:B",
                prediction=wrong_prediction,
                materialized=_automatic_materialization(wrong_prediction),
                gold=JunctionEvaluationGold(
                    truth_known=True,
                    acceptable_automatic_results=(wrong_gold,),
                ),
            ),
            JunctionEvaluationItem(
                case_key="T10:U",
                prediction=unknown_prediction,
                materialized=_automatic_materialization(unknown_prediction),
                gold=JunctionEvaluationGold(truth_known=False),
            ),
        )
    )
    assert report.dangerous_automatic == 1
    assert report.unknown_automatic == 1
    assert not report.release_enabled


def test_fallback_exact_and_abnormal_recall_do_not_inflate_automatic_exact() -> None:
    prediction = JunctionResultPrediction.abstained(
        junction_key="T03_Error:C|J1",
        review_reason="ANCHOR_AMBIGUOUS",
    )
    report = evaluate_junction_results(
        (
            JunctionEvaluationItem(
                case_key="T03_Error:C",
                prediction=prediction,
                materialized=_fallback_materialization(prediction),
                gold=JunctionEvaluationGold(
                    truth_known=True,
                    expected_abnormal_or_abstain=True,
                    acceptable_fallback_graph_signatures=("SWSD:exact",),
                ),
                fallback_graph_signature="SWSD:exact",
            ),
        )
    )
    assert report.automatic_accepted == 0
    assert report.automatic_exact == 0
    assert report.fallback_count == 1
    assert report.fallback_exact == 1
    assert report.final_exact == 1
    assert report.abnormal_recall == 1.0
    assert report.release_enabled


def test_case_worst_performance_and_generated_ids_are_auditable_but_not_gold() -> None:
    exact_prediction = _prediction("T03:good|J1")
    wrong_prediction = _prediction("T04:bad|J2")
    exact_signature = CompleteResultSignature.from_prediction(exact_prediction)
    wrong_expected = replace(
        CompleteResultSignature.from_prediction(wrong_prediction),
        associated_node_keys=("RCSD_NODE:other",),
    )
    report = evaluate_junction_results(
        (
            JunctionEvaluationItem(
                case_key="T03:good",
                prediction=exact_prediction,
                materialized=_automatic_materialization(exact_prediction),
                gold=JunctionEvaluationGold(
                    truth_known=True,
                    acceptable_automatic_results=(exact_signature,),
                ),
            ),
            JunctionEvaluationItem(
                case_key="T04:bad",
                prediction=wrong_prediction,
                materialized=_automatic_materialization(wrong_prediction),
                gold=JunctionEvaluationGold(
                    truth_known=True,
                    acceptable_automatic_results=(wrong_expected,),
                ),
            ),
        )
    )
    assert report.worst_case_final_exact_rate == 0.0
    assert tuple(metric.case_key for metric in report.case_metrics) == (
        "T03:good",
        "T04:bad",
    )
    payload = report.to_dict()
    assert payload["dangerous_automatic"] == 1
    assert "generated_ids" not in payload
