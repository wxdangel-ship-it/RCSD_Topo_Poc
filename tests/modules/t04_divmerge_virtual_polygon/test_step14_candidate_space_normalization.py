from __future__ import annotations

import rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._event_interpretation_core as core

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._event_interpretation_core import (
    _degraded_scope_metadata,
)
from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403


def _write_candidate_space_case_package(
    case_dir: Path,
    *,
    case_id: str,
    roads: list[dict],
    nodes: list[dict],
    drivezone,
    divstrip,
) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    file_list = [
        "manifest.json",
        "size_report.json",
        "drivezone.gpkg",
        "divstripzone.gpkg",
        "nodes.gpkg",
        "roads.gpkg",
        "rcsdroad.gpkg",
        "rcsdnode.gpkg",
    ]
    _write_json(
        case_dir / "manifest.json",
        {
            "bundle_version": 1,
            "bundle_mode": "single_case",
            "mainnodeid": case_id,
            "epsg": 3857,
            "file_list": file_list,
            "decoded_output": {
                "vector_crs": "EPSG:3857",
            },
        },
    )
    _write_json(case_dir / "size_report.json", {"within_limit": True})
    write_vector(
        case_dir / "drivezone.gpkg",
        [{"properties": {"id": 1, "patchid": 1}, "geometry": drivezone}],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "divstripzone.gpkg",
        [{"properties": {"id": 1, "patchid": 1}, "geometry": divstrip}],
        crs_text="EPSG:3857",
    )
    write_vector(case_dir / "nodes.gpkg", nodes, crs_text="EPSG:3857")
    write_vector(case_dir / "roads.gpkg", roads, crs_text="EPSG:3857")
    write_vector(
        case_dir / "rcsdroad.gpkg",
        [
            {
                "properties": {
                    "id": 9001,
                    "snodeid": 9001,
                    "enodeid": 9002,
                    "direction": 2,
                },
                "geometry": LineString([(380, 400), (420, 400)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        case_dir / "rcsdnode.gpkg",
        [
            {
                "properties": {"id": 9001, "mainnodeid": None, "kind_2": 0, "grade_2": 0},
                "geometry": Point(380, 400),
            },
            {
                "properties": {"id": 9002, "mainnodeid": None, "kind_2": 0, "grade_2": 0},
                "geometry": Point(420, 400),
            },
        ],
        crs_text="EPSG:3857",
    )


def _build_long_forward_case_package(case_dir: Path) -> None:
    drivezone = Polygon([(-160, -120), (280, -120), (280, 120), (-160, 120), (-160, -120)])
    divstrip = Polygon([(2, -5), (22, 0), (2, 5), (-2, 0), (2, -5)])
    nodes = [
        {
            "properties": {
                "id": 3001,
                "mainnodeid": 3001,
                "has_evd": "yes",
                "is_anchor": "no",
                "kind_2": 16,
                "grade_2": 1,
            },
            "geometry": Point(0, 0),
        },
        {
            "properties": {"id": 3002, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0},
            "geometry": Point(-120, 0),
        },
        {
            "properties": {"id": 3003, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0},
            "geometry": Point(240, 8),
        },
        {
            "properties": {"id": 3004, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0},
            "geometry": Point(240, -8),
        },
    ]
    roads = [
        {
            "properties": {"id": 3101, "snodeid": 3002, "enodeid": 3001, "direction": 2},
            "geometry": LineString([(-120, 0), (0, 0)]),
        },
        {
            "properties": {"id": 3102, "snodeid": 3001, "enodeid": 3003, "direction": 2},
            "geometry": LineString([(0, 0), (120, 4), (240, 8)]),
        },
        {
            "properties": {"id": 3103, "snodeid": 3001, "enodeid": 3004, "direction": 2},
            "geometry": LineString([(0, 0), (120, -4), (240, -8)]),
        },
    ]
    _write_candidate_space_case_package(
        case_dir,
        case_id="3001",
        roads=roads,
        nodes=nodes,
        drivezone=drivezone,
        divstrip=divstrip,
    )


def _build_intrusion_case_package(case_dir: Path) -> None:
    drivezone = Polygon([(-120, -120), (280, -120), (280, 120), (-120, 120), (-120, -120)])
    divstrip = Polygon([(2, -5), (22, 0), (2, 5), (-2, 0), (2, -5)])
    nodes = [
        {
            "properties": {
                "id": 4001,
                "mainnodeid": 4001,
                "has_evd": "yes",
                "is_anchor": "no",
                "kind_2": 16,
                "grade_2": 1,
            },
            "geometry": Point(0, 0),
        },
        {
            "properties": {"id": 4002, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0},
            "geometry": Point(-80, 0),
        },
        {
            "properties": {"id": 4003, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0},
            "geometry": Point(220, 40),
        },
        {
            "properties": {"id": 4004, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0},
            "geometry": Point(220, -40),
        },
        {
            "properties": {"id": 4010, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0},
            "geometry": Point(120, -30),
        },
        {
            "properties": {"id": 4011, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "kind_2": 0, "grade_2": 0},
            "geometry": Point(120, 30),
        },
    ]
    roads = [
        {
            "properties": {"id": 4101, "snodeid": 4002, "enodeid": 4001, "direction": 2},
            "geometry": LineString([(-80, 0), (0, 0)]),
        },
        {
            "properties": {"id": 4102, "snodeid": 4001, "enodeid": 4003, "direction": 2},
            "geometry": LineString([(0, 0), (60, 10), (140, 25), (220, 40)]),
        },
        {
            "properties": {"id": 4103, "snodeid": 4001, "enodeid": 4004, "direction": 2},
            "geometry": LineString([(0, 0), (60, -10), (140, -25), (220, -40)]),
        },
        {
            "properties": {"id": 4104, "snodeid": 4010, "enodeid": 4011, "direction": 2},
            "geometry": LineString([(120, -30), (120, 30)]),
        },
    ]
    _write_candidate_space_case_package(
        case_dir,
        case_id="4001",
        roads=roads,
        nodes=nodes,
        drivezone=drivezone,
        divstrip=divstrip,
    )


def _load_single_case_result(case_root: Path, case_id: str):
    case_specs, _ = load_case_specs(case_root=case_root, case_ids=[case_id])
    assert len(case_specs) == 1
    return build_case_result(load_case_bundle(case_specs[0]))


def _load_real_cases(case_ids: list[str]) -> dict[str, object]:
    case_specs, _ = load_case_specs(case_root=REAL_ANCHOR_2_ROOT, case_ids=case_ids)
    return {spec.case_id: build_case_result(load_case_bundle(spec)) for spec in case_specs}


def test_pair_local_scan_caps_at_200m_and_records_forward_direction(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "3001"
    _build_long_forward_case_package(case_dir)

    case_result = _load_single_case_result(case_root, "3001")
    assert len(case_result.event_units) == 1
    event_unit = case_result.event_units[0]
    offsets = [float(item) for item in event_unit.pair_local_summary["valid_scan_offsets_m"]]

    _assert_one_sided_offsets(offsets)
    assert event_unit.pair_local_summary["pair_local_direction"] in {"forward", "reverse_fallback"}
    assert event_unit.pair_local_summary["stop_reason"] in {
        "max_branch_length_reached",
        "branch_separation_too_large",
    }
    assert max(abs(item) for item in offsets) == pytest.approx(200.0, abs=1e-6)
    assert float(event_unit.pair_local_summary["branch_separation_max_m"]) > 0.0
    assert float(event_unit.pair_local_summary["branch_separation_mean_m"]) > 0.0
    assert event_unit.pair_local_summary["branch_separation_stop_triggered"] is False


def test_forward_official_direction_does_not_fall_back_to_reverse_when_forward_is_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not (REAL_ANCHOR_2_ROOT / "785671").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '785671'}")

    recorded_scan_s: list[float] = []
    real_builder = core._build_pair_local_slice_diagnostic

    def _spy_slice_diagnostic(**kwargs):
        recorded_scan_s.append(float(kwargs["scan_dist_m"]))
        return real_builder(**kwargs)

    monkeypatch.setattr(core, "_build_pair_local_slice_diagnostic", _spy_slice_diagnostic)
    case_result = _load_real_cases(["785671"])["785671"]
    event_unit = case_result.event_units[0]

    assert event_unit.pair_local_summary["pair_local_direction"] == "forward"
    assert any(scan_s > 0.0 for scan_s in recorded_scan_s)
    assert not any(scan_s < 0.0 for scan_s in recorded_scan_s)


def test_pair_local_intrusion_gate_records_stop_reason_and_intruding_road_ids(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "4001"
    _build_intrusion_case_package(case_dir)

    case_result = _load_single_case_result(case_root, "4001")
    event_unit = case_result.event_units[0]

    assert event_unit.pair_local_summary["stop_reason"] == "road_intrusion_between_branches"
    assert event_unit.pair_local_summary["intruding_road_ids"] == ["4104"]
    assert event_unit.pair_local_summary["pair_local_direction"] in {"forward", "reverse_fallback"}
    assert event_unit.pair_local_summary["branch_separation_max_m"] is not None


def test_degraded_scope_metadata_classifies_soft_and_hard() -> None:
    assert _degraded_scope_metadata([]) == (None, None, False)
    assert _degraded_scope_metadata(["pair_local_scope_rcsd_empty"]) == (
        "pair_local_scope_rcsd_empty",
        "soft",
        True,
    )
    assert _degraded_scope_metadata(["pair_local_middle_missing", "pair_local_scope_rcsd_empty"]) == (
        "pair_local_middle_missing|pair_local_scope_rcsd_empty",
        "hard",
        True,
    )


def test_hard_degraded_scope_can_elevate_step4_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "3001"
    _build_long_forward_case_package(case_dir)

    def _always_fail_slice(**kwargs):
        return {
            "scan_s": float(kwargs["scan_dist_m"]),
            "segment": None,
            "center_point": Point(0, 0),
            "ok": False,
            "reason": "semantic_boundary_reached",
            "seg_len_m": 0.0,
            "branch_a_crossline_hit": False,
            "branch_b_crossline_hit": False,
            "pair_replacement_road_ids": (),
            "intruding_road_ids": (),
            "branch_separation_threshold_m": float(kwargs["branch_separation_threshold_m"]),
            "branch_separation_exceeded": False,
            "stop_reason": "semantic_boundary_reached",
        }

    monkeypatch.setattr(core, "_build_pair_local_slice_diagnostic", _always_fail_slice)
    case_result = _load_single_case_result(case_root, "3001")
    event_unit = case_result.event_units[0]

    assert event_unit.unit_envelope.degraded_scope_severity == "hard"
    assert event_unit.unit_envelope.degraded_scope_fallback_used is True
    assert event_unit.review_state == "STEP4_FAIL"
    assert "hard_degraded_scope" in event_unit.review_reasons


@pytest.mark.smoke
def test_step14_batch_exports_candidate_space_normalization_fields(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "3001"
    _build_long_forward_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_candidate_space",
        run_id="synthetic_t04_candidate_space_norm",
    )
    unit_dir = next((run_root / "cases" / "3001" / "event_units").iterdir())
    candidate_doc = json.loads((unit_dir / "step4_candidates.json").read_text(encoding="utf-8"))
    evidence_doc = json.loads((unit_dir / "step4_evidence_audit.json").read_text(encoding="utf-8"))

    pair_local_summary = candidate_doc["pair_local_summary"]
    assert pair_local_summary["pair_local_direction"] in {"forward", "reverse_fallback"}
    assert pair_local_summary["branch_separation_mean_m"] is not None
    assert pair_local_summary["branch_separation_max_m"] is not None
    assert pair_local_summary["branch_separation_consecutive_exceed_count"] >= 0
    assert pair_local_summary["branch_separation_stop_triggered"] in {True, False}
    assert pair_local_summary["stop_reason"] != ""
    assert "intruding_road_ids" in pair_local_summary
    assert "degraded_scope_severity" in pair_local_summary
    assert "degraded_scope_fallback_used" in pair_local_summary
    assert evidence_doc["audit_summary"]["candidate_pool_size"] >= 1

    with (run_root / "step4_review_index.csv").open("r", encoding="utf-8-sig", newline="") as fp:
        row = next(csv.DictReader(fp))
    assert row["pair_local_direction"] in {"forward", "reverse_fallback"}
    assert row["branch_separation_max_m"] != ""
    assert row["stop_reason"] != ""
    assert row["degraded_scope_fallback_used"] in {"0", "1"}


def test_real_anchor2_candidate_space_metrics_present_without_container_drift() -> None:
    if not (REAL_ANCHOR_2_ROOT / "17943587").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '17943587'}")

    cases = _load_real_cases(["17943587", "73462878"])

    for case_id, case_result in cases.items():
        for event_unit in case_result.event_units:
            assert "pair_local_direction" in event_unit.pair_local_summary
            assert "branch_separation_mean_m" in event_unit.pair_local_summary
            assert "branch_separation_max_m" in event_unit.pair_local_summary
            assert "branch_separation_stop_triggered" in event_unit.pair_local_summary
            assert "stop_reason" in event_unit.pair_local_summary
            assert "intruding_road_ids" in event_unit.pair_local_summary
            assert "degraded_scope_severity" in event_unit.pair_local_summary
            assert "degraded_scope_fallback_used" in event_unit.pair_local_summary
            _assert_one_sided_offsets(event_unit.pair_local_summary["valid_scan_offsets_m"])
            _assert_selected_candidate_region_is_pair_local_container(event_unit)
            expected_pair_signature = _stable_boundary_pair_signature(
                event_unit.unit_envelope.branch_road_memberships,
                event_unit.unit_envelope.boundary_branch_ids,
            )
            assert event_unit.pair_local_summary["boundary_pair_signature"] == expected_pair_signature
            assert event_unit.pair_local_summary["region_id"] == f"{event_unit.spec.event_unit_id}:{expected_pair_signature}"


def test_real_same_case_sibling_continuation_keeps_pair_local_container_stable() -> None:
    required_case_ids = ["17943587", "760213"]
    if any(not (REAL_ANCHOR_2_ROOT / case_id).is_dir() for case_id in required_case_ids):
        pytest.skip(f"missing real case package(s): {required_case_ids}")

    cases = _load_real_cases(required_case_ids)
    bridged_units = []
    for case_result in cases.values():
        for event_unit in case_result.event_units:
            bridge_node_ids = event_unit.pair_local_summary.get("branch_bridge_node_ids", {})
            if not any(bridge_node_ids.values()):
                continue
            bridged_units.append((event_unit.spec.event_unit_id, bridge_node_ids))
            _assert_selected_candidate_region_is_pair_local_container(event_unit)
            expected_pair_signature = _stable_boundary_pair_signature(
                event_unit.unit_envelope.branch_road_memberships,
                event_unit.unit_envelope.boundary_branch_ids,
            )
            assert event_unit.pair_local_summary["boundary_pair_signature"] == expected_pair_signature
            assert event_unit.pair_local_summary["region_id"] == f"{event_unit.spec.event_unit_id}:{expected_pair_signature}"

    assert bridged_units
