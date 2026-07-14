from __future__ import annotations

import csv
import json
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p02_wuhan_local_experiment.endpoint_overrides import (
    apply_confirmed_endpoint_overrides,
)
from rcsd_topo_poc.modules.p02_wuhan_local_experiment.internal_case_runner import (
    _create_t05_compatibility,
    _require_raw_inputs,
    _resolve_qgis_python,
)
from rcsd_topo_poc.modules.p02_wuhan_local_experiment.manual_overrides import (
    apply_wuhan_t_junction_override,
)
from rcsd_topo_poc.modules.t08_preprocess.vector_io import read_vector, write_gpkg


def test_apply_confirmed_endpoint_overrides_is_explicit_copy_on_write(tmp_path: Path) -> None:
    nodes = tmp_path / "nodes.gpkg"
    roads = tmp_path / "roads.gpkg"
    overrides = tmp_path / "overrides.csv"
    write_gpkg(
        nodes,
        [
            {"properties": {"Id": "1"}, "geometry": Point(0, 0)},
            {"properties": {"Id": "2"}, "geometry": Point(1, 0)},
            {"properties": {"Id": "20"}, "geometry": Point(2, 0)},
        ],
        crs_text="EPSG:4326",
    )
    write_gpkg(
        roads,
        [
            {
                "properties": {"Id": "100", "SNodeId": "1", "ENodeId": "9", "CrossLid": "ignored"},
                "geometry": LineString([(0, 0), (1, 0)]),
            }
        ],
        crs_text="EPSG:4326",
    )
    _write_csv(
        overrides,
        [
            {
                "road_id": "100",
                "endpoint_field": "ENodeId",
                "expected_old_node_id": "9",
                "replacement_node_id": "20",
                "confirmation_source": "user",
            }
        ],
    )

    artifacts = apply_confirmed_endpoint_overrides(
        roads_path=roads,
        nodes_path=nodes,
        override_list_path=overrides,
        out_dir=tmp_path / "out",
        expected_override_count=1,
    )

    written = read_vector(artifacts.corrected_roads, target_epsg=None)
    assert str(written.features[0].properties["ENodeId"]) == "20"
    assert written.features[0].properties["CrossLid"] == "ignored"
    audit = json.loads(artifacts.audit.read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
    assert audit["checks"]["missing_endpoint_count_before"] == 1
    assert audit["checks"]["missing_endpoint_count_after"] == 0
    assert audit["checks"]["crosslid_used"] is False
    assert audit["checks"]["geometry_inference_used"] is False
    assert artifacts.confirmed_overrides.read_bytes() == overrides.read_bytes()


def test_apply_manual_t_junction_override_augments_tool6_without_geometry_change(
    tmp_path: Path,
) -> None:
    nodes = tmp_path / "nodes.gpkg"
    roads = tmp_path / "roads.gpkg"
    tool6_csv = tmp_path / "tool6.csv"
    write_gpkg(
        nodes,
        [
            {
                "properties": {
                    "id": "609020493",
                    "mainnodeid": 0,
                    "grade": 1,
                    "grade_2": 1,
                    "kind_2": 4,
                },
                "geometry": Point(0, 0),
            },
            {
                "properties": {"id": "1", "mainnodeid": 0, "grade": 1, "grade_2": 1, "kind_2": 1},
                "geometry": Point(-1, 0),
            },
            {
                "properties": {"id": "2", "mainnodeid": 0, "grade": 1, "grade_2": 1, "kind_2": 1},
                "geometry": Point(1, 0),
            },
            {
                "properties": {"id": "3", "mainnodeid": 0, "grade": 1, "grade_2": 1, "kind_2": 1},
                "geometry": Point(0, 1),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        roads,
        [
            {
                "properties": {"id": "11", "snodeid": "1", "enodeid": "609020493", "direction": 1},
                "geometry": LineString([(-1, 0), (0, 0)]),
            },
            {
                "properties": {"id": "12", "snodeid": "609020493", "enodeid": "2", "direction": 1},
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "properties": {"id": "13", "snodeid": "609020493", "enodeid": "3", "direction": 1},
                "geometry": LineString([(0, 0), (0, 1)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    tool6_fields = (
        "error_id",
        "error_group_id",
        "error_type",
        "semantic_node_id",
        "source_node_id",
        "role",
        "kind_2",
        "in_degree",
        "out_degree",
        "paired_semantic_node_id",
        "related_node_ids",
        "related_road_ids",
        "reason",
        "audit_json",
        "是否修复",
    )
    with tool6_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.DictWriter(handle, fieldnames=tool6_fields).writeheader()

    artifacts = apply_wuhan_t_junction_override(
        nodes_path=nodes,
        roads_path=roads,
        tool6_csv_path=tool6_csv,
        out_dir=tmp_path / "out",
    )

    written = read_vector(artifacts.nodes, target_epsg=None)
    target = next(feature for feature in written.features if str(feature.properties["id"]) == "609020493")
    assert int(target.properties["grade"]) == 2
    assert int(target.properties["grade_2"]) == 2
    assert int(target.properties["kind_2"]) == 4
    with artifacts.tool6_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["semantic_node_id"] == "609020493"
    assert rows[0]["是否修复"] == "1"
    audit = json.loads(artifacts.audit.read_text(encoding="utf-8"))
    assert audit["checks"]["input_geometry_unchanged"] is True
    assert audit["in_degree"] == 3
    assert audit["out_degree"] == 3


def test_t05_compatibility_is_explicitly_empty_and_unavailable(tmp_path: Path) -> None:
    artifacts = _create_t05_compatibility(tmp_path)
    surface = read_vector(artifacts["surface"], target_epsg=None)
    assert surface.output_crs.to_string() == "EPSG:3857"
    assert surface.features == []
    manifest = json.loads((tmp_path / "compatibility_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "unavailable_empty_compat"


def test_raw_input_contract_and_explicit_qgis_executable(tmp_path: Path) -> None:
    for name in ("node.geojson", "road.geojson", "RCSDNode.geojson", "RCSDRoad.geojson"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    assert set(_require_raw_inputs(tmp_path)) == {
        "node.geojson",
        "road.geojson",
        "RCSDNode.geojson",
        "RCSDRoad.geojson",
    }
    executable = tmp_path / "python-qgis-ltr"
    executable.write_text("", encoding="utf-8")
    assert _resolve_qgis_python(str(executable)) == str(executable.resolve())


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = tuple(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
