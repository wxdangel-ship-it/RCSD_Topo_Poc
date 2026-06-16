from __future__ import annotations

import json
import csv
from pathlib import Path
from typing import Any

import fiona
import pytest
from shapely.geometry import Point, Polygon, mapping

from rcsd_topo_poc.modules.t07_semantic_junction_anchor import (
    T07RunError,
    run_t07_semantic_junction_anchor,
    run_t07_step1_has_evd,
    run_t07_step2_anchor_recognition,
)
from rcsd_topo_poc.modules.t07_semantic_junction_anchor.runner import _normalize_id


def _feature(properties: dict[str, Any], geometry: Any) -> dict[str, Any]:
    return {"type": "Feature", "properties": properties, "geometry": mapping(geometry)}


def _write_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
                "features": features,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_geojson_without_crs(path: Path, features: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )


def _read_gpkg_properties_by_id(path: Path) -> dict[str, dict[str, Any]]:
    with fiona.open(str(path)) as src:
        return {
            str(dict(feature["properties"])["id"]): dict(feature["properties"])
            for feature in src
        }


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("622700016.0", "622700016"),
        ("622700016", "622700016"),
        ("6.22700016E+8", "622700016"),
        ("622700016.5", "622700016.5"),
        ("SWSD-622700016.0", "SWSD-622700016.0"),
    ],
)
def test_normalize_id_canonicalizes_integer_numeric_strings(raw_value: Any, expected: str) -> None:
    assert _normalize_id(raw_value) == expected


