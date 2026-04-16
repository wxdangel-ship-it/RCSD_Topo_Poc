from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.aggregate_continuous_divmerge import (
    run_t02_aggregate_continuous_divmerge,
)


def _load_properties_by_id(path: Path) -> dict[str, dict]:
    with fiona.open(path) as src:
        return {str(feature["properties"]["id"]): dict(feature["properties"]) for feature in src}


def _node(
    node_id: str,
    x: float,
    y: float,
    *,
    mainnodeid: str | None = None,
    has_evd: str | None = None,
    is_anchor: str | None = None,
    kind: int | None = None,
    grade: int | None = None,
    kind_2: int | None = None,
    grade_2: int | None = None,
    subnodeid: str | None = None,
) -> dict:
    return {
        "properties": {
            "id": node_id,
            "mainnodeid": mainnodeid,
            "has_evd": has_evd,
            "is_anchor": is_anchor,
            "kind": kind,
            "grade": grade,
            "kind_2": kind_2,
            "grade_2": grade_2,
            "subnodeid": subnodeid,
        },
        "geometry": Point(x, y),
    }


def _road(road_id: str, snodeid: str, enodeid: str, coords: list[tuple[float, float]], *, direction: int = 2, formway: int = 1) -> dict:
    return {
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "formway": formway,
        },
        "geometry": LineString(coords),
    }


