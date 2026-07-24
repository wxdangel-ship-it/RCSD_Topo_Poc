from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p8_audit import (
    build_source_signature,
    classify_field_role,
    join_segment_sources,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p8_models import (
    DECISION_AUDIT_NO_GO,
    DECISION_PARTIAL_GO,
    DECISION_SOURCE_GO,
    DECISION_SOURCE_NO_GO,
    choose_p8_decision,
)


def test_choose_p8_decision_keeps_partial_carrier_result() -> None:
    assert choose_p8_decision(True, True, True) == DECISION_SOURCE_GO
    assert choose_p8_decision(True, True, False) == DECISION_PARTIAL_GO
    assert choose_p8_decision(True, False, True) == DECISION_SOURCE_NO_GO
    assert choose_p8_decision(False, True, True) == DECISION_AUDIT_NO_GO


def test_field_roles_exclude_lineage_and_free_text() -> None:
    assert classify_field_role("relation_state") == "PROMOTION_CANDIDATE"
    assert classify_field_role("target_id") == "LINEAGE_ONLY"
    assert classify_field_role("swsd_point_x") == "PROHIBITED_COORDINATE"
    assert classify_field_role("geometry_path") == "PROHIBITED_PATH"
    assert classify_field_role("reason") == "PROHIBITED_FREE_TEXT"


def test_source_signature_excludes_ids_coordinates_and_reason() -> None:
    signature = build_source_signature(
        {
            "source_module": "T04",
            "relation_state": "no_related_rcsd",
            "status_suggested": 1,
            "target_id": "secret-id",
            "swsd_point_x": 123.0,
            "reason": "label-like reason",
        }
    )
    assert "secret-id" not in signature
    assert "123.0" not in signature
    assert "label-like reason" not in signature
    assert "no_related_rcsd" in signature


def test_t04_carrier_signature_is_divmerge_direction_invariant() -> None:
    shared = {
        "source_module": "T04",
        "relation_state": "no_related_rcsd",
        "status_suggested": 1,
        "final_state": "accepted",
    }
    diverge = build_source_signature(
        {**shared, "junction_type": "diverge", "scene_type": "diverge"}
    )
    merge = build_source_signature(
        {**shared, "junction_type": "merge", "scene_type": "merge"}
    )
    assert diverge == merge
    assert "DIVMERGE_DIRECTION_INVARIANT" in diverge


def test_join_segment_sources_uses_explicit_junction_ids_only() -> None:
    sources = {
        "j1": {"source_module": "T03", "source_signature": "a"},
        "j2": {"source_module": "T04", "source_signature": "b"},
    }
    result = join_segment_sources(("j2", "missing", "j1"), sources)
    assert [row["source_signature"] for row in result] == ["a", "b"]
    assert join_segment_sources((), sources) == []
