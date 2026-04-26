from __future__ import annotations

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.step4_final_conflict_resolver import (
    resolve_step4_final_conflicts,
)


def _resolve_real_cases(case_ids: list[str]) -> list:
    missing_cases = [case_id for case_id in case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")
    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=case_ids,
    )
    case_results = [build_case_result(load_case_bundle(spec)) for spec in specs]
    resolved_case_results, _ = resolve_step4_final_conflicts(case_results)
    return resolved_case_results


def test_anchor2_current_units_keep_frozen_support_after_second_pass() -> None:
    expected_candidates = {
        "760213": {
            "node_760213": "node_760213:divstrip:2:01",
            "node_760218": "node_760218:divstrip:2:01",
        },
        "785671": {
            "event_unit_01": "event_unit_01:divstrip:2:01",
        },
        "785675": {
            "event_unit_01": "event_unit_01:divstrip:4:01",
        },
        "857993": {
            "node_857993": "node_857993:divstrip:3:01",
            "node_870089": "node_870089:divstrip:3:01",
        },
        "987998": {
            "event_unit_01": "event_unit_01:divstrip:3:01",
        },
        "17943587": {
            "node_17943587": "node_17943587:divstrip:1:01",
            "node_55353233": "node_55353233:divstrip:1:01",
            "node_55353239": "node_55353239:divstrip:1:01",
            "node_55353248": "node_55353248:divstrip:1:01",
        },
        "30434673": {
            "event_unit_01": "event_unit_01:divstrip:3:01",
        },
        "73462878": {
            "event_unit_01": "event_unit_01:divstrip:0:01",
        },
    }
    expected_support_levels = {
        ("785671", "event_unit_01"): ("secondary_support", "B"),
    }
    case_results = _resolve_real_cases(list(expected_candidates))
    case_by_id = {case_result.case_spec.case_id: case_result for case_result in case_results}

    for case_id, expected_by_unit in expected_candidates.items():
        case_result = case_by_id[case_id]
        actual_by_unit = {item.spec.event_unit_id: item for item in case_result.event_units}
        assert set(actual_by_unit) == set(expected_by_unit)
        for unit_id, expected_candidate_id in expected_by_unit.items():
            event_unit = actual_by_unit[unit_id]
            assert event_unit.selected_evidence_state == "found"
            assert event_unit.selected_evidence_summary["candidate_id"] == expected_candidate_id
            assert event_unit.positive_rcsd_present is True
            expected_support, expected_consistency = expected_support_levels.get(
                (case_id, unit_id),
                ("primary_support", "A"),
            )
            assert event_unit.positive_rcsd_support_level == expected_support
            assert event_unit.positive_rcsd_consistency_level == expected_consistency
            assert event_unit.required_rcsd_node not in {"", None}


def test_real_case_17943587_second_pass_resolves_duplicate_required_rcsd_node_without_evidence_regression() -> None:
    (case_result,) = _resolve_real_cases(["17943587"])
    units = {event_unit.spec.event_unit_id: event_unit for event_unit in case_result.event_units}

    assert units["node_17943587"].selected_evidence_summary["candidate_id"] == "node_17943587:divstrip:1:01"
    assert units["node_55353233"].selected_evidence_summary["candidate_id"] == "node_55353233:divstrip:1:01"
    assert units["node_55353239"].selected_evidence_summary["candidate_id"] == "node_55353239:divstrip:1:01"
    assert units["node_55353248"].selected_evidence_summary["candidate_id"] == "node_55353248:divstrip:1:01"

    required_by_unit = {
        unit_id: str(event_unit.required_rcsd_node or "")
        for unit_id, event_unit in units.items()
    }
    assert len(set(required_by_unit.values())) == 4
    assert required_by_unit["node_17943587"] == "5381293925340513"
    assert required_by_unit["node_55353233"] == "5381293925340546"
    assert required_by_unit["node_55353239"] == "5381293925340519"
    assert required_by_unit["node_55353248"] == "5381293925340552"

    assert units["node_55353233"].pre_required_rcsd_node == "5381293925340546"
    assert units["node_55353233"].post_required_rcsd_node == "5381293925340546"
    assert units["node_55353233"].conflict_resolution_action == "kept"
    assert units["node_55353233"].rcsd_conflict_component_id != ""
    assert units["node_55353233"].positive_rcsd_support_level == "primary_support"
    assert units["node_55353233"].positive_rcsd_consistency_level == "A"

    assert units["node_55353248"].pre_required_rcsd_node == "5381293925340552"
    assert units["node_55353248"].post_required_rcsd_node == "5381293925340552"
    assert units["node_55353248"].conflict_resolution_action == "kept"
    assert units["node_55353248"].positive_rcsd_support_level == "primary_support"
    assert units["node_55353248"].positive_rcsd_consistency_level == "A"


def test_real_case_760213_same_case_non_conflict_units_remain_frozen_after_second_pass() -> None:
    (case_result,) = _resolve_real_cases(["760213"])
    units = {event_unit.spec.event_unit_id: event_unit for event_unit in case_result.event_units}

    assert units["node_760213"].selected_evidence_summary["candidate_id"] == "node_760213:divstrip:2:01"
    assert units["node_760218"].selected_evidence_summary["candidate_id"] == "node_760218:divstrip:2:01"
    assert units["node_760213"].pre_required_rcsd_node == units["node_760213"].post_required_rcsd_node
    assert units["node_760218"].pre_required_rcsd_node == units["node_760218"].post_required_rcsd_node
    assert units["node_760213"].conflict_resolution_action == "kept"
    assert units["node_760218"].conflict_resolution_action == "kept"
    assert units["node_760213"].positive_rcsd_support_level == "primary_support"
    assert units["node_760218"].positive_rcsd_support_level == "primary_support"
