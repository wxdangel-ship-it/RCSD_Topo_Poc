from __future__ import annotations

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step2_special_junctions import special_junction_gate


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


def test_special_junction_gate_still_blocks_when_group_has_uncovered_segment() -> None:
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
    assert props["gate_status"] == "blocked"
    assert props["replaceable_segment_ids"] == ["s_standard"]
    assert props["missing_replaceable_segment_ids"] == ["s_missing"]
    assert blocked == {"s_standard", "s_missing"}
    assert removed == {"s_standard"}
    assert blocking_groups == {"s_standard": ["j1"], "s_missing": ["j1"]}


def _replaceable(segment_id: str) -> dict:
    return {"type": "Feature", "properties": {"swsd_segment_id": segment_id}, "geometry": None}
