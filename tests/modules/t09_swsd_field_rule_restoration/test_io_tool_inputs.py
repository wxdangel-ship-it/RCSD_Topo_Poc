from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.io import load_t09_inputs


def _node(node_id: str, x: float, y: float, *, kind_2: int = 1, mainnodeid: str | None = None) -> dict:
    return {
        "properties": {"id": node_id, "mainnodeid": mainnodeid, "kind_2": kind_2},
        "geometry": Point(x, y),
    }


def _road(
    road_id: str,
    snodeid: str,
    enodeid: str,
    direction: int,
    coords: list[tuple[float, float]],
) -> dict:
    return {
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "formway": 0,
            "kind": "0101",
        },
        "geometry": LineString(coords),
    }


def test_load_t08_tool7_tool8_outputs_as_t09_inputs(tmp_path: Path) -> None:
    swnode_gpkg = tmp_path / "nodes.gpkg"
    swroad_gpkg = tmp_path / "roads.gpkg"
    segment_gpkg = tmp_path / "segment.gpkg"
    restriction_gpkg = tmp_path / "sw_restriction_tool7.gpkg"
    arrow_gpkg = tmp_path / "sw_arrow_tool8.gpkg"
    write_gpkg(
        swnode_gpkg,
        [
            _node("j1", 0.0, 0.0, kind_2=4),
            _node("j1_sub", 0.0, 1.0, kind_2=0, mainnodeid="j1"),
            _node("n_w", -10.0, 0.0),
            _node("n_n", 0.0, 10.0),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        swroad_gpkg,
        [
            _road("in_w", "n_w", "j1", 2, [(-10.0, 0.0), (0.0, 0.0)]),
            _road("out_n", "j1", "n_n", 2, [(0.0, 0.0), (0.0, 10.0)]),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        segment_gpkg,
        [
            {
                "properties": {
                    "id": "seg_1",
                    "sgrade": "0-2双",
                    "pair_nodes": "n_w,n_n",
                    "junc_nodes": "j1,j1_sub",
                    "roads": "in_w,out_n",
                },
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0), (0.0, 10.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        restriction_gpkg,
        [
            {
                "properties": {"CondType": 1, "inLinkID": "in_w", "outLinkID": "out_n"},
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0), (0.0, 10.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        arrow_gpkg,
        [
            {
                "properties": {
                    "linkid": "in_w",
                    "lane_dir": 2,
                    "road_direction": 2,
                    "arrow": "a,0,o",
                    "lane_count": 3,
                    "seq_start": 1,
                    "seq_end": 3,
                    "source_arrow_dir": "a|0|o",
                },
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )

    loaded = load_t09_inputs(
        swnode_gpkg=swnode_gpkg,
        swroad_gpkg=swroad_gpkg,
        segment_gpkg=segment_gpkg,
        restriction_gpkg=restriction_gpkg,
        arrow_gpkg=arrow_gpkg,
    )

    assert loaded.junction_member_node_ids == {"j1": ("j1", "j1_sub")}
    assert loaded.segments[0].junc_nodes == ("j1", "j1_sub")
    assert loaded.segment_geometries["seg_1"].equals(LineString([(-10.0, 0.0), (0.0, 0.0), (0.0, 10.0)]))
    assert loaded.restrictions[0].in_link_id == "in_w"
    assert loaded.restrictions[0].out_link_id == "out_n"
    assert loaded.arrows[0].road_id == "in_w"
    assert loaded.arrows[0].lane_codes == ("a", "0", "o")
    assert loaded.arrows[0].geometry_match_method == "t08_tool8_linkid_directional_geometry"
    assert loaded.input_audit["restrictions"]["in_link_field"] == "inLinkID"
    assert loaded.input_audit["arrows"]["arrow_field"] == "arrow"
