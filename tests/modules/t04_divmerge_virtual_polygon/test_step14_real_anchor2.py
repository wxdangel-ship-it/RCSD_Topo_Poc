from __future__ import annotations

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403

def test_anchor2_current_selected_units_match_frozen_support_levels() -> None:
    if not REAL_ANCHOR_2_ROOT.is_dir():
        pytest.skip(f"missing real Anchor_2 case root: {REAL_ANCHOR_2_ROOT}")
    case_ids = [
        "760213",
        "785671",
        "785675",
        "857993",
        "987998",
        "17943587",
        "30434673",
        "73462878",
    ]
    expected_support_levels = {
        ("785671", "event_unit_01"): ("secondary_support", "B"),
    }
    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=case_ids,
    )
    failures: list[str] = []
    for spec in specs:
        case_result = build_case_result(load_case_bundle(spec))
        for event_unit in case_result.event_units:
            expected_support, expected_consistency = expected_support_levels.get(
                (spec.case_id, event_unit.spec.event_unit_id),
                ("primary_support", "A"),
            )
            if event_unit.positive_rcsd_consistency_level != expected_consistency:
                failures.append(
                    f"{spec.case_id}/{event_unit.spec.event_unit_id}:"
                    f"{event_unit.positive_rcsd_consistency_level}/{event_unit.positive_rcsd_support_level}"
                )
            if event_unit.positive_rcsd_support_level != expected_support:
                failures.append(
                    f"{spec.case_id}/{event_unit.spec.event_unit_id}:"
                    f"support={event_unit.positive_rcsd_support_level}"
                )
    assert not failures, failures

def test_real_cases_760213_and_17943587_refresh_selected_evidence_outputs() -> None:
    case_ids = ["760213", "17943587"]
    missing_cases = [case_id for case_id in case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=case_ids,
    )
    case_by_id = {spec.case_id: spec for spec in specs}

    case_760213 = build_case_result(load_case_bundle(case_by_id["760213"]))
    selected_by_unit_760213 = {
        item.spec.event_unit_id: str(item.selected_evidence_summary.get("candidate_id") or "")
        for item in case_760213.event_units
    }
    assert selected_by_unit_760213 == {
        "node_760213": "node_760213:divstrip:2:01",
        "node_760218": "node_760218:divstrip:2:01",
    }

    case_17943587 = build_case_result(load_case_bundle(case_by_id["17943587"]))
    selected_by_unit_17943587 = {
        item.spec.event_unit_id: str(item.selected_evidence_summary.get("candidate_id") or "")
        for item in case_17943587.event_units
    }
    assert selected_by_unit_17943587 == {
        "node_17943587": "node_17943587:divstrip:1:01",
        "node_55353233": "node_55353233:divstrip:1:01",
        "node_55353239": "node_55353239:divstrip:1:01",
        "node_55353248": "node_55353248:divstrip:1:01",
    }

def test_real_anchor2_primary_evidence_and_reference_freeze_after_manual_acceptance() -> None:
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
    missing_cases = [case_id for case_id in expected_candidates if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    specs, _ = load_case_specs(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=list(expected_candidates),
    )
    case_by_id = {spec.case_id: spec for spec in specs}

    for case_id, expected_by_unit in expected_candidates.items():
        case_result = build_case_result(load_case_bundle(case_by_id[case_id]))
        actual_by_unit = {
            item.spec.event_unit_id: item
            for item in case_result.event_units
        }
        assert set(actual_by_unit) == set(expected_by_unit)

        for unit_id, expected_candidate_id in expected_by_unit.items():
            event_unit = actual_by_unit[unit_id]
            selected = event_unit.selected_evidence_summary
            assert event_unit.selected_evidence_state == "found"
            assert selected["candidate_id"] == expected_candidate_id
            assert selected["upper_evidence_kind"] == "divstrip"
            assert selected["node_fallback_only"] is False
            assert event_unit.fact_reference_point is not None
            assert event_unit.selected_evidence_region_geometry is not None
            assert event_unit.selected_evidence_region_geometry.buffer(1e-6).covers(
                event_unit.fact_reference_point
            )
            reference_distance = selected.get("reference_distance_to_origin_m")
            assert reference_distance is not None
            assert float(reference_distance) > 3.0
            assert float(
                event_unit.fact_reference_point.distance(event_unit.unit_context.representative_node.geometry)
            ) < float(reference_distance)