def test_step1_uses_representative_kind2_and_writes_only_representative(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"
    intersections_path = tmp_path / "intersections.geojson"
    _write_geojson(
        nodes_path,
        [
            _feature({"id": 1, "mainnodeid": 1, "kind_2": 4}, Point(0, 0)),
            _feature({"id": 101, "mainnodeid": 1, "kind_2": 0}, Point(1, 0)),
            _feature({"id": 2, "mainnodeid": 2, "kind_2": 8}, Point(100, 0)),
            _feature({"id": 201, "mainnodeid": 2, "kind_2": 0}, Point(101, 0)),
            _feature({"id": 3, "mainnodeid": 3, "kind_2": 16}, Point(200, 0)),
            _feature({"id": 4, "mainnodeid": 4, "kind_2": 1}, Point(0, 0)),
            _feature({"id": 5, "mainnodeid": 5, "kind_2": 4}, Point(11.2, 0)),
        ],
    )
    _write_geojson(
        drivezone_path,
        [_feature({"id": "dz"}, Polygon([(-10, -10), (10, -10), (10, 10), (-10, 10), (-10, -10)]))],
    )
    _write_geojson(
        intersections_path,
        [_feature({"id": "intersection"}, Polygon([(90, -10), (110, -10), (110, 10), (90, 10), (90, -10)]))],
    )

    artifacts = run_t07_step1_has_evd(
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        intersection_path=intersections_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    props = _read_gpkg_properties_by_id(artifacts.nodes_path)
    assert props["1"]["has_evd"] == "yes"
    assert props["101"]["has_evd"] is None
    assert props["2"]["has_evd"] == "yes"
    assert props["201"]["has_evd"] is None
    assert props["3"]["has_evd"] == "no"
    assert props["4"]["has_evd"] is None
    assert props["5"]["has_evd"] == "yes"

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["processed_kind2_count"] == 4
    assert summary["skipped_kind2_count"] == 1
    assert summary["has_evd_yes_count"] == 3
    assert summary["has_evd_no_count"] == 1
    assert summary["has_evd_null_count"] == 1
    assert summary["params"]["has_evd_evidence_tolerance_m"] == 1.5
    assert summary["input_paths"]["intersection"] == str(intersections_path)
    assert "stage_timings" in summary["performance"]
    assert "write_nodes_seconds" in summary["performance"]["stage_timings"]

    perf = json.loads(artifacts.perf_json_path.read_text(encoding="utf-8"))
    assert "stage_timings" in perf
    assert "read_inputs_seconds" in perf["stage_timings"]


def test_step2_outputs_anchor_states_reasons_and_conflicts(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersections_path = tmp_path / "intersections.geojson"
    _write_geojson(
        nodes_path,
        [
            _feature({"id": 1, "mainnodeid": 1, "kind_2": 4, "has_evd": "yes"}, Point(0, 0)),
            _feature({"id": 2, "mainnodeid": 2, "kind_2": 4, "has_evd": "yes"}, Point(100, 0)),
            _feature({"id": 3, "mainnodeid": 3, "kind_2": 64, "has_evd": "yes"}, Point(200, 0)),
            _feature({"id": 301, "mainnodeid": 3, "kind_2": 0, "has_evd": None}, Point(202, 0)),
            _feature({"id": 4, "mainnodeid": 4, "kind_2": 2048, "has_evd": "yes"}, Point(300, 0)),
            _feature({"id": 401, "mainnodeid": 4, "kind_2": 0, "has_evd": None}, Point(302, 0)),
            _feature({"id": 5, "mainnodeid": 5, "kind_2": 4, "has_evd": "yes"}, Point(400, 0)),
            _feature({"id": 501, "mainnodeid": 5, "kind_2": 0, "has_evd": None}, Point(430, 0)),
            _feature({"id": 6, "mainnodeid": 6, "kind_2": 4, "has_evd": "yes"}, Point(500, 0)),
            _feature({"id": 7, "mainnodeid": 7, "kind_2": 4, "has_evd": "yes"}, Point(502, 0)),
            _feature({"id": 8, "mainnodeid": 8, "kind_2": 4, "has_evd": "no"}, Point(0, 100)),
            _feature({"id": 9, "mainnodeid": 9, "kind_2": 128, "has_evd": "yes"}, Point(504, 0)),
            _feature({"id": 10, "mainnodeid": 10, "kind_2": 2048, "has_evd": "yes"}, Point(600, 0)),
            _feature({"id": 1001, "mainnodeid": 10, "kind_2": 0, "has_evd": None}, Point(630, 0)),
        ],
    )
    _write_geojson(
        intersections_path,
        [
            _feature({"id": "a"}, Polygon([(-10, -10), (10, -10), (10, 10), (-10, 10), (-10, -10)])),
            _feature({"id": "roundabout"}, Polygon([(190, -10), (210, -10), (210, 10), (190, 10), (190, -10)])),
            _feature({"id": "t"}, Polygon([(290, -10), (310, -10), (310, 10), (290, 10), (290, -10)])),
            _feature({"id": "fail1a"}, Polygon([(390, -10), (410, -10), (410, 10), (390, 10), (390, -10)])),
            _feature({"id": "fail1b"}, Polygon([(420, -10), (440, -10), (440, 10), (420, 10), (420, -10)])),
            _feature({"id": "shared"}, Polygon([(490, -10), (510, -10), (510, 10), (490, 10), (490, -10)])),
            _feature({"id": "t_mismatch_a"}, Polygon([(590, -10), (610, -10), (610, 10), (590, 10), (590, -10)])),
            _feature({"id": "t_mismatch_b"}, Polygon([(620, -10), (640, -10), (640, 10), (620, 10), (620, -10)])),
        ],
    )

    artifacts = run_t07_step2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersections_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    props = _read_gpkg_properties_by_id(artifacts.nodes_path)
    assert props["1"]["is_anchor"] == "yes"
    assert props["2"]["is_anchor"] == "no"
    assert props["3"]["is_anchor"] == "no"
    assert props["3"]["anchor_reason"] is None
    assert props["4"]["is_anchor"] == "no"
    assert props["4"]["anchor_reason"] is None
    assert props["5"]["is_anchor"] == "fail1"
    assert props["6"]["is_anchor"] == "fail2"
    assert props["7"]["is_anchor"] == "fail2"
    assert props["8"]["is_anchor"] is None
    assert props["9"]["is_anchor"] == "fail2"
    assert props["9"]["anchor_reason"] is None
    assert props["10"]["is_anchor"] == "no"
    assert props["10"]["anchor_reason"] is None

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["anchor_yes_count"] == 1
    assert summary["anchor_no_count"] == 4
    assert summary["anchor_fail1_count"] == 1
    assert summary["anchor_fail2_count"] == 3
    assert summary["anchor_null_count"] == 1
    assert summary["t_reason_count"] == 0
    assert summary["relation_evidence_row_count"] == 10
    assert summary["surface_candidate_count"] == 3
    assert artifacts.relation_evidence_csv_path is not None
    assert artifacts.relation_evidence_csv_path.is_file()
    assert artifacts.relation_evidence_json_path is not None
    relation_payload = json.loads(artifacts.relation_evidence_json_path.read_text(encoding="utf-8"))
    relation_rows = {str(row["target_id"]): row for row in relation_payload["rows"]}
    with artifacts.relation_evidence_csv_path.open("r", encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == relation_payload["row_count"]
    assert relation_rows["1"]["relation_source"] == "T07_STEP2"
    assert relation_rows["1"]["relation_state"] == "existing_rcsdintersection_matched"
    assert relation_rows["1"]["status_suggested"] == 0
    assert relation_rows["1"]["base_id_candidate"] == "a"
    assert relation_rows["2"]["relation_state"] == "no_existing_rcsdintersection"
    assert relation_rows["4"]["relation_state"] == "t_junction_deferred_to_t03"
    assert relation_rows["4"]["status_suggested"] == 1
    assert relation_rows["5"]["relation_state"] == "multiple_intersections_for_group"
    assert relation_rows["5"]["status_suggested"] == 1
    assert relation_rows["5"]["base_id_candidate"] == "fail1a|fail1b"
    assert relation_rows["6"]["relation_state"] == "intersection_shared_by_multiple_groups"
    assert relation_rows["8"]["relation_state"] == "not_evaluated_no_evidence"
    assert relation_rows["9"]["relation_state"] == "intersection_shared_by_multiple_groups"
    assert artifacts.anchor_surface_path is not None
    with fiona.open(str(artifacts.anchor_surface_path)) as src:
        surface_rows = [dict(feature["properties"]) for feature in src]
    assert {str(row["target_id"]) for row in surface_rows} == {"1", "5"}
    assert [str(row["target_id"]) for row in surface_rows].count("5") == 2
    fail1_surfaces = [row for row in surface_rows if str(row["target_id"]) == "5"]
    assert {row["relation_state"] for row in fail1_surfaces} == {"multiple_intersections_for_group"}
    assert {row["status_suggested"] for row in fail1_surfaces} == {1}
    assert {row["source_module"] for row in surface_rows} == {"T07_STEP2"}
    assert "stage_timings" in summary["performance"]
    assert "build_intersection_index_seconds" in summary["performance"]["stage_timings"]

    error2 = json.loads((artifacts.stage_root / "node_error_2_audit.json").read_text(encoding="utf-8"))
    assert "9" in {row["junction_id"] for row in error2["rows"]}
    assert all(row["junction_id"] != "10" for row in error2["rows"])


def test_step2_rcsdnode_gate_reopens_unconsumable_intersection_surface(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersections_path = tmp_path / "intersections.geojson"
    rcsdnode_path = tmp_path / "rcsdnode.geojson"
    _write_geojson(
        nodes_path,
        [
            _feature({"id": 1, "mainnodeid": 1, "kind_2": 4, "has_evd": "yes"}, Point(0, 0)),
            _feature({"id": 2, "mainnodeid": 2, "kind_2": 4, "has_evd": "yes"}, Point(100, 0)),
        ],
    )
    _write_geojson(
        intersections_path,
        [
            _feature({"id": "empty-surface"}, Polygon([(-5, -5), (5, -5), (5, 5), (-5, 5), (-5, -5)])),
            _feature({"id": "semantic-surface"}, Polygon([(95, -5), (105, -5), (105, 5), (95, 5), (95, -5)])),
        ],
    )
    _write_geojson(
        rcsdnode_path,
        [
            _feature({"id": "900", "mainnodeid": "900"}, Point(100, 0)),
        ],
    )

    artifacts = run_t07_step2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersections_path,
        rcsdnode_path=rcsdnode_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    props = _read_gpkg_properties_by_id(artifacts.nodes_path)
    assert props["1"]["is_anchor"] == "no"
    assert props["2"]["is_anchor"] == "yes"

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["anchor_yes_count"] == 1
    assert summary["anchor_no_count"] == 1
    assert summary["rcsdintersection_no_rcsdnode_count"] == 1
    assert summary["input_paths"]["rcsdnode"] == str(rcsdnode_path)

    assert artifacts.relation_evidence_json_path is not None
    relation_payload = json.loads(artifacts.relation_evidence_json_path.read_text(encoding="utf-8"))
    relation_rows = {str(row["target_id"]): row for row in relation_payload["rows"]}
    assert relation_rows["1"]["relation_state"] == "rcsdintersection_no_rcsd_semantic_node"
    assert relation_rows["1"]["status_suggested"] == 1
    assert relation_rows["1"]["matched_rcsdintersection_ids"] == "empty-surface"
    assert relation_rows["1"]["base_id_candidate"] == -1
    assert relation_rows["2"]["relation_state"] == "existing_rcsdintersection_matched"
    assert relation_rows["2"]["status_suggested"] == 0

    assert artifacts.anchor_surface_path is not None
    with fiona.open(str(artifacts.anchor_surface_path)) as src:
        surface_rows = [dict(feature["properties"]) for feature in src]
    assert {str(row["target_id"]) for row in surface_rows} == {"2"}

    audit = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert any(row["reason"] == "rcsdintersection_no_rcsd_semantic_node" for row in audit["rows"])


def test_step2_canonicalizes_string_float_semantic_ids_in_handoff_outputs(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersections_path = tmp_path / "intersections.geojson"
    _write_geojson(
        nodes_path,
        [
            _feature(
                {"id": "622700016.0", "mainnodeid": "622700016.0", "kind_2": 4, "has_evd": "yes"},
                Point(0, 0),
            )
        ],
    )
    _write_geojson(
        intersections_path,
        [_feature({"id": "surface-a"}, Polygon([(-5, -5), (5, -5), (5, 5), (-5, 5), (-5, -5)]))],
    )

    artifacts = run_t07_step2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersections_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    assert artifacts.relation_evidence_json_path is not None
    relation_payload = json.loads(artifacts.relation_evidence_json_path.read_text(encoding="utf-8"))
    assert relation_payload["rows"][0]["target_id"] == "622700016"
    assert relation_payload["rows"][0]["representative_node_id"] == "622700016"
    with artifacts.relation_evidence_csv_path.open("r", encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert csv_rows[0]["target_id"] == "622700016"
    assert csv_rows[0]["representative_node_id"] == "622700016"

    assert artifacts.anchor_surface_path is not None
    with fiona.open(str(artifacts.anchor_surface_path)) as src:
        surface_rows = [dict(feature["properties"]) for feature in src]
    assert surface_rows[0]["target_id"] == "622700016"
    assert surface_rows[0]["mainnodeid"] == "622700016"
    assert surface_rows[0]["representative_node_id"] == "622700016"


def test_step2_shared_intersection_fail2_excludes_t_junction_kind2(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersections_path = tmp_path / "intersections.geojson"
    _write_geojson(
        nodes_path,
        [
            _feature({"id": 1, "mainnodeid": 1, "kind_2": 4, "has_evd": "yes"}, Point(0, 0)),
            _feature({"id": 2, "mainnodeid": 2, "kind_2": 8, "has_evd": "yes"}, Point(1, 0)),
            _feature({"id": 3, "mainnodeid": 3, "kind_2": 16, "has_evd": "yes"}, Point(2, 0)),
            _feature({"id": 4, "mainnodeid": 4, "kind_2": 64, "has_evd": "yes"}, Point(3, 0)),
            _feature({"id": 5, "mainnodeid": 5, "kind_2": 128, "has_evd": "yes"}, Point(4, 0)),
            _feature({"id": 6, "mainnodeid": 6, "kind_2": 2048, "has_evd": "yes"}, Point(5, 0)),
            _feature({"id": 601, "mainnodeid": 6, "kind_2": 0, "has_evd": None}, Point(6, 0)),
        ],
    )
    _write_geojson(
        intersections_path,
        [_feature({"id": "shared"}, Polygon([(-1, -1), (7, -1), (7, 1), (-1, 1), (-1, -1)]))],
    )

    artifacts = run_t07_step2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersections_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    props = _read_gpkg_properties_by_id(artifacts.nodes_path)
    for junction_id in ["1", "2", "3", "4", "5"]:
        assert props[junction_id]["is_anchor"] == "fail2"
        assert props[junction_id]["anchor_reason"] is None
    assert props["6"]["is_anchor"] == "no"
    assert props["6"]["anchor_reason"] is None

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["anchor_yes_count"] == 0
    assert summary["anchor_no_count"] == 1
    assert summary["anchor_fail1_count"] == 0
    assert summary["anchor_fail2_count"] == 5
    assert summary["anchor_null_count"] == 0

    error2 = json.loads((artifacts.stage_root / "node_error_2_audit.json").read_text(encoding="utf-8"))
    assert {row["junction_id"] for row in error2["rows"]} == {"1", "2", "3", "4", "5"}


def test_combined_runner_has_no_segment_dependency_or_outputs(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"
    intersections_path = tmp_path / "intersections.geojson"
    _write_geojson(nodes_path, [_feature({"id": 1, "mainnodeid": 1, "kind_2": 4}, Point(0, 0))])
    _write_geojson(
        drivezone_path,
        [_feature({"id": "dz"}, Polygon([(-10, -10), (10, -10), (10, 10), (-10, 10), (-10, -10)]))],
    )
    _write_geojson(
        intersections_path,
        [_feature({"id": "a"}, Polygon([(-5, -5), (5, -5), (5, 5), (-5, 5), (-5, -5)]))],
    )

    artifacts = run_t07_semantic_junction_anchor(
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        intersection_path=intersections_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    assert artifacts.step1.nodes_path.is_file()
    assert artifacts.step2.nodes_path.is_file()
    assert not list(artifacts.run_root.rglob("segment.gpkg"))

    step1_summary = json.loads(artifacts.step1.summary_path.read_text(encoding="utf-8"))
    step2_summary = json.loads(artifacts.step2.summary_path.read_text(encoding="utf-8"))
    assert "summary_by_s_grade" not in step1_summary
    assert "anchor_summary_by_s_grade" not in step2_summary


def test_geojson_without_crs_fails_explicitly(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"
    _write_geojson_without_crs(nodes_path, [_feature({"id": 1, "mainnodeid": 1, "kind_2": 4}, Point(0, 0))])
    _write_geojson(
        drivezone_path,
        [_feature({"id": "dz"}, Polygon([(-10, -10), (10, -10), (10, 10), (-10, 10), (-10, -10)]))],
    )

    with pytest.raises(T07RunError) as excinfo:
        run_t07_step1_has_evd(
            nodes_path=nodes_path,
            drivezone_path=drivezone_path,
            out_root=tmp_path / "out",
            run_id="case",
        )
    assert excinfo.value.reason == "invalid_crs_or_unprojectable"


def test_missing_required_field_is_audited_not_business_no(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"
    _write_geojson(nodes_path, [_feature({"id": 1, "mainnodeid": 1}, Point(0, 0))])
    _write_geojson(
        drivezone_path,
        [_feature({"id": "dz"}, Polygon([(-10, -10), (10, -10), (10, 10), (-10, 10), (-10, -10)]))],
    )

    artifacts = run_t07_step1_has_evd(
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    audit = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert audit["rows"][0]["reason"] == "missing_required_field"
    assert "kind_2" in audit["rows"][0]["detail"]


def test_invalid_geometry_topology_fails_without_silent_fix(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"
    invalid_bowtie = Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])
    _write_geojson(nodes_path, [_feature({"id": 1, "mainnodeid": 1, "kind_2": 4}, Point(0, 0))])
    _write_geojson(drivezone_path, [_feature({"id": "dz"}, invalid_bowtie)])

    with pytest.raises(T07RunError) as excinfo:
        run_t07_step1_has_evd(
            nodes_path=nodes_path,
            drivezone_path=drivezone_path,
            out_root=tmp_path / "out",
            run_id="case",
        )
    assert excinfo.value.reason == "invalid_geometry_topology"
