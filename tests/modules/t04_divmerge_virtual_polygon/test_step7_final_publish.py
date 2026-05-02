from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

ANCHOR2_FULL_BASELINE_20260426: dict[str, str] = {
    "17943587": "accepted",
    "30434673": "accepted",
    "505078921": "accepted",
    "698380": "accepted",
    "698389": "accepted",
    "699870": "accepted",
    "706629": "accepted",
    "723276": "accepted",
    "724067": "accepted",
    "724081": "accepted",
    "73462878": "accepted",
    "758784": "accepted",
    "760213": "accepted",
    "760256": "accepted",
    "760598": "rejected",
    "760936": "rejected",
    "760984": "accepted",
    "785671": "accepted",
    "785675": "accepted",
    "788824": "accepted",
    "824002": "accepted",
    "857993": "rejected",
    "987998": "accepted",
}

ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501: dict[str, str] = {
    "698380": "accepted",
    "698389": "accepted",
    "699870": "accepted",
    "706347": "accepted",
    "706629": "accepted",
    "723276": "accepted",
    "724067": "accepted",
    "724081": "accepted",
    "758784": "accepted",
    "760213": "accepted",
    "760230": "accepted",
    "760256": "accepted",
    "760277": "accepted",
    "760598": "rejected",
    "760936": "rejected",
    "760984": "accepted",
    "765050": "accepted",
    "765170": "accepted",
    "768680": "accepted",
    "785671": "accepted",
    "785675": "accepted",
    "788824": "accepted",
    "824002": "accepted",
    "857993": "rejected",
    "987998": "accepted",
    "17943587": "accepted",
    "30434673": "accepted",
    "73462878": "accepted",
    "505078921": "accepted",
    "607602562": "rejected",
}

ANCHOR2_30CASE_REJECTED_20260501 = {
    "607602562",
    "760598",
    "760936",
    "857993",
}

ANCHOR2_30CASE_KEY_ACCEPTED_20260501 = {
    "706629",
    "706347",
    "760984",
    "788824",
    "760230",
    "760277",
    "765170",
    "768680",
    "699870",
    "698389",
}

ANCHOR2_30CASE_STEP6_GUARD_FIELDS_20260501 = {
    "surface_scenario_type",
    "section_reference_source",
    "surface_generation_mode",
    "post_cleanup_allowed_growth_ok",
    "post_cleanup_forbidden_ok",
    "post_cleanup_terminal_cut_ok",
    "post_cleanup_lateral_limit_ok",
    "no_surface_reference_guard",
    "final_polygon_suppressed_by_no_surface_reference",
    "fallback_overexpansion_detected",
}

ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502: dict[str, dict[str, object]] = {
    "785629": {
        "surface_scenario_type": "mixed",
        "section_reference_source": "mixed",
        "surface_generation_mode": "mixed",
        "unit_surface_scenario_type": "main_evidence_without_rcsd",
        "step4_evidence_source": "multibranch_event",
        "step4_main_evidence_type": "divstrip",
    },
    "785631": {
        "surface_scenario_type": "main_evidence_with_rcsd_junction",
        "section_reference_source": "reference_point_and_rcsd_junction",
        "surface_generation_mode": "main_evidence_driven",
        "step4_evidence_source": "divstrip_direct",
        "step4_main_evidence_type": "divstrip",
    },
    "785731": {
        "surface_scenario_type": "no_main_evidence_with_swsd_only",
        "section_reference_source": "swsd_junction",
        "surface_generation_mode": "swsd_junction_window",
        "step4_evidence_source": "road_surface_fork",
        "step4_main_evidence_type": "none",
    },
    "795682": {
        "surface_scenario_type": "no_main_evidence_with_swsd_only",
        "section_reference_source": "swsd_junction",
        "surface_generation_mode": "swsd_junction_window",
        "step4_evidence_source": "swsd_junction_window",
        "step4_main_evidence_type": "none",
    },
    "807908": {
        "surface_scenario_type": "main_evidence_with_rcsd_junction",
        "section_reference_source": "reference_point_and_rcsd_junction",
        "surface_generation_mode": "main_evidence_driven",
        "step4_evidence_source": "rcsd_anchored_reverse",
        "step4_main_evidence_type": "divstrip",
    },
    "823826": {
        "surface_scenario_type": "main_evidence_with_rcsd_junction",
        "section_reference_source": "reference_point_and_rcsd_junction",
        "surface_generation_mode": "main_evidence_driven",
        "step4_evidence_source": "multibranch_event",
        "step4_main_evidence_type": "divstrip",
    },
}

# The 23-case business gate remains the 2026-04-26 frozen Anchor_2 set,
# but its final_review.png visual fingerprints were refreshed on 2026-05-01.
# The previous PNG hashes came from the 2026-04-26 frozen visual baseline.
# Surface-scenario, section-reference, case-level bridge, and Step6 guard
# upgrades intentionally changed review geometry/layers for 8 of the 23 cases.
# The 30-case visual audit was manually reviewed and accepted by the user; this
# is not an algorithm change, a quiet refresh, or a relaxation of business gates.
# Row counts, accepted/rejected states, nodes writeback, and Step7 consistency
# assertions are still enforced below before these PNG hashes are checked.
ANCHOR2_FULL_FINAL_REVIEW_PNG_FINGERPRINTS_20260501_SURFACE_SCENARIO: dict[
    str, dict[str, object]
] = {
    "17943587": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "3aa7529455b1a3d425b7e5232d3ffaeab91a6d664d8db583e2718fe4185104fe",
    },
    "30434673": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "1b0d73e8d84ac35723ce8d35511a9bc52e9c7e35ddab4e80b8e038c80331c03c",
    },
    "505078921": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "25411781090208b4429974564b25edc3098bd5b3febfd9f92a92a62a8a450234",
    },
    "698380": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "e96ff65515f999859a29fdb4d9792b0a8da88314f3de192d31ee23aea1145b5c",
    },
    "698389": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "ce9b5d9acf5481642ac10f80eb7f4460363da8eca206fd561a029fed44841c25",
    },
    "699870": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "c871c336d9a3e93b3912a94ee458dee7a534840d3ade1223eb5f47bb4245d2df",
    },
    "706629": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "383d5df26423a0bf86fdc9c5ede71607aed8f48495b4339d1e704331d4aeb03b",
    },
    "723276": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "c2a2cb34ec55a8bde0300f05a03d811c227a90fbfa7ae9cbb5bd9aee681be003",
    },
    "724067": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "636ab2be1d189d25bb8d3f84fc006653215f683e34d948a2d0c6fdac41d3d8a9",
    },
    "724081": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "01d4168a7a1079b1c497b86d6c47a6a0e4654e00f48d3ac06c253419dd87234e",
    },
    "73462878": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "dc6ac748d4f67643772dadc4f27cba1d5ccaef662c1780ea2a961f86aa04ee99",
    },
    "758784": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "7181aef5f5b5ccbb8a5b11a5ebb0bdb09fb0a569300c4b4b4e92c7fed74bf0e6",
    },
    "760213": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "9f9428603f054c88e1085d52d1c5aebebe7e355d2d5f77eb85644d56ce5ddd7f",
    },
    "760256": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "88e52b22974fade61645d9fddbe6048e3eb15a276d683ff1c13e4c831cf0c10b",
    },
    "760598": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "0034347434d4badbfe5c8bf2bb0cff71846a38a346bf2e4477864465f3dee684",
    },
    "760936": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "68d492ce9aa6fdd8f1df64419cb267d3925f6a9bf922a435d291f2212971a953",
    },
    "760984": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "4a169b8d5b43d1e0f469f9f7d104365858254b5e29ed97076a477044338bdac8",
    },
    "785671": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "c465d9318bd5509dde2ce84c3ea9941444f90f6d262d02fd02707d5befff8964",
    },
    "785675": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "baca9612ae99e8f775ae0d7c621df75c088f48c40d360d93a8d809be744b8c9f",
    },
    "788824": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "18fa73d4e41d13f10dcf096a320346baee3a69773534558ea06f13d1fc7bcdb7",
    },
    "824002": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "e08ef8a2e8dfaddf92a0aad7edd0f32be65dd91099ab2f2bff20b45856e6bfa5",
    },
    "857993": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "f021dc4aa67f41c3759bcd0950dc52c7065eed27ca6b5a698c9d1e94a9de24e9",
    },
    "987998": {
        "width": 1720,
        "height": 1040,
        "raw_scanline_sha256": "bbb870ab2ffccecf98f36c411acd41640f24f818e0425f5d7d0bc785e8f3fd56",
    },
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_provenance(doc: dict, *, input_dataset_id_prefix: str) -> None:
    assert doc["produced_at"]
    assert doc["git_sha"]
    assert str(doc["input_dataset_id"]).startswith(input_dataset_id_prefix)


