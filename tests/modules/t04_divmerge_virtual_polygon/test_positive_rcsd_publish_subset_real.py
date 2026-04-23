from __future__ import annotations

import pytest

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
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.step4_final_conflict_resolver import (
    resolve_step4_final_conflicts,
)

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import REAL_ANCHOR_2_ROOT


def _resolved_real_case(case_id: str):
    if not (REAL_ANCHOR_2_ROOT / case_id).is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / case_id}")
    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=[case_id],
    )
    resolved, _ = resolve_step4_final_conflicts(
        [build_case_result(load_case_bundle(specs[0]))]
    )
    return resolved[0]


def test_857993_node_870089_publishes_aggregated_forward_rcsd_branches() -> None:
    case_result = _resolved_real_case("857993")
    unit = next(item for item in case_result.event_units if item.spec.event_unit_id == "node_870089")

    assert unit.positive_rcsd_consistency_level == "A"
    assert set(unit.selected_rcsdroad_ids).issuperset(
        {
            "5384381334946288",
            "5384381334946289",
            "5384383918381062",
            "5384383918381065",
        }
    )


def test_17943587_keeps_5381295501542402_in_positive_support_graph() -> None:
    case_result = _resolved_real_case("17943587")
    units = {item.spec.event_unit_id: item for item in case_result.event_units}
    step5_result = build_step5_support_domain(case_result)

    for unit_id in ("node_17943587", "node_55353233", "node_55353248"):
        unit = units[unit_id]
        assert unit.positive_rcsd_consistency_level == "A"
        audit = unit.positive_rcsd_audit
        assert any(
            "5381295501542402" in set(item["event_side_road_ids"])
            for item in audit["aggregated_rcsd_units"]
        )
    assert "5381295501542402" in set(step5_result.related_rcsd_road_ids)
