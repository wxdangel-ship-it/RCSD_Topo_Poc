from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.case_loader import (
    load_case_bundle,
    load_case_specs,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.event_interpretation import (
    build_case_result,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.support_domain import (
    build_step5_support_domain,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.support_domain_common import (
    _derive_related_swsd_road_ids_from_topology,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.review_render import (
    _related_swsd_road_ids as _render_related_swsd_road_ids,
)

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import _build_synthetic_case_package


def _synthetic_case_result(tmp_path: Path):
    case_root = tmp_path / "cases"
    case_dir = case_root / "1001"
    _build_synthetic_case_package(case_dir)
    case_specs, _ = load_case_specs(case_root=case_root, case_ids=["1001"])
    assert len(case_specs) == 1
    return build_case_result(load_case_bundle(case_specs[0]))


def _all_swsd_road_ids(case_result) -> set[str]:
    return {
        str(road.road_id)
        for road in case_result.case_bundle.roads
        if str(road.road_id)
    }


def test_step5_related_swsd_roads_match_step3_semantic_junction(tmp_path: Path) -> None:
    case_result = _synthetic_case_result(tmp_path)

    step5_result = build_step5_support_domain(case_result)
    expected_related = _derive_related_swsd_road_ids_from_topology(case_result.base_context.topology_skeleton)

    assert set(step5_result.related_swsd_road_ids) == expected_related
    assert set(_render_related_swsd_road_ids(case_result)) == expected_related
    assert set(step5_result.unrelated_swsd_road_ids) == _all_swsd_road_ids(case_result) - expected_related


def test_step5_related_swsd_roads_change_with_step3_connector_fixture(tmp_path: Path) -> None:
    case_result = _synthetic_case_result(tmp_path)
    skeleton = case_result.base_context.topology_skeleton
    junction = skeleton.swsd_semantic_junction
    first_arm = junction.semantic_arms[0]
    removed_connector_ids = set(first_arm.inter_junction_connector_road_ids)
    assert removed_connector_ids

    trimmed_arm = replace(first_arm, inter_junction_connector_road_ids=())
    trimmed_junction = replace(
        junction,
        semantic_arms=(trimmed_arm, *junction.semantic_arms[1:]),
    )
    case_result.base_context = replace(
        case_result.base_context,
        topology_skeleton=replace(skeleton, swsd_semantic_junction=trimmed_junction),
    )

    step5_result = build_step5_support_domain(case_result)
    expected_related = _derive_related_swsd_road_ids_from_topology(case_result.base_context.topology_skeleton)

    assert set(step5_result.related_swsd_road_ids) == expected_related
    assert set(_render_related_swsd_road_ids(case_result)) == expected_related
    assert removed_connector_ids.isdisjoint(step5_result.related_swsd_road_ids)
