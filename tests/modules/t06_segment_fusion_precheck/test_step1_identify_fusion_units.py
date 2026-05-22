from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import run_t06_step1_identify_fusion_units


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def _seg(seg_id: str, pair_nodes, junc_nodes, sgrade: str = "主双"):
    return {
        "properties": {
            "id": seg_id,
            "sgrade": sgrade,
            "pair_nodes": pair_nodes,
            "junc_nodes": junc_nodes,
            "roads": ["r1"],
        },
        "geometry": LineString([(0, 0), (10, 0)]),
    }


def _node(node_id: int, has_evd: str | None, is_anchor: str | None, kind_2: int | str | None = None):
    props = {"id": node_id, "mainnodeid": 0}
    if has_evd is not None:
        props["has_evd"] = has_evd
    if is_anchor is not None:
        props["is_anchor"] = is_anchor
    if kind_2 is not None:
        props["kind_2"] = kind_2
    return {"properties": props, "geometry": Point(node_id, 0)}


def test_step1_identifies_evd_fusion_fail4_and_rejections(tmp_path: Path) -> None:
    segment_path = _write(
        tmp_path / "segment.gpkg",
        [
            _seg("eligible", [1, 2], []),
            _seg("fail4", "[2, 3]", ""),
            _seg("no_evd", "1,4", ""),
            _seg("bad_pair", [1], []),
            _seg("bad_anchor", [1, 5], []),
        ],
    )
    nodes_path = _write(
        tmp_path / "nodes.gpkg",
        [
            _node(1, "yes", "yes"),
            _node(2, "yes", "yes"),
            _node(3, "yes", "fail4_fallback"),
            _node(4, "no", "yes"),
            _node(5, "yes", "no"),
        ],
    )

    artifacts = run_t06_step1_identify_fusion_units(
        swsd_segment_path=segment_path,
        swsd_nodes_path=nodes_path,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["input_segment_count"] == 5
    assert summary["evd_candidate_count"] == 3
    assert summary["final_fusion_unit_count"] == 2
    assert summary["has_fail4_fallback_segment_count"] == 1
    assert summary["reject_reason_counts"]["has_evd_not_yes"] == 1
    assert summary["reject_reason_counts"]["invalid_pair_nodes"] == 1
    assert summary["reject_reason_counts"]["is_anchor_not_eligible"] == 1

    fusion = read_vector_layer(artifacts.fusion_units_gpkg_path).features
    assert {item.properties["swsd_segment_id"] for item in fusion} == {"eligible", "fail4"}


def test_step1_rejects_missing_node_and_missing_fields(tmp_path: Path) -> None:
    segment_path = _write(tmp_path / "segment.gpkg", [_seg("missing_node", [10, 11], []), _seg("missing_anchor", [1, 2], [])])
    nodes_path = _write(tmp_path / "nodes.gpkg", [_node(1, "yes", None), _node(2, "yes", "yes")])

    artifacts = run_t06_step1_identify_fusion_units(
        swsd_segment_path=segment_path,
        swsd_nodes_path=nodes_path,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["reject_reason_counts"]["missing_node_reference"] == 1
    assert summary["reject_reason_counts"]["is_anchor_missing"] == 1


def test_step1_exempts_pair_kind2_nodes_from_evd_and_anchor_checks(tmp_path: Path) -> None:
    segment_path = _write(
        tmp_path / "segment.gpkg",
        [
            _seg("pair_kind2_missing_attrs", [100, 2], []),
            _seg("pair_kind2_bad_attrs", [101, 2], []),
            _seg("pair_kind2_value_one", [102, 2], []),
            _seg("junc_kind2_still_checked", [1, 2], [100]),
        ],
    )
    nodes_path = _write(
        tmp_path / "nodes.gpkg",
        [
            _node(1, "yes", "yes"),
            _node(2, "yes", "yes"),
            _node(100, None, None, kind_2=4096),
            _node(101, "no", "no", kind_2="8192"),
            _node(102, "no", "no", kind_2=1),
        ],
    )

    artifacts = run_t06_step1_identify_fusion_units(
        swsd_segment_path=segment_path,
        swsd_nodes_path=nodes_path,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["input_segment_count"] == 4
    assert summary["evd_candidate_count"] == 3
    assert summary["final_fusion_unit_count"] == 3
    assert summary["reject_reason_counts"]["has_evd_missing"] == 1
    assert summary["pair_kind2_exempt_segment_count"] == 3
    assert summary["pair_kind2_exempt_node_count"] == 3

    fusion_payload = json.loads(artifacts.fusion_units_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    fusion_rows = {item["properties"]["swsd_segment_id"]: item["properties"] for item in fusion_payload["features"]}
    assert set(fusion_rows) == {"pair_kind2_missing_attrs", "pair_kind2_bad_attrs", "pair_kind2_value_one"}
    assert fusion_rows["pair_kind2_missing_attrs"]["pair_kind2_exempt_nodes"] == ["100"]
    assert fusion_rows["pair_kind2_bad_attrs"]["pair_kind2_exempt_nodes"] == ["101"]
    assert fusion_rows["pair_kind2_value_one"]["pair_kind2_exempt_nodes"] == ["102"]

    rejected_payload = json.loads(artifacts.rejected_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    rejected_rows = {item["properties"]["swsd_segment_id"]: item["properties"] for item in rejected_payload["features"]}
    assert rejected_rows["junc_kind2_still_checked"]["reject_reason"] == "has_evd_missing"
    assert rejected_rows["junc_kind2_still_checked"]["failed_node_ids"] == ["100"]
