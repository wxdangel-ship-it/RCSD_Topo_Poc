from __future__ import annotations

import csv
import json
from pathlib import Path

import fiona
import pytest
from shapely.geometry import LineString, Point, mapping

from rcsd_topo_poc.modules.p01_arm_build.final_road_next_road import (
    build_frcsd_road_next_road,
    final_geojson,
)
from rcsd_topo_poc.modules.p01_arm_build.io import load_dataset, write_gpkg_layers
from rcsd_topo_poc.modules.p01_arm_build.models import DatasetInput
from rcsd_topo_poc.modules.p01_arm_build.review import (
    _dataset_review_context,
    _geometry_bounds,
    _line_points,
    _projector,
)
from rcsd_topo_poc.modules.p01_arm_build.runner import run_p01_arm_build_from_args
from rcsd_topo_poc.modules.p01_arm_build.road_next_road import read_road_next_road
from rcsd_topo_poc.modules.p01_arm_build.text_bundle import (
    P01_TEXT_BUNDLE_LIMIT_BYTES,
    run_p01_decode_text_bundle,
    run_p01_export_text_bundle,
)
from rcsd_topo_poc.modules.p01_arm_build.topology import build_dataset_arm_result


def _write_nodes(path: Path, features: list[tuple]) -> None:
    schema = {"geometry": "Point", "properties": {"id": "str", "mainnodeid": "str", "kind": "str", "grade": "int"}}
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for feature in features:
            if len(feature) == 5:
                node_id, mainnodeid, x, y, kind = feature
            else:
                node_id, mainnodeid, x, y = feature
                kind = "4" if mainnodeid and node_id == mainnodeid else "1"
            sink.write(
                {
                    "geometry": mapping(Point(x, y)),
                    "properties": {
                        "id": node_id,
                        "mainnodeid": mainnodeid,
                        "kind": kind,
                        "grade": 9,
                    },
                }
            )


def _write_roads(
    path: Path,
    features: list[tuple[str, str, str, int, str, list[tuple[float, float]]]],
    *,
    source: str | None = None,
) -> None:
    properties_schema = {
        "id": "str",
        "snodeid": "str",
        "enodeid": "str",
        "direction": "int",
        "formway": "str",
        "grade_2": "int",
    }
    if source is not None:
        properties_schema["Source"] = "str"
    schema = {
        "geometry": "LineString",
        "properties": properties_schema,
    }
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for road_id, snodeid, enodeid, direction, formway, coords in features:
            properties = {
                "id": road_id,
                "snodeid": snodeid,
                "enodeid": enodeid,
                "direction": direction,
                "formway": formway,
                "grade_2": 7,
            }
            if source is not None:
                properties["Source"] = source
            sink.write(
                {
                    "geometry": mapping(LineString(coords)),
                    "properties": properties,
                }
            )


def _write_roads_with_source(
    path: Path,
    features: list[tuple[str, str, str, int, str, str, list[tuple[float, float]]]],
) -> None:
    schema = {
        "geometry": "LineString",
        "properties": {
            "id": "str",
            "snodeid": "str",
            "enodeid": "str",
            "direction": "int",
            "formway": "str",
            "Source": "str",
        },
    }
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for road_id, snodeid, enodeid, direction, formway, source, coords in features:
            sink.write(
                {
                    "geometry": mapping(LineString(coords)),
                    "properties": {
                        "id": road_id,
                        "snodeid": snodeid,
                        "enodeid": enodeid,
                        "direction": direction,
                        "formway": formway,
                        "Source": source,
                    },
                }
            )


def _feature_ids(path: Path) -> set[str]:
    with fiona.open(path) as src:
        return {str(feature["properties"]["id"]) for feature in src}


def _case_nodes(prefix: str, index: int, dx: float) -> list[tuple[str, str | None, float, float]]:
    jid = f"{prefix}{index}"
    return [
        (jid, jid, dx, 0.0),
        (f"{jid}b", jid, dx + 5.0, 0.0),
        (f"{jid}n", None, dx, 30.0),
        (f"{jid}s", None, dx, -30.0),
        (f"{jid}w", None, dx - 30.0, 0.0),
        (f"{jid}e1", None, dx + 35.0, 0.0),
        (f"{jid}e2", None, dx + 65.0, 0.0),
        (f"{jid}rt", None, dx + 25.0, -22.0),
    ]


def _case_roads(prefix: str, index: int, dx: float) -> list[tuple[str, str, str, int, str, list[tuple[float, float]]]]:
    jid = f"{prefix}{index}"
    return [
        (f"{jid}_internal", jid, f"{jid}b", 0, "0", [(dx, 0.0), (dx + 5.0, 0.0)]),
        (f"{jid}_in", f"{jid}n", jid, 2, "0", [(dx, 30.0), (dx, 0.0)]),
        (f"{jid}_out", jid, f"{jid}s", 2, "0", [(dx, 0.0), (dx, -30.0)]),
        (f"{jid}_bi", f"{jid}b", f"{jid}w", 0, "0", [(dx + 5.0, 0.0), (dx - 30.0, 0.0)]),
        (f"{jid}_east_seed", f"{jid}b", f"{jid}e1", 2, "0", [(dx + 5.0, 0.0), (dx + 35.0, 0.0)]),
        (f"{jid}_east_continue", f"{jid}e1", f"{jid}e2", 2, "0", [(dx + 35.0, 0.0), (dx + 65.0, 0.0)]),
        (f"{jid}_right_turn", jid, f"{jid}rt", 2, "128", [(dx, 0.0), (dx + 25.0, -22.0)]),
    ]


def _write_dataset(
    tmp_path: Path,
    prefix: str,
    *,
    include_far_noise: bool = False,
    include_far_trace: bool = False,
    road_source: str | None = None,
) -> tuple[Path, Path]:
    nodes_path = tmp_path / f"{prefix.lower()}_nodes.gpkg"
    roads_path = tmp_path / f"{prefix.lower()}_roads.gpkg"
    nodes = _case_nodes(prefix, 1, 0.0) + _case_nodes(prefix, 2, 160.0)
    roads = _case_roads(prefix, 1, 0.0) + _case_roads(prefix, 2, 160.0)
    if include_far_noise:
        nodes.extend(
            [
                (f"{prefix}far_a", None, 100000.0, 100000.0),
                (f"{prefix}far_b", None, 100050.0, 100000.0),
            ]
        )
        roads.append(
            (
                f"{prefix}_far_noise",
                f"{prefix}far_a",
                f"{prefix}far_b",
                2,
                "0",
                [(100000.0, 100000.0), (100050.0, 100000.0)],
            )
        )
    if include_far_trace:
        nodes.append((f"{prefix}1far_trace", None, 100000.0, 0.0))
        roads.append(
            (
                f"{prefix}1_far_trace",
                f"{prefix}1e2",
                f"{prefix}1far_trace",
                2,
                "0",
                [(65.0, 0.0), (100000.0, 0.0)],
            )
        )
    _write_nodes(nodes_path, nodes)
    _write_roads(roads_path, roads, source=road_source)
    return nodes_path, roads_path


