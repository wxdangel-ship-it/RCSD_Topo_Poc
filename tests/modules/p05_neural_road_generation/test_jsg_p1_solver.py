from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import (
    CarrierRealization,
    DirectionRole,
    DirectionStructure,
    JSGCaseTruth,
    JunctionSegmentRelation,
    JunctionType,
    JunctionUnit,
    ObjectState,
    StandardSegmentUnit,
    StructuralRole,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p1_models import (
    JSGP1Candidate,
    P1ObjectType,
    P1Stage,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p1_solver import (
    _projection_truth,
    solve_pto_a_case,
)


def _truth() -> JSGCaseTruth:
    junctions = tuple(
        JunctionUnit(value, JunctionType.NORMAL, "1", (), ObjectState.PUBLISHABLE)
        for value in ("j1", "j2")
    )
    segment = StandardSegmentUnit(
        "s1", ("j1", "j2"), (), DirectionStructure.BIDIRECTIONAL, "1", "UNSPECIFIED", (), (), False, ObjectState.PUBLISHABLE
    )
    relations = tuple(
        JunctionSegmentRelation(value, "s1", StructuralRole.ENDPOINT, DirectionRole.BOTH, (), (), ObjectState.PUBLISHABLE)
        for value in ("j1", "j2")
    )
    carrier = CarrierRealization("oracle.json", "sample", "roads.jsonl", "nodes.jsonl", "road.gpkg", "node.gpkg", ())
    return JSGCaseTruth("T10:fixture", "T10", "fixture", "EPSG:3857", "manifest.json", (), junctions, (segment,), relations, (), (), carrier, ())


def _candidates(truth: JSGCaseTruth) -> list[dict]:
    expected, _counts = _projection_truth(truth)
    rows = []
    for group_id, payload in expected.items():
        if ":JUNCTION:" in group_id:
            object_type = P1ObjectType.JUNCTION
        elif ":STANDARD_SEGMENT:" in group_id:
            object_type = P1ObjectType.STANDARD_SEGMENT
        else:
            object_type = P1ObjectType.RELATION
        dependencies = ()
        if object_type is P1ObjectType.STANDARD_SEGMENT:
            dependencies = ("PTO_A:JUNCTION:j1", "PTO_A:JUNCTION:j2")
        elif object_type is P1ObjectType.RELATION:
            dependencies = (f"PTO_A:JUNCTION:{payload['junction_id']}", "PTO_A:STANDARD_SEGMENT:s1")
        rows.append(
            JSGP1Candidate.build(
                case_key=truth.case_key,
                stage=P1Stage.PTO_A,
                object_type=object_type,
                object_key=group_id.rsplit(":", 1)[-1],
                group_id=group_id,
                payload=payload,
                dependencies=dependencies,
                source_kinds=("T01_INFERENCE_EVIDENCE",),
            ).to_dict()
        )
    rows.append(
        JSGP1Candidate.build(
            case_key=truth.case_key,
            stage=P1Stage.PTO_B,
            object_type=P1ObjectType.ROADGRAPH_CARRIER,
            object_key="sample",
            group_id="PTO_B:ROADGRAPH:sample",
            payload={"sample_id": "sample"},
            source_kinds=("TRUTH_FREE_STRATEGY_PROPOSAL",),
        ).to_dict()
    )
    return rows


def test_pto_a_oracle_finds_exact_zero_gap_solution() -> None:
    truth = _truth()
    result = solve_pto_a_case(_candidates(truth), truth)
    assert result["status"] == "OPTIMAL"
    assert result["objective"] == 0.0
    assert result["optimality_gap"] == 0.0
    assert result["missing_groups"] == []
    assert result["unmatched_groups"] == []
    assert result["dependency_failures"] == []
    assert result["silent_fix"] is False


def test_pto_a_oracle_reports_missing_truth_group_without_repair() -> None:
    truth = _truth()
    candidates = [row for row in _candidates(truth) if row["group_id"] != "PTO_A:JUNCTION:j1"]
    result = solve_pto_a_case(candidates, truth)
    assert result["status"] == "INFEASIBLE"
    assert "PTO_A:JUNCTION:j1" in result["missing_groups"]
    assert result["content_repair"] is False


def test_pto_a_rejects_candidate_leakage_flag() -> None:
    truth = _truth()
    candidates = _candidates(truth)
    candidates[0]["truth_derived"] = True
    try:
        solve_pto_a_case(candidates, truth)
    except ValueError as error:
        assert "leakage" in str(error)
    else:
        raise AssertionError("truth-derived candidate was accepted")
