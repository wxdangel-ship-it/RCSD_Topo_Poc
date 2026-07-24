from __future__ import annotations

import sqlite3
from pathlib import Path

import fiona
import pytest
from shapely.geometry import LineString, Point, mapping, shape

from rcsd_topo_poc.modules.p05_neural_road_generation.r2_models import R2OracleConfig
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import read_vector_payloads
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_oracle import (
    derive_node_edits,
    derive_road_edits,
    derive_t05_pointers,
    materialize_edit_payloads,
    semantic_node_candidate_ids,
)


def _road(
    road_id: str,
    coords: list[tuple[float, float]],
    *,
    start: str,
    end: str,
    direction: int = 0,
    source: int = 1,
    split_parent: str = "",
) -> dict[str, object]:
    return {
        "id": road_id,
        "geometry": mapping(LineString(coords)),
        "properties": {
            "id": road_id,
            "snodeid": start,
            "enodeid": end,
            "direction": direction,
            "source": source,
            "t06_split_original_road_id": split_parent,
        },
    }


def _node(node_id: str, x: float, y: float) -> dict[str, object]:
    return {
        "id": node_id,
        "geometry": mapping(Point(x, y)),
        "properties": {"id": node_id},
    }


def test_reader_supports_gpkg_declared_as_unknown_3d_geometry(tmp_path: Path) -> None:
    path = tmp_path / "unknown_3d.gpkg"
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer="roads",
        schema={"geometry": "LineString", "properties": {"id": "int"}},
        crs="EPSG:3857",
    ) as sink:
        sink.write(
            {
                "geometry": mapping(LineString([(0, 0), (1, 1)])),
                "properties": {"id": 7},
            }
        )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE gpkg_geometry_columns SET geometry_type_name='GEOMETRY', z=1 WHERE table_name='roads'"
        )
        connection.commit()

    payloads, meta = read_vector_payloads(path, source_role="fixture")

    assert set(payloads) == {"7"}
    assert shape(payloads["7"]["geometry"]).equals(LineString([(0, 0), (1, 1)]))
    assert meta["crs_wkt"]


def test_oracle_edit_domain_covers_copy_update_split_create_and_drop() -> None:
    base = {
        "copy": _road("copy", [(0, 0), (1, 0)], start="n0", end="n1"),
        "update": _road("update", [(0, 1), (1, 1)], start="n2", end="n3"),
        "parent": _road("parent", [(0, 2), (2, 2)], start="n4", end="n6"),
        "drop": _road("drop", [(0, 3), (1, 3)], start="n7", end="n8"),
    }
    truth = {
        "copy": _road("copy", [(0, 0), (1, 0)], start="n0", end="n1"),
        "update": _road("update", [(0, 1), (1, 1)], start="n2", end="n3", direction=1),
        "child-a": _road("child-a", [(0, 2), (1, 2)], start="n4", end="n5", split_parent="parent"),
        "child-b": _road("child-b", [(1, 2), (2, 2)], start="n5", end="n6", split_parent="parent"),
        "create": _road("create", [(0, 4), (1, 4)], start="n9", end="n10"),
    }

    edits, summary = derive_road_edits(base, truth)

    assert summary["action_counts"] == {"COPY": 1, "CREATE": 1, "DROP": 1, "SPLIT": 1, "UPDATE": 1}
    assert summary["truth_count"] == 5
    assert summary["represented_truth_count"] == 5
    assert summary["coverage"] == 1.0
    roads, _ = materialize_edit_payloads(edits, [])
    assert set(roads) == set(truth)


def test_node_edits_cover_copy_update_create_and_drop() -> None:
    base = {
        "copy": _node("copy", 0, 0),
        "update": _node("update", 1, 0),
        "drop": _node("drop", 2, 0),
    }
    truth = {
        "copy": _node("copy", 0, 0),
        "update": _node("update", 1.5, 0),
        "create": _node("create", 3, 0),
    }

    edits, summary = derive_node_edits(base, truth)

    assert summary["action_counts"] == {"COPY": 1, "CREATE": 1, "DROP": 1, "UPDATE": 1}
    _, nodes = materialize_edit_payloads([], edits)
    assert set(nodes) == set(truth)


def test_materializer_rejects_duplicate_output_ids() -> None:
    payload = _road("same", [(0, 0), (1, 0)], start="a", end="b")
    edits = [
        {"action": "CREATE", "output_payloads": [payload]},
        {"action": "CREATE", "output_payloads": [payload]},
    ]

    with pytest.raises(ValueError, match="duplicate Road output id"):
        materialize_edit_payloads(edits, [])


def test_t05_pointer_audits_cardinality_and_base_existence() -> None:
    rows = [
        {"target_id": "t1", "base_id": "b1", "status": 0},
        {"target_id": "t2", "base_id": "b2", "status": 0},
        {"target_id": "t2", "base_id": "b3", "status": 0},
        {"target_id": "t3", "base_id": "b4", "status": 1},
    ]

    pointers, summary = derive_t05_pointers(rows, {"b1", "b2"})
    by_target = {row["target_id"]: row for row in pointers}

    assert by_target["t1"]["selected_base_id"] == "b1"
    assert by_target["t1"]["selected_base_exists"] is True
    assert by_target["t2"]["cardinality_error"] is True
    assert by_target["t3"]["no_match"] is True
    assert summary == {
        "target_count": 3,
        "expressible_target_count": 2,
        "coverage": 2 / 3,
        "cardinality_error_count": 1,
        "missing_selected_base_count": 0,
    }


def test_semantic_node_candidates_include_ids_and_nonzero_mainnodeids() -> None:
    nodes = {
        "n1": {"id": "n1", "properties": {"id": "n1", "mainnodeid": "group"}},
        "n2": {"id": "n2", "properties": {"id": "n2", "mainnodeid": 0}},
    }

    assert semantic_node_candidate_ids(nodes) == {"n1", "n2", "group"}


def test_r2_oracle_config_rejects_empty_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        R2OracleConfig(m2r_dataset_run_root=tmp_path, output_root=tmp_path, run_id="")