def _write_fixture(tmp_path: Path, *, start_kind_2: int, end_kind_2: int, segment_lengths: tuple[float, ...]) -> tuple[Path, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"

    x_positions = [0.0]
    for length in segment_lengths:
        x_positions.append(x_positions[-1] + float(length))

    road_features = []
    previous_node_id = "100"
    intermediate_ids: list[str] = []
    for index, x_pos in enumerate(x_positions[1:-1], start=1):
        node_id = f"10{index}"
        intermediate_ids.append(node_id)
        road_features.append(
            _road(
                f"r-main-{index}",
                previous_node_id,
                node_id,
                [(x_positions[index - 1], 0.0), (x_pos, 0.0)],
            )
        )
        previous_node_id = node_id
    road_features.append(
        _road(
            f"r-main-{len(segment_lengths)}",
            previous_node_id,
            "200",
            [(x_positions[-2], 0.0), (x_positions[-1], 0.0)],
        )
    )
    road_features.extend(
        [
            _road("r-100-out", "100", "110", [(0.0, 0.0), (0.0, 10.0)]),
            _road("r-100-in", "120", "100", [(0.0, -10.0), (0.0, 0.0)]),
            _road("r-200-out", "200", "210", [(x_positions[-1], 0.0), (x_positions[-1], 10.0)]),
            _road("r-200-in", "220", "200", [(x_positions[-1], -10.0), (x_positions[-1], 0.0)]),
        ]
    )

    write_vector(
        nodes_path,
        [
            _node("100", 0.0, 0.0, mainnodeid="100", has_evd="yes", is_anchor="no", kind=16, grade=2, kind_2=start_kind_2, grade_2=2),
            _node("200", x_positions[-1], 0.0, mainnodeid="200", has_evd="yes", is_anchor="no", kind=8, grade=1, kind_2=end_kind_2, grade_2=1),
            _node("110", 0.0, 10.0),
            _node("120", 0.0, -10.0),
            _node("210", x_positions[-1], 10.0),
            _node("220", x_positions[-1], -10.0),
            *[_node(node_id, x_positions[index], 0.0) for index, node_id in enumerate(intermediate_ids, start=1)],
        ],
        crs_text="EPSG:3857",
    )
    write_vector(roads_path, road_features, crs_text="EPSG:3857")
    return nodes_path, roads_path


def test_aggregate_continuous_divmerge_merges_diverge_to_merge_component(tmp_path: Path) -> None:
    nodes_path, roads_path = _write_fixture(tmp_path, start_kind_2=16, end_kind_2=8, segment_lengths=(20.0, 20.0, 20.0))
    nodes_fix_path = tmp_path / "nodes_fix.gpkg"
    roads_fix_path = tmp_path / "roads_fix.gpkg"
    report_path = tmp_path / "report.json"

    artifacts = run_t02_aggregate_continuous_divmerge(
        nodes_path=nodes_path,
        roads_path=roads_path,
        nodes_fix_path=nodes_fix_path,
        roads_fix_path=roads_fix_path,
        report_path=report_path,
    )

    assert artifacts.success is True
    assert artifacts.complex_junction_count == 1
    assert artifacts.complex_mainnodeids == ("200",)
    nodes_fix = _load_properties_by_id(nodes_fix_path)
    assert nodes_fix["200"]["mainnodeid"] == "200"
    assert nodes_fix["200"]["kind"] == 128
    assert nodes_fix["200"]["kind_2"] == 128
    assert nodes_fix["200"]["grade"] == 1
    assert nodes_fix["200"]["grade_2"] == 1
    assert nodes_fix["200"]["subnodeid"] == "100,200"

    assert nodes_fix["100"]["mainnodeid"] == "200"
    assert nodes_fix["100"]["kind"] == 0
    assert nodes_fix["100"]["kind_2"] == 0
    assert nodes_fix["100"]["grade"] == 0
    assert nodes_fix["100"]["grade_2"] == 0
    assert nodes_fix["100"]["subnodeid"] is None

    roads_fix = _load_properties_by_id(roads_fix_path)
    assert roads_fix["r-main-1"]["formway"] == 2048
    assert roads_fix["r-main-2"]["formway"] == 2048
    assert roads_fix["r-main-3"]["formway"] == 2048
    assert roads_fix["r-100-out"]["formway"] == 1
    assert roads_fix["r-200-out"]["formway"] == 1

    report_doc = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_doc["counts"]["complex_junction_count"] == 1
    assert report_doc["complex_mainnodeids"] == ["200"]
    assert report_doc["counts"]["aggregated_component_count"] == 1
    assert report_doc["rows"][0]["status"] == "aggregated"
    assert report_doc["rows"][0]["mainnodeid"] == "200"
    assert report_doc["rows"][0]["road_ids"] == ["r-main-1", "r-main-2", "r-main-3"]


def test_aggregate_continuous_divmerge_rejects_diverge_to_merge_over_75m(tmp_path: Path) -> None:
    nodes_path, roads_path = _write_fixture(tmp_path, start_kind_2=16, end_kind_2=8, segment_lengths=(30.0, 30.0, 20.0))
    nodes_fix_path = tmp_path / "nodes_fix.gpkg"
    roads_fix_path = tmp_path / "roads_fix.gpkg"
    report_path = tmp_path / "report.json"

    run_t02_aggregate_continuous_divmerge(
        nodes_path=nodes_path,
        roads_path=roads_path,
        nodes_fix_path=nodes_fix_path,
        roads_fix_path=roads_fix_path,
        report_path=report_path,
    )

    nodes_fix = _load_properties_by_id(nodes_fix_path)
    assert nodes_fix["100"]["mainnodeid"] == "100"
    assert nodes_fix["200"]["mainnodeid"] == "200"
    roads_fix = _load_properties_by_id(roads_fix_path)
    assert roads_fix["r-main-1"]["formway"] == 1
    assert roads_fix["r-main-2"]["formway"] == 1
    assert roads_fix["r-main-3"]["formway"] == 1

    report_doc = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_doc["counts"]["complex_junction_count"] == 0
    assert report_doc["complex_mainnodeids"] == []
    assert report_doc["counts"]["aggregated_component_count"] == 0


def test_aggregate_continuous_divmerge_keeps_non_diverge_merge_pair_on_50m_limit(tmp_path: Path) -> None:
    nodes_path, roads_path = _write_fixture(tmp_path, start_kind_2=8, end_kind_2=16, segment_lengths=(20.0, 20.0, 20.0))
    nodes_fix_path = tmp_path / "nodes_fix.gpkg"
    roads_fix_path = tmp_path / "roads_fix.gpkg"
    report_path = tmp_path / "report.json"

    run_t02_aggregate_continuous_divmerge(
        nodes_path=nodes_path,
        roads_path=roads_path,
        nodes_fix_path=nodes_fix_path,
        roads_fix_path=roads_fix_path,
        report_path=report_path,
    )

    nodes_fix = _load_properties_by_id(nodes_fix_path)
    assert nodes_fix["100"]["mainnodeid"] == "100"
    assert nodes_fix["200"]["mainnodeid"] == "200"
    report_doc = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_doc["counts"]["complex_junction_count"] == 0
    assert report_doc["complex_mainnodeids"] == []
    assert report_doc["counts"]["aggregated_component_count"] == 0
