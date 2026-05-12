from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, mapping

from rcsd_topo_poc.modules.p01_arm_build.alignment import _build_logical_groups
from rcsd_topo_poc.modules.p01_arm_build.alignment_models import ArmAlignmentCandidate, ArmProfile
from rcsd_topo_poc.modules.p01_arm_build.alignment_review import _profile_review_road_geometries
from rcsd_topo_poc.modules.p01_arm_build.io import load_dataset
from rcsd_topo_poc.modules.p01_arm_build.models import DatasetInput
from rcsd_topo_poc.modules.p01_arm_build.alignment_runner import run_p01_arm_alignment_from_args


DATASETS = ("SWSD", "RCSD", "FRCSD")


def _alignment_profile(dataset: str, arm_id: str) -> ArmProfile:
    return ArmProfile(
        dataset=dataset,
        junction_group_id="group_0001",
        current_junction_id=f"{dataset}_J",
        arm_id=arm_id,
        source_final_arm_id=arm_id,
        source_initial_arm_ids=(f"I_{arm_id}",),
        member_road_ids=(f"{dataset}_{arm_id}_r1",),
        seed_road_ids=(f"{dataset}_{arm_id}_r1",),
        connector_road_ids=(),
        inbound_seed_road_ids=(f"{dataset}_{arm_id}_r1",),
        outbound_seed_road_ids=(),
        bidirectional_seed_road_ids=(),
        terminal_type="semantic_boundary",
        terminal_junction_id=f"T_{arm_id}",
        terminal_member_node_ids=(f"T_{arm_id}",),
        build_status="stable",
        risk_flags=(),
        merge_status="not_applied",
        merge_reason="test_fixture",
        local_candidate_ids=(f"L_{arm_id}",),
        local_trend_angle_deg=0.0,
        local_stub_road_ids=(f"{dataset}_{arm_id}_r1",),
        trace_ids=(f"{dataset}_{arm_id}_trace",),
        trace_stop_types=("semantic_boundary",),
        through_decision_summary={"semantic_boundary": 1},
        geometry_summary={},
        lineage_summary={},
    )


def _alignment_candidate(
    candidate_id: str,
    f_arm_id: str,
    source_dataset: str,
    source_arm_id: str,
    score: float,
) -> ArmAlignmentCandidate:
    return ArmAlignmentCandidate(
        candidate_id=candidate_id,
        junction_group_id="group_0001",
        left_dataset="FRCSD",
        right_dataset=source_dataset,
        left_arm_id=f_arm_id,
        right_arm_id=source_arm_id,
        score=score,
        confidence="high",
        seed_role_score=25.0,
        local_candidate_score=25.0,
        trace_terminal_score=20.0,
        road_coverage_score=20.0,
        geometry_score=max(0.0, score - 90.0),
        evidence_flags=(),
        conflict_flags=(),
    )


def _write_nodes(path: Path, features: list[tuple[str, float, float]]) -> None:
    schema = {"geometry": "Point", "properties": {"id": "str", "mainnodeid": "str", "kind": "str"}}
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for node_id, x, y in features:
            sink.write(
                {
                    "geometry": mapping(Point(x, y)),
                    "properties": {"id": node_id, "mainnodeid": "", "kind": "1"},
                }
            )


def _write_roads(path: Path, features: list[tuple[str, str, str, list[tuple[float, float]]]]) -> None:
    schema = {
        "geometry": "LineString",
        "properties": {"id": "str", "snodeid": "str", "enodeid": "str", "direction": "int", "formway": "str"},
    }
    with fiona.open(path, "w", driver="GPKG", schema=schema, crs="EPSG:3857") as sink:
        for road_id, snodeid, enodeid, coords in features:
            sink.write(
                {
                    "geometry": mapping(LineString(coords)),
                    "properties": {"id": road_id, "snodeid": snodeid, "enodeid": enodeid, "direction": 2, "formway": "0"},
                }
            )


def _coords(angle: float, offset: float) -> tuple[tuple[float, float], tuple[float, float]]:
    radians = math.radians(angle)
    start = (offset, 0.0)
    end = (offset + math.cos(radians) * 80.0, math.sin(radians) * 80.0)
    return start, end


