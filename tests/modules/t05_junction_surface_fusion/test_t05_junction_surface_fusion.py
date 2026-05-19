from __future__ import annotations

from pathlib import Path

from shapely.geometry import box

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t05_junction_surface_fusion.models import MAIN_SURFACE_FIELDS
from rcsd_topo_poc.modules.t05_junction_surface_fusion.runner import run_t05_junction_surface_fusion


def _feature(properties: dict, x: float = 0.0, y: float = 0.0):
    return {"properties": properties, "geometry": box(x, y, x + 10.0, y + 10.0)}


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def _read_props(path: Path) -> list[dict]:
    return [feature.properties for feature in read_vector_layer(path).features]


def _run(
    tmp_path: Path,
    *,
    t02_features: list[dict],
    t03_features: list[dict] | None = None,
    t04_features: list[dict] | None = None,
    nodes_features: list[dict] | None = None,
):
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    t02_path = _write(input_root / "rcsdintersection.gpkg", t02_features)
    t03_path = _write(input_root / "virtual_intersection_polygons.gpkg", t03_features) if t03_features is not None else None
    t04_path = _write(input_root / "divmerge_virtual_anchor_surface.gpkg", t04_features) if t04_features is not None else None
    nodes_path = _write(input_root / "nodes.gpkg", nodes_features) if nodes_features is not None else None
    return run_t05_junction_surface_fusion(
        t02_rcsdintersection_path=t02_path,
        t03_surface_path=t03_path,
        t04_surface_path=t04_path,
        nodes_path=nodes_path,
        out_root=tmp_path / "out",
        run_id="run",
    )


def test_schema_crs_and_t02_single_source(tmp_path: Path) -> None:
    artifacts = _run(
        tmp_path,
        t02_features=[_feature({"id": "rcsd_1", "mainnodeid": "100", "patch_id": "P1"})],
    )

    features = read_vector_layer(artifacts.surface_path).features
    assert len(features) == 1
    props = features[0].properties
    assert list(props.keys()) == MAIN_SURFACE_FIELDS
    assert props["surface_id"] == "JAS:100"
    assert props["mainnodeid"] == "100"
    assert props["junction_type"] == "rcsd_intersection"
    assert props["surface_sources"] == "T02_INPUT"
    assert props["is_multi_source_merged"] == 0
    assert read_vector_layer(artifacts.surface_path).source_crs.to_epsg() == 3857
    assert "intersection_match_all" not in props
    assert not (artifacts.run_root / "intersection_match_all.geojson").exists()


def test_single_source_filters_formal_accepted_surfaces(tmp_path: Path) -> None:
    artifacts = _run(
        tmp_path,
        t02_features=[_feature({"id": "rcsd_1", "mainnodeid": "200"}, 0, 0)],
        t03_features=[
            _feature({"id": "t03_ok", "mainnodeid": "300", "kind_2": 4, "step7_state": "accepted"}, 30, 0),
            _feature({"id": "t03_bad", "mainnodeid": "301", "kind_2": 4, "step7_state": "rejected"}, 60, 0),
        ],
        t04_features=[
            _feature({"id": "t04_ok", "mainnodeid": "400", "kind_2": 8, "final_state": "accepted"}, 90, 0),
            _feature({"id": "t04_bad", "mainnodeid": "401", "kind_2": 8, "final_state": "rejected"}, 120, 0),
        ],
    )

    rows = _read_props(artifacts.surface_path)
    by_id = {row["surface_id"]: row for row in rows}
    assert "JAS:300" in by_id
    assert by_id["JAS:300"]["junction_type"] == "center_junction"
    assert "JAS:400" in by_id
    assert by_id["JAS:400"]["junction_type"] == "merge"
    assert "JAS:301" not in by_id
    assert "JAS:401" not in by_id
    assert artifacts.skipped_count == 2


def test_t02_t03_merge_and_different_mainnodeids_do_not_merge(tmp_path: Path) -> None:
    artifacts = _run(
        tmp_path,
        t02_features=[_feature({"id": "rcsd_100", "mainnodeid": "100"}, 0, 0)],
        t03_features=[
            _feature({"id": "t03_100", "mainnodeid": "100", "kind_2": 4, "step7_state": "accepted"}, 1, 0),
            _feature({"id": "t03_200", "mainnodeid": "200", "kind_2": 4, "step7_state": "accepted"}, 40, 0),
        ],
        t04_features=[
            _feature({"id": "t04_201", "mainnodeid": "201", "kind_2": 8, "final_state": "accepted"}, 40, 0),
        ],
    )

    by_id = {row["surface_id"]: row for row in _read_props(artifacts.surface_path)}
    assert by_id["JAS:100"]["surface_sources"] == "T02_INPUT|T03"
    assert by_id["JAS:100"]["is_multi_source_merged"] == 1
    assert by_id["JAS:100"]["junction_type"] == "center_junction"
    assert "JAS:200" in by_id
    assert "JAS:201" in by_id
    assert by_id["JAS:200"]["surface_sources"] == "T03"
    assert by_id["JAS:201"]["surface_sources"] == "T04"