def _run_args(tmp_path: Path, out_root: Path, *, include_right_turn_value: bool = True) -> list[str]:
    swsd_nodes, swsd_roads = _write_dataset(tmp_path, "S")
    rcsd_nodes, rcsd_roads = _write_dataset(tmp_path, "R")
    frcsd_nodes, frcsd_roads = _write_dataset(tmp_path, "F")
    args = [
        "--swsd-nodes",
        str(swsd_nodes),
        "--swsd-roads",
        str(swsd_roads),
        "--rcsd-nodes",
        str(rcsd_nodes),
        "--rcsd-roads",
        str(rcsd_roads),
        "--frcsd-nodes",
        str(frcsd_nodes),
        "--frcsd-roads",
        str(frcsd_roads),
        "--junction-group",
        "S1,R1,F1",
        "--junction-group",
        "S2,R2,F2",
        "--out-root",
        str(out_root),
        "--run-id",
        "test_run",
    ]
    if include_right_turn_value:
        args.extend(["--right-turn-formway-value", "128"])
    return args


def test_p01_arm_build_outputs_multi_group_review_artifacts(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    assert run_p01_arm_build_from_args(_run_args(tmp_path, out_root)) == 0

    run_root = out_root / "test_run"
    assert (run_root / "preflight.json").is_file()
    assert (run_root / "p01_arm_build_summary.json").is_file()
    assert (run_root / "p01_arm_build_review_index.csv").is_file()
    assert (run_root / "cases" / "group_0001" / "case_input.json").is_file()
    assert (run_root / "cases" / "group_0002" / "case_summary.json").is_file()

    swsd_dir = run_root / "cases" / "group_0001" / "SWSD"
    context = json.loads((swsd_dir / "junction_context.json").read_text(encoding="utf-8"))
    assert context["member_node_ids"] == ["S1", "S1b"]
    assert context["internal_road_ids"] == ["S1_internal"]
    assert context["excluded_right_turn_road_ids"] == []
    assert context["advance_right_turn_road_ids"] == ["S1_right_turn"]
    assert context["formway_missing_road_ids"] == []
    assert context["formway_unparseable_road_ids"] == []

    initial_arms = json.loads((swsd_dir / "initial_arms.json").read_text(encoding="utf-8"))
    assert len(initial_arms) == 4
    assert any("S1_east_continue" in arm["connector_road_ids"] for arm in initial_arms)
    assert all("S1_right_turn" not in arm["member_road_ids"] for arm in initial_arms)
    assert all("trunk_status" in arm for arm in initial_arms)
    assert all("S1_right_turn" not in arm["trunk_road_ids"] for arm in initial_arms)

    advance_right_relations = json.loads((swsd_dir / "advance_right_turn_relations.json").read_text(encoding="utf-8"))
    assert len(advance_right_relations) == 1
    assert advance_right_relations[0]["advance_right_turn_road_ids"] == ["S1_right_turn"]
    assert advance_right_relations[0]["trace_status"] in {"target_arm_not_found", "ambiguous", "partial", "resolved"}
    assert (swsd_dir / "arm_movements.json").is_file()
    assert (swsd_dir / "road_movement_evidence.json").is_file()
    assert (swsd_dir / "arm_receiving_road_roles.json").is_file()
    assert (swsd_dir / "trunk_corrections.json").is_file()
    assert (swsd_dir / "corrected_final_arms.json").is_file()
    trunk_corrections = json.loads((swsd_dir / "trunk_corrections.json").read_text(encoding="utf-8"))
    assert {item["trunk_correction_status"] for item in trunk_corrections} == {
        "not_evaluated_no_road_next_road_input"
    }

    local_candidates = json.loads((swsd_dir / "local_arm_candidates.json").read_text(encoding="utf-8"))
    assert len(local_candidates) == 4
    assert all("S1_right_turn" not in item["source_seed_road_ids"] for item in local_candidates)
    assert any(item["local_stub_road_ids"] == ["S1_east_continue", "S1_east_seed"] for item in local_candidates)

    decisions = json.loads((swsd_dir / "through_decisions.json").read_text(encoding="utf-8"))
    assert any(decision["status"] == "simple_through" for decision in decisions)
    assert any(decision["status"] == "dead_end" for decision in decisions)

    assert (swsd_dir / "p01_arm_review.png").is_file()
    assert (swsd_dir / "review_layers.gpkg").is_file()
    frcsd_dir = run_root / "cases" / "group_0001" / "FRCSD"
    assert (frcsd_dir / "frcsd_road_next_road.geojson").is_file()
    assert (frcsd_dir / "frcsd_source_road_map.json").is_file()
    assert (frcsd_dir / "source_movement_policy_swsd.json").is_file()
    assert (frcsd_dir / "source_movement_policy_rcsd.json").is_file()
    assert (frcsd_dir / "parallel_branch_alignment.json").is_file()
    assert (frcsd_dir / "frcsd_road_next_road_audit.json").is_file()
    assert (frcsd_dir / "frcsd_road_next_road_issue_report.json").is_file()
    assert (frcsd_dir / "frcsd_road_next_road_review_layers.gpkg").is_file()
    assert (frcsd_dir / "frcsd_road_next_road_review.png").is_file()
    assert (run_root / "cases" / "group_0001" / "compare" / "p01_arm_compare.png").is_file()
    assert (run_root / "cases" / "group_0001" / "compare" / "p01_arm_compare_layers.gpkg").is_file()
    case_summary = json.loads((run_root / "cases" / "group_0001" / "case_summary.json").read_text(encoding="utf-8"))
    assert "trace_review_png_paths" not in case_summary
    assert not (run_root / "cases" / "group_0001" / "trace_review").exists()
    assert set(fiona.listlayers(swsd_dir / "review_layers.gpkg")) >= {
        "current_junction_nodes",
        "arm_roads",
        "local_arm_candidate_roads",
        "through_decision_nodes",
        "excluded_right_turn_roads",
        "advance_left_turn_roads",
        "advance_right_turn_roads",
        "arm_trunk_roads",
        "advance_right_turn_relations",
        "arm_movements",
        "road_movement_evidence",
        "straight_receiving_roads",
        "advance_left_receiving_roads",
        "trunk_excluded_by_movement_roads",
        "corrected_trunk_roads",
        "special_formway_issue_points",
    }

    with (run_root / "p01_arm_build_review_index.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 6
    assert {row["junction_group_id"] for row in rows} == {"group_0001", "group_0002"}
    assert {row["dataset"] for row in rows} == {"SWSD", "RCSD", "FRCSD"}
    assert all(row["review_priority"] in {"P0", "P1", "P2", "P3"} for row in rows)
    assert all("advance_right_turn_road_count" in row for row in rows)
    assert all("trunk_partial_count" in row for row in rows)
    assert all("arm_movement_count" in row for row in rows)
    assert all("trunk_correction_count" in row for row in rows)
    assert all("frcsd_generated_road_next_road_count" in row for row in rows)
    assert all("frcsd_parallel_branch_alignment_count" in row for row in rows)


def test_advance_right_turn_bit7_is_detected_without_explicit_field_value(tmp_path: Path) -> None:
    out_root = tmp_path / "out_no_rt"
    assert run_p01_arm_build_from_args(_run_args(tmp_path, out_root, include_right_turn_value=False)) == 0
    context = json.loads(
        (out_root / "test_run" / "cases" / "group_0001" / "SWSD" / "junction_context.json").read_text(
            encoding="utf-8"
        )
    )
    assert context["excluded_right_turn_road_ids"] == []
    assert context["advance_right_turn_road_ids"] == ["S1_right_turn"]
    initial_arms = json.loads(
        (out_root / "test_run" / "cases" / "group_0001" / "SWSD" / "initial_arms.json").read_text(
            encoding="utf-8"
        )
    )
    assert all("S1_right_turn" not in arm["seed_road_ids"] for arm in initial_arms)
    assert all("S1_right_turn" not in arm["member_road_ids"] for arm in initial_arms)


def test_advance_left_turn_bit8_stays_in_arm_but_not_trunk(tmp_path: Path) -> None:
    nodes_path = tmp_path / "adv_left_nodes.gpkg"
    roads_path = tmp_path / "adv_left_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
            ("L", None, 40.0, 10.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("in", "N", "C", 2, "0", [(0.0, 20.0), (0.0, 0.0)]),
            ("out", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("adv_left", "E", "L", 2, "256", [(20.0, 0.0), (40.0, 10.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert "adv_left" in result.context.advance_left_turn_road_ids
    arm = next(item for item in result.initial_arms if "adv_left" in item.member_road_ids)
    assert arm.has_advance_left_turn is True
    assert arm.advance_left_turn_road_ids == ("adv_left",)
    assert "adv_left" not in arm.trunk_road_ids
    assert "adv_left" in arm.non_trunk_member_road_ids


def test_advance_right_turn_relation_resolves_to_outbound_arm(tmp_path: Path) -> None:
    nodes_path = tmp_path / "adv_right_nodes.gpkg"
    roads_path = tmp_path / "adv_right_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
            ("M", None, 20.0, -12.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("in", "N", "C", 2, "0", [(0.0, 20.0), (0.0, 0.0)]),
            ("out", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("adv_right", "C", "M", 2, "128", [(0.0, 0.0), (20.0, -12.0)]),
            ("adv_right_link", "M", "E", 2, "0", [(20.0, -12.0), (20.0, 0.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert "adv_right" in result.context.advance_right_turn_road_ids
    assert all("adv_right" not in arm.member_road_ids for arm in result.initial_arms)
    assert len(result.advance_right_turn_relations) == 1
    relation = result.advance_right_turn_relations[0]
    assert relation.trace_status == "resolved"
    assert relation.from_arm_id
    assert relation.to_arm_id
    assert relation.advance_right_turn_road_ids == ("adv_right",)
    assert relation.trace_road_ids[:2] == ("adv_right", "adv_right_link")
    assert any(relation.relation_id in arm.advance_right_turn_relation_ids for arm in result.initial_arms)


def test_advance_right_turn_adjacent_to_seed_outside_node_is_detected(tmp_path: Path) -> None:
    nodes_path = tmp_path / "adjacent_adv_right_nodes.gpkg"
    roads_path = tmp_path / "adjacent_adv_right_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("in", "N", "C", 2, "0", [(0.0, 20.0), (0.0, 0.0)]),
            ("out", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("adjacent_adv_right", "N", "E", 2, "128", [(0.0, 20.0), (20.0, 0.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert result.context.advance_right_turn_road_ids == ("adjacent_adv_right",)
    assert all("adjacent_adv_right" not in arm.member_road_ids for arm in result.initial_arms)
    assert len(result.advance_right_turn_relations) == 1
    relation = result.advance_right_turn_relations[0]
    assert relation.trace_status == "resolved"
    assert relation.advance_right_turn_road_ids == ("adjacent_adv_right",)
    assert relation.from_arm_id
    assert relation.to_arm_id


def test_contiguous_advance_right_turn_roads_form_one_relation(tmp_path: Path) -> None:
    nodes_path = tmp_path / "chain_adv_right_nodes.gpkg"
    roads_path = tmp_path / "chain_adv_right_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("M", None, 12.0, 12.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("in", "N", "C", 2, "0", [(0.0, 20.0), (0.0, 0.0)]),
            ("out", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("adv_right_1", "N", "M", 2, "128", [(0.0, 20.0), (12.0, 12.0)]),
            ("adv_right_2", "M", "E", 2, "128", [(12.0, 12.0), (20.0, 0.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert result.context.advance_right_turn_road_ids == ("adv_right_1", "adv_right_2")
    assert len(result.advance_right_turn_relations) == 1
    relation = result.advance_right_turn_relations[0]
    assert relation.trace_status == "resolved"
    assert relation.advance_right_turn_road_ids == ("adv_right_1", "adv_right_2")
    assert relation.trace_road_ids[:3] == ("adv_right_1", "adv_right_2", "out")
    assert all("adv_right_1" not in arm.member_road_ids for arm in result.initial_arms)
    assert all("adv_right_2" not in arm.member_road_ids for arm in result.initial_arms)


def test_trunk_falls_back_to_local_non_special_seed_roads(tmp_path: Path) -> None:
    nodes_path = tmp_path / "local_trunk_nodes.gpkg"
    roads_path = tmp_path / "local_trunk_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
            ("L", None, 40.0, 10.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("in", "N", "C", 2, "0", [(0.0, 20.0), (0.0, 0.0)]),
            ("out", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("adv_left", "E", "L", 2, "256", [(20.0, 0.0), (40.0, 10.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert any(arm.trunk_road_ids for arm in result.initial_arms)
    for arm in result.initial_arms:
        assert "adv_left" not in arm.trunk_road_ids
        if set(arm.seed_road_ids) & {"in", "out"}:
            assert arm.trunk_status == "partial"
            assert set(arm.trunk_road_ids) <= {"in", "out"}


def test_formway_missing_and_unparseable_are_audited(tmp_path: Path) -> None:
    nodes_path = tmp_path / "formway_nodes.gpkg"
    roads_path = tmp_path / "formway_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("missing_formway", "N", "C", 2, "", [(0.0, 20.0), (0.0, 0.0)]),
            ("bad_formway", "C", "E", 2, "abc", [(0.0, 0.0), (20.0, 0.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert result.context.formway_missing_road_ids == ("missing_formway",)
    assert result.context.formway_unparseable_road_ids == ("bad_formway",)
    assert result.issue_report.issue_counts["formway_missing"] == 1
    assert result.issue_report.issue_counts["formway_unparseable"] == 1
    assert result.metrics["formway_missing_count"] == 1
    assert result.metrics["formway_unparseable_count"] == 1


def _movement_fixture(tmp_path: Path) -> tuple[Path, Path]:
    nodes_path = tmp_path / "movement_nodes.gpkg"
    roads_path = tmp_path / "movement_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("W", None, -20.0, 0.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("n_adv_left", "N", "C", 2, "256", [(0.0, 20.0), (0.0, 0.0)]),
            ("w_in", "W", "C", 2, "0", [(-20.0, 0.0), (0.0, 0.0)]),
            ("e_main", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("e_left_recv", "C", "E", 2, "0", [(0.0, 1.0), (20.0, 1.0)]),
        ],
    )
    return nodes_path, roads_path


def _frcsd_source_fixture(tmp_path: Path, *, from_source: str = "2", to_source: str = "2") -> tuple[Path, Path]:
    nodes_path = tmp_path / f"frcsd_{from_source}_{to_source}_nodes.gpkg"
    roads_path = tmp_path / f"frcsd_{from_source}_{to_source}_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("W", None, -20.0, 0.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads_with_source(
        roads_path,
        [
            ("f_n_adv_left", "N", "C", 2, "256", from_source, [(0.0, 20.0), (0.0, 0.0)]),
            ("f_w_in", "W", "C", 2, "0", from_source, [(-20.0, 0.0), (0.0, 0.0)]),
            ("f_e_main", "C", "E", 2, "0", to_source, [(0.0, 0.0), (20.0, 0.0)]),
            ("f_e_left_recv", "C", "E", 2, "0", to_source, [(0.0, 1.0), (20.0, 1.0)]),
        ],
    )
    return nodes_path, roads_path


def _renamed_source_fixture(tmp_path: Path, prefix: str) -> tuple[Path, Path]:
    nodes_path = tmp_path / f"{prefix.lower()}_source_nodes.gpkg"
    roads_path = tmp_path / f"{prefix.lower()}_source_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("W", None, -20.0, 0.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            (f"{prefix}_n_adv_left", "N", "C", 2, "256", [(0.0, 20.0), (0.0, 0.0)]),
            (f"{prefix}_w_in", "W", "C", 2, "0", [(-20.0, 0.0), (0.0, 0.0)]),
            (f"{prefix}_e_main", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            (f"{prefix}_e_left_recv", "C", "E", 2, "0", [(0.0, 1.0), (20.0, 1.0)]),
        ],
    )
    return nodes_path, roads_path


def _arm_id_by_seed(result, seed_road_id: str) -> str:
    for arm in result.final_arms:
        if seed_road_id in arm.initial_arm["seed_road_ids"]:
            return arm.final_arm_id
    raise AssertionError(f"seed road not found: {seed_road_id}")


def _build_result(dataset: str, nodes_path: Path, roads_path: Path, rnr_records=tuple()):
    loaded = load_dataset(DatasetInput(dataset, nodes_path, roads_path))
    result = build_dataset_arm_result(
        loaded,
        junction_id="C",
        right_turn_formway_values={"128"},
        road_next_road_records=tuple(rnr_records),
        has_road_next_road_input=bool(rnr_records),
    )
    return loaded, result


def test_road_next_road_json_and_geojson_are_normalised(tmp_path: Path) -> None:
    swsd_path = tmp_path / "RoadNextRoad.json"
    swsd_path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "roadId": -1,
                    "nextRoadId": -2,
                    "road_id": "r1",
                    "next_road_id": "r2",
                    "turnType": 8,
                    "type": 1,
                    "source": 2,
                }
            ]
        ),
        encoding="utf-8",
    )
    geojson_path = tmp_path / "RoadNextRoad.geojson"
    geojson_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "id": 2,
                            "road_id": "r3",
                            "next_road_id": "r4",
                            "turntype": 4,
                            "source": 1,
                        },
                        "geometry": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    swsd = read_road_next_road(swsd_path)
    rcsd = read_road_next_road(geojson_path)

    assert swsd[0].road_id == "r1"
    assert swsd[0].next_road_id == "r2"
    assert swsd[0].raw_turn_type == "8"
    assert rcsd[0].road_id == "r3"
    assert rcsd[0].next_road_id == "r4"
    assert rcsd[0].raw_turn_type == "4"


def test_road_next_road_movement_excludes_advance_left_only_receiving_trunk(tmp_path: Path) -> None:
    nodes_path, roads_path = _movement_fixture(tmp_path)
    rnr_path = tmp_path / "RoadNextRoad.json"
    rnr_path.write_text(
        json.dumps(
            [
                {"id": "straight", "road_id": "w_in", "next_road_id": "e_main", "turnType": "left_code"},
                {"id": "adv_left", "road_id": "n_adv_left", "next_road_id": "e_left_recv", "turnType": "straight_code"},
                {"id": "outside", "road_id": "outside_a", "next_road_id": "outside_b", "turnType": "4"},
            ]
        ),
        encoding="utf-8",
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(
        loaded,
        junction_id="C",
        right_turn_formway_values={"128"},
        road_next_road_records=read_road_next_road(rnr_path),
        has_road_next_road_input=True,
    )

    from_w = _arm_id_by_seed(result, "w_in")
    from_n = _arm_id_by_seed(result, "n_adv_left")
    to_e = _arm_id_by_seed(result, "e_main")
    straight = next(item for item in result.arm_movements if item.from_arm_id == from_w and item.to_arm_id == to_e)
    left = next(item for item in result.arm_movements if item.from_arm_id == from_n and item.to_arm_id == to_e)
    correction = next(item for item in result.trunk_corrections if item.arm_id == to_e)

    assert len(result.arm_movements) == len(result.final_arms) * len(result.final_arms)
    assert result.metrics["road_movement_evidence_count"] == 3
    assert result.metrics["road_movement_mapped_count"] == 2
    assert result.metrics["road_movement_unmapped_count"] == 1
    assert straight.movement_type == "straight"
    assert straight.permission_evidence_status == "allowed_supported"
    assert left.movement_type == "left"
    assert left.has_advance_left_road_evidence is True
    assert correction.trunk_correction_status == "corrected"
    assert correction.movement_excluded_receiving_road_ids == ("e_left_recv",)
    assert "e_left_recv" not in correction.corrected_trunk_road_ids
    assert "e_main" in correction.corrected_trunk_road_ids
    assert any(role.road_id == "e_left_recv" and role.exclude_from_trunk for role in result.arm_receiving_road_roles)
    assert result.corrected_final_arms
    assert result.corrected_final_arms[0].final_arm["advance_left_turn_road_ids"] is not None


def test_road_next_road_without_straight_receiving_does_not_exclude_trunk(tmp_path: Path) -> None:
    nodes_path, roads_path = _movement_fixture(tmp_path)
    rnr_path = tmp_path / "RoadNextRoad.json"
    rnr_path.write_text(
        json.dumps([{"id": "adv_left", "road_id": "n_adv_left", "next_road_id": "e_left_recv", "turnType": 1}]),
        encoding="utf-8",
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(
        loaded,
        junction_id="C",
        right_turn_formway_values={"128"},
        road_next_road_records=read_road_next_road(rnr_path),
        has_road_next_road_input=True,
    )

    to_e = _arm_id_by_seed(result, "e_main")
    correction = next(item for item in result.trunk_corrections if item.arm_id == to_e)

    assert correction.trunk_correction_status == "straight_evidence_missing"
    assert correction.movement_excluded_receiving_road_ids == tuple()
    assert "e_left_recv" in correction.corrected_trunk_road_ids


def test_frcsd_road_next_road_same_source_inheritance(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="2", to_source="2")
    swsd_rnr = tmp_path / "swsd_rnr.json"
    swsd_rnr.write_text(
        json.dumps(
            [
                {"id": "s_allowed", "road_id": "s_w_in", "next_road_id": "s_e_main", "turnType": 9},
                {"id": "s_adv_left", "road_id": "s_n_adv_left", "next_road_id": "s_e_left_recv", "turnType": 9},
            ]
        ),
        encoding="utf-8",
    )
    frcsd_rnr = tmp_path / "frcsd_rnr.json"
    frcsd_rnr.write_text(
        json.dumps(
            [
                {"id": "f_allowed", "road_id": "f_w_in", "next_road_id": "f_e_main", "turnType": 9},
                {"id": "f_adv_left", "road_id": "f_n_adv_left", "next_road_id": "f_e_left_recv", "turnType": 9},
            ]
        ),
        encoding="utf-8",
    )
    swsd_records = read_road_next_road(swsd_rnr)
    frcsd_records = read_road_next_road(frcsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads, swsd_records)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads, frcsd_records)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": frcsd_records},
    )
    geojson = final_geojson(final)

    pairs = {(feature["properties"]["road_id"], feature["properties"]["next_road_id"]) for feature in geojson["features"]}
    assert ("f_w_in", "f_e_main") in pairs
    assert final.metrics["frcsd_same_source_inherited_count"] >= 1
    assert all(item.match_status == "matched" for item in final.source_road_map)
    assert geojson["features"][0]["geometry"] is None
    assert {"id", "road_id", "next_road_id", "type", "source", "turntype", "city_code"} <= set(
        geojson["features"][0]["properties"]
    )
    assert any(
        item.source_dataset == "SWSD"
        and item.alignment_status == "count_matched_ordered"
        and any(
            pair["frcsd_road_id"] == "f_e_left_recv" and pair["source_road_id"] == "s_e_left_recv"
            for pair in item.aligned_pairs
        )
        for item in final.parallel_branch_alignment
    )


def test_frcsd_source_policy_records_prohibited_and_missing_right_carrier_issue(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="2", to_source="2")
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": tuple(), "RCSD": tuple(), "FRCSD": tuple()},
    )

    assert any(item.permission_status == "prohibited" for item in final.source_movement_policy_swsd)
    assert any(item.permission_status == "prohibited" for item in final.source_movement_policy_rcsd)
    assert "data_error_or_missing_right_turn_carrier" in final.issue_report["issue_counts"]
    assert any(
        item.movement_type == "right"
        and item.permission_status == "manual_review_required"
        and "data_error_or_missing_right_turn_carrier" in item.issue_flags
        for item in final.audit
    )


def test_frcsd_road_next_road_cross_source_uses_primary_source(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="1", to_source="2")
    rcsd_rnr = tmp_path / "rcsd_rnr.geojson"
    rcsd_rnr.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {"id": "r_allowed", "road_id": "r_w_in", "next_road_id": "r_e_main", "turntype": 1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rcsd_records = read_road_next_road(rcsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads, rcsd_records)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": tuple(), "RCSD": rcsd_records, "FRCSD": tuple()},
    )

    generated = [
        item
        for item in final.audit
        if item.f_road_id == "f_w_in" and item.f_next_road_id == "f_e_main" and item.permission_status == "allowed"
    ]
    assert generated
    assert generated[0].primary_source == "RCSD"
    assert generated[0].generation_rule == "cross_source_primary_source_policy"
    assert final.metrics["frcsd_cross_source_generated_count"] >= 1


def test_frcsd_road_next_road_rcsd_to_swsd_fallback(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="1", to_source="2")
    swsd_rnr = tmp_path / "swsd_fallback_rnr.json"
    swsd_rnr.write_text(
        json.dumps([{"id": "s_fallback", "road_id": "s_w_in", "next_road_id": "s_e_main", "turnType": 1}]),
        encoding="utf-8",
    )
    swsd_records = read_road_next_road(swsd_rnr)
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, swsd_roads, swsd_records)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": swsd_records, "RCSD": tuple(), "FRCSD": tuple()},
    )

    fallback = [
        item
        for item in final.audit
        if item.f_road_id == "f_w_in" and item.f_next_road_id == "f_e_main" and item.permission_status == "allowed"
    ]
    assert fallback
    assert fallback[0].generation_rule == "rcsd_to_swsd_fallback"
    assert fallback[0].reference_source == "SWSD"
    assert final.metrics["frcsd_fallback_to_swsd_count"] >= 1


def test_frcsd_source_geometry_mapping_missing_and_ambiguous_are_issues(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _renamed_source_fixture(tmp_path, "s")
    rcsd_nodes, rcsd_roads = _renamed_source_fixture(tmp_path, "r")
    duplicate_path = tmp_path / "s_duplicate_roads.gpkg"
    _write_roads(
        duplicate_path,
        [
            ("s_w_in", "W", "C", 2, "0", [(-20.0, 0.0), (0.0, 0.0)]),
            ("s_w_in_dup", "W", "C", 2, "0", [(-20.0, 0.0), (0.0, 0.0)]),
            ("s_e_main", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("s_e_left_recv", "C", "E", 2, "0", [(0.0, 1.0), (20.0, 1.0)]),
            ("s_n_adv_left", "N", "C", 2, "256", [(0.0, 20.0), (0.0, 0.0)]),
        ],
    )
    frcsd_nodes, frcsd_roads = _frcsd_source_fixture(tmp_path, from_source="2", to_source="2")
    loaded_s, result_s = _build_result("SWSD", swsd_nodes, duplicate_path)
    loaded_r, result_r = _build_result("RCSD", rcsd_nodes, rcsd_roads)
    loaded_f, result_f = _build_result("FRCSD", frcsd_nodes, frcsd_roads)

    final = build_frcsd_road_next_road(
        loaded_by_dataset={"SWSD": loaded_s, "RCSD": loaded_r, "FRCSD": loaded_f},
        result_by_dataset={"SWSD": result_s, "RCSD": result_r, "FRCSD": result_f},
        road_next_road_by_dataset={"SWSD": tuple(), "RCSD": tuple(), "FRCSD": tuple()},
    )

    assert final.metrics["frcsd_source_geometry_match_ambiguous_count"] >= 1
    assert "ambiguous_source_geometry_match" in final.issue_report["issue_counts"]


def test_dataset_review_context_excludes_far_unrelated_roads(tmp_path: Path) -> None:
    nodes_path, roads_path = _write_dataset(tmp_path, "S", include_far_noise=True)
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))
    result = build_dataset_arm_result(loaded, junction_id="S1", right_turn_formway_values={"128"})

    geometries, road_ids, node_ids = _dataset_review_context(loaded, result)
    bounds = _geometry_bounds(geometries)

    assert "S_far_noise" not in road_ids
    assert "Sfar_a" not in node_ids
    assert bounds[2] < 120.0
    assert bounds[3] < 60.0


def test_dataset_review_context_stays_near_junction_for_long_traces(tmp_path: Path) -> None:
    nodes_path, roads_path = _write_dataset(tmp_path, "S", include_far_trace=True)
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))
    result = build_dataset_arm_result(loaded, junction_id="S1", right_turn_formway_values={"128"})

    geometries, road_ids, _ = _dataset_review_context(loaded, result)
    bounds = _geometry_bounds(geometries)

    assert any("S1_far_trace" in trace.traced_road_ids for trace in result.traces)
    assert "S1_far_trace" not in road_ids
    assert bounds[2] < 120.0


def test_local_arm_candidates_group_current_seed_trends_with_optional_final_fallback(tmp_path: Path) -> None:
    nodes_path, roads_path = _write_dataset(tmp_path, "S")
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))
    result = build_dataset_arm_result(loaded, junction_id="S1", right_turn_formway_values={"128"})

    assert len(result.final_arms) == len(result.initial_arms)
    assert {arm.merge_status for arm in result.final_arms} == {"not_applied"}
    assert len(result.local_arm_candidates) == 4
    west = next(item for item in result.local_arm_candidates if item.bidirectional_seed_road_ids == ("S1_bi",))
    east = next(item for item in result.local_arm_candidates if item.outbound_seed_road_ids == ("S1_east_seed",))

    assert west.build_status == "candidate"
    assert east.local_stub_road_ids == ("S1_east_continue", "S1_east_seed")
    assert "S1_right_turn" not in {seed for item in result.local_arm_candidates for seed in item.source_seed_road_ids}
    assert result.metrics["local_arm_candidate_count"] == 4


def test_final_arms_use_local_candidate_fallback_when_trace_fragments_same_local_arm(tmp_path: Path) -> None:
    nodes_path = tmp_path / "fallback_nodes.gpkg"
    roads_path = tmp_path / "fallback_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("D", None, 20.0, 0.0, "0"),
            ("B", None, 10.0, 0.5, "1"),
            ("T", "T", 20.0, 0.8, "4"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("dead_seed", "C", "D", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("live_seed", "C", "B", 2, "0", [(0.0, 0.0), (10.0, 0.5)]),
            ("live_continue", "B", "T", 2, "0", [(10.0, 0.5), (20.0, 0.8)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert len(result.initial_arms) == 2
    assert len(result.local_arm_candidates) == 1
    assert len(result.final_arms) == 1
    assert result.final_arms[0].source_initial_arm_ids == ("A1", "A2")
    assert result.final_arms[0].merge_status == "local_candidate_fallback"
    assert result.metrics["final_arm_count"] == 1
    assert result.metrics["local_arm_fragmentation_gap"] == 1


def test_through_tie_break_avoids_near_parallel_one_hop_dead_end(tmp_path: Path) -> None:
    nodes_path = tmp_path / "tie_nodes.gpkg"
    roads_path = tmp_path / "tie_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("G", None, 10.0, 0.0, "1"),
            ("D", None, 20.0, 0.1, "0"),
            ("L", None, 20.0, 0.5, "1"),
            ("T", "T", 30.0, 1.0, "4"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("seed", "C", "G", 2, "0", [(0.0, 0.0), (10.0, 0.0)]),
            ("dead_candidate", "G", "D", 2, "0", [(10.0, 0.0), (20.0, 0.1)]),
            ("live_candidate", "G", "L", 2, "0", [(10.0, 0.0), (20.0, 0.5)]),
            ("live_continue", "L", "T", 2, "0", [(20.0, 0.5), (30.0, 1.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("FRCSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert result.traces[0].traced_road_ids == ("seed", "live_candidate", "live_continue")
    assert "dead_candidate" not in result.traces[0].traced_road_ids
    assert result.decisions[0].outgoing_road_id == "live_candidate"
    assert "tie_break=near_parallel_non_dead_end_over_one_hop_dead_end" in result.decisions[0].decision_reason


def test_kind_aware_t_junction_and_kind4_stop_rules(tmp_path: Path) -> None:
    nodes_path = tmp_path / "kind_nodes.gpkg"
    roads_path = tmp_path / "kind_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("JM", "JM", 0.0, 0.0, "4"),
            ("TM", None, 10.0, 0.0, "2048"),
            ("EM", None, 20.0, 0.0, "1"),
            ("NM", None, 10.0, 10.0, "1"),
            ("JS", "JS", 0.0, 40.0, "4"),
            ("TS", None, 0.0, 50.0, "2048"),
            ("WS", None, -10.0, 50.0, "1"),
            ("ES", None, 10.0, 50.0, "1"),
            ("JK", "JK", 0.0, 80.0, "4"),
            ("K4", None, 10.0, 80.0, "4"),
            ("EK", None, 20.0, 80.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("main_seed", "JM", "TM", 2, "0", [(0.0, 0.0), (10.0, 0.0)]),
            ("main_continue", "TM", "EM", 2, "0", [(10.0, 0.0), (20.0, 0.0)]),
            ("main_side", "TM", "NM", 2, "0", [(10.0, 0.0), (10.0, 10.0)]),
            ("side_seed", "JS", "TS", 2, "0", [(0.0, 40.0), (0.0, 50.0)]),
            ("side_left", "WS", "TS", 2, "0", [(-10.0, 50.0), (0.0, 50.0)]),
            ("side_right", "TS", "ES", 2, "0", [(0.0, 50.0), (10.0, 50.0)]),
            ("kind4_seed", "JK", "K4", 2, "0", [(0.0, 80.0), (10.0, 80.0)]),
            ("kind4_continue", "K4", "EK", 2, "0", [(10.0, 80.0), (20.0, 80.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    mainline = build_dataset_arm_result(loaded, junction_id="JM", right_turn_formway_values={"128"})
    assert any(decision.status == "t_mainline_through" for decision in mainline.decisions)
    assert any("main_continue" in trace.traced_road_ids for trace in mainline.traces)

    side = build_dataset_arm_result(loaded, junction_id="JS", right_turn_formway_values={"128"})
    assert side.traces[0].stop_type == "t_side_terminal"
    assert side.traces[0].traced_road_ids == ("side_seed",)

    kind4 = build_dataset_arm_result(loaded, junction_id="JK", right_turn_formway_values={"128"})
    assert kind4.traces[0].stop_type == "semantic_boundary"
    assert kind4.traces[0].traced_road_ids == ("kind4_seed",)


def test_p01_text_bundle_roundtrip_uses_bfs_context_not_far_spatial_noise(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _write_dataset(tmp_path, "S", include_far_noise=True)
    rcsd_nodes, rcsd_roads = _write_dataset(tmp_path, "R", include_far_noise=True)
    frcsd_nodes, frcsd_roads = _write_dataset(tmp_path, "F", include_far_noise=True, road_source="2")
    bundle_path = tmp_path / "p01_case_bundle.txt"
    swsd_road_node_road = tmp_path / "SWSD_RoadNodeRoad.json"
    swsd_road_node_road.write_text(
        json.dumps(
            [
                {"id": "s_keep", "road_id": "S1_in", "next_road_id": "S1_out", "turnType": "raw_keep"},
                {"id": "s_far", "road_id": "S_far_noise", "next_road_id": "S_far_other", "turnType": "raw_far"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rcsd_road_next_road = tmp_path / "RCSD_RoadNextRoad.geojson"
    rcsd_road_next_road.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {
                            "id": "r_keep",
                            "road_id": "R1_in",
                            "next_road_id": "R1_out",
                            "turntype": "audit_only",
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": None,
                        "properties": {
                            "id": "r_far",
                            "road_id": "R_far_noise",
                            "next_road_id": "R_far_other",
                            "turntype": "audit_far",
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifacts = run_p01_export_text_bundle(
        swsd_nodes=swsd_nodes,
        swsd_roads=swsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        frcsd_nodes=frcsd_nodes,
        frcsd_roads=frcsd_roads,
        swsd_road_node_road=swsd_road_node_road,
        rcsd_road_next_road=rcsd_road_next_road,
        junction_group="S1,R1,F1",
        out_txt=bundle_path,
        bfs_depth=1,
    )

    assert artifacts.success, artifacts.failure_detail
    assert bundle_path.is_file()
    assert artifacts.bundle_size_bytes <= P01_TEXT_BUNDLE_LIMIT_BYTES

    decoded = run_p01_decode_text_bundle(bundle_txt=bundle_path, out_dir=tmp_path / "decoded_bundle")
    assert decoded.success
    swsd_decoded = decoded.out_dir / "SWSD"
    road_ids = _feature_ids(swsd_decoded / "roads.gpkg")
    node_ids = _feature_ids(swsd_decoded / "nodes.gpkg")

    assert "S1_east_seed" in road_ids
    assert "S1_east_continue" in road_ids
    assert "S_far_noise" not in road_ids
    assert "Sfar_a" not in node_ids
    with fiona.open(decoded.out_dir / "FRCSD" / "roads.gpkg") as src:
        schema_keys = {key.lower() for key in src.schema["properties"]}
        decoded_roads = [dict(feature["properties"]) for feature in src]
    assert "source" in schema_keys
    assert "grade_2" in schema_keys
    assert {str(item.get("source") or item.get("Source")) for item in decoded_roads} == {"2"}
    swsd_rnr_payload = json.loads((decoded.out_dir / "SWSD" / "RoadNodeRoad.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in swsd_rnr_payload] == ["s_keep"]
    rcsd_rnr_payload = json.loads((decoded.out_dir / "RCSD" / "RoadNextRoad.geojson").read_text(encoding="utf-8"))
    assert [feature["properties"]["id"] for feature in rcsd_rnr_payload["features"]] == ["r_keep"]

    manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))
    assert manifest["encoder_info"]["selection"] == "semantic-road-topology-bfs"
    assert manifest["datasets"]["SWSD"]["selected_road_count"] < 10
    assert manifest["datasets"]["SWSD"]["optional_relation_inputs"]["RoadNodeRoad.json"]["included_record_count"] == 1
    assert manifest["datasets"]["RCSD"]["optional_relation_inputs"]["RoadNextRoad.geojson"]["included_record_count"] == 1


def test_p01_text_bundle_resolves_dataset_junction_id_prefixes(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _write_dataset(tmp_path, "S")
    rcsd_nodes, rcsd_roads = _write_dataset(tmp_path, "C")
    frcsd_nodes, frcsd_roads = _write_dataset(tmp_path, "D")
    bundle_path = tmp_path / "p01_prefixed_bundle.txt"

    artifacts = run_p01_export_text_bundle(
        swsd_nodes=swsd_nodes,
        swsd_roads=swsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        frcsd_nodes=frcsd_nodes,
        frcsd_roads=frcsd_roads,
        junction_group="S1,RC1,FD1",
        out_txt=bundle_path,
        bfs_depth=1,
    )

    assert artifacts.success, artifacts.failure_detail

    decoded = run_p01_decode_text_bundle(bundle_txt=bundle_path, out_dir=tmp_path / "decoded_prefixed")
    manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))

    assert manifest["junction_group"] == {"SWSD": "S1", "RCSD": "RC1", "FRCSD": "FD1"}
    assert manifest["datasets"]["RCSD"]["resolved_group_id"] == "C1"
    assert manifest["datasets"]["FRCSD"]["resolved_group_id"] == "D1"
    assert _feature_ids(decoded.out_dir / "RCSD" / "nodes.gpkg")
    assert _feature_ids(decoded.out_dir / "FRCSD" / "roads.gpkg")


def test_p01_text_bundle_auto_fit_expands_to_deeper_trace_context(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _write_dataset(tmp_path, "S", include_far_trace=True)
    rcsd_nodes, rcsd_roads = _write_dataset(tmp_path, "R", include_far_trace=True)
    frcsd_nodes, frcsd_roads = _write_dataset(tmp_path, "F", include_far_trace=True)
    bundle_path = tmp_path / "p01_auto_fit_bundle.txt"

    artifacts = run_p01_export_text_bundle(
        swsd_nodes=swsd_nodes,
        swsd_roads=swsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        frcsd_nodes=frcsd_nodes,
        frcsd_roads=frcsd_roads,
        junction_group="S1,R1,F1",
        out_txt=bundle_path,
        bfs_depth=1,
        auto_fit=True,
        max_bfs_depth=2,
    )

    assert artifacts.success, artifacts.failure_detail
    assert artifacts.selected_bfs_depth == 2
    decoded = run_p01_decode_text_bundle(bundle_txt=bundle_path, out_dir=tmp_path / "decoded_auto_fit")
    road_ids = _feature_ids(decoded.out_dir / "SWSD" / "roads.gpkg")
    manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))

    assert "S1_far_trace" in road_ids
    assert manifest["auto_fit"]["selected_bfs_depth"] == 2
    assert [attempt["bfs_depth"] for attempt in manifest["auto_fit"]["attempts"]] == [1, 2]


def test_p01_text_bundle_splits_when_text_limit_is_too_small(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _write_dataset(tmp_path, "S", include_far_trace=True)
    rcsd_nodes, rcsd_roads = _write_dataset(tmp_path, "R", include_far_trace=True)
    frcsd_nodes, frcsd_roads = _write_dataset(tmp_path, "F", include_far_trace=True)
    bundle_path = tmp_path / "p01_split_bundle.txt"

    artifacts = run_p01_export_text_bundle(
        swsd_nodes=swsd_nodes,
        swsd_roads=swsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        frcsd_nodes=frcsd_nodes,
        frcsd_roads=frcsd_roads,
        junction_group="S1,R1,F1",
        out_txt=bundle_path,
        bfs_depth=2,
        max_text_size_bytes=40_000,
    )

    assert artifacts.success, artifacts.failure_detail
    assert len(artifacts.part_txt_paths) > 1
    assert all(path.is_file() and path.stat().st_size <= 40_000 for path in artifacts.part_txt_paths)

    decoded = run_p01_decode_text_bundle(bundle_txt=artifacts.part_txt_paths[-1], out_dir=tmp_path / "decoded_split")
    manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))

    assert set(manifest["datasets"]) == {"SWSD", "RCSD", "FRCSD"}
    assert (decoded.out_dir / "SWSD" / "roads.gpkg").is_file()
    assert (decoded.out_dir / "RCSD" / "roads.gpkg").is_file()
    assert (decoded.out_dir / "FRCSD" / "roads.gpkg").is_file()
    size_report = json.loads((decoded.out_dir / "size_report.json").read_text(encoding="utf-8"))
    assert size_report["split_bundle"]["enabled"] is True


def test_review_line_points_accepts_3d_coordinates() -> None:
    project = _projector((0.0, 0.0, 10.0, 10.0), left=0, top=0, width=100, height=100)

    points = _line_points(LineString([(0.0, 0.0, 5.0), (10.0, 10.0, 6.0)]), project)

    assert len(points) == 2
    assert all(len(point) == 2 for point in points)


def test_write_gpkg_layers_reports_locked_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gpkg_path = tmp_path / "review_layers.gpkg"
    gpkg_path.write_bytes(b"locked")
    original_unlink = Path.unlink

    def locked_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == gpkg_path:
            raise PermissionError("locked")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)

    with pytest.raises(RuntimeError, match="new --run-id"):
        write_gpkg_layers(gpkg_path, layers=[], crs=None, crs_wkt=None)


def test_p01_source_does_not_reference_grade_fields() -> None:
    source_dir = Path("src/rcsd_topo_poc/modules/p01_arm_build")
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_dir.glob("*.py"))
    assert "grade" not in source_text.lower()