def _arm(
    dataset: str,
    group: str,
    arm_id: str,
    angle: float,
    *,
    road_count: int = 2,
    status: str = "semantic_boundary",
    role: str = "inbound",
):
    prefix = f"{dataset}_{group}_{arm_id}"
    road_ids = tuple(f"{prefix}_r{idx}" for idx in range(1, road_count + 1))
    seed_id = road_ids[0]
    initial_id = f"I_{arm_id}"
    return {
        "arm_id": arm_id,
        "initial_id": initial_id,
        "road_ids": road_ids,
        "seed_id": seed_id,
        "angle": angle,
        "terminal_type": status,
        "through_status": "t_side_terminal" if status == "t_side_terminal" else status,
        "role": role,
    }


def _write_raw_dataset(tmp_path: Path, dataset: str, arms: list[dict]) -> tuple[Path, Path]:
    nodes: list[tuple[str, float, float]] = []
    roads: list[tuple[str, str, str, list[tuple[float, float]]]] = []
    for index, arm in enumerate(arms, start=1):
        offset = index * 400.0
        previous_node = f"{dataset}_{arm['arm_id']}_n0"
        start, end = _coords(float(arm["angle"]), offset)
        nodes.append((previous_node, start[0], start[1]))
        for road_index, road_id in enumerate(arm["road_ids"], start=1):
            next_node = f"{dataset}_{arm['arm_id']}_n{road_index}"
            ratio0 = (road_index - 1) / len(arm["road_ids"])
            ratio1 = road_index / len(arm["road_ids"])
            p0 = (start[0] + (end[0] - start[0]) * ratio0, start[1] + (end[1] - start[1]) * ratio0)
            p1 = (start[0] + (end[0] - start[0]) * ratio1, start[1] + (end[1] - start[1]) * ratio1)
            nodes.append((next_node, p1[0], p1[1]))
            roads.append((road_id, previous_node, next_node, [p0, p1]))
            previous_node = next_node
    nodes_path = tmp_path / f"{dataset.lower()}_nodes.gpkg"
    roads_path = tmp_path / f"{dataset.lower()}_roads.gpkg"
    _write_nodes(nodes_path, nodes)
    _write_roads(roads_path, roads)
    return nodes_path, roads_path


