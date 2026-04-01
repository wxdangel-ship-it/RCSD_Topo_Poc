from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import fiona
import numpy as np
from shapely.geometry import LineString, Point, Polygon, box, shape
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    BranchEvidence,
    ParsedNode,
    ParsedRoad,
    _branch_prefers_compact_local_support,
    _can_soft_exclude_outside_rc,
    _branch_has_minimal_local_road_touch,
    _branch_has_positive_rc_gap,
    _branch_has_local_road_mouth,
    _branch_uses_rc_tip_suppression,
    _build_positive_negative_rc_groups,
    _build_polygon_support_from_association,
    _effect_success_acceptance,
    _has_structural_side_branch,
    _local_road_mouth_polygon_length_m,
    _max_nonmain_branch_polygon_length_m,
    _max_selected_side_branch_covered_length_m,
    _polygon_branch_length_m,
    _regularize_virtual_polygon_geometry,
    _rc_gap_branch_polygon_length_m,
    _select_positive_rc_road_ids,
    _status_from_risks,
    run_t02_virtual_intersection_poc,
)


def _load_vector_doc(path: Path) -> dict:
    with fiona.open(path) as src:
        return {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": [
                {
                    "type": "Feature",
                    "properties": dict(feature["properties"]),
                    "geometry": feature["geometry"],
                }
                for feature in src
            ],
        }


def _read_png_rgba(path: Path) -> np.ndarray:
    png_bytes = path.read_bytes()
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    width = None
    height = None
    idat_parts: list[bytes] = []
    while offset < len(png_bytes):
        chunk_length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        payload = png_bytes[offset + 8 : offset + 8 + chunk_length]
        offset += 12 + chunk_length
        if chunk_type == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        elif chunk_type == b"IDAT":
            idat_parts.append(payload)
        elif chunk_type == b"IEND":
            break
    assert width is not None and height is not None
    raw_rows = zlib.decompress(b"".join(idat_parts))
    row_size = 1 + width * 4
    image = np.zeros((height, width, 4), dtype=np.uint8)
    for row_index in range(height):
        row = raw_rows[row_index * row_size : (row_index + 1) * row_size]
        assert row[0] == 0
        image[row_index] = np.frombuffer(row[1:], dtype=np.uint8).reshape((width, 4))
    return image