def _final_review_png_fingerprint(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    assert data.startswith(PNG_SIGNATURE)
    offset = len(PNG_SIGNATURE)
    width: int | None = None
    height: int | None = None
    idat_chunks: list[bytes] = []
    while offset < len(data):
        chunk_length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        payload_start = offset + 8
        payload_end = payload_start + chunk_length
        payload = data[payload_start:payload_end]
        offset = payload_end + 4
        if chunk_type == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        elif chunk_type == b"IDAT":
            idat_chunks.append(payload)
        elif chunk_type == b"IEND":
            break
    assert width is not None
    assert height is not None
    raw_scanlines = zlib.decompress(b"".join(idat_chunks))
    digest = hashlib.sha256()
    digest.update(f"{width}x{height}\n".encode("ascii"))
    digest.update(raw_scanlines)
    return {
        "width": width,
        "height": height,
        "raw_scanline_sha256": digest.hexdigest(),
    }


def _assert_step6_guard_fields_enter_step7(doc: dict) -> None:
    guard_audit = doc.get("step6_guard_audit")
    assert isinstance(guard_audit, dict)
    for field in ANCHOR2_30CASE_STEP6_GUARD_FIELDS_20260501:
        assert field in doc
        assert field in guard_audit
    for field in [
        "surface_scenario_type",
        "section_reference_source",
        "surface_generation_mode",
    ]:
        assert doc[field]
        assert guard_audit[field] == doc[field]


def _assert_no_main_evidence_has_no_virtual_reference_point(step4_doc: dict) -> None:
    for unit in step4_doc["event_units"]:
        if unit.get("has_main_evidence") is False or unit.get("main_evidence_type") == "none":
            assert unit["reference_point_present"] is False
            assert unit.get("reference_point_source") in {None, "", "none"}


@pytest.mark.smoke
def test_t04_step7_batch_publishes_accepted_and_rejected_layers(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    _build_synthetic_case_package(case_root / "1001")
    _build_multi_event_case_package(case_root / "2002")

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_step7",
        run_id="synthetic_t04_step7_publish",
    )

    accepted_layer = run_root / "divmerge_virtual_anchor_surface.gpkg"
    rejected_layer = run_root / "divmerge_virtual_anchor_surface_rejected.geojson"
    summary_csv = run_root / "divmerge_virtual_anchor_surface_summary.csv"
    summary_json = run_root / "divmerge_virtual_anchor_surface_summary.json"
    audit_layer = run_root / "divmerge_virtual_anchor_surface_audit.gpkg"
    rejected_index_csv = run_root / "step7_rejected_index.csv"
    rejected_index_json = run_root / "step7_rejected_index.json"
    consistency_report = run_root / "step7_consistency_report.json"
    final_review_1001 = run_root / "cases" / "1001" / "final_review.png"
    final_review_2002 = run_root / "cases" / "2002" / "final_review.png"
    flat_review_1001 = run_root / "step4_review_flat" / "case__1001__final_review.png"
    flat_review_2002 = run_root / "step4_review_flat" / "case__2002__final_review.png"

    assert accepted_layer.is_file()
    assert rejected_layer.is_file()
    assert summary_csv.is_file()
    assert summary_json.is_file()
    assert audit_layer.is_file()
    assert rejected_index_csv.is_file()
    assert rejected_index_json.is_file()
    assert consistency_report.is_file()
    assert final_review_1001.is_file()
    assert final_review_2002.is_file()
    assert flat_review_1001.is_file()
    assert flat_review_2002.is_file()

    status_1001 = json.loads((run_root / "cases" / "1001" / "step7_status.json").read_text(encoding="utf-8"))
    status_2002 = json.loads((run_root / "cases" / "2002" / "step7_status.json").read_text(encoding="utf-8"))
    assert status_1001["final_state"] == "accepted"
    assert status_1001["published_layer_target"] == "accepted_layer"
    assert status_2002["final_state"] == "rejected"
    assert status_2002["published_layer_target"] == "rejected_index"

    summary_payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary_payload["accepted_count"] == 1
    assert summary_payload["rejected_count"] == 1
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}
    assert rows_by_case["1001"]["publish_target"] == "accepted_layer"
    assert rows_by_case["2002"]["publish_target"] == "rejected_index"
    assert rows_by_case["1001"]["review_png_path"] == str(flat_review_1001)
    assert rows_by_case["2002"]["review_png_path"] == str(flat_review_2002)

    rejected_index_payload = json.loads(rejected_index_json.read_text(encoding="utf-8"))
    assert rejected_index_payload["row_count"] == 1
    assert rejected_index_payload["rows"][0]["case_id"] == "2002"
    assert rejected_index_payload["rows"][0]["review_png_path"] == str(flat_review_2002)

    consistency_payload = json.loads(consistency_report.read_text(encoding="utf-8"))
    assert consistency_payload["passed"] is True
    assert consistency_payload["accepted_count"] == 1
    assert consistency_payload["rejected_count"] == 1
    assert consistency_payload["rejected_index_row_count"] == 1
    assert consistency_payload["review_png_present_count"] == 2

    fiona = pytest.importorskip("fiona")
    with fiona.open(accepted_layer) as src:
        accepted_rows = list(src)
    assert len(accepted_rows) == 1
    assert accepted_rows[0]["properties"]["case_id"] == "1001"
    assert accepted_rows[0]["properties"]["final_state"] == "accepted"

    with fiona.open(audit_layer) as src:
        audit_rows = list(src)
    assert {row["properties"]["case_id"] for row in audit_rows} == {"1001", "2002"}

    rejected_payload = json.loads(rejected_layer.read_text(encoding="utf-8"))
    rejected_rows = rejected_payload["features"]
    assert len(rejected_rows) == 1
    assert rejected_rows[0]["properties"]["case_id"] == "2002"
    assert rejected_rows[0]["properties"]["final_state"] == "rejected"


@pytest.mark.smoke
def test_t04_step7_rejected_case_writes_reject_stub_without_final_review_state(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    _build_multi_event_case_package(case_root / "2002")

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_step7_rejected",
        run_id="synthetic_t04_step7_rejected",
    )

    case_dir = run_root / "cases" / "2002"
    step7_status = json.loads((case_dir / "step7_status.json").read_text(encoding="utf-8"))
    step7_audit = json.loads((case_dir / "step7_audit.json").read_text(encoding="utf-8"))
    reject_index = json.loads((case_dir / "reject_index.json").read_text(encoding="utf-8"))

    assert step7_status["final_state"] == "rejected"
    assert "review" not in step7_status["final_state"]
    assert step7_status["published_layer_target"] == "rejected_index"
    assert "multi_component_result" in set(step7_status["reject_reasons"])
    assert step7_audit["publish_target"] == "rejected_index"
    assert step7_audit["final_publish_outputs"]["case_final_review_png_path"] == str(case_dir / "final_review.png")
    assert reject_index["final_state"] == "rejected"
    assert (case_dir / "reject_stub.geojson").is_file()
    assert (case_dir / "final_review.png").is_file()