def _write_dataset_a1(case_dir: Path, dataset: str, arms: list[dict]) -> None:
    dataset_dir = case_dir / dataset
    dataset_dir.mkdir(parents=True, exist_ok=True)
    context = {
        "dataset": dataset,
        "junction_id": f"{dataset}_{case_dir.name}",
        "member_node_ids": [f"{dataset}_{case_dir.name}_J"],
        "internal_road_ids": [],
        "inbound_seed_road_ids": [arm["seed_id"] for arm in arms if arm["role"] == "inbound"],
        "outbound_seed_road_ids": [arm["seed_id"] for arm in arms if arm["role"] == "outbound"],
        "bidirectional_seed_road_ids": [arm["seed_id"] for arm in arms if arm["role"] == "bidirectional"],
        "excluded_right_turn_road_ids": [],
        "input_issue_flags": [],
    }
    initial_arms = []
    final_arms = []
    local_candidates = []
    traces = []
    decisions = []
    for index, arm in enumerate(arms, start=1):
        initial = {
            "dataset": dataset,
            "current_junction_id": context["junction_id"],
            "initial_arm_id": arm["initial_id"],
            "terminal_type": arm["terminal_type"],
            "terminal_junction_id": f"T_{round(float(arm['angle']))}",
            "terminal_member_node_ids": [f"T_{round(float(arm['angle']))}"],
            "member_road_ids": list(arm["road_ids"]),
            "seed_road_ids": [arm["seed_id"]],
            "connector_road_ids": list(arm["road_ids"][1:]),
            "inbound_member_road_ids": list(arm["road_ids"]) if arm["role"] == "inbound" else [],
            "outbound_member_road_ids": list(arm["road_ids"]) if arm["role"] == "outbound" else [],
            "bidirectional_member_road_ids": list(arm["road_ids"]) if arm["role"] == "bidirectional" else [],
            "build_status": "stable",
            "risk_flags": [],
        }
        initial_arms.append(initial)
        final_arms.append(
            {
                "dataset": dataset,
                "current_junction_id": context["junction_id"],
                "final_arm_id": arm["arm_id"],
                "source_initial_arm_ids": [arm["initial_id"]],
                "merge_status": arm.get("merge_status", "not_applied"),
                "merge_reason": arm.get("merge_reason", "reserved_for_future_case_based_rules"),
                "initial_arm": initial,
            }
        )
        local_candidates.append(
            {
                "dataset": dataset,
                "current_junction_id": context["junction_id"],
                "local_arm_candidate_id": f"L_{arm['arm_id']}",
                "source_seed_road_ids": [arm["seed_id"]],
                "source_initial_arm_ids": [arm["initial_id"]],
                "local_stub_road_ids": list(arm["road_ids"]),
                "inbound_seed_road_ids": [arm["seed_id"]] if arm["role"] == "inbound" else [],
                "outbound_seed_road_ids": [arm["seed_id"]] if arm["role"] == "outbound" else [],
                "bidirectional_seed_road_ids": [arm["seed_id"]] if arm["role"] == "bidirectional" else [],
                "member_node_ids": context["member_node_ids"],
                "trend_angle_deg": arm["angle"],
                "angular_spread_deg": 0.0,
                "grouping_reason": "test_fixture",
                "build_status": "candidate",
                "risk_flags": [],
            }
        )
        trace_id = f"{dataset.lower()}_{case_dir.name}_{arm['arm_id']}_trace"
        traces.append(
            {
                "dataset": dataset,
                "current_junction_id": context["junction_id"],
                "trace_id": trace_id,
                "seed_road_id": arm["seed_id"],
                "seed_role": arm["role"],
                "traced_road_ids": list(arm["road_ids"]),
                "traced_node_ids": [],
                "through_decisions": [arm["through_status"]],
                "stop_type": arm["terminal_type"],
                "stop_reason": "test_fixture",
                "assigned_initial_arm_id": arm["initial_id"],
                "issue_flags": [],
            }
        )
        decisions.append(
            {
                "dataset": dataset,
                "current_junction_id": context["junction_id"],
                "trace_id": trace_id,
                "node_group_id": f"N{index}",
                "member_node_ids": [f"N{index}"],
                "incoming_road_id": arm["seed_id"],
                "outgoing_road_id": None,
                "status": arm["through_status"],
                "decision_reason": "test_fixture",
                "incident_road_ids": list(arm["road_ids"]),
            }
        )
    for name, payload in {
        "junction_context.json": context,
        "initial_arms.json": initial_arms,
        "final_arms.json": final_arms,
        "local_arm_candidates.json": local_candidates,
        "arm_traces.json": traces,
        "through_decisions.json": decisions,
        "issue_report.json": {"dataset": dataset, "current_junction_id": context["junction_id"], "issues": [], "issue_counts": {}},
    }.items():
        (dataset_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_a1_run_root(tmp_path: Path) -> Path:
    run_root = tmp_path / "a1_run"
    run_root.mkdir()
    specs = {
        "group_0001": {
            "FRCSD": [_arm("FRCSD", "g1", "F1", 0)],
            "SWSD": [_arm("SWSD", "g1", "S1", 0), _arm("SWSD", "g1", "S_extra", 180)],
            "RCSD": [_arm("RCSD", "g1", "R1", 0)],
        },
        "group_0002": {
            "FRCSD": [_arm("FRCSD", "g2", "F1", 90)],
            "SWSD": [],
            "RCSD": [_arm("RCSD", "g2", "R1", 90)],
        },
        "group_0003": {
            "FRCSD": [_arm("FRCSD", "g3", "F1", 15, road_count=4)],
            "SWSD": [_arm("SWSD", "g3", "S1", 15, road_count=1)],
            "RCSD": [_arm("RCSD", "g3", "R1", 15, road_count=4)],
        },
        "group_0004": {
            "FRCSD": [_arm("FRCSD", "g4", "F1", 0, road_count=4)],
            "SWSD": [_arm("SWSD", "g4", "S1a", 0), _arm("SWSD", "g4", "S1b", 2)],
            "RCSD": [_arm("RCSD", "g4", "R1", 0, road_count=4)],
        },
        "group_0005": {
            "FRCSD": [_arm("FRCSD", "g5", "F1", 0), _arm("FRCSD", "g5", "F2", 30)],
            "SWSD": [_arm("SWSD", "g5", "S_merged", 15, road_count=4)],
            "RCSD": [_arm("RCSD", "g5", "R1", 0), _arm("RCSD", "g5", "R2", 30)],
        },
        "group_0006": {
            "FRCSD": [_arm("FRCSD", "g6", "F1", 0, status="t_mainline_through")],
            "SWSD": [_arm("SWSD", "g6", "S1", 0, status="t_side_terminal")],
            "RCSD": [_arm("RCSD", "g6", "R1", 0, status="semantic_boundary")],
        },
        "group_0007": {
            "FRCSD": [_arm("FRCSD", "g7", "F1", 0, road_count=2, status="semantic_boundary")],
            "SWSD": [_arm("SWSD", "g7", "S1", 240, road_count=2, status="mixed", role="outbound")],
            "RCSD": [_arm("RCSD", "g7", "R1", 0, road_count=2, status="semantic_boundary")],
        },
    }
    raw_paths = {}
    for dataset in DATASETS:
        all_arms = [arm for group in specs.values() for arm in group[dataset]]
        nodes_path, roads_path = _write_raw_dataset(tmp_path, dataset, all_arms)
        raw_paths[dataset] = {"nodes": str(nodes_path), "roads": str(roads_path)}
    (run_root / "preflight.json").write_text(
        json.dumps({"run_id": "a1_fixture", "input_paths": raw_paths}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_root / "p01_arm_build_summary.json").write_text(json.dumps({"run_id": "a1_fixture"}), encoding="utf-8")
    with (run_root / "p01_arm_build_review_index.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["junction_group_id", "dataset", "review_priority"])
        writer.writeheader()
    cases_dir = run_root / "cases"
    for group_index, (group_id, group_spec) in enumerate(specs.items(), start=1):
        case_dir = cases_dir / group_id
        case_dir.mkdir(parents=True)
        case_input = {
            "group_id": group_id,
            "group_index": group_index,
            "swsd_junction_id": f"S{group_index}",
            "rcsd_junction_id": f"R{group_index}",
            "frcsd_junction_id": f"F{group_index}",
        }
        (case_dir / "case_input.json").write_text(json.dumps(case_input, ensure_ascii=False, indent=2), encoding="utf-8")
        (case_dir / "case_summary.json").write_text(json.dumps({"group": case_input}, ensure_ascii=False), encoding="utf-8")
        for dataset in DATASETS:
            _write_dataset_a1(case_dir, dataset, group_spec[dataset])
    return run_root


def test_p01_arm_alignment_outputs_statuses_and_review_artifacts(tmp_path: Path) -> None:
    a1_root = _write_a1_run_root(tmp_path)
    out_root = tmp_path / "a2_out"
    assert run_p01_arm_alignment_from_args(
        ["--arm-build-run-root", str(a1_root), "--out-root", str(out_root), "--run-id", "a2_test"]
    ) == 0

    run_root = out_root / "a2_test"
    assert (run_root / "preflight.json").is_file()
    assert (run_root / "p01_arm_alignment_summary.json").is_file()
    assert (run_root / "p01_arm_alignment_review_index.csv").is_file()

    statuses = []
    for group_dir in sorted((run_root / "cases").iterdir()):
        groups = json.loads((group_dir / "logical_arm_groups.json").read_text(encoding="utf-8"))
        statuses.extend(group["group_status"] for group in groups)
        assert (group_dir / "arm_profiles.json").is_file()
        assert (group_dir / "arm_alignment_candidates.json").is_file()
        assert (group_dir / "source_extra_arms.json").is_file()
        assert (group_dir / "SWSD" / "raw_arm_alignment.json").is_file()
        assert (group_dir / "RCSD" / "raw_arm_alignment.json").is_file()
        assert (group_dir / "SWSD" / "p01_arm_alignment_review.png").is_file()
        assert (group_dir / "RCSD" / "arm_alignment_review_layers.gpkg").is_file()
        assert (group_dir / "compare" / "p01_arm_alignment_compare.png").is_file()
        assert (group_dir / "compare" / "p01_arm_alignment_compare_layers.gpkg").is_file()
        assert {"logical_arm_groups", "raw_alignment_edges", "candidate_edges", "issue_points"} <= set(
            fiona.listlayers(group_dir / "compare" / "p01_arm_alignment_compare_layers.gpkg")
        )

    assert "stable" in statuses
    assert "source_missing" in statuses
    assert "source_partial" in statuses
    assert "source_over_split_resolved" in statuses
    assert "source_over_merged_unresolved" in statuses
    assert "conflict" in statuses
    assert "uncertain" in statuses

    feedback = json.loads((run_root / "cases" / "group_0004" / "arm_build_feedback.json").read_text(encoding="utf-8"))
    assert any(item["feedback_type"] == "recommended_merge" for item in feedback)
    split_feedback = json.loads((run_root / "cases" / "group_0005" / "arm_build_feedback.json").read_text(encoding="utf-8"))
    assert any(item["feedback_type"] == "recommended_split" for item in split_feedback)
    extras = json.loads((run_root / "cases" / "group_0001" / "source_extra_arms.json").read_text(encoding="utf-8"))
    assert any(item["source_arm_id"] == "S_extra" for item in extras)

    summary = json.loads((run_root / "p01_arm_alignment_summary.json").read_text(encoding="utf-8"))
    assert summary["logical_arm_group_count"] >= 8
    assert summary["feedback_count"] >= 2


def test_alignment_prefers_exclusive_source_binding_when_alternate_candidate_exists() -> None:
    profiles_by_dataset = {
        "FRCSD": (_alignment_profile("FRCSD", "F2"), _alignment_profile("FRCSD", "F3")),
        "SWSD": (_alignment_profile("SWSD", "S1"), _alignment_profile("SWSD", "S2")),
        "RCSD": (_alignment_profile("RCSD", "R2"), _alignment_profile("RCSD", "R3")),
    }
    candidates = (
        _alignment_candidate("cand_s1", "F2", "SWSD", "S1", 94.97),
        _alignment_candidate("cand_s2", "F3", "SWSD", "S2", 104.99),
        _alignment_candidate("cand_r2_owner", "F2", "RCSD", "R2", 104.82),
        _alignment_candidate("cand_r2_reused", "F3", "RCSD", "R2", 102.77),
        _alignment_candidate("cand_r3_alt", "F3", "RCSD", "R3", 85.40),
    )

    groups, selected_candidates, feedback = _build_logical_groups("group_0001", profiles_by_dataset, candidates)

    groups_by_f = {group.frcsd_arm_ids[0]: group for group in groups}
    assert groups_by_f["F2"].rcsd_arm_ids == ("R2",)
    assert groups_by_f["F3"].rcsd_arm_ids == ("R3",)
    assert all("rcsd_over_merged_unresolved" not in group.risk_flags for group in groups)
    assert not [item for item in feedback if item.dataset == "RCSD" and item.feedback_type == "recommended_split"]
    assert {candidate.candidate_id for candidate in selected_candidates if candidate.selected} == {
        "cand_s1",
        "cand_s2",
        "cand_r2_owner",
        "cand_r3_alt",
    }


def test_alignment_png_review_context_uses_local_stub_not_full_trace(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    _write_nodes(nodes_path, [("n0", 0, 0), ("n1", 20, 0), ("n2", 100000, 0)])
    _write_roads(
        roads_path,
        [
            ("near", "n0", "n1", [(0, 0), (20, 0)]),
            ("far", "n1", "n2", [(20, 0), (100000, 0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))
    profile = ArmProfile(
        dataset="SWSD",
        junction_group_id="group_0001",
        current_junction_id="J",
        arm_id="S1",
        source_final_arm_id="S1",
        source_initial_arm_ids=("A1",),
        member_road_ids=("near", "far"),
        seed_road_ids=("near",),
        connector_road_ids=("far",),
        inbound_seed_road_ids=("near",),
        outbound_seed_road_ids=(),
        bidirectional_seed_road_ids=(),
        terminal_type="semantic_boundary",
        terminal_junction_id="T",
        terminal_member_node_ids=("T",),
        build_status="stable",
        risk_flags=(),
        merge_status="not_applied",
        merge_reason="test",
        local_candidate_ids=("L1",),
        local_trend_angle_deg=0.0,
        local_stub_road_ids=("near",),
        trace_ids=("trace1",),
        trace_stop_types=("semantic_boundary",),
        through_decision_summary={"semantic_boundary": 1},
        geometry_summary={},
        lineage_summary={},
    )

    geometries = _profile_review_road_geometries(profile, loaded)
    assert [round(geom.length) for geom in geometries] == [20]
