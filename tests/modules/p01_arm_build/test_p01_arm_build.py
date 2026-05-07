from __future__ import annotations

import csv
import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, mapping

from rcsd_topo_poc.modules.p01_arm_build.io import load_dataset
from rcsd_topo_poc.modules.p01_arm_build.models import DatasetInput
from rcsd_topo_poc.modules.p01_arm_build.review import (
    _dataset_review_context,
    _geometry_bounds,
    _line_points,
    _projector,
    _trace_review_context,
)
from rcsd_topo_poc.modules.p01_arm_build.runner import run_p01_arm_build_from_args
from rcsd_topo_poc.modules.p01_arm_build.text_bundle import (
    P01_TEXT_BUNDLE_LIMIT_BYTES,
    run_p01_decode_text_bundle,
    run_p01_export_text_bundle,
)
from rcsd_topo_poc.modules.p01_arm_build.topology import build_dataset_arm_result


def _write_nodes(path: Path, features: list[tuple[str, str | None, float, float]]) -> None:
    schema = {"geometry": "Point", "properties": {"id": "str", "mainnodeid": "str", "kind": "str", "grade": "int"}}
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for node_id, mainnodeid, x, y in features:
            sink.write(
                {
                    "geometry": mapping(Point(x, y)),
                    "properties": {
                        "id": node_id,
                        "mainnodeid": mainnodeid,
                        "kind": "4",
                        "grade": 9,
                    },
                }
            )


def _write_roads(path: Path, features: list[tuple[str, str, str, int, str, list[tuple[float, float]]]]) -> None:
    schema = {
        "geometry": "LineString",
        "properties": {
            "id": "str",
            "snodeid": "str",
            "enodeid": "str",
            "direction": "int",
            "formway": "str",
            "grade_2": "int",
        },
    }
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for road_id, snodeid, enodeid, direction, formway, coords in features:
            sink.write(
                {
                    "geometry": mapping(LineString(coords)),
                    "properties": {
                        "id": road_id,
                        "snodeid": snodeid,
                        "enodeid": enodeid,
                        "direction": direction,
                        "formway": formway,
                        "grade_2": 7,
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
    _write_roads(roads_path, roads)
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
    assert context["excluded_right_turn_road_ids"] == ["S1_right_turn"]

    initial_arms = json.loads((swsd_dir / "initial_arms.json").read_text(encoding="utf-8"))
    assert len(initial_arms) == 4
    assert any("S1_east_continue" in arm["connector_road_ids"] for arm in initial_arms)

    local_candidates = json.loads((swsd_dir / "local_arm_candidates.json").read_text(encoding="utf-8"))
    assert len(local_candidates) == 4
    assert all("S1_right_turn" not in item["source_seed_road_ids"] for item in local_candidates)
    assert any(item["local_stub_road_ids"] == ["S1_east_continue", "S1_east_seed"] for item in local_candidates)

    decisions = json.loads((swsd_dir / "through_decisions.json").read_text(encoding="utf-8"))
    assert any(decision["status"] == "simple_through" for decision in decisions)
    assert any(decision["status"] == "dead_end" for decision in decisions)

    assert (swsd_dir / "p01_arm_review.png").is_file()
    assert (swsd_dir / "review_layers.gpkg").is_file()
    assert (run_root / "cases" / "group_0001" / "compare" / "p01_arm_compare.png").is_file()
    assert (run_root / "cases" / "group_0001" / "compare" / "p01_arm_compare_layers.gpkg").is_file()
    assert set(fiona.listlayers(swsd_dir / "review_layers.gpkg")) >= {
        "current_junction_nodes",
        "arm_roads",
        "local_arm_candidate_roads",
        "through_decision_nodes",
        "excluded_right_turn_roads",
    }

    with (run_root / "p01_arm_build_review_index.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 6
    assert {row["junction_group_id"] for row in rows} == {"group_0001", "group_0002"}
    assert {row["dataset"] for row in rows} == {"SWSD", "RCSD", "FRCSD"}
    assert all(row["review_priority"] in {"P0", "P1", "P2", "P3"} for row in rows)


def test_right_turn_is_not_excluded_without_explicit_field_value(tmp_path: Path) -> None:
    out_root = tmp_path / "out_no_rt"
    assert run_p01_arm_build_from_args(_run_args(tmp_path, out_root, include_right_turn_value=False)) == 0
    context = json.loads(
        (out_root / "test_run" / "cases" / "group_0001" / "SWSD" / "junction_context.json").read_text(
            encoding="utf-8"
        )
    )
    assert context["excluded_right_turn_road_ids"] == []
    initial_arms = json.loads(
        (out_root / "test_run" / "cases" / "group_0001" / "SWSD" / "initial_arms.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("S1_right_turn" in arm["seed_road_ids"] for arm in initial_arms)


def test_trace_review_context_excludes_far_unrelated_roads(tmp_path: Path) -> None:
    nodes_path, roads_path = _write_dataset(tmp_path, "S", include_far_noise=True)
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))
    result = build_dataset_arm_result(loaded, junction_id="S1", right_turn_formway_values={"128"})
    trace_id = result.traces[0].trace_id

    geometries, road_ids, node_ids = _trace_review_context(loaded, result, trace_id)
    bounds = _geometry_bounds(geometries)

    assert "S_far_noise" not in road_ids
    assert "Sfar_a" not in node_ids
    assert bounds[2] < 120.0
    assert bounds[3] < 60.0


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


def test_local_arm_candidates_group_current_seed_trends_without_merging_outputs(tmp_path: Path) -> None:
    nodes_path, roads_path = _write_dataset(tmp_path, "S")
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))
    result = build_dataset_arm_result(loaded, junction_id="S1", right_turn_formway_values={"128"})

    assert len(result.final_arms) == len(result.initial_arms)
    assert len(result.local_arm_candidates) == 4
    west = next(item for item in result.local_arm_candidates if item.bidirectional_seed_road_ids == ("S1_bi",))
    east = next(item for item in result.local_arm_candidates if item.outbound_seed_road_ids == ("S1_east_seed",))

    assert west.build_status == "candidate"
    assert east.local_stub_road_ids == ("S1_east_continue", "S1_east_seed")
    assert "S1_right_turn" not in {seed for item in result.local_arm_candidates for seed in item.source_seed_road_ids}
    assert result.metrics["local_arm_candidate_count"] == 4


def test_p01_text_bundle_roundtrip_uses_bfs_context_not_far_spatial_noise(tmp_path: Path) -> None:
    swsd_nodes, swsd_roads = _write_dataset(tmp_path, "S", include_far_noise=True)
    rcsd_nodes, rcsd_roads = _write_dataset(tmp_path, "R", include_far_noise=True)
    frcsd_nodes, frcsd_roads = _write_dataset(tmp_path, "F", include_far_noise=True)
    bundle_path = tmp_path / "p01_case_bundle.txt"

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

    manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))
    assert manifest["encoder_info"]["selection"] == "semantic-road-topology-bfs"
    assert manifest["datasets"]["SWSD"]["selected_road_count"] < 10


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


def test_review_line_points_accepts_3d_coordinates() -> None:
    project = _projector((0.0, 0.0, 10.0, 10.0), left=0, top=0, width=100, height=100)

    points = _line_points(LineString([(0.0, 0.0, 5.0), (10.0, 10.0, 6.0)]), project)

    assert len(points) == 2
    assert all(len(point) == 2 for point in points)


def test_p01_source_does_not_reference_grade_fields() -> None:
    source_dir = Path("src/rcsd_topo_poc/modules/p01_arm_build")
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_dir.glob("*.py"))
    assert "grade" not in source_text.lower()
