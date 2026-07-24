from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_evaluation import evaluate_jsg_case
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


def _carrier() -> CarrierRealization:
    return CarrierRealization(
        r2_oracle_run_manifest="oracle.json",
        r2_case_sample_id="sample",
        road_edits_path="roads.jsonl",
        node_edits_path="nodes.jsonl",
        expected_truth_road="road.gpkg",
        expected_truth_node="node.gpkg",
        artifact_hashes=(),
    )


def _case(
    *,
    junctions: tuple[JunctionUnit, ...],
    segments: tuple[StandardSegmentUnit, ...],
    relations: tuple[JunctionSegmentRelation, ...],
) -> JSGCaseTruth:
    return JSGCaseTruth(
        case_key="T10:fixture",
        family="T10",
        business_id="fixture",
        crs="EPSG:3857",
        source_manifest="manifest.json",
        source_hashes=(),
        junction_units=junctions,
        standard_segments=segments,
        junction_segment_relations=relations,
        physical_movements=(),
        segment_connectors=(),
        carrier_realization=_carrier(),
        anomalies=(),
    )


def test_explicit_loop_roundtrips_without_inventing_second_junction() -> None:
    junction = JunctionUnit("j1", JunctionType.NORMAL, "1", (), ObjectState.PUBLISHABLE)
    segment = StandardSegmentUnit(
        "s1",
        ("j1", "j1"),
        (),
        DirectionStructure.BIDIRECTIONAL,
        "0-1",
        "UNSPECIFIED",
        ("r1",),
        (),
        True,
        ObjectState.PUBLISHABLE,
    )
    relation = JunctionSegmentRelation(
        "j1",
        "s1",
        StructuralRole.ENDPOINT,
        DirectionRole.BOTH,
        ("n1",),
        (),
        ObjectState.PUBLISHABLE,
    )
    result = evaluate_jsg_case(_case(junctions=(junction,), segments=(segment,), relations=(relation,)))
    assert result["passed"] is True
    assert result["canonical_roundtrip_exact"] is True
    assert result["object_counts"]["loop"] == 1


def test_multiple_through_relations_must_all_remain_review() -> None:
    junctions = (
        JunctionUnit("j0", JunctionType.NORMAL, "1", (), ObjectState.REVIEW),
        JunctionUnit("j1", JunctionType.NORMAL, "1", (), ObjectState.PUBLISHABLE),
        JunctionUnit("j2", JunctionType.NORMAL, "1", (), ObjectState.PUBLISHABLE),
        JunctionUnit("j3", JunctionType.NORMAL, "1", (), ObjectState.PUBLISHABLE),
        JunctionUnit("j4", JunctionType.NORMAL, "1", (), ObjectState.PUBLISHABLE),
    )
    segments = (
        StandardSegmentUnit("s1", ("j1", "j2"), ("j0",), DirectionStructure.BIDIRECTIONAL, "0-1", "UNSPECIFIED", (), (), False, ObjectState.PUBLISHABLE),
        StandardSegmentUnit("s2", ("j3", "j4"), ("j0",), DirectionStructure.BIDIRECTIONAL, "0-1", "UNSPECIFIED", (), (), False, ObjectState.PUBLISHABLE),
    )
    relations = []
    for segment in segments:
        for junction_id in segment.endpoint_positions:
            relations.append(JunctionSegmentRelation(junction_id, segment.segment_id, StructuralRole.ENDPOINT, DirectionRole.BOTH, (), (), ObjectState.PUBLISHABLE))
        relations.append(JunctionSegmentRelation("j0", segment.segment_id, StructuralRole.THROUGH, DirectionRole.BOTH, (), (), ObjectState.REVIEW))
    result = evaluate_jsg_case(_case(junctions=junctions, segments=segments, relations=tuple(relations)))
    assert result["passed"] is True
    assert result["through_conflict_junction_count"] == 1
    assert result["multi_through_auto_selected_count"] == 0


def test_roundabout_through_is_a_hard_failure() -> None:
    junctions = (
        JunctionUnit("ring", JunctionType.ROUNDABOUT, "1", (), ObjectState.PUBLISHABLE),
        JunctionUnit("a", JunctionType.NORMAL, "1", (), ObjectState.PUBLISHABLE),
        JunctionUnit("b", JunctionType.NORMAL, "1", (), ObjectState.PUBLISHABLE),
    )
    segment = StandardSegmentUnit("s", ("a", "b"), ("ring",), DirectionStructure.BIDIRECTIONAL, "0-1", "UNSPECIFIED", (), (), False, ObjectState.PUBLISHABLE)
    relations = (
        JunctionSegmentRelation("a", "s", StructuralRole.ENDPOINT, DirectionRole.BOTH, (), (), ObjectState.PUBLISHABLE),
        JunctionSegmentRelation("b", "s", StructuralRole.ENDPOINT, DirectionRole.BOTH, (), (), ObjectState.PUBLISHABLE),
        JunctionSegmentRelation("ring", "s", StructuralRole.THROUGH, DirectionRole.BOTH, (), (), ObjectState.PUBLISHABLE),
    )
    result = evaluate_jsg_case(_case(junctions=junctions, segments=(segment,), relations=relations))
    assert result["passed"] is False
    assert any(row["code"] == "roundabout_not_truncated" for row in result["hard_failures"])


def test_config_rejects_empty_run_id() -> None:
    from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import JSGP0Config

    try:
        JSGP0Config(Path("oracle"), Path("output"), "")
    except ValueError as error:
        assert "run_id" in str(error)
    else:
        raise AssertionError("empty run_id was accepted")
