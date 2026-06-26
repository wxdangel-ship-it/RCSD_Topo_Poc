from __future__ import annotations

import csv
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


def _node(
    node_id: int,
    has_evd: str | None,
    is_anchor: str | None,
    kind_2: int | str | None = None,
    mainnodeid: int = 0,
):
    props = {"id": node_id, "mainnodeid": mainnodeid}
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
    legacy_root = tmp_path / "out" / "run" / "step1_identify_fusion_units"
    legacy_root.mkdir(parents=True)
    (legacy_root / "t06_swsd_segment_evd_candidates.json").write_text("stale", encoding="utf-8")
    (legacy_root / "t06_swsd_segment_fusion_units.csv").write_text("stale", encoding="utf-8")

    artifacts = run_t06_step1_identify_fusion_units(
        swsd_segment_path=segment_path,
        swsd_nodes_path=nodes_path,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["input_segment_count"] == 5
    assert summary["evd_candidate_count"] == 3
    assert summary["swsd_candidate_count"] == 3
    assert summary["final_fusion_unit_count"] == 2
    assert summary["swsd_final_fusion_unit_count"] == 2
    assert summary["has_fail4_fallback_segment_count"] == 1
    assert summary["reject_reason_counts"]["has_evd_not_yes"] == 1
    assert summary["reject_reason_counts"]["invalid_pair_nodes"] == 1
    assert summary["reject_reason_counts"]["is_anchor_not_eligible"] == 1
    assert Path(summary["outputs"]["swsd_candidates_gpkg"]).exists()
    assert Path(summary["outputs"]["swsd_final_fusion_units_gpkg"]).exists()
    assert Path(summary["outputs"]["segment_stats_csv"]).exists()
    assert "evd_candidates_gpkg" not in summary["outputs"]
    assert "fusion_units_gpkg" not in summary["outputs"]
    assert artifacts.swsd_candidates_gpkg_path is not None
    assert artifacts.final_fusion_units_gpkg_path is not None
    assert artifacts.stats_csv_path is not None
    assert artifacts.evd_candidates_gpkg_path == artifacts.swsd_candidates_gpkg_path
    assert artifacts.fusion_units_gpkg_path == artifacts.final_fusion_units_gpkg_path
    assert not (artifacts.step_root / "t06_swsd_segment_evd_candidates.gpkg").exists()
    assert not (artifacts.step_root / "t06_swsd_segment_evd_candidates.json").exists()
    assert not (artifacts.step_root / "t06_swsd_segment_fusion_units.gpkg").exists()
    assert not (artifacts.step_root / "t06_swsd_segment_fusion_units.csv").exists()

    fusion = read_vector_layer(artifacts.fusion_units_gpkg_path).features
    assert {item.properties["swsd_segment_id"] for item in fusion} == {"eligible", "fail4"}
    final_fusion = read_vector_layer(artifacts.final_fusion_units_gpkg_path).features
    assert {item.properties["swsd_segment_id"] for item in final_fusion} == {"eligible", "fail4"}
    with artifacts.stats_csv_path.open("r", encoding="utf-8", newline="") as fp:
        stats_rows = list(csv.DictReader(fp))
    assert stats_rows == [
        {"sgrade": "__TOTAL__", "total_segment_count": "5", "evd_candidate_count": "3", "final_fusion_unit_count": "2"},
        {"sgrade": "主双", "total_segment_count": "5", "evd_candidate_count": "3", "final_fusion_unit_count": "2"},
    ]


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


def test_step1_stats_csv_groups_by_sgrade(tmp_path: Path) -> None:
    segment_path = _write(
        tmp_path / "segment.gpkg",
        [
            _seg("dual_final", [1, 2], [], sgrade="0-0双"),
            _seg("dual_after_evd", [1, 3], [], sgrade="0-0双"),
            _seg("single_before_evd", [1, 4], [], sgrade="0-1单"),
            _seg("single_final", [1, 5], [], sgrade="0-1单"),
        ],
    )
    nodes_path = _write(
        tmp_path / "nodes.gpkg",
        [
            _node(1, "yes", "yes"),
            _node(2, "yes", "yes"),
            _node(3, "yes", "no"),
            _node(4, "no", "yes"),
            _node(5, "yes", "yes"),
        ],
    )

    artifacts = run_t06_step1_identify_fusion_units(
        swsd_segment_path=segment_path,
        swsd_nodes_path=nodes_path,
        out_root=tmp_path / "out",
        run_id="run",
    )

    assert artifacts.stats_csv_path is not None
    with artifacts.stats_csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert rows == [
        {"sgrade": "__TOTAL__", "total_segment_count": "4", "evd_candidate_count": "3", "final_fusion_unit_count": "2"},
        {"sgrade": "0-0双", "total_segment_count": "2", "evd_candidate_count": "2", "final_fusion_unit_count": "1"},
        {"sgrade": "0-1单", "total_segment_count": "2", "evd_candidate_count": "1", "final_fusion_unit_count": "1"},
    ]


def test_step1_exempts_junc_kind2_nodes_from_evd_and_anchor_checks(tmp_path: Path) -> None:
    segment_path = _write(
        tmp_path / "segment.gpkg",
        [
            _seg("junc_kind2_missing_attrs", [1, 2], [100]),
            _seg("junc_kind2_bad_attrs", [1, 2], [101]),
            _seg("junc_kind2_value_one", [1, 2], [102]),
            _seg("pair_kind2_still_checked", [100, 2], []),
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
    assert summary["junc_kind2_exempt_segment_count"] == 3
    assert summary["junc_kind2_exempt_node_count"] == 3

    fusion_payload = json.loads(artifacts.fusion_units_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    fusion_rows = {item["properties"]["swsd_segment_id"]: item["properties"] for item in fusion_payload["features"]}
    assert set(fusion_rows) == {"junc_kind2_missing_attrs", "junc_kind2_bad_attrs", "junc_kind2_value_one"}
    assert fusion_rows["junc_kind2_missing_attrs"]["junc_kind2_exempt_nodes"] == ["100"]
    assert fusion_rows["junc_kind2_bad_attrs"]["junc_kind2_exempt_nodes"] == ["101"]
    assert fusion_rows["junc_kind2_value_one"]["junc_kind2_exempt_nodes"] == ["102"]

    rejected_payload = json.loads(artifacts.rejected_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    rejected_rows = {item["properties"]["swsd_segment_id"]: item["properties"] for item in rejected_payload["features"]}
    assert rejected_rows["pair_kind2_still_checked"]["reject_reason"] == "has_evd_missing"
    assert rejected_rows["pair_kind2_still_checked"]["failed_node_ids"] == ["100"]


def test_step1_prefers_exact_node_id_over_earlier_mainnodeid_fallback(tmp_path: Path) -> None:
    segment_path = _write(tmp_path / "segment.gpkg", [_seg("representative_pair", [100, 200], [])])
    nodes_path = _write(
        tmp_path / "nodes.gpkg",
        [
            _node(10001, None, None, kind_2=0, mainnodeid=100),
            _node(20001, None, None, kind_2=0, mainnodeid=200),
            _node(100, "yes", "yes", kind_2=4, mainnodeid=100),
            _node(200, "yes", "yes", kind_2=4, mainnodeid=200),
        ],
    )

    artifacts = run_t06_step1_identify_fusion_units(
        swsd_segment_path=segment_path,
        swsd_nodes_path=nodes_path,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["evd_candidate_count"] == 1
    assert summary["final_fusion_unit_count"] == 1
    assert summary["reject_reason_counts"] == {}

    fusion_payload = json.loads(artifacts.fusion_units_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    row = fusion_payload["features"][0]["properties"]
    assert row["swsd_segment_id"] == "representative_pair"
    assert row["junc_kind2_exempt_nodes"] == []


def test_step1_detaches_high_grade_failed_junc_without_weakening_pair_or_special_junctions(tmp_path: Path) -> None:
    segment_path = _write(
        tmp_path / "segment.gpkg",
        [
            _seg("junc_anchor_failed_detached", [1, 2], [3], sgrade="0-0双"),
            _seg("junc_no_evd_detached", [1, 2], [4], sgrade="0-1双"),
            _seg("junc_anchor_missing_detached", [1, 2], [5], sgrade="0-0双"),
            _seg("low_grade_junc_still_rejected", [1, 2], [3], sgrade="2-0双"),
            _seg("pair_anchor_still_rejected", [1, 6], [], sgrade="0-0双"),
            _seg("special_junc_still_rejected", [1, 2], [7], sgrade="0-0双"),
        ],
    )
    nodes_path = _write(
        tmp_path / "nodes.gpkg",
        [
            _node(1, "yes", "yes", kind_2=4),
            _node(2, "yes", "yes", kind_2=4),
            _node(3, "yes", "no", kind_2=4),
            _node(4, "no", "no", kind_2=2048),
            _node(5, "yes", None, kind_2=4),
            _node(6, "yes", "no", kind_2=4),
            _node(7, "yes", "no", kind_2=64),
        ],
    )

    artifacts = run_t06_step1_identify_fusion_units(
        swsd_segment_path=segment_path,
        swsd_nodes_path=nodes_path,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["final_fusion_unit_count"] == 3
    assert summary["detached_junc_segment_count"] == 3
    assert summary["detached_junc_node_count"] == 3
    assert summary["detached_junc_reason_counts"] == {
        "has_evd_not_yes": 1,
        "is_anchor_missing": 1,
        "is_anchor_not_eligible": 1,
    }

    fusion_payload = json.loads(artifacts.fusion_units_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    fusion_rows = {item["properties"]["swsd_segment_id"]: item["properties"] for item in fusion_payload["features"]}
    assert set(fusion_rows) == {
        "junc_anchor_failed_detached",
        "junc_no_evd_detached",
        "junc_anchor_missing_detached",
    }
    assert fusion_rows["junc_anchor_failed_detached"]["junc_nodes"] == []
    assert fusion_rows["junc_anchor_failed_detached"]["semantic_node_set"] == ["1", "2"]
    assert fusion_rows["junc_anchor_failed_detached"]["detached_junc_nodes"] == ["3"]
    assert fusion_rows["junc_anchor_failed_detached"]["detached_junc_reasons"] == ["3:is_anchor_not_eligible"]
    assert fusion_rows["junc_no_evd_detached"]["detached_junc_reasons"] == ["4:has_evd_not_yes"]
    assert fusion_rows["junc_anchor_missing_detached"]["detached_junc_reasons"] == ["5:is_anchor_missing"]

    rejected_payload = json.loads(artifacts.rejected_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    rejected_rows = {item["properties"]["swsd_segment_id"]: item["properties"] for item in rejected_payload["features"]}
    assert rejected_rows["low_grade_junc_still_rejected"]["reject_reason"] == "is_anchor_not_eligible"
    assert rejected_rows["pair_anchor_still_rejected"]["reject_reason"] == "is_anchor_not_eligible"
    assert rejected_rows["pair_anchor_still_rejected"]["failed_node_ids"] == ["6"]
    assert rejected_rows["special_junc_still_rejected"]["reject_reason"] == "is_anchor_not_eligible"


def test_step1_allows_only_dual_0_2_virtual_t_pair_nodes_for_step2_probe(tmp_path: Path) -> None:
    segment_path = _write(
        tmp_path / "segment.gpkg",
        [
            _seg("high_grade_virtual_t_pair", [10, 11], [], sgrade="0-1双"),
            _seg("dual_0_2_virtual_t_pair", [20, 21], [], sgrade="0-2双"),
            _seg("single_0_2_virtual_t_pair_still_rejected", [22, 23], [], sgrade="0-2单"),
            _seg("dual_0_2_mixed_pair_still_rejected", [20, 24], [], sgrade="0-2双"),
            _seg("dual_0_2_junc_still_rejected", [30, 31], [32], sgrade="0-2双"),
        ],
    )
    nodes_path = _write(
        tmp_path / "nodes.gpkg",
        [
            _node(10, "yes", "no", kind_2=2048),
            _node(11, "yes", "no", kind_2=2048),
            _node(20, "yes", "no", kind_2=2048),
            _node(21, "yes", "no", kind_2=2048),
            _node(22, "yes", "no", kind_2=2048),
            _node(23, "yes", "no", kind_2=2048),
            _node(24, "yes", "no", kind_2=4),
            _node(30, "yes", "yes", kind_2=4),
            _node(31, "yes", "yes", kind_2=4),
            _node(32, "yes", "no", kind_2=2048),
        ],
    )

    artifacts = run_t06_step1_identify_fusion_units(
        swsd_segment_path=segment_path,
        swsd_nodes_path=nodes_path,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["final_fusion_unit_count"] == 2
    assert summary["reject_reason_counts"]["is_anchor_not_eligible"] == 3

    fusion_payload = json.loads(artifacts.fusion_units_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    fusion_rows = {item["properties"]["swsd_segment_id"]: item["properties"] for item in fusion_payload["features"]}
    assert set(fusion_rows) == {"high_grade_virtual_t_pair", "dual_0_2_virtual_t_pair"}

    rejected_payload = json.loads(artifacts.rejected_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    rejected_rows = {item["properties"]["swsd_segment_id"]: item["properties"] for item in rejected_payload["features"]}
    assert rejected_rows["single_0_2_virtual_t_pair_still_rejected"]["failed_node_ids"] == ["22", "23"]
    assert rejected_rows["dual_0_2_mixed_pair_still_rejected"]["failed_node_ids"] == ["20", "24"]
    assert rejected_rows["dual_0_2_junc_still_rejected"]["failed_node_ids"] == ["32"]


def test_step1_allows_high_grade_pair_fail1_multi_rcsd_group_for_step2_probe(tmp_path: Path) -> None:
    segment_path = _write(
        tmp_path / "segment.gpkg",
        [
            _seg("high_grade_pair_fail1_multi_rcsd", [40, 41], [], sgrade="0-0双"),
            _seg("low_grade_pair_fail1_still_rejected", [42, 43], [], sgrade="2-0双"),
        ],
    )
    nodes_path = _write(
        tmp_path / "nodes.gpkg",
        [
            _node(40, "yes", "fail1", kind_2=4),
            _node(41, "yes", "yes", kind_2=4),
            _node(42, "yes", "fail1", kind_2=4),
            _node(43, "yes", "yes", kind_2=4),
        ],
    )

    artifacts = run_t06_step1_identify_fusion_units(
        swsd_segment_path=segment_path,
        swsd_nodes_path=nodes_path,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["evd_candidate_count"] == 2
    assert summary["final_fusion_unit_count"] == 1
    assert summary["reject_reason_counts"]["is_anchor_not_eligible"] == 1

    fusion_payload = json.loads(artifacts.fusion_units_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert [item["properties"]["swsd_segment_id"] for item in fusion_payload["features"]] == [
        "high_grade_pair_fail1_multi_rcsd"
    ]
    rejected_payload = json.loads(artifacts.rejected_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    rejected_rows = {item["properties"]["swsd_segment_id"]: item["properties"] for item in rejected_payload["features"]}
    assert rejected_rows["low_grade_pair_fail1_still_rejected"]["failed_node_ids"] == ["42"]