@pytest.mark.smoke
def test_anchor2_step7_freezes_857993_as_expected_rejected(tmp_path: Path) -> None:
    if not REAL_ANCHOR_2_ROOT.is_dir():
        pytest.skip(f"missing real Anchor_2 case root: {REAL_ANCHOR_2_ROOT}")

    anchor2_case_ids = [
        "760213",
        "785671",
        "785675",
        "857993",
        "987998",
        "17943587",
        "30434673",
        "73462878",
    ]
    missing_cases = [
        case_id for case_id in anchor2_case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=anchor2_case_ids,
        out_root=tmp_path / "anchor2_step7",
        run_id="anchor2_expected_857993_rejected",
    )

    summary_payload = json.loads(
        (run_root / "divmerge_virtual_anchor_surface_summary.json").read_text(encoding="utf-8")
    )
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}

    assert summary_payload["accepted_count"] == 7
    assert summary_payload["rejected_count"] == 1
    assert rows_by_case["857993"]["final_state"] == "rejected"
    assert rows_by_case["857993"]["publish_target"] == "rejected_index"
    assert {row["final_state"] for row in summary_payload["rows"]} <= {"accepted", "rejected"}

    rejected_status = json.loads(
        (run_root / "cases" / "857993" / "step7_status.json").read_text(encoding="utf-8")
    )
    assert rejected_status["final_state"] == "rejected"
    assert "review" not in rejected_status["final_state"]
    assert (run_root / "cases" / "857993" / "reject_stub.geojson").is_file()

    step5_760213 = json.loads(
        (run_root / "cases" / "760213" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_760213 = step5_760213["unit_results"][0]
    assert unit_760213["surface_fill_mode"] == "junction_full_road_fill"
    assert unit_760213["surface_fill_axis_half_width_m"] == pytest.approx(20.0, abs=1e-6)
    assert unit_760213["single_component_surface_seed"] is False
    step6_760213 = json.loads(
        (run_root / "cases" / "760213" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step6_760213["component_count"] == 1
    assert step6_760213["review_reasons"] == []


@pytest.mark.smoke
def test_anchor2_added_cases_recover_698389_road_surface_without_wrong_rcsd(tmp_path: Path) -> None:
    anchor2_case_ids = [
        "698380",
        "698389",
        "699870",
        "857993",
    ]
    missing_cases = [
        case_id for case_id in anchor2_case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=anchor2_case_ids,
        out_root=tmp_path / "anchor2_added_cases_step7",
        run_id="anchor2_added_cases_698380_698389",
    )

    summary_payload = json.loads(
        (run_root / "divmerge_virtual_anchor_surface_summary.json").read_text(encoding="utf-8")
    )
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}

    assert summary_payload["accepted_count"] == 3
    assert summary_payload["rejected_count"] == 1
    assert rows_by_case["698380"]["final_state"] == "accepted"
    assert rows_by_case["698389"]["final_state"] == "accepted"
    assert rows_by_case["699870"]["final_state"] == "accepted"
    assert rows_by_case["857993"]["final_state"] == "rejected"
    assert {row["final_state"] for row in summary_payload["rows"]} <= {"accepted", "rejected"}

    step4_698380 = json.loads(
        (run_root / "cases" / "698380" / "step4_event_interpretation.json").read_text(encoding="utf-8")
    )
    unit_698380 = step4_698380["event_units"][0]
    assert unit_698380["surface_scenario_type"] == "main_evidence_with_rcsd_junction"
    assert unit_698380["required_rcsd_node"] == "5396472305684358"
    assert set(unit_698380["selected_rcsdnode_ids"]) == {
        "5396472305684357",
        "5396472305684358",
    }
    assert set(unit_698380["selected_rcsdroad_ids"]) == {
        "5396472305684664",
        "5396472305684674",
        "5396472305684679",
    }
    assert "5396472305684588" not in set(unit_698380["selected_rcsdnode_ids"])
    assert "5396482943156286" not in set(unit_698380["selected_rcsdroad_ids"])
    assert "5396482943156330" not in set(unit_698380["selected_rcsdroad_ids"])
    audit_698380 = unit_698380["positive_rcsd_audit"]
    assert audit_698380["aggregated_rcsd_unit_ids"] == ["event_unit_01:node:5396472305684358"]
    selected_aggregate_698380 = next(
        entry
        for entry in audit_698380["aggregated_rcsd_units"]
        if entry["unit_id"] == audit_698380["aggregated_rcsd_unit_id"]
    )
    assert selected_aggregate_698380["semantic_group_ids"] == ["5396472305684358"]

    surface_binding_payload = json.loads(
        (run_root / "step4_road_surface_fork_binding.json").read_text(encoding="utf-8")
    )
    surface_binding_by_case = {record["case_id"]: record for record in surface_binding_payload["records"]}
    assert surface_binding_by_case["698389"]["action"] == "divstrip_primary_over_wide_road_surface_fork"
    assert surface_binding_by_case["698389"]["post_state"] == "found"
    assert surface_binding_by_case["698389"]["required_rcsd_node"] == "5396318492905216"
    assert surface_binding_by_case["698389"]["positive_rcsd_consistency_level"] == "A"
    suppressed_binding_698389 = surface_binding_by_case["698389"]["detail"]["suppressed_road_surface_fork_binding"]
    assert suppressed_binding_698389["action"] == "bound_forward_rcsd_to_road_surface_fork"
    assert suppressed_binding_698389["required_rcsd_node"] == "5396318492905216"

    reverse_payload = json.loads((run_root / "step4_rcsd_anchored_reverse.json").read_text(encoding="utf-8"))
    reverse_by_case = {record["case_id"]: record for record in reverse_payload["records"]}
    assert reverse_by_case["698389"]["skip_reason"] == "skipped_selected_evidence_present"
    assert reverse_by_case["698389"]["post_state"] == "found"
    reverse_699870 = [
        record for record in reverse_payload["records"] if record["case_id"] == "699870"
    ][0]
    assert reverse_699870["post_reverse_conflict_recheck"] == "passed"
    assert reverse_699870["post_state"] == "found"
    assert reverse_699870["reference_point_mode"] == "selected_divstrip_branch_tip"
    assert reverse_699870["reference_point_axis_s"] == pytest.approx(0.0, abs=1e-3)

    step5_699870 = json.loads(
        (run_root / "cases" / "699870" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_699870 = step5_699870["unit_results"][0]
    assert unit_699870["surface_fill_mode"] == "junction_full_road_fill"
    assert unit_699870["surface_fill_axis_half_width_m"] == pytest.approx(20.0, abs=1e-6)
    assert unit_699870["junction_full_road_fill_domain"]["present"] is True
    assert (
        unit_699870["junction_full_road_fill_domain"]["area_m2"]
        > unit_699870["terminal_support_corridor_geometry"]["area_m2"] * 2.0
    )

    step4_698389 = json.loads(
        (run_root / "cases" / "698389" / "step4_event_interpretation.json").read_text(encoding="utf-8")
    )
    unit_698389 = step4_698389["event_units"][0]
    assert unit_698389["selected_evidence_state"] == "found"
    assert unit_698389["evidence_source"] == "reverse_tip_retry"
    assert unit_698389["position_source"] == "divstrip_ref"
    assert unit_698389["main_evidence_type"] == "divstrip"
    assert unit_698389["selected_evidence"]["candidate_id"] == "event_unit_01:divstrip:1:01"
    assert unit_698389["selected_evidence"]["candidate_scope"] == "divstrip_component"
    assert unit_698389["selected_evidence"]["upper_evidence_kind"] == "divstrip"
    assert unit_698389["selected_evidence"]["node_fallback_only"] is False
    assert unit_698389["positive_rcsd_present"] is True
    assert unit_698389["positive_rcsd_consistency_level"] == "A"
    assert unit_698389["required_rcsd_node"] == "5396318492905216"
    assert unit_698389["required_rcsd_node_source"] == "road_surface_fork_forward_rcsd"
    assert unit_698389["rcsd_selection_mode"] == "road_surface_fork_forward_rcsd_binding"
    assert "divstrip_primary_over_wide_road_surface_fork" in set(unit_698389["review_reasons"])

    fiona = pytest.importorskip("fiona")
    from shapely.geometry import shape

    with fiona.open(run_root / "cases" / "698389" / "step4_event_evidence.gpkg") as src:
        evidence_features = list(src)
    fact_reference = next(
        shape(feature["geometry"])
        for feature in evidence_features
        if feature["properties"]["geometry_role"] == "fact_reference_point"
    )
    selected_surface = next(
        shape(feature["geometry"])
        for feature in evidence_features
        if feature["properties"]["geometry_role"] == "selected_evidence_region_geometry"
    )
    assert fact_reference.x == pytest.approx(12724336.311, abs=1e-3)
    assert fact_reference.y == pytest.approx(2605452.472, abs=1e-3)
    assert selected_surface.area == pytest.approx(899.887, abs=1e-3)

    step5_698389 = json.loads(
        (run_root / "cases" / "698389" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_698389_step5 = step5_698389["unit_results"][0]
    assert unit_698389_step5["surface_fill_mode"] == "junction_full_road_fill"
    assert unit_698389_step5["surface_fill_axis_half_width_m"] == pytest.approx(20.0, abs=1e-6)
    assert unit_698389_step5["single_component_surface_seed"] is False
    assert unit_698389_step5["must_cover_components"]["required_rcsd_node_patch_geometry"] is True
    assert unit_698389_step5["must_cover_components"]["junction_full_road_fill_domain"] is True
    step6_698389 = json.loads(
        (run_root / "cases" / "698389" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step6_698389["component_count"] == 1
    assert step6_698389["review_reasons"] == []

    assert unit_698389["selected_evidence"]["primary_eligible"] is True


@pytest.mark.smoke
def test_anchor2_724067_road_surface_fork_primary_evidence_keeps_known_rejects(tmp_path: Path) -> None:
    anchor2_case_ids = [
        "699870",
        "724067",
        "760598",
        "760936",
        "760984",
        "788824",
        "857993",
    ]
    missing_cases = [
        case_id for case_id in anchor2_case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=anchor2_case_ids,
        out_root=tmp_path / "anchor2_724067_road_surface_fork",
        run_id="anchor2_724067_road_surface_fork",
    )

    summary_payload = json.loads(
        (run_root / "divmerge_virtual_anchor_surface_summary.json").read_text(encoding="utf-8")
    )
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}
    assert summary_payload["accepted_count"] == 4
    assert summary_payload["rejected_count"] == 3
    assert rows_by_case["699870"]["final_state"] == "accepted"
    assert rows_by_case["724067"]["final_state"] == "accepted"
    assert rows_by_case["760598"]["final_state"] == "rejected"
    assert rows_by_case["760936"]["final_state"] == "rejected"
    assert rows_by_case["760984"]["final_state"] == "accepted"
    assert rows_by_case["788824"]["final_state"] == "accepted"
    assert rows_by_case["857993"]["final_state"] == "rejected"
    assert {row["final_state"] for row in summary_payload["rows"]} <= {"accepted", "rejected"}

    reverse_payload = json.loads((run_root / "step4_rcsd_anchored_reverse.json").read_text(encoding="utf-8"))
    reverse_by_case = {record["case_id"]: record for record in reverse_payload["records"]}
    assert reverse_by_case["699870"]["post_reverse_conflict_recheck"] == "passed"
    assert reverse_by_case["699870"]["post_state"] == "found"
    assert reverse_by_case["699870"]["reference_point_mode"] == "selected_divstrip_branch_tip"
    assert reverse_by_case["699870"]["reference_point_axis_s"] == pytest.approx(33.72, abs=1e-3)
    step5_699870 = json.loads(
        (run_root / "cases" / "699870" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_699870 = step5_699870["unit_results"][0]
    assert unit_699870["surface_fill_mode"] == "junction_full_road_fill"
    assert unit_699870["surface_fill_axis_half_width_m"] == pytest.approx(20.0, abs=1e-6)
    surface_binding_payload = json.loads(
        (run_root / "step4_road_surface_fork_binding.json").read_text(encoding="utf-8")
    )
    surface_binding_by_case = {record["case_id"]: record for record in surface_binding_payload["records"]}
    assert surface_binding_by_case["724067"]["action"] == "bound_forward_rcsd_to_road_surface_fork"
    assert surface_binding_by_case["724067"]["required_rcsd_node"] == "5395137610783733"
    reference_detail_724067 = surface_binding_by_case["724067"]["detail"]["reference_point"]
    assert reference_detail_724067["road_surface_fork_reference_point_mode"] == "road_surface_fork_boundary_apex"
    assert reference_detail_724067["boundary_pair_road_ids"] == ["611600880", "18386573"]
    assert reference_detail_724067["road_surface_fork_reference_distance_m"] == pytest.approx(87.922, abs=1e-3)
    assert reference_detail_724067["road_surface_fork_reference_sample_s_m"] == pytest.approx(87.028, abs=1e-3)
    assert reference_detail_724067["road_surface_fork_branch_separation_m"] == pytest.approx(13.717, abs=1e-3)
    assert reference_detail_724067["road_surface_fork_apex_midline_distance_m"] == pytest.approx(1.397, abs=1e-3)
    assert reference_detail_724067["road_surface_fork_apex_transverse_alignment"] == pytest.approx(0.954, abs=1e-3)
    assert reference_detail_724067["road_surface_fork_apex_segment_index"] == 61
    assert surface_binding_by_case["760598"]["action"] == "cleared_unbound_road_surface_fork"
    assert surface_binding_by_case["760598"]["post_state"] == "none"
    assert surface_binding_by_case["760598"]["required_rcsd_node"] is None
    assert surface_binding_by_case["760984"]["action"] == "bound_selected_surface_to_rcsd_junction_window"
    assert surface_binding_by_case["760984"]["required_rcsd_node"] == "5384392508834203"
    assert surface_binding_by_case["788824"]["action"] == "bound_selected_surface_to_rcsd_junction_window"
    assert surface_binding_by_case["788824"]["required_rcsd_node"] == "5395664851308727"
    assert reverse_by_case["724067"]["skip_reason"] == "skipped_selected_evidence_present"
    assert reverse_by_case["724067"]["post_state"] == "found"
    assert reverse_by_case["724067"]["mother_candidate_id"] is None

    case_dir = run_root / "cases" / "724067"
    step4_status = json.loads((case_dir / "step4_event_interpretation.json").read_text(encoding="utf-8"))
    step4_unit = step4_status["event_units"][0]
    selected_evidence = step4_unit["selected_evidence"]
    assert step4_unit["evidence_source"] == "road_surface_fork"
    assert step4_unit["position_source"] == "road_surface_fork"
    assert step4_unit["event_chosen_s_m"] == 0.0
    assert step4_unit["required_rcsd_node"] == "5395137610783733"
    assert step4_unit["positive_rcsd_present"] is True
    assert step4_unit["positive_rcsd_consistency_level"] == "A"
    assert step4_unit["rcsd_selection_mode"] == "road_surface_fork_forward_rcsd_binding"
    assert selected_evidence["candidate_id"] == "event_unit_01:structure:road_surface_fork:01"
    assert selected_evidence["candidate_scope"] == "road_surface_fork"
    assert selected_evidence["primary_eligible"] is True
    assert selected_evidence["node_fallback_only"] is False
    road_surface_fork_area = float(step4_unit["pair_local_summary"]["pair_local_region_area_m2"])

    step5_status = json.loads((case_dir / "step5_status.json").read_text(encoding="utf-8"))
    unit_status = step5_status["unit_results"][0]
    assert unit_status["surface_fill_mode"] == "junction_full_road_fill"
    assert unit_status["surface_fill_axis_half_width_m"] == pytest.approx(20.0, abs=1e-6)
    assert unit_status["single_component_surface_seed"] is False
    assert step5_status["case_must_cover_domain"]["present"] is True
    assert unit_status["must_cover_components"]["localized_evidence_core_geometry"] is True
    assert unit_status["must_cover_components"]["required_rcsd_node_patch_geometry"] is True
    assert unit_status["must_cover_components"]["junction_full_road_fill_domain"] is True
    assert unit_status["must_cover_components"]["fallback_support_strip_geometry"] is False
    assert unit_status["junction_full_road_fill_domain"]["area_m2"] < road_surface_fork_area * 0.7
    assert unit_status["junction_full_road_fill_domain"]["area_m2"] == pytest.approx(1695.840, abs=1e-3)
    assert (
        unit_status["junction_full_road_fill_domain"]["area_m2"]
        > unit_status["terminal_support_corridor_geometry"]["area_m2"] * 1.1
    )

    step6_status = json.loads((case_dir / "step6_status.json").read_text(encoding="utf-8"))
    assert step6_status["assembly_state"] == "assembled"
    assert step6_status["component_count"] == 1
    assert step6_status["hard_must_cover_ok"] is True
    assert (
        step6_status["final_case_polygon"]["area_m2"]
        >= unit_status["junction_full_road_fill_domain"]["area_m2"] * 0.9
    )
    assert step6_status["final_case_polygon"]["area_m2"] < road_surface_fork_area * 0.75
    assert step6_status["final_case_polygon"]["area_m2"] == pytest.approx(1666.546, abs=1e-3)
    assert (
        step6_status["final_case_polygon"]["area_m2"]
        > unit_status["terminal_support_corridor_geometry"]["area_m2"] * 1.1
    )
    geopandas = pytest.importorskip("geopandas")
    step4_geometries = geopandas.read_file(case_dir / "step4_event_evidence.gpkg")
    final_geometries = geopandas.read_file(case_dir / "final_case_polygon.gpkg")
    geometry_by_role = {row.geometry_role: row.geometry for _, row in step4_geometries.iterrows()}
    reference_point = geometry_by_role["fact_reference_point"]
    rcsd_node_point = geometry_by_role["required_rcsd_node_geometry"]
    throat_core_geometry = geometry_by_role["pair_local_throat_core_geometry"]
    selected_candidate_region_geometry = geometry_by_role["selected_candidate_region_geometry"]
    final_geometry = final_geometries.geometry.iloc[0]
    assert reference_point.x == pytest.approx(12737746.898, abs=1e-3)
    assert reference_point.y == pytest.approx(2586260.366, abs=1e-3)
    assert selected_candidate_region_geometry.buffer(1e-6).covers(reference_point)
    assert reference_point.distance(selected_candidate_region_geometry.boundary) <= 1e-6
    assert not throat_core_geometry.buffer(1e-6).covers(reference_point)
    assert throat_core_geometry.representative_point().distance(reference_point) > 80.0
    axis_dx = float(rcsd_node_point.x) - float(reference_point.x)
    axis_dy = float(rcsd_node_point.y) - float(reference_point.y)
    axis_length = (axis_dx * axis_dx + axis_dy * axis_dy) ** 0.5
    unit_x = axis_dx / axis_length
    unit_y = axis_dy / axis_length

    def signed_axis_range(geometry: object) -> tuple[float, float]:
        coords = []
        if geometry.geom_type == "Polygon":
            coords = list(geometry.exterior.coords)
        elif geometry.geom_type == "MultiPolygon":
            coords = [coord for part in geometry.geoms for coord in part.exterior.coords]
        values = [
            ((float(x) - float(reference_point.x)) * unit_x)
            + ((float(y) - float(reference_point.y)) * unit_y)
            for x, y, *_ in coords
        ]
        return min(values), max(values)

    min_axis_s, max_axis_s = signed_axis_range(final_geometry)
    assert min_axis_s >= -22.0
    assert max_axis_s <= axis_length + 22.0

    for accepted_surface_case in ("760984", "788824"):
        step4_surface = json.loads(
            (run_root / "cases" / accepted_surface_case / "step4_event_interpretation.json").read_text(
                encoding="utf-8"
            )
        )
        unit_surface = step4_surface["event_units"][0]
        assert unit_surface["selected_evidence_state"] == "found"
        assert unit_surface["evidence_source"] == "rcsd_junction_window"
        assert unit_surface["required_rcsd_node"]
        assert unit_surface["positive_rcsd_present"] is True
        assert unit_surface["rcsd_selection_mode"] == "rcsd_junction_window"
        assert "rcsd_junction_window_used" in "|".join(unit_surface["review_reasons"])

        step5_surface = json.loads(
            (run_root / "cases" / accepted_surface_case / "step5_status.json").read_text(
                encoding="utf-8"
            )
        )
        unit_step5_surface = step5_surface["unit_results"][0]
        assert unit_step5_surface["surface_fill_mode"] == "junction_window"
        assert unit_step5_surface["junction_full_road_fill_domain"]["present"] is True
        assert unit_step5_surface["required_rcsd_node_patch_geometry"]["present"] is True

    status_760936 = json.loads(
        (run_root / "cases" / "760936" / "step7_status.json").read_text(encoding="utf-8")
    )
    status_760598 = json.loads(
        (run_root / "cases" / "760598" / "step7_status.json").read_text(encoding="utf-8")
    )
    status_857993 = json.loads(
        (run_root / "cases" / "857993" / "step7_status.json").read_text(encoding="utf-8")
    )
    assert status_760598["final_state"] == "rejected"
    assert "assembly_failed" in set(status_760598["reject_reasons"])
    assert status_760936["final_state"] == "rejected"
    assert "multi_component_result" in set(status_760936["reject_reasons"])
    assert status_857993["final_state"] == "rejected"


@pytest.mark.smoke
def test_anchor2_rcsdnode_pair_local_drivezone_filter_keeps_cross_patch_cases_publishable(tmp_path: Path) -> None:
    anchor2_case_ids = [
        "723276",
        "758784",
    ]
    missing_cases = [
        case_id for case_id in anchor2_case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=anchor2_case_ids,
        out_root=tmp_path / "anchor2_cross_patch_rcsdnode_filter",
        run_id="anchor2_cross_patch_rcsdnode_filter",
    )

    batch_summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    summary_payload = json.loads(
        (run_root / "divmerge_virtual_anchor_surface_summary.json").read_text(encoding="utf-8")
    )
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}

    assert batch_summary["failed_case_ids"] == []
    assert summary_payload["row_count"] == 2
    assert set(rows_by_case) == set(anchor2_case_ids)
    assert {row["final_state"] for row in summary_payload["rows"]} <= {"accepted", "rejected"}


@pytest.mark.smoke
def test_anchor2_new_structure_only_road_surface_forks_keep_760598_rejected(tmp_path: Path) -> None:
    anchor2_case_ids = [
        "706629",
        "724081",
        "824002",
        "760598",
    ]
    missing_cases = [
        case_id for case_id in anchor2_case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=anchor2_case_ids,
        out_root=tmp_path / "anchor2_new_structure_only_surface_forks",
        run_id="anchor2_new_structure_only_surface_forks",
    )

    summary_payload = json.loads(
        (run_root / "divmerge_virtual_anchor_surface_summary.json").read_text(encoding="utf-8")
    )
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}

    assert rows_by_case["706629"]["final_state"] == "accepted"
    assert rows_by_case["724081"]["final_state"] == "accepted"
    assert rows_by_case["824002"]["final_state"] == "accepted"
    assert rows_by_case["760598"]["final_state"] == "rejected"

    step5_824002 = json.loads(
        (run_root / "cases" / "824002" / "step5_status.json").read_text(encoding="utf-8")
    )
    step6_824002 = json.loads(
        (run_root / "cases" / "824002" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step5_824002["case_bridge_zone_geometry"]["present"] is True
    assert step5_824002["case_bridge_zone_geometry"]["area_m2"] == pytest.approx(656.616, abs=1e-3)
    assert step6_824002["assembly_state"] == "assembled"
    assert step6_824002["component_count"] == 1
    assert step6_824002["hole_count"] == 0
    assert step6_824002["hard_must_cover_ok"] is True
    assert step6_824002["final_case_polygon"]["area_m2"] == pytest.approx(2735.149, abs=1e-3)
    assert step6_824002["final_case_polygon"]["length_m"] == pytest.approx(333.511, abs=1e-3)

    geopandas = pytest.importorskip("geopandas")
    step5_domains_824002 = geopandas.read_file(run_root / "cases" / "824002" / "step5_domains.gpkg")
    final_824002 = geopandas.read_file(run_root / "cases" / "824002" / "final_case_polygon.gpkg").geometry.iloc[0]
    bridge_824002 = step5_domains_824002[
        (step5_domains_824002.event_unit_id == "")
        & (step5_domains_824002.component_role == "case_bridge_zone_geometry")
    ].geometry.iloc[0]
    assert bridge_824002.intersection(final_824002).area / bridge_824002.area > 0.97
    for unit_id in ("node_824002", "node_824003"):
        localized_core = step5_domains_824002[
            (step5_domains_824002.event_unit_id == unit_id)
            & (step5_domains_824002.component_role == "localized_evidence_core_geometry")
        ].geometry.iloc[0]
        assert localized_core.difference(final_824002.buffer(1e-6)).area <= 1e-6

    surface_binding_payload = json.loads(
        (run_root / "step4_road_surface_fork_binding.json").read_text(encoding="utf-8")
    )
    surface_binding_by_case = {record["case_id"]: record for record in surface_binding_payload["records"]}
    record_706629 = surface_binding_by_case["706629"]
    assert record_706629["action"] == "kept_swsd_junction_window_no_rcsd"
    assert record_706629["post_state"] == "found"
    assert record_706629["positive_rcsd_consistency_level"] == "C"

    step4_706629 = json.loads(
        (run_root / "cases" / "706629" / "step4_event_interpretation.json").read_text(
            encoding="utf-8"
        )
    )
    unit_706629 = step4_706629["event_units"][0]
    assert unit_706629["selected_evidence_state"] == "found"
    assert unit_706629["evidence_source"] == "swsd_junction_window"
    assert unit_706629["required_rcsd_node"] is None
    assert unit_706629["rcsd_selection_mode"] == "swsd_junction_window_no_rcsd"
    assert "swsd_junction_window_no_rcsd_used" in set(unit_706629["review_reasons"])

    step5_706629 = json.loads(
        (run_root / "cases" / "706629" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_step5_706629 = step5_706629["unit_results"][0]
    assert step5_706629["case_bridge_zone_geometry"]["present"] is False
    assert step5_706629["case_terminal_window_domain"]["present"] is False
    assert unit_step5_706629["surface_fill_mode"] == "junction_window"
    assert unit_step5_706629["single_component_surface_seed"] is False
    assert unit_step5_706629["junction_full_road_fill_domain"]["present"] is True
    assert unit_step5_706629["required_rcsd_node_patch_geometry"]["present"] is False

    step6_706629 = json.loads(
        (run_root / "cases" / "706629" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step6_706629["assembly_state"] == "assembled"
    assert step6_706629["component_count"] == 1
    assert step6_706629["hole_count"] == 0
    assert step6_706629["final_case_polygon"]["area_m2"] == pytest.approx(552.368, abs=1e-3)

    record_724081 = surface_binding_by_case["724081"]
    assert record_724081["action"] == "kept_structure_only_road_surface_fork"
    assert record_724081["post_state"] == "found"
    assert record_724081["positive_rcsd_consistency_level"] == "C"

    step4_724081 = json.loads(
        (run_root / "cases" / "724081" / "step4_event_interpretation.json").read_text(
            encoding="utf-8"
        )
    )
    unit_724081 = step4_724081["event_units"][0]
    assert unit_724081["selected_evidence_state"] == "found"
    assert unit_724081["evidence_source"] == "road_surface_fork"
    assert unit_724081["required_rcsd_node"] is None
    assert unit_724081["rcsd_selection_mode"] == "road_surface_fork_structure_only_no_rcsd"
    assert "road_surface_fork_structure_only_used" in set(unit_724081["review_reasons"])

    step5_724081 = json.loads(
        (run_root / "cases" / "724081" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_step5_724081 = step5_724081["unit_results"][0]
    assert step5_724081["case_bridge_zone_geometry"]["present"] is False
    assert step5_724081["case_terminal_window_domain"]["present"] is False
    assert unit_step5_724081["surface_fill_mode"] == "standard"
    assert unit_step5_724081["single_component_surface_seed"] is True
    assert unit_step5_724081["junction_full_road_fill_domain"]["present"] is False
    assert unit_step5_724081["required_rcsd_node_patch_geometry"]["present"] is False

    step6_724081 = json.loads(
        (run_root / "cases" / "724081" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step6_724081["assembly_state"] == "assembled"
    assert step6_724081["component_count"] == 1
    assert step6_724081["hole_count"] == 0
    assert step5_724081["case_must_cover_domain"]["area_m2"] == pytest.approx(116.738, abs=1e-3)
    assert step6_724081["final_case_polygon"]["area_m2"] == pytest.approx(353.828, abs=1e-3)
    assert step6_724081["final_case_polygon"]["length_m"] == pytest.approx(87.868, abs=1e-3)

    assert surface_binding_by_case["760598"]["action"] == "cleared_unbound_road_surface_fork"


@pytest.mark.smoke
def test_anchor2_full_20260426_baseline_gate(tmp_path: Path) -> None:
    missing_cases = [
        case_id
        for case_id in ANCHOR2_FULL_BASELINE_20260426
        if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=list(ANCHOR2_FULL_BASELINE_20260426),
        out_root=tmp_path / "anchor2_full_20260426_baseline",
        run_id="anchor2_full_20260426_baseline",
    )

    summary_payload = json.loads(
        (run_root / "divmerge_virtual_anchor_surface_summary.json").read_text(encoding="utf-8")
    )
    batch_summary = _load_json(run_root / "summary.json")
    preflight = _load_json(run_root / "preflight.json")
    consistency_payload = _load_json(run_root / "step7_consistency_report.json")
    rejected_index_payload = _load_json(run_root / "step7_rejected_index.json")
    nodes_audit_payload = _load_json(run_root / "nodes_anchor_update_audit.json")
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}
    states_by_case = {case_id: row["final_state"] for case_id, row in rows_by_case.items()}
    rejected_case_ids = {
        case_id
        for case_id, final_state in ANCHOR2_FULL_BASELINE_20260426.items()
        if final_state == "rejected"
    }

    _assert_provenance(preflight, input_dataset_id_prefix="case-package-stat-sha256:")
    _assert_provenance(batch_summary, input_dataset_id_prefix="case-package-stat-sha256:")
    _assert_provenance(summary_payload, input_dataset_id_prefix="case-package-stat-sha256:")
    _assert_provenance(consistency_payload, input_dataset_id_prefix="case-package-stat-sha256:")
    _assert_provenance(rejected_index_payload, input_dataset_id_prefix="case-package-stat-sha256:")
    _assert_provenance(nodes_audit_payload, input_dataset_id_prefix="case-package-stat-sha256:")
    assert batch_summary["failed_case_ids"] == []
    assert batch_summary["step7_accepted_count"] == 20
    assert batch_summary["step7_rejected_count"] == 3
    assert batch_summary["nodes_gpkg"] == str(run_root / "nodes.gpkg")
    assert batch_summary["nodes_total_update_count"] == 23
    assert batch_summary["nodes_updated_to_yes_count"] == 20
    assert batch_summary["nodes_updated_to_fail4_count"] == 3
    assert summary_payload["row_count"] == 23
    assert summary_payload["accepted_count"] == 20
    assert summary_payload["rejected_count"] == 3
    assert states_by_case == ANCHOR2_FULL_BASELINE_20260426
    assert {row["final_state"] for row in summary_payload["rows"]} <= {"accepted", "rejected"}
    assert rows_by_case["857993"]["publish_target"] == "rejected_index"
    assert rows_by_case["857993"]["final_state"] == "rejected"
    assert rows_by_case["699870"]["final_state"] == "accepted"

    assert consistency_payload["passed"] is True
    assert consistency_payload["total_case_count"] == 23
    assert consistency_payload["accepted_count"] == 20
    assert consistency_payload["rejected_count"] == 3
    assert consistency_payload["accepted_layer_feature_count"] == 20
    assert consistency_payload["rejected_layer_feature_count"] == 3
    assert consistency_payload["audit_layer_feature_count"] == 23
    assert consistency_payload["summary_row_count"] == 23
    assert consistency_payload["rejected_index_row_count"] == 3
    assert consistency_payload["review_png_present_count"] == 23
    assert consistency_payload["missing_review_png_case_ids"] == []
    assert consistency_payload["missing_reject_stub_case_ids"] == []
    assert consistency_payload["missing_reject_index_case_ids"] == []
    assert consistency_payload["missing_step7_status_case_ids"] == []
    assert consistency_payload["missing_step7_audit_case_ids"] == []
    assert consistency_payload["nodes_consistency_passed"] is True
    assert consistency_payload["nodes_total_update_count"] == 23
    assert consistency_payload["nodes_updated_to_yes_count"] == 20
    assert consistency_payload["nodes_updated_to_fail4_count"] == 3
    assert consistency_payload["nodes_mismatch_case_ids"] == []

    assert rejected_index_payload["row_count"] == 3
    assert {row["case_id"] for row in rejected_index_payload["rows"]} == rejected_case_ids
    assert (run_root / "nodes.gpkg").is_file()
    assert nodes_audit_payload["total_update_count"] == 23
    assert nodes_audit_payload["updated_to_yes_count"] == 20
    assert nodes_audit_payload["updated_to_fail4_count"] == 3
    nodes_audit_by_case = {row["case_id"]: row for row in nodes_audit_payload["rows"]}
    assert nodes_audit_by_case["857993"]["step7_state"] == "rejected"
    assert nodes_audit_by_case["857993"]["new_is_anchor"] == "fail4"
    assert nodes_audit_by_case["699870"]["step7_state"] == "accepted"
    assert nodes_audit_by_case["699870"]["new_is_anchor"] == "yes"

    fiona = pytest.importorskip("fiona")
    with fiona.open(run_root / "nodes.gpkg") as src:
        node_is_anchor_by_id = {
            str(row["properties"]["id"]): row["properties"]["is_anchor"]
            for row in src
        }
    for case_id, expected_state in ANCHOR2_FULL_BASELINE_20260426.items():
        expected_is_anchor = "yes" if expected_state == "accepted" else "fail4"
        audit_row = nodes_audit_by_case[case_id]
        assert audit_row["new_is_anchor"] == expected_is_anchor
        assert node_is_anchor_by_id[audit_row["representative_node_id"]] == expected_is_anchor

    for (
        case_id,
        expected_fingerprint,
    ) in ANCHOR2_FULL_FINAL_REVIEW_PNG_FINGERPRINTS_20260501_SURFACE_SCENARIO.items():
        png_path = Path(rows_by_case[case_id]["review_png_path"])
        assert png_path.is_file()
        assert _final_review_png_fingerprint(png_path) == expected_fingerprint

    for case_id, expected_state in ANCHOR2_FULL_BASELINE_20260426.items():
        case_dir = run_root / "cases" / case_id
        for filename in [
            "case_meta.json",
            "step1_status.json",
            "step3_status.json",
            "step3_audit.json",
            "step4_event_interpretation.json",
            "step4_audit.json",
            "step5_status.json",
            "step5_audit.json",
            "step6_status.json",
            "step6_audit.json",
            "step7_status.json",
            "step7_audit.json",
        ]:
            _assert_provenance(
                _load_json(case_dir / filename),
                input_dataset_id_prefix="case-input-stat-sha256:",
            )
        step7_status = _load_json(case_dir / "step7_status.json")
        assert step7_status["final_state"] == expected_state
        assert step7_status["final_state"] in {"accepted", "rejected"}
        assert Path(rows_by_case[case_id]["audit_path"]).is_file()
        if expected_state == "rejected":
            _assert_provenance(
                _load_json(case_dir / "reject_index.json"),
                input_dataset_id_prefix="case-input-stat-sha256:",
            )

    step4_505078921 = json.loads(
        (run_root / "cases" / "505078921" / "step4_event_interpretation.json").read_text(
            encoding="utf-8"
        )
    )
    units_505078921 = {unit["event_unit_id"]: unit for unit in step4_505078921["event_units"]}
    assert units_505078921["node_505078921"]["required_rcsd_node"] == "5385438602535104"
    assert units_505078921["node_510222629"]["required_rcsd_node"] == "5385438602535122"
    assert units_505078921["node_510222629__pair_02"]["evidence_source"] == "road_surface_fork"
    assert units_505078921["node_510222629__pair_02"]["required_rcsd_node"] is None
    assert (
        units_505078921["node_510222629__pair_02"]["rcsd_selection_mode"]
        == "road_surface_fork_partial_rcsd_support_only"
    )

    step7_505078921 = json.loads(
        (run_root / "cases" / "505078921" / "step7_status.json").read_text(encoding="utf-8")
    )
    assert step7_505078921["final_state"] == "accepted"

    step6_505078921 = json.loads(
        (run_root / "cases" / "505078921" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step6_505078921["component_count"] == 1
    assert step6_505078921["hole_count"] == 0

    step4_706629 = json.loads(
        (run_root / "cases" / "706629" / "step4_event_interpretation.json").read_text(
            encoding="utf-8"
        )
    )
    assert step4_706629["event_units"][0]["evidence_source"] == "swsd_junction_window"

    for case_id, expected_node in {
        "760984": "5384392508834203",
        "788824": "5395664851308727",
    }.items():
        step4_doc = json.loads(
            (run_root / "cases" / case_id / "step4_event_interpretation.json").read_text(
                encoding="utf-8"
            )
        )
        unit = step4_doc["event_units"][0]
        assert unit["evidence_source"] == "rcsd_junction_window"
        assert unit["required_rcsd_node"] == expected_node


@pytest.mark.smoke
def test_anchor2_30case_surface_scenario_baseline_gate(tmp_path: Path) -> None:
    missing_cases = [
        case_id
        for case_id in ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501
        if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=list(ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501),
        out_root=tmp_path / "anchor2_30case_surface_scenario_baseline",
        run_id="anchor2_30case_surface_scenario_baseline",
    )

    summary_payload = _load_json(run_root / "divmerge_virtual_anchor_surface_summary.json")
    batch_summary = _load_json(run_root / "summary.json")
    preflight = _load_json(run_root / "preflight.json")
    consistency_payload = _load_json(run_root / "step7_consistency_report.json")
    rejected_index_payload = _load_json(run_root / "step7_rejected_index.json")
    nodes_audit_payload = _load_json(run_root / "nodes_anchor_update_audit.json")
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}
    states_by_case = {case_id: row["final_state"] for case_id, row in rows_by_case.items()}
    rejected_case_ids = {
        case_id
        for case_id, final_state in ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501.items()
        if final_state == "rejected"
    }

    _assert_provenance(preflight, input_dataset_id_prefix="case-package-stat-sha256:")
    _assert_provenance(batch_summary, input_dataset_id_prefix="case-package-stat-sha256:")
    _assert_provenance(summary_payload, input_dataset_id_prefix="case-package-stat-sha256:")
    _assert_provenance(consistency_payload, input_dataset_id_prefix="case-package-stat-sha256:")
    _assert_provenance(rejected_index_payload, input_dataset_id_prefix="case-package-stat-sha256:")
    _assert_provenance(nodes_audit_payload, input_dataset_id_prefix="case-package-stat-sha256:")

    assert batch_summary["failed_case_ids"] == []
    assert batch_summary["step7_accepted_count"] == 26
    assert batch_summary["step7_rejected_count"] == 4
    assert batch_summary["nodes_gpkg"] == str(run_root / "nodes.gpkg")
    assert batch_summary["nodes_total_update_count"] == 30
    assert batch_summary["nodes_updated_to_yes_count"] == 26
    assert batch_summary["nodes_updated_to_fail4_count"] == 4

    assert summary_payload["row_count"] == 30
    assert summary_payload["accepted_count"] == 26
    assert summary_payload["rejected_count"] == 4
    assert states_by_case == ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501
    assert {row["final_state"] for row in summary_payload["rows"]} <= {"accepted", "rejected"}
    assert rejected_case_ids == ANCHOR2_30CASE_REJECTED_20260501
    assert {case_id for case_id, state in states_by_case.items() if state == "rejected"} == (
        ANCHOR2_30CASE_REJECTED_20260501
    )
    for case_id in ANCHOR2_30CASE_KEY_ACCEPTED_20260501:
        assert rows_by_case[case_id]["final_state"] == "accepted"
    for case_id in ANCHOR2_30CASE_REJECTED_20260501:
        assert rows_by_case[case_id]["final_state"] == "rejected"
        assert rows_by_case[case_id]["publish_target"] == "rejected_index"
    assert rows_by_case["607602562"]["final_state"] == "rejected"

    assert set(summary_payload["no_surface_reference_case_ids"]) == {"607602562", "760598"}
    assert consistency_payload["no_surface_reference_accepted_case_ids"] == []
    assert set(consistency_payload["no_surface_reference_case_ids"]) == {"607602562", "760598"}
    for row in summary_payload["rows"]:
        assert row["surface_scenario_type"]
        assert row["section_reference_source"]
        assert row["surface_generation_mode"]
        assert Path(row["review_png_path"]).is_file()
        if row["final_state"] == "accepted":
            assert row["surface_scenario_type"] != "no_surface_reference"
            assert row["no_surface_reference_guard"] is False

    assert consistency_payload["passed"] is True
    assert consistency_payload["total_case_count"] == 30
    assert consistency_payload["accepted_count"] == 26
    assert consistency_payload["rejected_count"] == 4
    assert consistency_payload["accepted_layer_feature_count"] == 26
    assert consistency_payload["rejected_layer_feature_count"] == 4
    assert consistency_payload["audit_layer_feature_count"] == 30
    assert consistency_payload["summary_row_count"] == 30
    assert consistency_payload["rejected_index_row_count"] == 4
    assert consistency_payload["review_png_present_count"] == 30
    assert consistency_payload["missing_review_png_case_ids"] == []
    assert consistency_payload["missing_reject_stub_case_ids"] == []
    assert consistency_payload["missing_reject_index_case_ids"] == []
    assert consistency_payload["missing_step7_status_case_ids"] == []
    assert consistency_payload["missing_step7_audit_case_ids"] == []
    assert consistency_payload["step7_allowed_final_states"] == ["accepted", "rejected"]
    assert consistency_payload["unexpected_final_state_values"] == []
    assert consistency_payload["step6_guard_fields_present"] is True
    assert consistency_payload["step6_guard_field_missing_case_ids"] == []
    assert consistency_payload["step7_guard_consistency_passed"] is True
    assert consistency_payload["step6_guard_failure_reject_mapping_passed"] is True
    assert consistency_payload["step6_guard_failure_reject_mapping_issues"] == []
    assert consistency_payload["nodes_consistency_passed"] is True
    assert consistency_payload["nodes_total_update_count"] == 30
    assert consistency_payload["nodes_updated_to_yes_count"] == 26
    assert consistency_payload["nodes_updated_to_fail4_count"] == 4
    assert consistency_payload["nodes_mismatch_case_ids"] == []
    assert consistency_payload["nodes_missing_case_ids"] == []

    assert rejected_index_payload["row_count"] == 4
    assert {row["case_id"] for row in rejected_index_payload["rows"]} == rejected_case_ids
    assert (run_root / "nodes.gpkg").is_file()
    assert nodes_audit_payload["total_update_count"] == 30
    assert nodes_audit_payload["updated_to_yes_count"] == 26
    assert nodes_audit_payload["updated_to_fail4_count"] == 4
    nodes_audit_by_case = {row["case_id"]: row for row in nodes_audit_payload["rows"]}
    assert nodes_audit_by_case["607602562"]["step7_state"] == "rejected"
    assert nodes_audit_by_case["607602562"]["new_is_anchor"] == "fail4"
    assert nodes_audit_by_case["699870"]["step7_state"] == "accepted"
    assert nodes_audit_by_case["699870"]["new_is_anchor"] == "yes"

    fiona = pytest.importorskip("fiona")
    with fiona.open(run_root / "nodes.gpkg") as src:
        node_is_anchor_by_id = {
            str(row["properties"]["id"]): row["properties"]["is_anchor"]
            for row in src
        }
    for case_id, expected_state in ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501.items():
        expected_is_anchor = "yes" if expected_state == "accepted" else "fail4"
        audit_row = nodes_audit_by_case[case_id]
        assert audit_row["new_is_anchor"] == expected_is_anchor
        assert node_is_anchor_by_id[audit_row["representative_node_id"]] == expected_is_anchor

    for case_id, expected_state in ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501.items():
        case_dir = run_root / "cases" / case_id
        for filename in [
            "case_meta.json",
            "step1_status.json",
            "step3_status.json",
            "step3_audit.json",
            "step4_event_interpretation.json",
            "step4_audit.json",
            "step5_status.json",
            "step5_audit.json",
            "step6_status.json",
            "step6_audit.json",
            "step7_status.json",
            "step7_audit.json",
        ]:
            _assert_provenance(
                _load_json(case_dir / filename),
                input_dataset_id_prefix="case-input-stat-sha256:",
            )
        step4_doc = _load_json(case_dir / "step4_event_interpretation.json")
        step7_status = _load_json(case_dir / "step7_status.json")
        step7_audit = _load_json(case_dir / "step7_audit.json")
        assert step7_status["final_state"] == expected_state
        assert step7_status["final_state"] in {"accepted", "rejected"}
        _assert_no_main_evidence_has_no_virtual_reference_point(step4_doc)
        _assert_step6_guard_fields_enter_step7(step7_status)
        _assert_step6_guard_fields_enter_step7(step7_audit)
        assert Path(rows_by_case[case_id]["audit_path"]).is_file()
        if expected_state == "rejected":
            _assert_provenance(
                _load_json(case_dir / "reject_index.json"),
                input_dataset_id_prefix="case-input-stat-sha256:",
            )


@pytest.mark.smoke
def test_anchor2_new6_user_audit_surface_scenario_gate(tmp_path: Path) -> None:
    missing_cases = [
        case_id
        for case_id in ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502
        if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=list(ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502),
        out_root=tmp_path / "anchor2_new6_user_audit_surface_scenario",
        run_id="anchor2_new6_user_audit_surface_scenario",
    )

    batch_summary = _load_json(run_root / "summary.json")
    summary_payload = _load_json(run_root / "divmerge_virtual_anchor_surface_summary.json")
    consistency_payload = _load_json(run_root / "step7_consistency_report.json")
    nodes_audit_payload = _load_json(run_root / "nodes_anchor_update_audit.json")
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}
    expected_case_ids = set(ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502)

    assert batch_summary["failed_case_ids"] == []
    assert batch_summary["step7_accepted_count"] == 6
    assert batch_summary["step7_rejected_count"] == 0
    assert summary_payload["row_count"] == 6
    assert summary_payload["accepted_count"] == 6
    assert summary_payload["rejected_count"] == 0
    assert set(rows_by_case) == expected_case_ids
    assert summary_payload["no_surface_reference_case_ids"] == []
    assert consistency_payload["passed"] is True
    assert consistency_payload["nodes_updated_to_yes_count"] == 6
    assert nodes_audit_payload["updated_to_yes_count"] == 6

    for case_id, expected in ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502.items():
        case_dir = run_root / "cases" / case_id
        row = rows_by_case[case_id]
        step4_doc = _load_json(case_dir / "step4_event_interpretation.json")
        step6_status = _load_json(case_dir / "step6_status.json")
        step7_status = _load_json(case_dir / "step7_status.json")
        unit = step4_doc["event_units"][0]

        assert row["final_state"] == "accepted"
        assert row["surface_scenario_type"] == expected["surface_scenario_type"]
        assert row["section_reference_source"] == expected["section_reference_source"]
        assert row["surface_generation_mode"] == expected["surface_generation_mode"]
        assert row["no_surface_reference_guard"] is False
        assert step7_status["final_state"] == "accepted"
        assert unit["evidence_source"] == expected["step4_evidence_source"]
        assert unit["main_evidence_type"] == expected["step4_main_evidence_type"]
        assert unit["surface_scenario_type"] == expected.get(
            "unit_surface_scenario_type",
            expected["surface_scenario_type"],
        )
        _assert_no_main_evidence_has_no_virtual_reference_point(step4_doc)

        assert step6_status["assembly_state"] == "assembled"
        assert step6_status["component_count"] == 1
        assert step6_status["post_cleanup_allowed_growth_ok"] is True
        assert step6_status["post_cleanup_forbidden_ok"] is True
        assert step6_status["post_cleanup_terminal_cut_ok"] is True
        assert step6_status["post_cleanup_lateral_limit_ok"] is True
        assert (case_dir / "final_case_polygon.gpkg").is_file()
        assert Path(row["review_png_path"]).is_file()

    assert rows_by_case["807908"]["surface_scenario_type"] == "main_evidence_with_rcsd_junction"
    step4_807908 = _load_json(run_root / "cases" / "807908" / "step4_event_interpretation.json")
    unit_807908 = step4_807908["event_units"][0]
    assert unit_807908["selected_rcsdroad_ids"] == [
        "5395523385822744",
        "5395541068551328",
        "5395541068551367",
    ]
    step4_785629 = _load_json(run_root / "cases" / "785629" / "step4_event_interpretation.json")
    assert {
        unit["positive_rcsd_present"] for unit in step4_785629["event_units"]
    } == {False}
    assert {
        tuple(unit["selected_rcsdroad_ids"]) for unit in step4_785629["event_units"]
    } == {()}

    assert rows_by_case["823826"]["surface_scenario_type"] == "main_evidence_with_rcsd_junction"
    step6_823826 = _load_json(run_root / "cases" / "823826" / "step6_status.json")
    assert step6_823826["hole_count"] == 0
    assert step6_823826["business_hole_count"] == 0
    assert step6_823826["unexpected_hole_count"] == 0
