import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import (
    run_t09_decode_text_bundle,
    run_t09_export_step3_input_text_bundle,
)


def _node(node_id: str, x: float, y: float, *, kind_2: int = 0, mainnodeid: str | None = None) -> dict:
    return {
        "properties": {"id": node_id, "mainnodeid": mainnodeid, "kind_2": kind_2},
        "geometry": Point(x, y),
    }


def _road(road_id: str, snodeid: str, enodeid: str, coords: list[tuple[float, float]]) -> dict:
    return {
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": 2,
            "kind": "0101",
            "formway": 0,
        },
        "geometry": LineString(coords),
    }


def _payload(index: int) -> str:
    return hashlib.sha256(f"t09-text-bundle-{index}".encode("ascii")).hexdigest() * 2


def _feature_ids(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [str(item["properties"]["id"]) for item in payload["features"]]


def test_step3_input_text_bundle_slices_frcsd_and_splits_under_size_limit(tmp_path: Path) -> None:
    swsd_root = tmp_path / "swsd"
    t06_step3_root = tmp_path / "t06" / "step3_segment_replacement"
    out_txt = tmp_path / "bundle" / "t09_step3_input_slice_bundle.txt"

    swnode_path = swsd_root / "nodes.gpkg"
    swroad_path = swsd_root / "roads.gpkg"
    segment_path = swsd_root / "segment.gpkg"
    restriction_path = swsd_root / "sw_restriction_tool7.gpkg"
    arrow_path = swsd_root / "sw_arrow_tool8.gpkg"
    frcsd_road_path = t06_step3_root / "t06_frcsd_road.gpkg"
    frcsd_node_path = t06_step3_root / "t06_frcsd_node.gpkg"
    replacement_units_path = t06_step3_root / "t06_step3_replacement_units.gpkg"
    junction_audit_path = t06_step3_root / "t06_step3_junction_rebuild_audit.gpkg"

    write_gpkg(
        swnode_path,
        [
            _node("j1", 0.0, 0.0, kind_2=4),
            _node("n_w", -10.0, 0.0),
            _node("n_e", 10.0, 0.0),
            _node("j_far", 1000.0, 0.0, kind_2=4),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        swroad_path,
        [
            _road("in_w", "n_w", "j1", [(-10.0, 0.0), (0.0, 0.0)]),
            _road("out_e", "j1", "n_e", [(0.0, 0.0), (10.0, 0.0)]),
            _road("far_road", "j_far", "n_far", [(1000.0, 0.0), (1010.0, 0.0)]),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        segment_path,
        [
            {
                "properties": {"id": "seg_near", "pair_nodes": "n_w,n_e", "junc_nodes": "j1", "roads": "in_w,out_e"},
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0), (10.0, 0.0)]),
            },
            {
                "properties": {"id": "seg_far", "pair_nodes": "j_far,n_far", "junc_nodes": "", "roads": "far_road"},
                "geometry": LineString([(1000.0, 0.0), (1010.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        restriction_path,
        [
            {
                "properties": {"CondType": 1, "inLinkID": "in_w", "outLinkID": "out_e"},
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0), (10.0, 0.0)]),
            },
            {
                "properties": {"CondType": 1, "inLinkID": "far_road", "outLinkID": "far_out"},
                "geometry": LineString([(1000.0, 0.0), (1010.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        arrow_path,
        [
            {
                "properties": {"linkid": "in_w", "arrow": "b", "lane_count": 1},
                "geometry": LineString([(-10.0, 0.0), (0.0, 0.0)]),
            },
            {
                "properties": {"linkid": "far_road", "arrow": "a", "lane_count": 1},
                "geometry": LineString([(1000.0, 0.0), (1010.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )

    frcsd_nodes = [
        {"properties": {"id": f"fn_{index}", "mainnodeid": 0, "source": 1}, "geometry": Point(index * 0.2, 2.0)}
        for index in range(80)
    ]
    frcsd_nodes.append({"properties": {"id": "fn_far", "mainnodeid": 0, "source": 1}, "geometry": Point(1000.0, 0.0)})
    write_gpkg(frcsd_node_path, frcsd_nodes, crs_text="EPSG:3857")
    write_gpkg(
        frcsd_road_path,
        [
            {
                "properties": {
                    "id": f"fr_{index}",
                    "snodeid": f"fn_{index}",
                    "enodeid": f"fn_{min(index + 1, 79)}",
                    "source": 1,
                    "audit_payload": _payload(index),
                },
                "geometry": LineString([(index * 0.2, 2.0), (min(index + 1, 79) * 0.2, 2.0)]),
            }
            for index in range(79)
        ]
        + [
            {
                "properties": {"id": "fr_far", "snodeid": "fn_far", "enodeid": "fn_far_2", "source": 1},
                "geometry": LineString([(1000.0, 0.0), (1010.0, 0.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        replacement_units_path,
        [
            {
                "properties": {"id": "unit_near", "swsd_segment_id": "seg_near"},
                "geometry": LineString([(-10.0, 0.0), (10.0, 0.0)]),
            },
            {
                "properties": {"id": "unit_far", "swsd_segment_id": "seg_far"},
                "geometry": LineString([(1000.0, 0.0), (1010.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        junction_audit_path,
        [{"properties": {"id": "junction_audit_without_geometry"}, "geometry": Point(0.0, 0.0)}],
        crs_text="EPSG:3857",
    )
    with sqlite3.connect(junction_audit_path) as conn:
        conn.execute("UPDATE t06_step3_junction_rebuild_audit SET geom = NULL")
        conn.commit()
    (t06_step3_root / "t06_step3_summary.json").write_text(
        json.dumps({"frcsd_road_count": 80, "frcsd_node_count": 81}),
        encoding="utf-8",
    )

    artifacts = run_t09_export_step3_input_text_bundle(
        swnode_path=swnode_path,
        swroad_path=swroad_path,
        segment_path=segment_path,
        restriction_path=restriction_path,
        arrow_path=arrow_path,
        t06_step3_root=t06_step3_root,
        out_txt=out_txt,
        center_x=0.0,
        center_y=0.0,
        size_m=100.0,
        max_text_size_bytes=9_000,
    )

    assert artifacts.success is True, artifacts.failure_detail
    assert len(artifacts.part_txt_paths) > 1
    assert artifacts.max_part_size_bytes <= 9_000
    assert all(path.stat().st_size <= 9_000 for path in artifacts.part_txt_paths)

    decoded = run_t09_decode_text_bundle(
        bundle_txt=artifacts.part_txt_paths[-1],
        out_dir=tmp_path / "decoded",
    )
    summary = json.loads((decoded.out_dir / "slice" / "t09_step3_input_slice_summary.json").read_text(encoding="utf-8"))
    size_report = json.loads((decoded.out_dir / "t09_evidence_size_report.json").read_text(encoding="utf-8"))
    testcase_manifest = json.loads(
        (decoded.out_dir / "audit" / "t09_local_testcase_manifest.json").read_text(encoding="utf-8")
    )

    assert summary["size_m"] == 100.0
    assert summary["radius_m"] == 50.0
    assert summary["source_paths"]["swnode_path"] == str(swnode_path)
    assert summary["source_paths"]["frcsd_road_path"] == str(frcsd_road_path)
    assert summary["selected_swsd_segment_ids"] == ["seg_near"]
    assert summary["selected_restriction_count"] == 1
    assert summary["selected_arrow_count"] == 1
    assert summary["selected_frcsd_road_count"] == 79
    assert summary["selected_t06_step3_optional_counts"]["t06_step3_replacement_units"] == 1
    assert summary["selected_t06_step3_optional_counts"]["t06_step3_junction_rebuild_audit"] == 0
    assert "has no geometry" in summary["selected_t06_step3_optional_errors"]["t06_step3_junction_rebuild_audit"]
    assert size_report["split_bundle"]["enabled"] is True
    assert size_report["split_bundle"]["part_count"] == len(artifacts.part_txt_paths)
    assert testcase_manifest["source_input_paths"]["swnode_path"] == str(swnode_path)
    assert testcase_manifest["source_input_paths"]["frcsd_node_path"] == str(frcsd_node_path)
    assert testcase_manifest["fixture_paths"]["swsd_nodes"] == "slice/swsd/nodes.geojson"
    assert testcase_manifest["fixture_paths"]["frcsd_road"] == "slice/frcsd/frcsd_road.geojson"
    assert testcase_manifest["fixture_paths"]["pytest_file"] == "local_testcase/test_t09_decoded_bundle.py"
    assert "--rootdir <decoded_bundle_dir>" in testcase_manifest["pytest_command_from_repo_root"]
    assert (
        testcase_manifest["recommended_t09_step1_step2_kwargs"]["restriction_gpkg"]
        == "slice/t08_tool7/sw_restriction_tool7.geojson"
    )
    assert testcase_manifest["recommended_t09_step3_inputs"]["frcsd_node_path"] == "slice/frcsd/frcsd_node.geojson"

    assert _feature_ids(decoded.out_dir / "slice" / "frcsd" / "frcsd_road.geojson") == [
        f"fr_{index}" for index in range(79)
    ]
    assert "fr_far" not in _feature_ids(decoded.out_dir / "slice" / "frcsd" / "frcsd_road.geojson")
    assert _feature_ids(decoded.out_dir / "slice" / "swsd" / "segment.geojson") == ["seg_near"]
    assert _feature_ids(decoded.out_dir / "slice" / "t06_step3" / "t06_step3_replacement_units.geojson") == [
        "unit_near"
    ]
    assert (decoded.out_dir / "reference" / "t06_step3" / "t06_step3_summary.json").is_file()
    generated_test = decoded.out_dir / "local_testcase" / "test_t09_decoded_bundle.py"
    assert generated_test.is_file()
    nested = subprocess.run(
        [sys.executable, "-m", "pytest", "--rootdir", str(decoded.out_dir), str(generated_test), "-q", "-s"],
        cwd=Path(__file__).resolve().parents[3],
        check=False,
        capture_output=True,
        text=True,
    )
    assert nested.returncode == 0, nested.stdout + nested.stderr
