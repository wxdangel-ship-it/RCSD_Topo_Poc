from pathlib import Path

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_surface_runtime import (
    Step3SurfaceRuntimeState,
    publish_step3_surface_runtime_state,
    take_step3_surface_runtime_state,
)


def test_surface_runtime_normalizes_vector_properties_and_keeps_connectivity_ids(tmp_path) -> None:
    road = {"properties": {"id": "r1", "segment_ids": ["s1", "s2"]}, "geometry": None}
    state = Step3SurfaceRuntimeState(
        step_root=tmp_path,
        swsd_segments=[],
        swsd_roads=[],
        swsd_nodes=[],
        step2_replaceable_rows=[],
        frcsd_roads=[road],
        frcsd_nodes=[],
        segment_relation_rows=[],
        semantic_junction_group_rows=[],
        advance_right_audit_rows=[],
        connectivity_supplement_road_ids={"r1"},
        authoritative_transition_closure_rows=[
            {"properties": {"swsd_node_id": "n1"}, "geometry": None}
        ],
    )

    publish_step3_surface_runtime_state(state)
    actual = take_step3_surface_runtime_state(Path(tmp_path))

    assert actual is state
    assert road["properties"]["segment_ids"] == '["s1","s2"]'
    assert actual.connectivity_supplement_road_ids == {"r1"}
    assert actual.authoritative_transition_closure_rows[0]["properties"]["swsd_node_id"] == "n1"
