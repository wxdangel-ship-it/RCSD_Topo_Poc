from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p02_wuhan_local_experiment.manual_relations import (
    ManualRelationTransformError,
    transform_manual_relations,
)
from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg


FIELDS = [
    "case_id",
    "swsd_segment_id",
    "target_id",
    "manual_relation_type",
    "selected_ids",
    "comment",
    "source_manual_table",
    "source_manual_xlsx",
]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    nodes = tmp_path / "tool5_nodes.gpkg"
    rcsd_nodes = tmp_path / "rcsd_nodes.gpkg"
    rcsd_roads = tmp_path / "rcsd_roads.gpkg"
    write_gpkg(
        nodes,
        [
            {"properties": {"id": "1", "mainnodeid": "100"}, "geometry": Point(0, 0)},
            {"properties": {"id": "2", "mainnodeid": "100"}, "geometry": Point(1, 0)},
            {"properties": {"id": "3", "mainnodeid": None}, "geometry": Point(2, 0)},
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        rcsd_nodes,
        [
            {"properties": {"id": "n1", "mainnodeid": "n1"}, "geometry": Point(0, 1)},
            {"properties": {"id": "n2", "mainnodeid": "n2"}, "geometry": Point(1, 1)},
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        rcsd_roads,
        [
            {"properties": {"id": "r1", "snodeid": "n1", "enodeid": "n2"}, "geometry": LineString([(0, 0), (1, 0)])},
            {"properties": {"id": "r2", "snodeid": "n2", "enodeid": "n3"}, "geometry": LineString([(1, 0), (2, 0)])},
        ],
        crs_text="EPSG:3857",
    )
    return nodes, rcsd_nodes, rcsd_roads


def _row(target: str, relation_type: str, selected: str) -> dict[str, str]:
    return {
        "case_id": "case",
        "swsd_segment_id": "",
        "target_id": target,
        "manual_relation_type": relation_type,
        "selected_ids": selected,
        "comment": "confirmed",
        "source_manual_table": "user_20260714",
        "source_manual_xlsx": "",
    }


def test_transform_manual_relations_remaps_deduplicates_and_preserves_1vn(tmp_path: Path) -> None:
    final_nodes, rcsd_nodes, rcsd_roads = _inputs(tmp_path)
    raw = tmp_path / "raw.csv"
    _write_csv(
        raw,
        [
            _row("1", "1v1_rcsd_junction", "n1"),
            _row("2", "1v1_rcsd_junction", "n1"),
            _row("3", "1vN_rcsd_road", "r1|r2"),
        ],
    )

    artifacts = transform_manual_relations(
        raw_relation_path=raw,
        final_swsd_nodes_path=final_nodes,
        rcsdnode_path=rcsd_nodes,
        rcsdroad_path=rcsd_roads,
        out_dir=tmp_path / "out",
    )

    with artifacts.converted_relations.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["target_id"], row["manual_relation_type"], row["selected_ids"]) for row in rows] == [
        ("100", "1v1_rcsd_junction", "n1"),
        ("3", "1vN_rcsd_road", "r1|r2"),
    ]
    summary = json.loads(artifacts.summary.read_text(encoding="utf-8"))
    assert summary["passed"] is True
    assert summary["raw_relation_count"] == 3
    assert summary["converted_relation_count"] == 2
    assert summary["deduplicated_relation_count"] == 1


def test_transform_manual_relations_upgrades_complex_junction_to_1vn(tmp_path: Path) -> None:
    final_nodes, rcsd_nodes, rcsd_roads = _inputs(tmp_path)
    raw = tmp_path / "raw.csv"
    _write_csv(
        raw,
        [
            _row("1", "1v1_rcsd_junction", "n1"),
            _row("2", "1v1_rcsd_junction", "n2"),
        ],
    )

    artifacts = transform_manual_relations(
        raw_relation_path=raw,
        final_swsd_nodes_path=final_nodes,
        rcsdnode_path=rcsd_nodes,
        rcsdroad_path=rcsd_roads,
        out_dir=tmp_path / "out",
    )

    with artifacts.converted_relations.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["target_id"], row["manual_relation_type"], row["selected_ids"]) for row in rows] == [
        ("100", "1vN_rcsd_junction", "n1|n2")
    ]
    summary = json.loads(artifacts.summary.read_text(encoding="utf-8"))
    assert summary["merged_to_1vn_group_count"] == 1
    with artifacts.audit.open("r", encoding="utf-8-sig", newline="") as handle:
        audit = list(csv.DictReader(handle))
    assert {row["transform_status"] for row in audit} == {"merged_to_1vN"}


