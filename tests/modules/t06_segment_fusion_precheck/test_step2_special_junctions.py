from __future__ import annotations

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step2_special_junctions import (
    annotate_special_junction_gate,
    special_junction_gate,
)


def test_special_junction_gate_accepts_path_corridor_group_covered_segment() -> None:
    rows, blocked, removed, blocking_groups = special_junction_gate(
        special_junction_segments={"j1": ["s_standard", "s_group"]},
        special_swsd_junction_types={"j1": "complex"},
        replaceable_rows=[_replaceable("s_standard")],
        additional_replaceable_segment_ids={"s_group"},
        relation_map={},
        rcsd_junction_node_ids={},
        rcsd_junction_road_ids={},
    )

    props = rows[0]["properties"]
    assert props["gate_status"] == "passed"
    assert props["replaceable_segment_ids"] == ["s_standard", "s_group"]
    assert props["missing_replaceable_segment_ids"] == []
    assert blocked == set()
    assert removed == set()
    assert blocking_groups == {}


def test_special_junction_gate_allows_partial_complex_group_replacement() -> None:
    rows, blocked, removed, blocking_groups = special_junction_gate(
        special_junction_segments={"j1": ["s_standard", "s_missing"]},
        special_swsd_junction_types={"j1": "complex"},
        replaceable_rows=[_replaceable("s_standard")],
        additional_replaceable_segment_ids=set(),
        relation_map={},
        rcsd_junction_node_ids={},
        rcsd_junction_road_ids={},
    )

    props = rows[0]["properties"]
    assert props["gate_status"] == "partial"
    assert props["replaceable_segment_ids"] == ["s_standard"]
    assert props["missing_replaceable_segment_ids"] == ["s_missing"]
    assert props["removed_replaceable_segment_ids"] == []
    assert blocked == {"s_missing"}
    assert removed == set()
    assert blocking_groups == {"s_standard": ["j1"], "s_missing": ["j1"]}

    replaceable_rows = [_replaceable("s_standard")]
    annotate_special_junction_gate(
        replaceable_rows,
        segment_special_junctions={"s_standard": ["j1"]},
        special_swsd_junction_types={"j1": "complex"},
        blocked_segment_ids=blocked,
        blocking_groups_by_segment=blocking_groups,
    )
    annotated = replaceable_rows[0]["properties"]
    assert annotated["special_junction_gate_status"] == "partial"
    assert annotated["special_junction_blocking_group_ids"] == ["j1"]


def test_special_junction_gate_blocks_when_no_roundabout_segment_is_replaceable() -> None:
    rows, blocked, removed, blocking_groups = special_junction_gate(
        special_junction_segments={"r1": ["s_missing_a", "s_missing_b"]},
        special_swsd_junction_types={"r1": "roundabout"},
        replaceable_rows=[],
        additional_replaceable_segment_ids=set(),
        relation_map={},
        rcsd_junction_node_ids={},
        rcsd_junction_road_ids={},
    )

    props = rows[0]["properties"]
    assert props["gate_status"] == "blocked"
    assert props["replaceable_segment_ids"] == []
    assert props["missing_replaceable_segment_ids"] == ["s_missing_a", "s_missing_b"]
    assert blocked == {"s_missing_a", "s_missing_b"}
    assert removed == set()
    assert blocking_groups == {"s_missing_a": ["r1"], "s_missing_b": ["r1"]}


def _replaceable(segment_id: str) -> dict:
    return {"type": "Feature", "properties": {"swsd_segment_id": segment_id}, "geometry": None}
