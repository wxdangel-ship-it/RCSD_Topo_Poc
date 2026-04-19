from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t03_virtual_junction_anchor import step3_engine
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import (
    CaseSpec,
    NodeRecord,
    RoadRecord,
    SemanticGroup,
    Step1Context,
    Step2TemplateResult,
)


def _build_step3_context(case_root: Path) -> Step1Context:
    case_spec = CaseSpec(
        case_id="100001",
        mainnodeid="100001",
        case_root=case_root,
        manifest={},
        size_report={},
        input_paths={},
    )
    representative_node = NodeRecord(
        feature_index=0,
        node_id="100001",
        mainnodeid="100001",
        has_evd="yes",
        is_anchor="no",
        kind_2=4,
        grade_2=1,
        geometry=Point(0.0, 0.0),
    )
    road_horizontal = RoadRecord(
        feature_index=0,
        road_id="road_h",
        snodeid="100001",
        enodeid="road_h_end",
        direction=2,
        geometry=LineString([(0.0, 0.0), (30.0, 0.0)]),
    )
    road_vertical = RoadRecord(
        feature_index=1,
        road_id="road_v",
        snodeid="road_v_start",
        enodeid="100001",
        direction=2,
        geometry=LineString([(0.0, -30.0), (0.0, 0.0)]),
    )
    return Step1Context(
        case_spec=case_spec,
        representative_node=representative_node,
        target_group=SemanticGroup(group_id="100001", nodes=(representative_node,)),
        all_nodes=(representative_node,),
        foreign_groups=(),
        roads=(road_horizontal, road_vertical),
        rcsd_roads=(),
        rcsd_nodes=(),
        drivezone_geometry=box(-40.0, -40.0, 40.0, 40.0),
        target_road_ids=frozenset({"road_h", "road_v"}),
    )


def _same_geometry(left, right) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return left.equals_exact(right, 1e-6) or left.equals(right)


def test_build_step3_case_result_cache_preserves_semantics(tmp_path: Path) -> None:
    context = _build_step3_context(tmp_path / "case_root")
    template_result = Step2TemplateResult(template_class="center_junction", supported=True, reason=None)

    uncached_result = step3_engine.build_step3_case_result(
        context,
        template_result,
        use_reachable_support_cache=False,
    )
    cached_result = step3_engine.build_step3_case_result(
        context,
        template_result,
        use_reachable_support_cache=True,
    )

    assert cached_result.step3_state == uncached_result.step3_state
    assert cached_result.step3_established == uncached_result.step3_established
    assert cached_result.reason == uncached_result.reason
    assert cached_result.visual_review_class == uncached_result.visual_review_class
    assert cached_result.root_cause_layer == uncached_result.root_cause_layer
    assert cached_result.root_cause_type == uncached_result.root_cause_type
    assert _same_geometry(cached_result.allowed_space_geometry, uncached_result.allowed_space_geometry)
    assert _same_geometry(cached_result.allowed_drivezone_geometry, uncached_result.allowed_drivezone_geometry)
    assert _same_geometry(
        cached_result.negative_masks.adjacent_junction_geometry,
        uncached_result.negative_masks.adjacent_junction_geometry,
    )
    assert _same_geometry(
        cached_result.negative_masks.foreign_objects_geometry,
        uncached_result.negative_masks.foreign_objects_geometry,
    )
    assert _same_geometry(
        cached_result.negative_masks.foreign_mst_geometry,
        uncached_result.negative_masks.foreign_mst_geometry,
    )
    assert cached_result.key_metrics == uncached_result.key_metrics
    assert cached_result.audit_doc == uncached_result.audit_doc
    assert cached_result.extra_status_fields == uncached_result.extra_status_fields


def test_build_step3_case_result_cache_reuses_support_preparation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    context = _build_step3_context(tmp_path / "case_root")
    template_result = Step2TemplateResult(template_class="center_junction", supported=True, reason=None)

    original_build_road_graph = step3_engine._build_road_graph
    original_multi_source_dijkstra = step3_engine._multi_source_dijkstra
    counts = {"graph": 0, "dijkstra": 0}

    def _count_build_road_graph(*args, **kwargs):
        counts["graph"] += 1
        return original_build_road_graph(*args, **kwargs)

    def _count_multi_source_dijkstra(*args, **kwargs):
        counts["dijkstra"] += 1
        return original_multi_source_dijkstra(*args, **kwargs)

    monkeypatch.setattr(step3_engine, "_build_road_graph", _count_build_road_graph)
    monkeypatch.setattr(step3_engine, "_multi_source_dijkstra", _count_multi_source_dijkstra)

    uncached_stage_timers: dict[str, float] = {}
    step3_engine.build_step3_case_result(
        context,
        template_result,
        stage_timers=uncached_stage_timers,
        use_reachable_support_cache=False,
    )
    assert counts == {"graph": 3, "dijkstra": 3}

    counts["graph"] = 0
    counts["dijkstra"] = 0
    cached_stage_timers: dict[str, float] = {}
    step3_engine.build_step3_case_result(
        context,
        template_result,
        stage_timers=cached_stage_timers,
        use_reachable_support_cache=True,
    )

    assert counts == {"graph": 1, "dijkstra": 1}
    assert set(cached_stage_timers) >= {
        "step3_reachable_support",
        "step3_negative_masks",
        "step3_cleanup_preview",
        "step3_hard_path_validation",
    }
    assert cached_stage_timers["step3_reachable_support"] >= 0.0
    assert cached_stage_timers["step3_negative_masks"] >= 0.0
    assert cached_stage_timers["step3_cleanup_preview"] >= 0.0
    assert cached_stage_timers["step3_hard_path_validation"] >= 0.0