def test_t02_t04_merge_and_t03_t04_conflict_audit(tmp_path: Path) -> None:
    artifacts = _run(
        tmp_path,
        t02_features=[_feature({"id": "rcsd_110", "mainnodeid": "110"}, 0, 0)],
        t03_features=[
            _feature({"id": "t03_120", "mainnodeid": "120", "kind_2": 4, "step7_state": "accepted"}, 50, 0),
        ],
        t04_features=[
            _feature({"id": "t04_110", "mainnodeid": "110", "kind_2": 8, "final_state": "accepted"}, 1, 0),
            _feature({"id": "t04_120", "mainnodeid": "120", "kind_2": 8, "final_state": "accepted"}, 51, 0),
        ],
    )

    by_id = {row["surface_id"]: row for row in _read_props(artifacts.surface_path)}
    assert by_id["JAS:110"]["surface_sources"] == "T02_INPUT|T04"
    assert by_id["JAS:110"]["junction_type"] == "merge"
    audit_rows = _read_audit_json(artifacts.audit_json_path)
    conflict_row = next(row for row in audit_rows if row["mainnodeid"] == "120")
    assert "t03_t04_same_mainnodeid" in conflict_row["conflict_reason"]
    assert artifacts.conflict_count >= 1


def test_kind_mapping_and_unanchored_surfaces_are_skipped(tmp_path: Path) -> None:
    artifacts = _run(
        tmp_path,
        t02_features=[
            _feature({"id": "t02_anchor", "mainnodeid": "2"}, 0, 0),
            _feature({"id": "t02_no_mainnode"}, 10, 0),
        ],
        t03_features=[
            _feature({"id": "t03_4", "mainnodeid": "4", "kind_2": 4, "step7_state": "accepted"}, 20, 0),
            _feature({"id": "t03_2048", "mainnodeid": "2048", "kind_2": 2048, "step7_state": "accepted"}, 40, 0),
            _feature({"id": "t03_no_mainnode", "kind_2": 4, "step7_state": "accepted"}, 50, 0),
        ],
        t04_features=[
            _feature({"id": "t04_8", "mainnodeid": "8", "kind_2": 8, "final_state": "accepted"}, 60, 0),
            _feature({"id": "t04_16", "mainnodeid": "16", "kind_2": 16, "final_state": "accepted"}, 80, 0),
            _feature({"id": "t04_128", "mainnodeid": "128", "kind_2": 128, "final_state": "accepted"}, 100, 0),
        ],
    )

    by_id = {row["surface_id"]: row for row in _read_props(artifacts.surface_path)}
    assert by_id["JAS:2"]["junction_type"] == "rcsd_intersection"
    assert by_id["JAS:4"]["junction_type"] == "center_junction"
    assert by_id["JAS:2048"]["junction_type"] == "single_sided_t_mouth"
    assert by_id["JAS:8"]["junction_type"] == "merge"
    assert by_id["JAS:16"]["junction_type"] == "diverge"
    assert by_id["JAS:128"]["junction_type"] == "complex_divmerge"
    skipped_rows = _read_skipped_json(artifacts.skipped_json_path)
    skipped_ids = {row["source_feature_id"] for row in skipped_rows}
    assert {"t02_no_mainnode", "t03_no_mainnode"}.issubset(skipped_ids)
    assert all(row["mainnodeid"] for row in _read_props(artifacts.surface_path))


def test_patch_id_source_nodes_lookup_and_conflict_audit(tmp_path: Path) -> None:
    artifacts = _run(
        tmp_path,
        t02_features=[
            _feature({"id": "rcsd_500", "nodeid": "500"}, 0, 0),
            _feature({"id": "rcsd_600", "mainnodeid": "600", "patch_id": "T02_PATCH"}, 60, 0),
        ],
        t03_features=[
            _feature({"id": "t03_500", "mainnodeid": "500", "step7_state": "accepted"}, 1, 0),
            _feature({"id": "t03_600", "mainnodeid": "600", "kind_2": 4, "patch_id": "T03_PATCH", "step7_state": "accepted"}, 61, 0),
        ],
        nodes_features=[
            _feature({"id": "500", "mainnodeid": "500", "kind_2": 4, "patch_id": "NODE_PATCH"}, 0, 0),
        ],
    )

    by_id = {row["surface_id"]: row for row in _read_props(artifacts.surface_path)}
    assert by_id["JAS:500"]["patch_id"] == "NODE_PATCH"
    assert by_id["JAS:500"]["kind_2"] == 4
    assert by_id["JAS:500"]["junction_type"] == "center_junction"
    assert by_id["JAS:600"]["patch_id"] == "T03_PATCH"
    conflict_row = next(row for row in _read_audit_json(artifacts.audit_json_path) if row["mainnodeid"] == "600")
    assert "patch_id_conflict" in conflict_row["conflict_reason"]


def test_phase_boundary_outputs_and_inputs_are_not_modified(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    t02_path = _write(input_root / "rcsdintersection.gpkg", [_feature({"id": "rcsd_1"}, 0, 0)])
    nodes_path = _write(input_root / "nodes.gpkg", [_feature({"id": "n1", "mainnodeid": "n1"}, 0, 0)])
    before = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in (t02_path, nodes_path)}

    artifacts = run_t05_junction_surface_fusion(
        t02_rcsdintersection_path=t02_path,
        t03_surface_path=None,
        t04_surface_path=None,
        nodes_path=nodes_path,
        out_root=tmp_path / "out",
        run_id="run",
    )

    after = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in (t02_path, nodes_path)}
    assert after == before
    forbidden_names = {
        "intersection_match_all.geojson",
        "rcsdroad_split.gpkg",
        "rcsd_node_insert.gpkg",
        "nodes_insert.gpkg",
    }
    assert not any((artifacts.run_root / name).exists() for name in forbidden_names)


def _read_audit_json(path: Path) -> list[dict]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def _read_skipped_json(path: Path | None) -> list[dict]:
    import json

    assert path is not None
    return json.loads(path.read_text(encoding="utf-8"))["rows"]