def _write_poc_inputs(
    tmp_path: Path,
    *,
    representative_overrides: dict[str, object] | None = None,
    rc_west_inside: bool = True,
    include_rc_group: bool = True,
    include_far_outside_rc: bool = False,
) -> dict[str, Path]:
    representative_props = {
        "id": "100",
        "mainnodeid": "100",
        "has_evd": "yes",
        "is_anchor": "no",
        "kind_2": 2048,
        "grade_2": 1,
    }
    if representative_overrides:
        representative_props.update(representative_overrides)

    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": representative_props,
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "101",
                    "mainnodeid": "100",
                    "has_evd": "yes",
                    "is_anchor": representative_props["is_anchor"],
                    "kind_2": representative_props["kind_2"],
                    "grade_2": representative_props["grade_2"],
                },
                "geometry": Point(6.0, 2.0),
            },
        ],
        crs_text="EPSG:3857",
    )

    write_vector(
        roads_path,
        [
            {
                "properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (0.0, 60.0)]),
            },
            {
                "properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2},
                "geometry": LineString([(0.0, -60.0), (0.0, 0.0)]),
            },
            {
                "properties": {"id": "road_east", "snodeid": "100", "enodeid": "400", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (55.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )

    drivezone_geometry = unary_union(
        [
            box(-12.0, -70.0, 12.0, 70.0),
            box(0.0, -12.0, 75.0, 12.0),
            box(-25.0, -8.0, 0.0, 8.0),
        ]
    )
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": drivezone_geometry}],
        crs_text="EPSG:3857",
    )

    west_geometry = LineString([(-18.0, 0.0), (0.0, 0.0)]) if rc_west_inside else LineString([(-40.0, 30.0), (-20.0, 30.0)])
    rcsdroad_features = [
        {
            "properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2},
            "geometry": LineString([(0.0, 0.0), (0.0, 55.0)]),
        },
        {
            "properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2},
            "geometry": LineString([(0.0, -55.0), (0.0, 0.0)]),
        },
        {
            "properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2},
            "geometry": LineString([(0.0, 0.0), (45.0, 0.0)]),
        },
        {
            "properties": {"id": "rc_west", "snodeid": "904", "enodeid": "100", "direction": 2},
            "geometry": west_geometry,
        },
    ]
    if include_far_outside_rc:
        rcsdroad_features.append(
            {
                "properties": {"id": "rc_far_noise", "snodeid": "907", "enodeid": "908", "direction": 2},
                "geometry": LineString([(82.0, 5.0), (94.0, 20.0)]),
            }
        )
    write_vector(rcsdroad_path, rcsdroad_features, crs_text="EPSG:3857")

    rcsdnode_features = [
        {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
        {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
        {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
        {"properties": {"id": "904", "mainnodeid": None}, "geometry": Point(-18.0 if rc_west_inside else -40.0, 0.0 if rc_west_inside else 30.0)},
    ]
    if include_far_outside_rc:
        rcsdnode_features.extend(
            [
                {"properties": {"id": "907", "mainnodeid": None}, "geometry": Point(82.0, 5.0)},
                {"properties": {"id": "908", "mainnodeid": None}, "geometry": Point(94.0, 20.0)},
            ]
        )
    if include_rc_group:
        rcsdnode_features.insert(0, {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)})
    write_vector(rcsdnode_path, rcsdnode_features, crs_text="EPSG:3857")

    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def _write_compound_center_inputs(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {
                    "id": "100",
                    "mainnodeid": None,
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 3,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "101",
                    "mainnodeid": None,
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 3,
                },
                "geometry": Point(12.0, 0.0),
            },
        ],
        crs_text="EPSG:3857",
    )

    write_vector(
        roads_path,
        [
            {
                "properties": {"id": "connector", "snodeid": "101", "enodeid": "100", "direction": 2},
                "geometry": LineString([(12.0, 0.0), (0.0, 0.0)]),
            },
            {
                "properties": {"id": "north", "snodeid": "101", "enodeid": "200", "direction": 2},
                "geometry": LineString([(12.0, 0.0), (12.0, 60.0)]),
            },
            {
                "properties": {"id": "south", "snodeid": "300", "enodeid": "101", "direction": 2},
                "geometry": LineString([(12.0, -60.0), (12.0, 0.0)]),
            },
            {
                "properties": {"id": "east", "snodeid": "101", "enodeid": "400", "direction": 2},
                "geometry": LineString([(12.0, 0.0), (60.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )

    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz"},
                "geometry": unary_union(
                    [
                        box(-6.0, -8.0, 18.0, 8.0),
                        box(4.0, -70.0, 20.0, 70.0),
                        box(12.0, -12.0, 75.0, 12.0),
                    ]
                ),
            }
        ],
        crs_text="EPSG:3857",
    )

    write_vector(
        rcsdroad_path,
        [
            {
                "properties": {"id": "rc_north", "snodeid": "101", "enodeid": "901", "direction": 2},
                "geometry": LineString([(12.0, 0.0), (12.0, 55.0)]),
            },
            {
                "properties": {"id": "rc_south", "snodeid": "902", "enodeid": "101", "direction": 2},
                "geometry": LineString([(12.0, -55.0), (12.0, 0.0)]),
            },
            {
                "properties": {"id": "rc_east", "snodeid": "101", "enodeid": "903", "direction": 2},
                "geometry": LineString([(12.0, 0.0), (45.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )

    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(12.0, 55.0)},
            {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(12.0, -55.0)},
            {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )

    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def _write_support_decoupling_inputs(tmp_path: Path) -> dict[str, Path]:
    paths = _write_poc_inputs(tmp_path, include_rc_group=False)

    write_vector(
        paths["rcsdroad_path"],
        [
            {
                "properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (0.0, 55.0)]),
            },
            {
                "properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2},
                "geometry": LineString([(0.0, -55.0), (0.0, 0.0)]),
            },
            {
                "properties": {"id": "rc_east_primary", "snodeid": "100", "enodeid": "905", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (20.0, 0.0)]),
            },
            {
                "properties": {"id": "rc_east_secondary", "snodeid": "905", "enodeid": "906", "direction": 2},
                "geometry": LineString([(20.0, 0.0), (44.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        paths["rcsdnode_path"],
        [
            {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
            {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
            {"properties": {"id": "905", "mainnodeid": None}, "geometry": Point(20.0, 0.0)},
            {"properties": {"id": "906", "mainnodeid": None}, "geometry": Point(44.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )
    return paths


def test_virtual_intersection_poc_fails_when_mainnodeid_missing(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="missing", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False
    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert audit_doc[0]["reason"] == "mainnodeid_not_found"


def test_virtual_intersection_poc_fails_when_target_out_of_scope(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, representative_overrides={"kind_2": 1})
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "mainnodeid_out_of_scope"


def test_virtual_intersection_poc_writes_debug_render_for_target_out_of_scope_failure(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, representative_overrides={"kind_2": 1})
    render_root = tmp_path / "batch_renders"
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        debug=True,
        debug_render_root=render_root,
        **paths,
    )
    assert artifacts.success is False
    assert artifacts.rendered_map_path == render_root / "100.png"
    assert artifacts.rendered_map_path.is_file()
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "mainnodeid_out_of_scope"
    assert status_doc["output_files"]["rendered_map_png"] == str(render_root / "100.png")


def test_virtual_intersection_poc_accepts_existing_anchor_status_for_explicit_case(tmp_path: Path) -> None:
    for anchor_status in ("yes", "fail1"):
        paths = _write_poc_inputs(tmp_path / anchor_status, representative_overrides={"is_anchor": anchor_status})
        artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
        assert artifacts.success is True
        status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
        assert status_doc["status"] == "stable"
        assert status_doc["risks"] == []


def test_virtual_intersection_poc_generates_polygon_branch_evidence_and_rc_associations(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is True

    polygon_doc = _load_vector_doc(artifacts.virtual_polygon_path)
    polygon = shape(polygon_doc["features"][0]["geometry"])
    assert polygon.area > 100.0
    assert polygon.area / polygon.convex_hull.area > 0.65
    assert polygon.buffer(0.5).covers(Point(6.0, 2.0))
    assert polygon.buffer(0.5).covers(Point(0.0, 55.0))
    assert polygon.buffer(0.5).covers(Point(0.0, -55.0))
    assert polygon.buffer(0.5).covers(Point(45.0, 0.0))

    branch_doc = json.loads(artifacts.branch_evidence_json_path.read_text(encoding="utf-8"))
    road_branches = branch_doc["branches"]
    assert len(road_branches) >= 3
    assert sum(1 for item in road_branches if item["is_main_direction"]) == 2
    assert any(item["evidence_level"] in {"arm_partial", "arm_full_rc"} for item in road_branches if not item["is_main_direction"])

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "stable"

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert {"rc_north", "rc_south", "rc_east"} <= associated_road_ids
    assert "rc_west" not in associated_road_ids

    associated_nodes_doc = _load_vector_doc(artifacts.associated_rcsdnode_path)
    associated_node_ids = {feature["properties"]["id"] for feature in associated_nodes_doc["features"]}
    assert {"100", "901", "902", "903"} <= associated_node_ids


def test_virtual_intersection_poc_writes_debug_render_to_explicit_root(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path)
    render_root = tmp_path / "batch_renders"
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        debug=True,
        debug_render_root=render_root,
        **paths,
    )
    assert artifacts.success is True
    assert artifacts.rendered_map_path == render_root / "100.png"
    assert artifacts.rendered_map_path.is_file()


def test_virtual_intersection_poc_errors_when_rc_outside_drivezone(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False
    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert audit_doc[0]["reason"] == "rc_outside_drivezone"


def test_virtual_intersection_poc_writes_debug_render_for_rc_outside_drivezone_failure(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)
    render_root = tmp_path / "batch_renders"
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        debug=True,
        debug_render_root=render_root,
        **paths,
    )
    assert artifacts.success is False
    assert artifacts.rendered_map_path == render_root / "100.png"
    assert artifacts.rendered_map_path.is_file()
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "rc_outside_drivezone"
    assert status_doc["output_files"]["rendered_map_png"] == str(render_root / "100.png")


def test_virtual_intersection_poc_review_mode_soft_excludes_rc_outside_drivezone(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        review_mode=True,
        **paths,
    )
    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["flow_success"] is True
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["review_mode"] is True
    assert "review_rc_outside_drivezone_excluded" in status_doc["risks"]
    assert status_doc["counts"]["review_excluded_rcsdroad_count"] >= 1

    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert any(row["reason"] == "review_rc_outside_drivezone_excluded" for row in audit_doc)

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert "rc_west" not in associated_road_ids


def test_virtual_intersection_poc_writes_failure_styled_render_when_effect_not_accepted(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)
    render_root = tmp_path / "batch_renders"
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        debug=True,
        debug_render_root=render_root,
        review_mode=True,
        **paths,
    )
    assert artifacts.success is False
    assert artifacts.rendered_map_path == render_root / "100.png"
    assert artifacts.rendered_map_path.is_file()
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["flow_success"] is True
    assert status_doc["success"] is False
    assert status_doc["acceptance_class"] == "review_required"
    image = _read_png_rgba(artifacts.rendered_map_path)
    assert tuple(image[0, 0]) == (144, 0, 0, 255)


def test_virtual_intersection_poc_ignores_far_rc_outside_drivezone_noise(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, include_far_outside_rc=True)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "stable"
    assert status_doc["risks"] == []

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert "rc_far_noise" not in associated_road_ids


def test_virtual_intersection_poc_without_rc_group_still_associates_rc_roads(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, include_rc_group=False)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] in {"stable", "ambiguous_rc_match"}
    assert artifacts.success is (status_doc["status"] == "stable")

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert associated_road_ids


def test_virtual_intersection_poc_uses_compound_center_when_short_link_neighbor_forms_main_axis(tmp_path: Path) -> None:
    paths = _write_compound_center_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] in {"stable", "surface_only"}
    assert artifacts.success is (status_doc["status"] == "stable")

    branch_doc = json.loads(artifacts.branch_evidence_json_path.read_text(encoding="utf-8"))
    road_branches = branch_doc["branches"]
    assert sum(1 for item in road_branches if item["is_main_direction"]) == 2

    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert any(row["reason"] == "compound_center_applied" for row in audit_doc)

    polygon_doc = _load_vector_doc(artifacts.virtual_polygon_path)
    polygon = shape(polygon_doc["features"][0]["geometry"])
    assert polygon.buffer(0.5).covers(Point(0.0, 0.0))


def test_virtual_intersection_poc_polygon_support_can_expand_beyond_conservative_association(tmp_path: Path) -> None:
    paths = _write_support_decoupling_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is True

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert "rc_east_secondary" not in associated_road_ids

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["counts"]["polygon_support_rcsdroad_count"] >= status_doc["counts"]["associated_rcsdroad_count"]

    polygon_doc = _load_vector_doc(artifacts.virtual_polygon_path)
    polygon = shape(polygon_doc["features"][0]["geometry"])
    assert polygon.buffer(0.5).covers(Point(10.0, 0.0))


def test_status_from_risks_marks_node_component_conflict_before_stable() -> None:
    assert _status_from_risks(["node_component_conflict"], has_associated_roads=True) == "node_component_conflict"


def test_effect_success_acceptance_promotes_supported_gap_cases_and_keeps_weak_gap_under_review() -> None:
    assert _effect_success_acceptance(
        status="stable",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=1,
        polygon_support_rc_road_count=1,
    ) == (True, "accepted", "stable")
    assert _effect_success_acceptance(
        status="no_valid_rc_connection",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
    ) == (False, "review_required", "rc_gap_without_substantive_nonmain_branch_coverage")
    assert _effect_success_acceptance(
        status="no_valid_rc_connection",
        review_mode=False,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=4.0,
        associated_rc_road_count=0,
        polygon_support_rc_road_count=0,
    ) == (True, "accepted", "rc_gap_with_nonmain_branch_polygon_coverage")
    assert _effect_success_acceptance(
        status="node_component_conflict",
        review_mode=False,
        max_selected_side_branch_covered_length_m=19.0,
        max_nonmain_branch_polygon_length_m=14.0,
        associated_rc_road_count=2,
        polygon_support_rc_road_count=2,
    ) == (True, "accepted", "node_component_conflict_with_strong_rc_supported_side_coverage")
    assert _effect_success_acceptance(
        status="node_component_conflict",
        review_mode=False,
        max_selected_side_branch_covered_length_m=8.0,
        max_nonmain_branch_polygon_length_m=14.0,
        associated_rc_road_count=2,
        polygon_support_rc_road_count=2,
    ) == (False, "review_required", "review_required_status:node_component_conflict")
    assert _effect_success_acceptance(
        status="stable",
        review_mode=True,
        max_selected_side_branch_covered_length_m=0.0,
        max_nonmain_branch_polygon_length_m=0.0,
        associated_rc_road_count=1,
        polygon_support_rc_road_count=1,
    ) == (False, "review_required", "review_mode")


def test_max_selected_side_branch_covered_length_ignores_main_and_edge_only_branches() -> None:
    polygon = box(-6.0, -6.0, 12.0, 6.0)
    local_roads = [
        ParsedRoad(0, {}, LineString([(0.0, 0.0), (0.0, 40.0)]), "main_1", "100", "200", 2),
        ParsedRoad(1, {}, LineString([(0.0, 0.0), (0.0, -40.0)]), "main_2", "300", "100", 2),
        ParsedRoad(2, {}, LineString([(0.0, 0.0), (20.0, 0.0)]), "side_selected", "100", "400", 2),
        ParsedRoad(3, {}, LineString([(0.0, 0.0), (-20.0, 0.0)]), "side_edge_only", "500", "100", 2),
    ]
    road_branches = [
        BranchEvidence(
            branch_id="road_1",
            angle_deg=90.0,
            branch_type="road",
            road_ids=["main_1"],
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_full_rc",
        ),
        BranchEvidence(
            branch_id="road_2",
            angle_deg=270.0,
            branch_type="road",
            road_ids=["main_2"],
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_full_rc",
        ),
        BranchEvidence(
            branch_id="road_3",
            angle_deg=0.0,
            branch_type="road",
            road_ids=["side_selected"],
            is_main_direction=False,
            selected_for_polygon=True,
            evidence_level="arm_partial",
        ),
        BranchEvidence(
            branch_id="road_4",
            angle_deg=180.0,
            branch_type="road",
            road_ids=["side_edge_only"],
            is_main_direction=False,
            selected_for_polygon=True,
            evidence_level="edge_only",
        ),
    ]

    covered_length_m = _max_selected_side_branch_covered_length_m(
        polygon_geometry=polygon,
        road_branches=road_branches,
        local_roads=local_roads,
    )

    assert round(covered_length_m, 3) == 12.0


def test_max_nonmain_branch_polygon_length_includes_edge_only_nonmain_coverage() -> None:
    road_branches = [
        BranchEvidence(
            branch_id="road_1",
            angle_deg=90.0,
            branch_type="road",
            is_main_direction=True,
            polygon_length_m=18.0,
        ),
        BranchEvidence(
            branch_id="road_2",
            angle_deg=0.0,
            branch_type="road",
            is_main_direction=False,
            selected_for_polygon=False,
            evidence_level="edge_only",
            polygon_length_m=7.544,
        ),
        BranchEvidence(
            branch_id="road_3",
            angle_deg=180.0,
            branch_type="road",
            is_main_direction=False,
            selected_for_polygon=True,
            evidence_level="arm_partial",
            polygon_length_m=10.0,
        ),
    ]

    assert _max_nonmain_branch_polygon_length_m(road_branches=road_branches) == 10.0


def test_build_positive_negative_rc_groups_deduplicates_same_group_top_candidates() -> None:
    road_branches = [
        BranchEvidence(
            branch_id="road_1",
            angle_deg=210.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            drivezone_support_m=100.0,
            rc_support_m=100.0,
        ),
        BranchEvidence(
            branch_id="road_2",
            angle_deg=30.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            drivezone_support_m=100.0,
            rc_support_m=100.0,
        ),
    ]
    road_branches[0].rcsdroad_ids = ["rc_group_1", "rc_group_2"]
    road_branches[1].rcsdroad_ids = ["rc_group_1", "rc_group_2"]
    rc_branches = [
        BranchEvidence(branch_id="rc_group_1", angle_deg=30.0, branch_type="rc_group", road_support_m=91.119),
        BranchEvidence(branch_id="rc_group_2", angle_deg=208.0, branch_type="rc_group", road_support_m=359.034),
    ]
    risks: list[str] = []

    positive, negative = _build_positive_negative_rc_groups(
        kind_2=2048,
        road_branches=road_branches,
        rc_branches=rc_branches,
        risks=risks,
        has_rc_group_nodes=False,
    )

    assert positive == {"rc_group_2"}
    assert negative == {"rc_group_1"}
    assert "ambiguous_rc_match" not in risks


def test_build_polygon_support_from_association_clears_orphan_support_nodes() -> None:
    group_nodes = [
        ParsedNode(
            feature_index=0,
            properties={},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=2048,
            grade_2=1,
        )
    ]
    local_rc_nodes = [
        ParsedNode(0, {}, Point(80.0, 0.0), "901", None, None, None, None, None),
        ParsedNode(1, {}, Point(140.0, 0.0), "902", None, None, None, None, None),
    ]
    local_rc_roads = [
        ParsedRoad(0, {}, LineString([(80.0, 0.0), (140.0, 0.0)]), "rc_far", "901", "902", 2),
    ]

    support_road_ids, support_node_ids, orphan_positive_support = _build_polygon_support_from_association(
        positive_rc_road_ids={"rc_far"},
        base_support_node_ids=set(),
        excluded_rc_road_ids=set(),
        local_rc_roads=local_rc_roads,
        local_rc_nodes=local_rc_nodes,
        group_nodes=group_nodes,
    )

    assert orphan_positive_support is True
    assert support_road_ids == set()
    assert support_node_ids == set()


def test_build_polygon_support_from_association_skips_extension_when_positive_road_lacks_both_local_endpoints() -> None:
    group_nodes = [
        ParsedNode(
            feature_index=0,
            properties={},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=2048,
            grade_2=1,
        )
    ]
    local_rc_nodes = [
        ParsedNode(0, {}, Point(8.0, 0.0), "near", None, None, None, None, None),
        ParsedNode(1, {}, Point(24.0, 0.0), "ext", None, None, None, None, None),
    ]
    local_rc_roads = [
        ParsedRoad(0, {}, LineString([(60.0, 0.0), (8.0, 0.0)]), "rc_main", "far_missing", "near", 2),
        ParsedRoad(1, {}, LineString([(8.0, 0.0), (24.0, 0.0)]), "rc_ext", "near", "ext", 2),
    ]

    support_road_ids, support_node_ids, orphan_positive_support = _build_polygon_support_from_association(
        positive_rc_road_ids={"rc_main"},
        base_support_node_ids=set(),
        excluded_rc_road_ids=set(),
        local_rc_roads=local_rc_roads,
        local_rc_nodes=local_rc_nodes,
        group_nodes=group_nodes,
    )

    assert orphan_positive_support is False
    assert support_road_ids == {"rc_main"}
    assert "rc_ext" not in support_road_ids
    assert support_node_ids == {"near"}


def test_build_polygon_support_from_association_filters_far_endpoint_nodes() -> None:
    group_nodes = [
        ParsedNode(
            feature_index=0,
            properties={},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=2048,
            grade_2=1,
        )
    ]
    local_rc_nodes = [
        ParsedNode(0, {}, Point(18.0, 0.0), "near", None, None, None, None, None),
        ParsedNode(1, {}, Point(48.0, 0.0), "far", None, None, None, None, None),
    ]
    local_rc_roads = [
        ParsedRoad(0, {}, LineString([(18.0, 0.0), (48.0, 0.0)]), "rc_main", "near", "far", 2),
    ]

    support_road_ids, support_node_ids, orphan_positive_support = _build_polygon_support_from_association(
        positive_rc_road_ids={"rc_main"},
        base_support_node_ids=set(),
        excluded_rc_road_ids=set(),
        local_rc_roads=local_rc_roads,
        local_rc_nodes=local_rc_nodes,
        group_nodes=group_nodes,
    )

    assert orphan_positive_support is False
    assert support_road_ids == {"rc_main"}
    assert support_node_ids == {"near"}


def test_build_polygon_support_from_association_allows_single_sided_local_connector() -> None:
    group_nodes = [
        ParsedNode(
            feature_index=0,
            properties={},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=2048,
            grade_2=1,
        )
    ]
    local_rc_nodes = [
        ParsedNode(0, {}, Point(8.0, 0.0), "near", None, None, None, None, None),
        ParsedNode(1, {}, Point(4.0, 9.0), "branch_tip", None, None, None, None, None),
    ]
    local_rc_roads = [
        ParsedRoad(0, {}, LineString([(50.0, -40.0), (8.0, 0.0)]), "rc_main", "far_missing", "near", 2),
        ParsedRoad(1, {}, LineString([(8.0, 0.0), (4.0, 9.0)]), "rc_branch", "near", "branch_tip", 2),
    ]

    support_road_ids, support_node_ids, orphan_positive_support = _build_polygon_support_from_association(
        positive_rc_road_ids={"rc_main"},
        base_support_node_ids=set(),
        excluded_rc_road_ids=set(),
        local_rc_roads=local_rc_roads,
        local_rc_nodes=local_rc_nodes,
        group_nodes=group_nodes,
    )

    assert orphan_positive_support is False
    assert support_road_ids == {"rc_main", "rc_branch"}
    assert support_node_ids == {"near", "branch_tip"}


def test_virtual_intersection_poc_writes_debug_rendered_map_when_enabled(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        debug=True,
        **paths,
    )
    assert artifacts.success is True
    assert artifacts.rendered_map_path is not None
    assert artifacts.rendered_map_path.is_file()
    assert artifacts.rendered_map_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_virtual_intersection_poc_accepts_no_valid_rc_connection_when_polygon_preserves_nonmain_branch_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _write_poc_inputs(tmp_path)

    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc._select_positive_rc_road_ids",
        lambda **_: ({"missing_rc"}, set(), set()),
    )
    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc._build_polygon_support_from_association",
        lambda **_: (set(), set(), False),
    )

    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", debug=True, **paths)

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["flow_success"] is True
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["acceptance_reason"] == "rc_gap_with_nonmain_branch_polygon_coverage"
    assert status_doc["status"] == "no_valid_rc_connection"


def test_virtual_intersection_poc_can_soft_exclude_outside_rc_and_accept_when_nonmain_branch_coverage_remains(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)

    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc._select_positive_rc_road_ids",
        lambda **_: ({"missing_rc"}, set(), set()),
    )
    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc._build_polygon_support_from_association",
        lambda **_: (set(), set(), False),
    )

    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", debug=True, **paths)

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["flow_success"] is True
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["acceptance_reason"] == "rc_gap_with_nonmain_branch_polygon_coverage"
    assert status_doc["status"] == "no_valid_rc_connection"


def test_has_structural_side_branch_requires_real_side_support() -> None:
    weak_side = BranchEvidence(
        branch_id="road_3",
        angle_deg=300.0,
        branch_type="road",
        road_support_m=15.0,
        drivezone_support_m=4.0,
        rc_support_m=0.0,
        is_main_direction=False,
        selected_for_polygon=False,
        evidence_level="edge_only",
    )
    strong_side = BranchEvidence(
        branch_id="road_4",
        angle_deg=140.0,
        branch_type="road",
        road_support_m=32.0,
        drivezone_support_m=24.0,
        rc_support_m=0.0,
        is_main_direction=False,
        selected_for_polygon=True,
        evidence_level="arm_partial",
    )
    assert _has_structural_side_branch([weak_side]) is False
    assert _has_structural_side_branch([weak_side, strong_side]) is True


def test_select_positive_rc_road_ids_keeps_dual_centered_roads_for_non_t_case() -> None:
    center = Point(0.0, 0.0)
    road_a = ParsedRoad(
        feature_index=0,
        properties={},
        geometry=LineString([(8.0, 8.0), (-30.0, -30.0)]),
        road_id="road_a",
        snodeid="a1",
        enodeid="a2",
        direction=2,
    )
    road_b = ParsedRoad(
        feature_index=1,
        properties={},
        geometry=LineString([(8.0, -8.0), (-30.0, 30.0)]),
        road_id="road_b",
        snodeid="b1",
        enodeid="b2",
        direction=2,
    )
    side_candidate = ParsedRoad(
        feature_index=2,
        properties={},
        geometry=LineString([(8.0, -8.0), (28.0, -28.0)]),
        road_id="side_candidate",
        snodeid="b1",
        enodeid="c1",
        direction=2,
    )
    rc_branch = BranchEvidence(
        branch_id="rc_group_1",
        angle_deg=225.0,
        branch_type="rc_group",
        road_ids=["road_a", "road_b"],
    )
    road_branches = [
        BranchEvidence(
            branch_id="road_1",
            angle_deg=45.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_full_rc",
            drivezone_support_m=100.0,
            road_support_m=100.0,
        ),
        BranchEvidence(
            branch_id="road_2",
            angle_deg=225.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_full_rc",
            drivezone_support_m=100.0,
            road_support_m=100.0,
        ),
        BranchEvidence(
            branch_id="road_3",
            angle_deg=300.0,
            branch_type="road",
            is_main_direction=False,
            selected_for_polygon=False,
            evidence_level="edge_only",
            drivezone_support_m=4.0,
            road_support_m=10.0,
        ),
    ]
    positive_ids, adjacent_ids, excluded_ids = _select_positive_rc_road_ids(
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        local_rc_roads=[road_a, road_b, side_candidate],
        center=center,
        road_branches=road_branches,
    )
    assert positive_ids == {"road_a", "road_b"}
    assert adjacent_ids == set()
    assert excluded_ids == set()


def test_select_positive_rc_road_ids_prefers_proximal_terminal_spur_over_distal_spur() -> None:
    center = Point(0.0, 0.0)
    selected = ParsedRoad(
        feature_index=0,
        properties={},
        geometry=LineString([(10.0, 0.0), (-25.0, 25.0)]),
        road_id="selected",
        snodeid="n1",
        enodeid="n2",
        direction=2,
    )
    proximal_spur = ParsedRoad(
        feature_index=1,
        properties={},
        geometry=LineString([(10.0, 0.0), (12.0, 18.0)]),
        road_id="proximal_spur",
        snodeid="n1",
        enodeid="n3",
        direction=2,
    )
    distal_spur = ParsedRoad(
        feature_index=2,
        properties={},
        geometry=LineString([(-25.0, 25.0), (-45.0, 28.0)]),
        road_id="distal_spur",
        snodeid="n2",
        enodeid="n4",
        direction=2,
    )
    rc_branch = BranchEvidence(
        branch_id="rc_group_1",
        angle_deg=135.0,
        branch_type="rc_group",
        road_ids=["selected"],
    )
    road_branches = [
        BranchEvidence(
            branch_id="road_main_a",
            angle_deg=315.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_partial",
            drivezone_support_m=80.0,
            road_support_m=80.0,
        ),
        BranchEvidence(
            branch_id="road_main_b",
            angle_deg=135.0,
            branch_type="road",
            is_main_direction=True,
            selected_for_polygon=True,
            evidence_level="arm_partial",
            drivezone_support_m=80.0,
            road_support_m=80.0,
        ),
        BranchEvidence(
            branch_id="road_side",
            angle_deg=90.0,
            branch_type="road",
            is_main_direction=False,
            selected_for_polygon=True,
            evidence_level="arm_partial",
            drivezone_support_m=20.0,
            road_support_m=20.0,
        ),
    ]
    positive_ids, adjacent_ids, excluded_ids = _select_positive_rc_road_ids(
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        local_rc_roads=[selected, proximal_spur, distal_spur],
        center=center,
        road_branches=road_branches,
    )
    assert positive_ids == {"selected"}
    assert adjacent_ids == {"proximal_spur"}
    assert "distal_spur" in excluded_ids


def test_branch_uses_rc_tip_suppression_requires_supported_positive_group() -> None:
    branch = BranchEvidence(
        branch_id="road_side",
        angle_deg=90.0,
        branch_type="road",
        rcsdroad_ids=["rc_group_1"],
    )
    rc_branch = BranchEvidence(
        branch_id="rc_group_1",
        angle_deg=90.0,
        branch_type="rc_group",
        road_ids=["rc_1", "rc_2"],
    )

    assert _branch_uses_rc_tip_suppression(
        branch=branch,
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids=set(),
    ) is False

    assert _branch_uses_rc_tip_suppression(
        branch=branch,
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids={"rc_2"},
    ) is True


def test_branch_uses_rc_tip_suppression_keeps_negative_group_suppressed() -> None:
    branch = BranchEvidence(
        branch_id="road_side",
        angle_deg=90.0,
        branch_type="road",
        rcsdroad_ids=["rc_group_1"],
    )
    rc_branch = BranchEvidence(
        branch_id="rc_group_1",
        angle_deg=90.0,
        branch_type="rc_group",
        road_ids=["rc_1"],
    )

    assert _branch_uses_rc_tip_suppression(
        branch=branch,
        positive_rc_groups=set(),
        negative_rc_groups={"rc_group_1"},
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids=set(),
    ) is True


def test_branch_has_positive_rc_gap_requires_positive_group_without_supported_roads() -> None:
    branch = BranchEvidence(
        branch_id="road_side",
        angle_deg=90.0,
        branch_type="road",
        rcsdroad_ids=["rc_group_1"],
    )
    rc_branch = BranchEvidence(
        branch_id="rc_group_1",
        angle_deg=90.0,
        branch_type="rc_group",
        road_ids=["rc_1", "rc_2"],
    )

    assert _branch_has_positive_rc_gap(
        branch=branch,
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids=set(),
    ) is True

    assert _branch_has_positive_rc_gap(
        branch=branch,
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups=set(),
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids={"rc_1"},
    ) is False

    assert _branch_has_positive_rc_gap(
        branch=branch,
        positive_rc_groups={"rc_group_1"},
        negative_rc_groups={"rc_group_1"},
        rc_branch_by_id={"rc_group_1": rc_branch},
        polygon_support_rc_road_ids=set(),
    ) is False


def test_rc_gap_branch_polygon_length_supports_partial_and_edge_only_side_branches() -> None:
    partial_branch = BranchEvidence(
        branch_id="road_partial",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="arm_partial",
        drivezone_support_m=19.5,
        road_support_m=15.0,
    )
    edge_branch = BranchEvidence(
        branch_id="road_edge",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        drivezone_support_m=7.5,
        road_support_m=7.5,
    )

    assert _rc_gap_branch_polygon_length_m(partial_branch) == 12.0
    assert _rc_gap_branch_polygon_length_m(edge_branch) == 6.0


def test_branch_has_local_road_mouth_detects_small_edge_only_side_branch_without_rc_group() -> None:
    local_mouth = BranchEvidence(
        branch_id="road_edge",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=7.5,
        road_support_m=7.5,
    )
    low_drivezone_but_clear_mouth = BranchEvidence(
        branch_id="road_low_drivezone",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=1.1,
        road_support_m=21.0,
        rc_support_m=1.3,
    )
    moderate_drivezone_local_mouth = BranchEvidence(
        branch_id="road_moderate_drivezone",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=4.7,
        road_support_m=17.0,
        rc_support_m=3.1,
    )
    weak_edge = BranchEvidence(
        branch_id="road_weak",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=2.0,
        road_support_m=2.0,
    )
    rc_backed_edge = BranchEvidence(
        branch_id="road_rc_backed",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=7.5,
        road_support_m=7.5,
        rc_support_m=9.0,
    )

    assert _branch_has_local_road_mouth(local_mouth) is True
    assert _branch_has_local_road_mouth(low_drivezone_but_clear_mouth) is True
    assert _branch_has_local_road_mouth(moderate_drivezone_local_mouth) is True
    assert _branch_has_local_road_mouth(weak_edge) is False
    assert _branch_has_local_road_mouth(rc_backed_edge) is False
    assert _local_road_mouth_polygon_length_m(low_drivezone_but_clear_mouth) == 10.0
    assert _local_road_mouth_polygon_length_m(moderate_drivezone_local_mouth) == 10.0


def test_branch_has_minimal_local_road_touch_detects_small_rc_gap_side_branch() -> None:
    weak_edge = BranchEvidence(
        branch_id="road_weak",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=2.3,
        road_support_m=2.3,
        rc_support_m=1.9,
    )
    stronger_edge = BranchEvidence(
        branch_id="road_stronger",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=3.3,
        road_support_m=3.4,
        rc_support_m=2.8,
    )

    assert _branch_has_minimal_local_road_touch(weak_edge) is True
    assert _branch_has_minimal_local_road_touch(stronger_edge) is False


def test_polygon_branch_length_keeps_selected_partial_side_branch_from_being_overcompressed() -> None:
    branch = BranchEvidence(
        branch_id="road_side",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        selected_for_polygon=True,
        evidence_level="arm_partial",
        rcsdroad_ids=[],
        drivezone_support_m=24.1,
        road_support_m=15.6,
        rc_support_m=0.0,
    )

    assert _polygon_branch_length_m(branch) == 10.0


def test_polygon_branch_length_expands_strong_selected_partial_side_branch_without_rc() -> None:
    branch = BranchEvidence(
        branch_id="road_side_strong",
        angle_deg=180.0,
        branch_type="road",
        is_main_direction=False,
        selected_for_polygon=True,
        evidence_level="arm_partial",
        rcsdroad_ids=[],
        drivezone_support_m=100.0,
        road_support_m=231.0,
        rc_support_m=3.8,
    )

    assert _polygon_branch_length_m(branch) == 14.0


def test_branch_prefers_compact_local_support_only_for_weak_local_mouths() -> None:
    weak_local_mouth = BranchEvidence(
        branch_id="road_edge",
        angle_deg=90.0,
        branch_type="road",
        is_main_direction=False,
        selected_for_polygon=False,
        evidence_level="edge_only",
        rcsdroad_ids=[],
        drivezone_support_m=4.7,
        road_support_m=17.0,
        rc_support_m=3.1,
    )
    strong_partial_branch = BranchEvidence(
        branch_id="road_partial",
        angle_deg=180.0,
        branch_type="road",
        is_main_direction=False,
        selected_for_polygon=True,
        evidence_level="arm_partial",
        rcsdroad_ids=[],
        drivezone_support_m=100.0,
        road_support_m=231.0,
        rc_support_m=3.8,
    )

    assert _branch_prefers_compact_local_support(
        weak_local_mouth,
        branch_has_local_road_mouth=True,
        branch_has_minimal_local_road_touch=False,
    ) is True
    assert _branch_prefers_compact_local_support(
        strong_partial_branch,
        branch_has_local_road_mouth=False,
        branch_has_minimal_local_road_touch=False,
    ) is False


def test_can_soft_exclude_outside_rc_only_when_remaining_polygon_evidence_is_strong() -> None:
    assert _can_soft_exclude_outside_rc(
        status="no_valid_rc_connection",
        selected_rc_road_count=0,
        polygon_support_rc_road_count=0,
        max_selected_side_branch_covered_length_m=0.0,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="node_component_conflict",
        selected_rc_road_count=2,
        polygon_support_rc_road_count=2,
        max_selected_side_branch_covered_length_m=19.984,
    ) is True
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=1,
        polygon_support_rc_road_count=1,
        max_selected_side_branch_covered_length_m=20.168,
    ) is False
    assert _can_soft_exclude_outside_rc(
        status="stable",
        selected_rc_road_count=0,
        polygon_support_rc_road_count=0,
        max_selected_side_branch_covered_length_m=0.0,
    ) is False


def test_regularize_virtual_polygon_geometry_keeps_single_seeded_component_without_holes() -> None:
    seeded = box(0.0, 0.0, 6.0, 6.0)
    detached = box(20.0, 0.0, 24.0, 4.0)
    holed = Polygon(
        seeded.exterior.coords,
        [box(1.0, 1.0, 2.0, 2.0).exterior.coords],
    )
    geometry = unary_union([holed, detached])
    drivezone = box(-5.0, -5.0, 30.0, 10.0)
    seed_geometry = box(0.0, 0.0, 1.0, 1.0)

    regularized = _regularize_virtual_polygon_geometry(
        geometry=geometry,
        drivezone_union=drivezone,
        seed_geometry=seed_geometry,
    )

    assert regularized.geom_type == "Polygon"
    assert len(regularized.interiors) == 0
    assert regularized.intersects(seed_geometry)
    assert not regularized.intersects(detached)
