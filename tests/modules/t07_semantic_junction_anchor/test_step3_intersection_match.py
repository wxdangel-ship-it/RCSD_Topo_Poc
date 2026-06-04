from __future__ import annotations

import json
import csv
import sqlite3
from pathlib import Path
from typing import Any

import fiona
from shapely.geometry import LineString, Point, Polygon, mapping, shape

from rcsd_topo_poc.modules.t07_semantic_junction_anchor import run_t07_step3_intersection_match
from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg


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


def _write_crs84_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "CRS84"}},
                "features": features,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_gpkg(path: Path, features: list[dict[str, Any]]) -> None:
    write_gpkg(
        path,
        (
            {
                "properties": feature["properties"],
                "geometry": shape(feature["geometry"]),
            }
            for feature in features
        ),
        crs_text="EPSG:3857",
    )


def _read_gpkg_properties_by_id(path: Path) -> dict[str, dict[str, Any]]:
    with fiona.open(str(path)) as src:
        return {
            str(dict(feature["properties"])["id"]): dict(feature["properties"])
            for feature in src
        }


def _remove_gpkg_ogr_count_metadata(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        triggers = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'trigger' AND name LIKE 'trigger_%_feature_count_%'
                """
            )
        ]
        for trigger_name in triggers:
            conn.execute(f'DROP TRIGGER "{trigger_name}"')
        conn.execute("DROP TABLE IF EXISTS gpkg_ogr_contents")


def _relation_targets(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(feature["properties"]["target_id"]) for feature in payload["features"]}


def test_step3_anchors_candidates_with_successful_t05_relation_and_existing_rcsdnode(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    relations_path = tmp_path / "intersection_match_all.geojson"
    rcsdnode_path = tmp_path / "rcsdnode.geojson"
    _write_geojson(
        nodes_path,
        [
            _feature({"id": 1, "mainnodeid": 1, "kind_2": 4, "has_evd": "yes", "is_anchor": "yes"}, Point(0, 0)),
            _feature({"id": 101, "mainnodeid": 1, "kind_2": 0}, Point(1, 0)),
            _feature({"id": 2, "mainnodeid": 2, "kind_2": 8, "has_evd": "yes", "is_anchor": "no"}, Point(10, 0)),
            _feature({"id": 3, "mainnodeid": 3, "kind_2": 16, "has_evd": "yes", "is_anchor": "yes"}, Point(20, 0)),
            _feature({"id": 4, "mainnodeid": 4, "kind_2": 2048, "has_evd": "yes", "is_anchor": "no"}, Point(30, 0)),
            _feature({"id": 5, "mainnodeid": 5, "kind_2": 64, "has_evd": "yes", "is_anchor": "no"}, Point(40, 0)),
            _feature({"id": 6, "mainnodeid": 6, "kind_2": 4, "has_evd": "no", "is_anchor": "no"}, Point(50, 0)),
            _feature({"id": 7, "mainnodeid": 7, "kind_2": 4, "has_evd": "yes", "is_anchor": "no"}, Point(60, 0)),
            _feature({"id": 8, "mainnodeid": 8, "kind_2": 4, "has_evd": "yes", "is_anchor": "no"}, Point(70, 0)),
            _feature({"id": 9, "mainnodeid": 9, "kind_2": 4, "has_evd": "yes", "is_anchor": "no"}, Point(80, 0)),
        ],
    )
    _write_geojson(
        relations_path,
        [
            _feature({"target_id": 1, "base_id": 900, "status": 0, "level": 1, "is_highway": 0}, LineString([(0, 0), (0, 1)])),
            _feature({"target_id": 2, "base_id": 901, "status": 0, "level": 1, "is_highway": 0}, LineString([(10, 0), (10, 1)])),
            _feature({"target_id": 3, "base_id": 900, "status": 0, "level": 1, "is_highway": 0}, LineString([(20, 0), (20, 1)])),
            _feature({"target_id": 4, "base_id": 999, "status": 0, "level": 1, "is_highway": 0}, LineString([(30, 0), (30, 1)])),
            _feature({"target_id": 5, "base_id": 900, "status": 0, "level": 1, "is_highway": 0}, LineString([(40, 0), (40, 1)])),
            _feature({"target_id": 7, "base_id": 0, "status": 1, "level": 1, "is_highway": 0}, LineString([(60, 0), (60, 1)])),
            _feature({"target_id": 9, "base_id": 800, "status": 0, "level": 1, "is_highway": 0}, LineString([(80, 0), (80, 1)])),
        ],
    )
    _write_geojson(
        rcsdnode_path,
        [
            _feature({"id": 800, "mainnodeid": None}, Point(99, 0)),
            _feature({"id": 900, "mainnodeid": None}, Point(100, 0)),
            _feature({"id": 901, "mainnodeid": 901}, Point(101, 0)),
        ],
    )
    (tmp_path / "t07_swsd_rcsd_relation_evidence.json").write_text(
        json.dumps(
            {
                "run_id": "step2",
                "target_crs": "EPSG:3857",
                "row_count": 2,
                "fieldnames": [],
                "rows": [
                    {"target_id": "1", "relation_source": "T07_STEP2", "relation_state": "existing_rcsdintersection_matched", "status_suggested": 0, "base_id_candidate": 800},
                    {"target_id": "8", "relation_source": "T07_STEP2", "relation_state": "no_existing_rcsdintersection", "status_suggested": 1, "base_id_candidate": -1},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_gpkg(
        tmp_path / "t07_rcsdintersection_anchor_surface.gpkg",
        [
            _feature(
                {"surface_candidate_id": "step2-surface", "target_id": 1, "source_module": "T07_STEP2", "kind_2": 4},
                Polygon([(98, -1), (99.5, -1), (99.5, 1), (98, 1), (98, -1)]),
            )
        ],
    )

    artifacts = run_t07_step3_intersection_match(
        nodes_path=nodes_path,
        intersection_match_all_path=relations_path,
        rcsdnode_path=rcsdnode_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    props = _read_gpkg_properties_by_id(artifacts.nodes_path)
    assert props["1"]["is_anchor"] == "yes"
    assert props["1"]["anchor_reason"] is None
    assert props["101"]["is_anchor"] is None
    assert props["2"]["is_anchor"] == "yes"
    assert props["3"]["is_anchor"] == "yes"
    assert props["4"]["is_anchor"] == "no"
    assert props["5"]["is_anchor"] == "no"
    assert props["6"]["is_anchor"] == "no"
    assert props["7"]["is_anchor"] == "no"
    assert props["8"]["is_anchor"] == "no"
    assert props["9"]["is_anchor"] == "no"

    assert _relation_targets(artifacts.intersection_match_t07_path) == {"1", "2"}
    relation_payload = json.loads(artifacts.intersection_match_t07_path.read_text(encoding="utf-8"))
    assert relation_payload["crs"]["properties"]["name"] == "CRS84"

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["candidate_count"] == 5
    assert summary["accepted_count"] == 2
    assert summary["step2_surface_1v1_relation_count"] == 1
    assert summary["intersection_match_backfill_relation_count"] == 1
    assert summary["relation_missing_count"] == 1
    assert summary["relation_failure_count"] == 1
    assert summary["rcsd_missing_count"] == 1
    assert summary["already_linked_base_skip_count"] == 1
    assert summary["rcsdnode_error_count"] == 0
    assert summary["swsd_multi_rcsd_error_count"] == 0
    assert summary["skipped_kind2_count"] == 1
    assert summary["crs"]["intersection_match_t07"] == "CRS84"
    assert summary["relation_evidence_row_count"] == 3
    assert summary["step2_anchor_count"] == 1
    assert summary["step3_anchor_count"] == 2
    assert summary["total_anchor_count"] == 3
    assert summary["relation_cardinality_error_count"] == 0
    assert summary["relation_cardinality_passed"] is True
    assert summary["output_strategy"]["anchor_surface_write_mode"] == "copy_step2_surface"
    assert "stage_timings" in summary["performance"]
    assert "evaluate_candidates_seconds" in summary["performance"]["stage_timings"]

    assert artifacts.anchor_surface_path.is_file()
    with fiona.open(str(artifacts.anchor_surface_path)) as src:
        surface_rows = [dict(feature["properties"]) for feature in src]
    assert len(surface_rows) == 1
    assert surface_rows[0]["source_module"] == "T07_STEP2"

    evidence_payload = json.loads(artifacts.relation_evidence_json_path.read_text(encoding="utf-8"))
    assert artifacts.relation_evidence_csv_path.is_file()
    with artifacts.relation_evidence_csv_path.open("r", encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == evidence_payload["row_count"]
    assert evidence_payload["anchor_counts"] == {
        "step2_anchor_count": 1,
        "step3_anchor_count": 2,
        "total_anchor_count": 3,
    }
    evidence_rows = {str(row["target_id"]): row for row in evidence_payload["rows"]}
    assert evidence_rows["1"]["relation_source"] == "T07_STEP3_STEP2_SURFACE"
    assert evidence_rows["1"]["relation_state"] == "step2_surface_1v1_rcsdnode_matched"
    assert evidence_rows["1"]["status_suggested"] == 0
    assert evidence_rows["1"]["base_id_candidate"] == "800"
    assert evidence_rows["2"]["base_id_candidate"] == "901"
    assert evidence_rows["8"]["relation_source"] == "T07_STEP2"
    assert artifacts.relation_cardinality_errors_csv_path.is_file()
    cardinality_payload = json.loads(artifacts.relation_cardinality_errors_json_path.read_text(encoding="utf-8"))
    assert cardinality_payload["rows"] == []
    audit_payload = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    audit_rows = {str(row.get("junction_id")): row for row in audit_payload["rows"]}
    assert audit_rows["9"]["reason"] == "rcsd_junction_already_linked"


def test_step3_relation_cardinality_qc_reports_one_to_many_and_many_to_one(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    relations_path = tmp_path / "intersection_match_all.geojson"
    rcsdnode_path = tmp_path / "rcsdnode.geojson"
    _write_geojson(
        nodes_path,
        [
            _feature({"id": 1, "mainnodeid": 1, "kind_2": 4, "has_evd": "yes", "is_anchor": "no"}, Point(0, 0)),
            _feature({"id": 2, "mainnodeid": 2, "kind_2": 8, "has_evd": "yes", "is_anchor": "no"}, Point(10, 0)),
            _feature({"id": 3, "mainnodeid": 3, "kind_2": 16, "has_evd": "yes", "is_anchor": "no"}, Point(20, 0)),
        ],
    )
    _write_geojson(
        relations_path,
        [
            _feature({"target_id": 1, "base_id": 900, "status": 0}, LineString([(0, 0), (0, 1)])),
            _feature({"target_id": 2, "base_id": 900, "status": 0}, LineString([(10, 0), (10, 1)])),
            _feature({"target_id": 3, "base_id": 901, "status": 0}, LineString([(20, 0), (20, 1)])),
            _feature({"target_id": 3, "base_id": 902, "status": 0}, LineString([(20, 0), (20, 2)])),
        ],
    )
    _write_geojson(
        rcsdnode_path,
        [
            _feature({"id": 900, "mainnodeid": None}, Point(100, 0)),
            _feature({"id": 901, "mainnodeid": None}, Point(101, 0)),
            _feature({"id": 902, "mainnodeid": None}, Point(102, 0)),
        ],
    )

    artifacts = run_t07_step3_intersection_match(
        nodes_path=nodes_path,
        intersection_match_all_path=relations_path,
        rcsdnode_path=rcsdnode_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    props = _read_gpkg_properties_by_id(artifacts.nodes_path)
    assert props["1"]["is_anchor"] == "yes"
    assert props["2"]["is_anchor"] == "yes"
    assert props["3"]["is_anchor"] == "no"
    assert _relation_targets(artifacts.intersection_match_t07_path) == {"1", "2"}

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["accepted_count"] == 2
    assert summary["relation_duplicate_count"] == 1
    assert summary["relation_cardinality_error_count"] == 3
    assert summary["one_target_to_many_base_count"] == 1
    assert summary["many_target_to_one_base_count"] == 1
    assert summary["duplicate_target_rows_count"] == 1
    assert summary["swsd_multi_rcsd_error_count"] == 1
    assert summary["relation_cardinality_passed"] is False

    cardinality_payload = json.loads(artifacts.relation_cardinality_errors_json_path.read_text(encoding="utf-8"))
    rows = {row["error_type"]: row for row in cardinality_payload["rows"]}
    assert rows["one_target_to_many_base"]["target_id"] == "3"
    assert rows["one_target_to_many_base"]["base_id"] == "901|902"
    assert rows["many_target_to_one_base"]["target_id"] == "1|2"
    assert rows["many_target_to_one_base"]["base_id"] == "900"
    assert rows["duplicate_target_rows"]["target_id"] == "3"
    assert "target_id duplicated 2 success rows" in rows["duplicate_target_rows"]["reasons"]


def test_step3_step2_surface_with_multiple_rcsd_junctions_outputs_rcsdnode_error(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    relations_path = tmp_path / "intersection_match_all.geojson"
    rcsdnode_path = tmp_path / "rcsdnode.geojson"
    _write_geojson(
        nodes_path,
        [_feature({"id": 1, "mainnodeid": 1, "kind_2": 4, "has_evd": "yes", "is_anchor": "yes"}, Point(0, 0))],
    )
    _write_geojson(relations_path, [])
    _write_geojson(
        rcsdnode_path,
        [
            _feature({"id": 800, "mainnodeid": None}, Point(10, 0)),
            _feature({"id": 801, "mainnodeid": None}, Point(12, 0)),
        ],
    )
    _write_gpkg(
        tmp_path / "t07_rcsdintersection_anchor_surface.gpkg",
        [
            _feature(
                {"surface_candidate_id": "step2-surface", "target_id": 1, "source_module": "T07_STEP2", "kind_2": 4},
                Polygon([(9, -1), (13, -1), (13, 1), (9, 1), (9, -1)]),
            )
        ],
    )

    artifacts = run_t07_step3_intersection_match(
        nodes_path=nodes_path,
        intersection_match_all_path=relations_path,
        rcsdnode_path=rcsdnode_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    assert _relation_targets(artifacts.intersection_match_t07_path) == set()
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["step2_surface_1v1_relation_count"] == 0
    assert summary["rcsdnode_error_surface_count"] == 1
    assert summary["rcsdnode_error_count"] == 2

    with fiona.open(str(artifacts.rcsdnode_error_path)) as src:
        error_rows = [dict(feature["properties"]) for feature in src]
    assert {str(row["rcsd_semantic_id"]) for row in error_rows} == {"800", "801"}
    assert {row["error_type"] for row in error_rows} == {"multiple_rcsd_junctions_in_step2_surface"}


def test_step3_uses_fast_paths_for_gpkg_nodes_and_crs84_relations(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.gpkg"
    relations_path = tmp_path / "intersection_match_all.geojson"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"
    _write_gpkg(
        nodes_path,
        [
            _feature({"id": 1, "mainnodeid": 1, "kind_2": 4, "has_evd": "yes", "is_anchor": "no", "anchor_reason": None}, Point(0, 0)),
            _feature({"id": 2, "mainnodeid": 2, "kind_2": 1, "has_evd": "no", "is_anchor": "no", "anchor_reason": None}, Point(2, 0)),
        ],
    )
    _remove_gpkg_ogr_count_metadata(nodes_path)
    _write_crs84_geojson(
        relations_path,
        [
            _feature(
                {"target_id": 1, "base_id": 900, "status": 0, "level": 1, "is_highway": 0},
                LineString([(120, 30), (120.1, 30.1)]),
            ),
        ],
    )
    _write_gpkg(
        rcsdnode_path,
        [_feature({"id": 900, "mainnodeid": None}, Point(100, 0))],
    )

    artifacts = run_t07_step3_intersection_match(
        nodes_path=nodes_path,
        intersection_match_all_path=relations_path,
        rcsdnode_path=rcsdnode_path,
        out_root=tmp_path / "out",
        run_id="case",
    )

    props = _read_gpkg_properties_by_id(artifacts.nodes_path)
    assert props["1"]["is_anchor"] == "yes"

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["output_strategy"]["nodes_write_mode"] == "copy_update_gpkg"
    assert summary["output_strategy"]["relation_write_mode"] == "raw_crs84"

    with sqlite3.connect(artifacts.nodes_path) as conn:
        assert conn.execute("SELECT feature_count FROM gpkg_ogr_contents WHERE table_name = 'nodes'").fetchone() == (2,)
        assert conn.execute("SELECT COUNT(*) FROM nodes WHERE kind_2 = 4").fetchone() == (1,)

    relation_payload = json.loads(artifacts.intersection_match_t07_path.read_text(encoding="utf-8"))
    assert relation_payload["features"][0]["geometry"]["coordinates"] == [[120.0, 30.0], [120.1, 30.1]]
