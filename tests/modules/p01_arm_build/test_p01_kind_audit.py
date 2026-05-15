"""Unit tests for the kind_distribution audit field on JunctionContext.

Covers spec `p01-four-case-closure-and-field-semantics` FR-002 (C-2=D).

The kind_distribution must be a serialisable mapping of kind raw string values
to member node counts, including a "null" bucket for member nodes whose kind
is None / missing.
"""

from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, mapping

from rcsd_topo_poc.modules.p01_arm_build.io import load_dataset
from rcsd_topo_poc.modules.p01_arm_build.models import DatasetInput, to_plain
from rcsd_topo_poc.modules.p01_arm_build.topology import build_dataset_arm_result


def _write_nodes(path: Path, nodes: list[tuple[str, str | None, float, float, str | None]]) -> None:
    schema = {"geometry": "Point", "properties": {"id": "str", "mainnodeid": "str", "kind": "str"}}
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for node_id, mainnodeid, x, y, kind in nodes:
            sink.write(
                {
                    "geometry": mapping(Point(x, y)),
                    "properties": {"id": node_id, "mainnodeid": mainnodeid, "kind": kind},
                }
            )


def _write_roads(path: Path) -> None:
    schema = {
        "geometry": "LineString",
        "properties": {"id": "str", "snodeid": "str", "enodeid": "str", "direction": "int", "formway": "str"},
    }
    roads = [
        ("main_in", "N", "C", 2, "0", [(0.0, 30.0), (0.0, 0.0)]),
        ("main_out", "C", "E", 2, "0", [(0.0, 0.0), (30.0, 0.0)]),
    ]
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for road_id, snodeid, enodeid, direction, formway, coords in roads:
            sink.write(
                {
                    "geometry": mapping(LineString(coords)),
                    "properties": {
                        "id": road_id,
                        "snodeid": snodeid,
                        "enodeid": enodeid,
                        "direction": direction,
                        "formway": formway,
                    },
                }
            )


def _build_single_member_context(tmp_path: Path, kind_value: str | None):
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, kind_value),
            ("N", None, 0.0, 30.0, "1"),
            ("E", None, 30.0, 0.0, "1"),
        ],
    )
    _write_roads(roads_path)
    loaded = load_dataset(DatasetInput(dataset="FRCSD", nodes_path=nodes_path, roads_path=roads_path))
    return build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values=set()).context


def test_kind_distribution_present_and_well_formed(tmp_path: Path) -> None:
    ctx = _build_single_member_context(tmp_path, kind_value="4")
    assert hasattr(ctx, "kind_distribution"), "JunctionContext must expose kind_distribution"
    assert isinstance(ctx.kind_distribution, dict)
    assert ctx.kind_distribution, "kind_distribution must not be empty when member nodes exist"
    assert all(isinstance(k, str) for k in ctx.kind_distribution), "all keys must be strings"
    assert all(isinstance(v, int) and v >= 1 for v in ctx.kind_distribution.values())
    assert sum(ctx.kind_distribution.values()) == len(ctx.member_node_ids)


def test_kind_distribution_captures_value(tmp_path: Path) -> None:
    ctx = _build_single_member_context(tmp_path, kind_value="4")
    assert ctx.kind_distribution == {"4": 1}


def test_kind_distribution_buckets_null_kind(tmp_path: Path) -> None:
    ctx = _build_single_member_context(tmp_path, kind_value=None)
    assert "null" in ctx.kind_distribution, (
        "missing kind must surface as 'null' bucket so audit retains coverage of nodes"
    )
    assert ctx.kind_distribution["null"] >= 1


def test_kind_distribution_aggregates_multi_member(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("C2", "C", 1.0, 0.0, "4"),
            ("C3", "C", 0.0, 1.0, "2048"),
            ("C4", "C", -1.0, 0.0, "8"),
            ("C5", "C", 0.0, -1.0, None),
            ("N", None, 0.0, 30.0, "1"),
            ("E", None, 30.0, 0.0, "1"),
        ],
    )
    _write_roads(roads_path)
    loaded = load_dataset(DatasetInput(dataset="FRCSD", nodes_path=nodes_path, roads_path=roads_path))
    ctx = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values=set()).context
    assert ctx.kind_distribution.get("4") == 2
    assert ctx.kind_distribution.get("2048") == 1
    assert ctx.kind_distribution.get("8") == 1
    assert ctx.kind_distribution.get("null") == 1
    assert sum(ctx.kind_distribution.values()) == len(ctx.member_node_ids)


def test_kind_distribution_round_trips_through_to_plain(tmp_path: Path) -> None:
    ctx = _build_single_member_context(tmp_path, kind_value="2048")
    plain = to_plain(ctx)
    assert "kind_distribution" in plain
    assert plain["kind_distribution"] == {"2048": 1}
    assert isinstance(json.dumps(plain), str)


def test_kind_distribution_keys_are_sorted(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "2048"),
            ("C2", "C", 1.0, 0.0, "8"),
            ("C3", "C", 0.0, 1.0, "4"),
            ("N", None, 0.0, 30.0, "1"),
            ("E", None, 30.0, 0.0, "1"),
        ],
    )
    _write_roads(roads_path)
    loaded = load_dataset(DatasetInput(dataset="FRCSD", nodes_path=nodes_path, roads_path=roads_path))
    ctx = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values=set()).context
    assert list(ctx.kind_distribution.keys()) == sorted(ctx.kind_distribution.keys())
