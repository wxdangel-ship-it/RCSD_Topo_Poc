from __future__ import annotations

import csv


import json


from dataclasses import replace


from pathlib import Path


import fiona


import pytest


from pyproj import Transformer


from shapely.geometry import LineString, Point, mapping


from rcsd_topo_poc.modules.p01_arm_build.final_road_next_road import (
    ArmSourceProfile,
    _choose_reference_source,
    build_frcsd_road_next_road,
    final_geojson,
)


from rcsd_topo_poc.modules.p01_arm_build.final_arm_validation import build_final_arm_validation


from rcsd_topo_poc.modules.p01_arm_build.io import load_dataset, write_gpkg_layers


from rcsd_topo_poc.modules.p01_arm_build.models import ArmTrace, DatasetInput, FinalArm, InitialArm, NodeRecord, RoadRecord


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


def _write_nodes(path: Path, features: list[tuple], *, crs: str = "EPSG:3857") -> None:
    schema = {"geometry": "Point", "properties": {"id": "str", "mainnodeid": "str", "kind": "str", "grade": "int"}}
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs=crs) as sink:
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
    crs: str = "EPSG:3857",
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
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs=crs) as sink:
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


def _validation_nodes(*, same_terminal: bool = True) -> dict[str, NodeRecord]:
    base = {
        "C": NodeRecord("C", "C", "4", Point(0.0, 0.0)),
        "T1": NodeRecord("T1", None, "1", Point(10.0, 0.0)),
        "T2": NodeRecord("T2", None, "1", Point(0.0, 10.0)),
        "X": NodeRecord("X", "X", "4", Point(20.0, 0.0)),
        "D": NodeRecord("D", None, "1", Point(30.0, 0.0)),
    }
    if not same_terminal:
        base["Y"] = NodeRecord("Y", "Y", "4", Point(0.0, 20.0))
    return base


def _validation_roads(*, same_terminal: bool = True, include_continuations: bool = True) -> dict[str, RoadRecord]:
    roads = {
        "s1": RoadRecord("s1", "C", "T1", 2, "0", LineString([(0.0, 0.0), (10.0, 0.0)])),
        "s2": RoadRecord("s2", "C", "T2", 2, "0", LineString([(0.0, 0.0), (0.0, 10.0)])),
    }
    if include_continuations:
        roads["c1"] = RoadRecord("c1", "T1", "X", 2, "0", LineString([(10.0, 0.0), (20.0, 0.0)]))
        target = "X" if same_terminal else "Y"
        roads["c2"] = RoadRecord("c2", "T2", target, 2, "0", LineString([(0.0, 10.0), (0.0, 20.0)]))
    else:
        roads["s1"] = RoadRecord("s1", "C", "D", 2, "0", LineString([(0.0, 0.0), (30.0, 0.0)]))
        roads["s2"] = RoadRecord("s2", "C", "D", 2, "0", LineString([(0.0, 1.0), (30.0, 1.0)]))
    return roads


def _validation_groups(nodes: dict[str, NodeRecord]) -> dict[str, tuple[str, ...]]:
    groups: dict[str, tuple[str, ...]] = {}
    for node_id, node in nodes.items():
        group_id = node.mainnodeid if node.mainnodeid else node_id
        groups.setdefault(group_id, tuple())
        groups[group_id] = tuple(sorted(set(groups[group_id]) | {node_id}))
    return groups


def _validation_initial(initial_id: str, terminal_id: str, seed_id: str, *, terminal_type: str = "semantic_boundary") -> InitialArm:
    return InitialArm(
        dataset="SWSD",
        current_junction_id="C",
        initial_arm_id=initial_id,
        terminal_type=terminal_type,
        terminal_junction_id=terminal_id,
        terminal_member_node_ids=(terminal_id,),
        member_road_ids=(seed_id,),
        seed_road_ids=(seed_id,),
        connector_road_ids=tuple(),
        inbound_member_road_ids=(seed_id,),
        outbound_member_road_ids=tuple(),
        bidirectional_member_road_ids=tuple(),
        build_status="unstable",
        risk_flags=tuple(),
    )


def _validation_trace(initial_id: str, terminal_id: str, seed_id: str, *, stop_type: str = "semantic_boundary") -> ArmTrace:
    return ArmTrace(
        dataset="SWSD",
        current_junction_id="C",
        trace_id=f"trace_{initial_id}",
        seed_road_id=seed_id,
        seed_role="inbound",
        traced_road_ids=(seed_id,),
        traced_node_ids=(terminal_id,),
        through_decisions=(stop_type,),
        stop_type=stop_type,
        stop_reason="fixture",
        assigned_initial_arm_id=initial_id,
    )


def _validation_final(source_ids: tuple[str, ...], *, merge_status: str = "local_candidate_fallback") -> FinalArm:
    return FinalArm(
        dataset="SWSD",
        current_junction_id="C",
        final_arm_id="F1",
        source_initial_arm_ids=source_ids,
        merge_status=merge_status,
        merge_reason="fixture",
        initial_arm={
            "member_road_ids": ["s1", "s2"],
            "seed_road_ids": ["s1", "s2"],
            "connector_road_ids": [],
            "inbound_member_road_ids": ["s1", "s2"],
            "outbound_member_road_ids": [],
            "bidirectional_member_road_ids": [],
        },
    )


def _write_roads_with_source(
    path: Path,
    features: list[tuple[str, str, str, int, str, str, list[tuple[float, float]]]],
    *,
    crs: str = "EPSG:3857",
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
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs=crs) as sink:
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


def _with_left_recv_as_parallel(result, prefix: str):
    target_arm_id = _arm_id_by_seed(result, f"{prefix}_e_main")
    main_id = f"{prefix}_e_main"
    branch_id = f"{prefix}_e_left_recv"
    trunk_ids = lambda items: tuple(sorted(set(item for item in items if item != branch_id).union({main_id})))
    return replace(
        result,
        final_arms=tuple(
            replace(
                arm,
                trunk_road_ids=trunk_ids(arm.trunk_road_ids),
                non_trunk_member_road_ids=(branch_id,),
            )
            if arm.final_arm_id == target_arm_id
            else arm
            for arm in result.final_arms
        ),
        trunk_corrections=tuple(
            replace(correction, corrected_trunk_road_ids=trunk_ids(correction.corrected_trunk_road_ids))
            if correction.arm_id == target_arm_id
            else correction
            for correction in result.trunk_corrections
        ),
    )


def _with_road_as_parallel(result, road_id: str):
    arm_id = _arm_id_by_seed(result, road_id)
    return replace(
        result,
        final_arms=tuple(
            replace(
                arm,
                trunk_road_ids=tuple(item for item in arm.trunk_road_ids if item != road_id),
                non_trunk_member_road_ids=tuple(sorted(set(arm.non_trunk_member_road_ids).union({road_id}))),
            )
            if arm.final_arm_id == arm_id
            else arm
            for arm in result.final_arms
        ),
        trunk_corrections=tuple(
            replace(correction, corrected_trunk_road_ids=tuple(item for item in correction.corrected_trunk_road_ids if item != road_id))
            if correction.arm_id == arm_id
            else correction
            for correction in result.trunk_corrections
        ),
    )


__all__=[name for name in globals() if not name.startswith("__")]