def test_transform_manual_relations_preserves_long_integer_ids(tmp_path: Path) -> None:
    final_nodes = tmp_path / "tool5_nodes.gpkg"
    rcsd_nodes = tmp_path / "rcsd_nodes.gpkg"
    rcsd_roads = tmp_path / "rcsd_roads.gpkg"
    write_gpkg(
        final_nodes,
        [{"properties": {"id": "521458225", "mainnodeid": None}, "geometry": Point(0, 0)}],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        rcsd_nodes,
        [{"properties": {"id": "5855295910117642", "mainnodeid": None}, "geometry": Point(0, 1)}],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        rcsd_roads,
        [
            {
                "properties": {"id": "5855295910117425", "snodeid": "1", "enodeid": "2"},
                "geometry": LineString([(0, 0), (1, 0)]),
            },
            {
                "properties": {"id": "5855295910117512", "snodeid": "2", "enodeid": "3"},
                "geometry": LineString([(1, 0), (2, 0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    raw = tmp_path / "raw.csv"
    _write_csv(raw, [_row("521458225", "1vN_rcsd_road", "5855295910117425|5855295910117512")])

    artifacts = transform_manual_relations(
        raw_relation_path=raw,
        final_swsd_nodes_path=final_nodes,
        rcsdnode_path=rcsd_nodes,
        rcsdroad_path=rcsd_roads,
        out_dir=tmp_path / "out",
    )

    with artifacts.converted_relations.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["selected_ids"] == "5855295910117425|5855295910117512"


def test_transform_manual_relations_blocks_conflicting_canonical_target(tmp_path: Path) -> None:
    final_nodes, rcsd_nodes, rcsd_roads = _inputs(tmp_path)
    raw = tmp_path / "raw.csv"
    _write_csv(
        raw,
        [
            _row("1", "1v1_rcsd_junction", "n1"),
            _row("2", "1v1_rcsd_road", "r1"),
        ],
    )

    with pytest.raises(ManualRelationTransformError, match="blocking manual relation transform") as exc_info:
        transform_manual_relations(
            raw_relation_path=raw,
            final_swsd_nodes_path=final_nodes,
            rcsdnode_path=rcsd_nodes,
            rcsdroad_path=rcsd_roads,
            out_dir=tmp_path / "out",
        )

    assert exc_info.value.summary_path.exists()
    summary = json.loads(exc_info.value.summary_path.read_text(encoding="utf-8"))
    assert summary["passed"] is False
    assert summary["conflict_count"] == 2
    assert not (tmp_path / "out" / "p02_manual_relations_converted.csv").exists()


def test_transform_manual_relations_blocks_missing_target_and_selected_id(tmp_path: Path) -> None:
    final_nodes, rcsd_nodes, rcsd_roads = _inputs(tmp_path)
    raw = tmp_path / "raw.csv"
    _write_csv(raw, [_row("404", "1vN_rcsd_road", "r1|missing")])

    with pytest.raises(ManualRelationTransformError) as exc_info:
        transform_manual_relations(
            raw_relation_path=raw,
            final_swsd_nodes_path=final_nodes,
            rcsdnode_path=rcsd_nodes,
            rcsdroad_path=rcsd_roads,
            out_dir=tmp_path / "out",
        )

    summary = json.loads(exc_info.value.summary_path.read_text(encoding="utf-8"))
    assert summary["missing_target_count"] == 1
    assert summary["invalid_selected_id_count"] == 1
