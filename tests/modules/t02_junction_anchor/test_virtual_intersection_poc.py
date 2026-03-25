from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, box, shape
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    BranchEvidence,
    ParsedRoad,
    _has_structural_side_branch,
    _select_positive_rc_road_ids,
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


def _write_poc_inputs(
    tmp_path: Path,
    *,
    representative_overrides: dict[str, object] | None = None,
    rc_west_inside: bool = True,
    include_rc_group: bool = True,
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
    write_vector(
        rcsdroad_path,
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
                "properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2},
                "geometry": LineString([(0.0, 0.0), (45.0, 0.0)]),
            },
            {
                "properties": {"id": "rc_west", "snodeid": "904", "enodeid": "100", "direction": 2},
                "geometry": west_geometry,
            },
        ],
        crs_text="EPSG:3857",
    )

    rcsdnode_features = [
        {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
        {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
        {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
        {"properties": {"id": "904", "mainnodeid": None}, "geometry": Point(-18.0 if rc_west_inside else -40.0, 0.0 if rc_west_inside else 30.0)},
    ]
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


def test_virtual_intersection_poc_fails_when_mainnodeid_missing(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="missing", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False
    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert audit_doc[0]["reason"] == "mainnodeid_not_found"


def test_virtual_intersection_poc_fails_when_target_out_of_scope(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, representative_overrides={"is_anchor": "yes"})
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] == "mainnodeid_out_of_scope"


def test_virtual_intersection_poc_review_mode_bypasses_anchor_gate(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, representative_overrides={"is_anchor": "yes"})
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        review_mode=True,
        **paths,
    )
    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["review_mode"] is True
    assert "review_anchor_gate_bypassed" in status_doc["risks"]


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


def test_virtual_intersection_poc_review_mode_soft_excludes_rc_outside_drivezone(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, rc_west_inside=False)
    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid="100",
        out_root=tmp_path / "out",
        review_mode=True,
        **paths,
    )
    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["review_mode"] is True
    assert "review_rc_outside_drivezone_excluded" in status_doc["risks"]
    assert status_doc["counts"]["review_excluded_rcsdroad_count"] >= 1

    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert any(row["reason"] == "review_rc_outside_drivezone_excluded" for row in audit_doc)

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert "rc_west" not in associated_road_ids


def test_virtual_intersection_poc_without_rc_group_still_associates_rc_roads(tmp_path: Path) -> None:
    paths = _write_poc_inputs(tmp_path, include_rc_group=False)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] in {"stable", "ambiguous_rc_match"}

    associated_roads_doc = _load_vector_doc(artifacts.associated_rcsdroad_path)
    associated_road_ids = {feature["properties"]["id"] for feature in associated_roads_doc["features"]}
    assert associated_road_ids


def test_virtual_intersection_poc_uses_compound_center_when_short_link_neighbor_forms_main_axis(tmp_path: Path) -> None:
    paths = _write_compound_center_inputs(tmp_path)
    artifacts = run_t02_virtual_intersection_poc(mainnodeid="100", out_root=tmp_path / "out", **paths)
    assert artifacts.success is True

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["status"] in {"stable", "surface_only"}

    branch_doc = json.loads(artifacts.branch_evidence_json_path.read_text(encoding="utf-8"))
    road_branches = branch_doc["branches"]
    assert sum(1 for item in road_branches if item["is_main_direction"]) == 2

    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert any(row["reason"] == "compound_center_applied" for row in audit_doc)


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
