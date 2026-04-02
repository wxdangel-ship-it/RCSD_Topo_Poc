from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess import skill_v1
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_geojson


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_oneway_passthrough(**kwargs):
    step5_artifacts = kwargs["step5_artifacts"]
    return SimpleNamespace(
        refreshed_nodes_path=step5_artifacts.refreshed_nodes_path,
        refreshed_roads_path=step5_artifacts.refreshed_roads_path,
        step6_nodes=(),
        step6_roads=(),
        step6_node_properties_map={},
        step6_road_properties_map={},
        step6_mainnode_groups={},
        step6_group_to_allowed_road_ids={},
    )


def _write_step5_markers(root: Path) -> None:
    _write_text(root / "step5_summary.json", "{}")


def test_skill_v1_runner_records_step2_subprogress(tmp_path: Path, monkeypatch) -> None:
    road_path = tmp_path / "roads.geojson"
    node_path = tmp_path / "nodes.geojson"
    strategy_path = tmp_path / "strategy.json"
    _write_text(road_path, "{}")
    _write_text(node_path, "{}")
    _write_text(strategy_path, "{}")

    def _fake_bootstrap(**kwargs):
        nodes = tmp_path / "bootstrap" / "nodes.geojson"
        roads = tmp_path / "bootstrap" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        callback = kwargs["progress_callback"]
        callback("working_layers_initialized", {"road_feature_count": 1, "node_feature_count": 1})
        return SimpleNamespace(nodes_path=nodes, roads_path=roads, summary={})

    def _fake_step2(**kwargs):
        callback = kwargs["progress_callback"]
        assert kwargs["assume_working_layers"] is True
        callback("candidate_search_completed", {"strategy_id": "S2", "candidate_pair_count": 3})
        callback("validation_completed", {"strategy_id": "S2", "validated_pair_count": 2, "rejected_pair_count": 1})
        return []

    def _fake_refresh(**kwargs):
        assert kwargs["assume_working_layers"] is True
        nodes = tmp_path / "refresh" / "nodes.geojson"
        roads = tmp_path / "refresh" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(nodes_path=nodes, roads_path=roads)

    def _fake_step4(**kwargs):
        nodes = tmp_path / "step4" / "nodes.geojson"
        roads = tmp_path / "step4" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(refreshed_nodes_path=nodes, refreshed_roads_path=roads)

    def _fake_step5(**kwargs):
        nodes = tmp_path / "step5" / "nodes.geojson"
        roads = tmp_path / "step5" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(refreshed_nodes_path=nodes, refreshed_roads_path=roads)

    def _fake_finalize_bundle(**kwargs):
        final_nodes_path = kwargs["final_nodes_path"]
        final_roads_path = kwargs["final_roads_path"]
        _write_text(final_nodes_path, "{}")
        _write_text(final_roads_path, "{}")
        manifest_path = kwargs["resolved_out_root"] / "skill_v1_manifest.json"
        summary_path = kwargs["resolved_out_root"] / "skill_v1_bundle_summary.json"
        segment_path = kwargs["resolved_out_root"] / "segment.geojson"
        inner_nodes_path = kwargs["resolved_out_root"] / "inner_nodes.geojson"
        segment_error_path = kwargs["resolved_out_root"] / "segment_error.geojson"
        step6_summary_path = kwargs["resolved_out_root"] / "segment_summary.json"
        _write_text(manifest_path, "{}")
        _write_text(summary_path, "{}")
        _write_text(segment_path, "{}")
        _write_text(inner_nodes_path, "{}")
        _write_text(segment_error_path, "{}")
        _write_text(step6_summary_path, "{}")
        return {
            "manifest_path": str(manifest_path.resolve()),
            "summary_path": str(summary_path.resolve()),
            "segment_path": str(segment_path.resolve()),
            "inner_nodes_path": str(inner_nodes_path.resolve()),
            "segment_error_path": str(segment_error_path.resolve()),
            "step6_summary_path": str(step6_summary_path.resolve()),
        }

    monkeypatch.setattr(skill_v1, "initialize_working_layers", _fake_bootstrap)
    monkeypatch.setattr(skill_v1, "run_step2_segment_poc", _fake_step2)
    monkeypatch.setattr(skill_v1, "refresh_s2_baseline", _fake_refresh)
    monkeypatch.setattr(skill_v1, "run_step4_residual_graph", _fake_step4)
    monkeypatch.setattr(skill_v1, "run_step5_staged_residual_graph", _fake_step5)
    monkeypatch.setattr(skill_v1, "run_step5_oneway_segment_completion", _fake_oneway_passthrough)
    monkeypatch.setattr(skill_v1, "_finalize_bundle", _fake_finalize_bundle)

    artifacts = skill_v1.run_t01_skill_v1(
        road_path=road_path,
        node_path=node_path,
        out_root=tmp_path / "run",
        run_id="t01_skill_v1_test",
        strategy_config_path=strategy_path,
        debug=True,
    )

    progress = json.loads((artifacts.out_root / "t01_skill_v1_progress.json").read_text(encoding="utf-8"))
    summary = json.loads((artifacts.out_root / "t01_skill_v1_summary.json").read_text(encoding="utf-8"))
    markers = [
        json.loads(line)
        for line in (artifacts.out_root / "t01_skill_v1_perf_markers.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    scope_check = json.loads((artifacts.out_root / "distance_gate_scope_check.json").read_text(encoding="utf-8"))

    assert progress["status"] == "completed"
    subprogress_events = [item for item in markers if item["event"] == "stage_subprogress"]
    assert any(item["stage_name"] == "bootstrap" for item in subprogress_events)
    assert any(item["stage_name"] == "step2" for item in subprogress_events)
    assert any(item["substage_event"] == "validation_completed" for item in subprogress_events)
    assert any(stage["name"] == "step6" for stage in summary["stages"])
    assert summary["memory_management"]["debug_default_enabled"] is False
    assert summary["segment_geojson_path"].endswith("segment.geojson")
    assert summary["inner_nodes_geojson_path"].endswith("inner_nodes.geojson")
    assert summary["segment_error_geojson_path"].endswith("segment_error.geojson")
    assert scope_check["step5c_present"] is False


def test_skill_v1_passes_trace_validation_pair_ids_to_step2(tmp_path: Path, monkeypatch) -> None:
    road_path = tmp_path / "roads.geojson"
    node_path = tmp_path / "nodes.geojson"
    strategy_path = tmp_path / "strategy.json"
    _write_text(road_path, "{}")
    _write_text(node_path, "{}")
    _write_text(strategy_path, "{}")

    def _fake_bootstrap(**kwargs):
        nodes = tmp_path / "bootstrap_trace" / "nodes.geojson"
        roads = tmp_path / "bootstrap_trace" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(nodes_path=nodes, roads_path=roads, summary={})

    captured_step2_kwargs: dict[str, object] = {}

    def _fake_step2(**kwargs):
        captured_step2_kwargs.update(kwargs)
        return []

    def _fake_refresh(**kwargs):
        nodes = tmp_path / "refresh_trace" / "nodes.geojson"
        roads = tmp_path / "refresh_trace" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(nodes_path=nodes, roads_path=roads)

    def _fake_step4(**kwargs):
        nodes = tmp_path / "step4_trace" / "nodes.geojson"
        roads = tmp_path / "step4_trace" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(refreshed_nodes_path=nodes, refreshed_roads_path=roads)

    def _fake_step5(**kwargs):
        nodes = tmp_path / "step5_trace" / "nodes.geojson"
        roads = tmp_path / "step5_trace" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(refreshed_nodes_path=nodes, refreshed_roads_path=roads)

    def _fake_finalize_bundle(**kwargs):
        resolved_out_root = kwargs["resolved_out_root"]
        _write_text(kwargs["final_nodes_path"], "{}")
        _write_text(kwargs["final_roads_path"], "{}")
        manifest_path = resolved_out_root / "skill_v1_manifest.json"
        summary_path = resolved_out_root / "skill_v1_bundle_summary.json"
        segment_path = resolved_out_root / "segment.geojson"
        inner_nodes_path = resolved_out_root / "inner_nodes.geojson"
        segment_error_path = resolved_out_root / "segment_error.geojson"
        step6_summary_path = resolved_out_root / "segment_summary.json"
        _write_text(manifest_path, "{}")
        _write_text(summary_path, "{}")
        _write_text(segment_path, "{}")
        _write_text(inner_nodes_path, "{}")
        _write_text(segment_error_path, "{}")
        _write_text(step6_summary_path, "{}")
        return {
            "manifest_path": str(manifest_path.resolve()),
            "summary_path": str(summary_path.resolve()),
            "segment_path": str(segment_path.resolve()),
            "inner_nodes_path": str(inner_nodes_path.resolve()),
            "segment_error_path": str(segment_error_path.resolve()),
            "step6_summary_path": str(step6_summary_path.resolve()),
        }

    monkeypatch.setattr(skill_v1, "initialize_working_layers", _fake_bootstrap)
    monkeypatch.setattr(skill_v1, "run_step2_segment_poc", _fake_step2)
    monkeypatch.setattr(skill_v1, "refresh_s2_baseline", _fake_refresh)
    monkeypatch.setattr(skill_v1, "run_step4_residual_graph", _fake_step4)
    monkeypatch.setattr(skill_v1, "run_step5_staged_residual_graph", _fake_step5)
    monkeypatch.setattr(skill_v1, "run_step5_oneway_segment_completion", _fake_oneway_passthrough)
    monkeypatch.setattr(skill_v1, "_finalize_bundle", _fake_finalize_bundle)

    skill_v1.run_t01_skill_v1(
        road_path=road_path,
        node_path=node_path,
        out_root=tmp_path / "run_trace",
        run_id="t01_skill_v1_trace",
        strategy_config_path=strategy_path,
        debug=False,
        trace_validation_pair_ids=["S2:866747__950704"],
    )

    assert captured_step2_kwargs["trace_validation_pair_ids"] == ["S2:866747__950704"]


def test_skill_v1_continue_oneway_runner_reuses_previous_stage_outputs(tmp_path: Path, monkeypatch) -> None:
    previous_root = tmp_path / "previous"
    stage_root = previous_root / "debug" / "step5"
    stage_root.mkdir(parents=True)

    nodes_path = stage_root / "nodes.geojson"
    roads_path = stage_root / "roads.geojson"
    write_geojson(
        nodes_path,
        [
            {
                "properties": {
                    "id": 1,
                    "mainnodeid": 1,
                    "working_mainnodeid": 1,
                    "kind": 4,
                    "grade": 1,
                    "kind_2": 4,
                    "grade_2": 1,
                    "closed_con": 2,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": 2,
                    "mainnodeid": 2,
                    "working_mainnodeid": 2,
                    "kind": 4,
                    "grade": 1,
                    "kind_2": 4,
                    "grade_2": 1,
                    "closed_con": 3,
                },
                "geometry": Point(1.0, 0.0),
            },
        ],
    )
    write_geojson(
        roads_path,
        [
            {
                "properties": {
                    "id": "r1",
                    "snodeid": 1,
                    "enodeid": 2,
                    "direction": 2,
                    "road_kind": 2,
                    "formway": 0,
                    "segmentid": None,
                    "sgrade": None,
                },
                "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
            },
        ],
    )
    _write_step5_markers(stage_root)

    continuation_context = skill_v1._resolve_oneway_continuation_context(previous_root)
    captured: dict[str, object] = {}

    def _fake_oneway(**kwargs):
        captured["step5_artifacts"] = kwargs["step5_artifacts"]
        return SimpleNamespace(
            refreshed_nodes_path=kwargs["step5_artifacts"].refreshed_nodes_path,
            refreshed_roads_path=kwargs["step5_artifacts"].refreshed_roads_path,
            step6_nodes=(),
            step6_roads=(),
            step6_node_properties_map={},
            step6_road_properties_map={},
            step6_mainnode_groups={},
            step6_group_to_allowed_road_ids={},
        )

    def _fake_finalize_continue(**kwargs):
        _write_text(kwargs["final_nodes_path"], "{}")
        _write_text(kwargs["final_roads_path"], "{}")
        segment_path = kwargs["resolved_out_root"] / "segment.geojson"
        inner_nodes_path = kwargs["resolved_out_root"] / "inner_nodes.geojson"
        segment_error_path = kwargs["resolved_out_root"] / "segment_error.geojson"
        step6_summary_path = kwargs["resolved_out_root"] / "segment_summary.json"
        _write_text(segment_path, "{}")
        _write_text(inner_nodes_path, "{}")
        _write_text(segment_error_path, "{}")
        _write_text(step6_summary_path, "{}")
        return {
            "manifest_path": None,
            "summary_path": None,
            "all_stage_segment_roads_path": None,
            "segment_path": str(segment_path.resolve()),
            "inner_nodes_path": str(inner_nodes_path.resolve()),
            "segment_error_path": str(segment_error_path.resolve()),
            "step6_summary_path": str(step6_summary_path.resolve()),
            "freeze_compare_nodes_source_path": str(kwargs["refreshed_nodes_path"].resolve()),
            "freeze_compare_roads_source_path": str(kwargs["refreshed_roads_path"].resolve()),
            "oneway_segment_summary_path": None,
            "unsegmented_roads_path": None,
            "unsegmented_roads_csv_path": None,
            "unsegmented_roads_summary_path": None,
        }

    monkeypatch.setattr(skill_v1, "run_step5_oneway_segment_completion", _fake_oneway)
    monkeypatch.setattr(skill_v1, "_finalize_oneway_continue_outputs", _fake_finalize_continue)

    artifacts = skill_v1.run_t01_skill_v1_continue_oneway(
        continue_from_dir=previous_root,
        out_root=tmp_path / "continue_run",
        run_id="t01_skill_v1_continue",
        debug=False,
    )

    assert captured["step5_artifacts"].refreshed_nodes_path == continuation_context.refreshed_nodes_path
    assert artifacts.summary["continuation_mode"] is True
    assert artifacts.summary["continue_from_stage_root"].endswith("/debug/step5")
    assert artifacts.summary["bundle_manifest_path"] is None




def test_skill_v1_continue_oneway_accepts_direct_debug_dir(tmp_path: Path, monkeypatch) -> None:
    debug_root = tmp_path / "previous_debug"
    stage_root = debug_root / "step5"
    (debug_root / "step2").mkdir(parents=True)
    (debug_root / "step4").mkdir(parents=True)
    stage_root.mkdir(parents=True)

    write_geojson(
        stage_root / "nodes.geojson",
        [
            {
                "properties": {
                    "id": 1,
                    "mainnodeid": 1,
                    "working_mainnodeid": 1,
                    "kind": 4,
                    "grade": 1,
                    "kind_2": 4,
                    "grade_2": 1,
                    "closed_con": 2,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": 2,
                    "mainnodeid": 2,
                    "working_mainnodeid": 2,
                    "kind": 4,
                    "grade": 1,
                    "kind_2": 4,
                    "grade_2": 1,
                    "closed_con": 3,
                },
                "geometry": Point(1.0, 0.0),
            },
        ],
    )
    write_geojson(
        stage_root / "roads.geojson",
        [
            {
                "properties": {
                    "id": "r1",
                    "snodeid": 1,
                    "enodeid": 2,
                    "direction": 2,
                    "road_kind": 2,
                    "formway": 0,
                    "segmentid": None,
                    "sgrade": None,
                },
                "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
            },
        ],
    )
    _write_step5_markers(stage_root)

    captured: dict[str, object] = {}

    def _fake_oneway(**kwargs):
        captured["step5_artifacts"] = kwargs["step5_artifacts"]
        return SimpleNamespace(
            refreshed_nodes_path=kwargs["step5_artifacts"].refreshed_nodes_path,
            refreshed_roads_path=kwargs["step5_artifacts"].refreshed_roads_path,
            step6_nodes=(),
            step6_roads=(),
            step6_node_properties_map={},
            step6_road_properties_map={},
            step6_mainnode_groups={},
            step6_group_to_allowed_road_ids={},
        )

    def _fake_finalize_bundle(**kwargs):
        resolved_out_root = kwargs["resolved_out_root"]
        _write_text(kwargs["final_nodes_path"], "{}")
        _write_text(kwargs["final_roads_path"], "{}")
        manifest_path = resolved_out_root / "skill_v1_manifest.json"
        summary_path = resolved_out_root / "skill_v1_bundle_summary.json"
        segment_path = resolved_out_root / "segment.geojson"
        inner_nodes_path = resolved_out_root / "inner_nodes.geojson"
        segment_error_path = resolved_out_root / "segment_error.geojson"
        step6_summary_path = resolved_out_root / "segment_summary.json"
        _write_text(manifest_path, "{}")
        _write_text(summary_path, "{}")
        _write_text(segment_path, "{}")
        _write_text(inner_nodes_path, "{}")
        _write_text(segment_error_path, "{}")
        _write_text(step6_summary_path, "{}")
        return {
            "manifest_path": str(manifest_path.resolve()),
            "summary_path": str(summary_path.resolve()),
            "all_stage_segment_roads_path": None,
            "segment_path": str(segment_path.resolve()),
            "inner_nodes_path": str(inner_nodes_path.resolve()),
            "segment_error_path": str(segment_error_path.resolve()),
            "step6_summary_path": str(step6_summary_path.resolve()),
            "freeze_compare_nodes_source_path": str(kwargs["freeze_compare_nodes_path"].resolve()),
            "freeze_compare_roads_source_path": str(kwargs["freeze_compare_roads_path"].resolve()),
            "oneway_segment_summary_path": None,
            "unsegmented_roads_path": None,
            "unsegmented_roads_csv_path": None,
            "unsegmented_roads_summary_path": None,
        }

    monkeypatch.setattr(skill_v1, "run_step5_oneway_segment_completion", _fake_oneway)
    monkeypatch.setattr(skill_v1, "_finalize_bundle", _fake_finalize_bundle)

    artifacts = skill_v1.run_t01_skill_v1_continue_oneway(
        continue_from_dir=debug_root,
        out_root=tmp_path / "continue_run_from_debug",
        run_id="t01_skill_v1_continue_from_debug",
        debug=False,
    )

    assert captured["step5_artifacts"].refreshed_nodes_path == stage_root / "nodes.geojson"
    assert artifacts.summary["continue_from_stage_root"].endswith("/step5")
    assert artifacts.summary["bundle_manifest_path"].endswith("skill_v1_manifest.json")


def test_skill_v1_continue_oneway_rejects_overlapping_out_root(tmp_path: Path) -> None:
    previous_root = tmp_path / "previous"
    stage_root = previous_root / "debug" / "step5"
    stage_root.mkdir(parents=True)

    write_geojson(
        stage_root / "nodes.geojson",
        [
            {
                "properties": {
                    "id": 1,
                    "mainnodeid": 1,
                    "working_mainnodeid": 1,
                    "kind": 4,
                    "grade": 1,
                    "kind_2": 4,
                    "grade_2": 1,
                    "closed_con": 2,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": 2,
                    "mainnodeid": 2,
                    "working_mainnodeid": 2,
                    "kind": 4,
                    "grade": 1,
                    "kind_2": 4,
                    "grade_2": 1,
                    "closed_con": 3,
                },
                "geometry": Point(1.0, 0.0),
            },
        ],
    )
    write_geojson(
        stage_root / "roads.geojson",
        [
            {
                "properties": {
                    "id": "r1",
                    "snodeid": 1,
                    "enodeid": 2,
                    "direction": 2,
                    "road_kind": 2,
                    "formway": 0,
                    "segmentid": None,
                    "sgrade": None,
                },
                "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
            },
        ],
    )
    _write_step5_markers(stage_root)

    try:
        skill_v1.run_t01_skill_v1_continue_oneway(
            continue_from_dir=previous_root,
            out_root=previous_root / "debug",
            run_id="t01_skill_v1_continue_overlap",
            debug=False,
        )
    except ValueError as exc:
        assert "--out-root must not overlap" in str(exc)
    else:
        raise AssertionError("expected ValueError for overlapping continuation out_root")

def test_skill_v1_continue_oneway_requires_full_skill_root_for_freeze_compare(tmp_path: Path) -> None:
    previous_root = tmp_path / "previous"
    stage_root = previous_root / "step5"
    stage_root.mkdir(parents=True)
    compare_dir = tmp_path / "freeze"
    compare_dir.mkdir()

    write_geojson(
        stage_root / "nodes.geojson",
        [
            {
                "properties": {
                    "id": 1,
                    "mainnodeid": 1,
                    "working_mainnodeid": 1,
                    "kind": 4,
                    "grade": 1,
                    "kind_2": 4,
                    "grade_2": 1,
                    "closed_con": 2,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": 2,
                    "mainnodeid": 2,
                    "working_mainnodeid": 2,
                    "kind": 4,
                    "grade": 1,
                    "kind_2": 4,
                    "grade_2": 1,
                    "closed_con": 3,
                },
                "geometry": Point(1.0, 0.0),
            },
        ],
    )
    write_geojson(
        stage_root / "roads.geojson",
        [
            {
                "properties": {
                    "id": "r1",
                    "snodeid": 1,
                    "enodeid": 2,
                    "direction": 2,
                    "road_kind": 2,
                    "formway": 0,
                    "segmentid": None,
                    "sgrade": None,
                },
                "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
            },
        ],
    )
    _write_step5_markers(stage_root)

    try:
        skill_v1.run_t01_skill_v1_continue_oneway(
            continue_from_dir=previous_root,
            out_root=tmp_path / "continue_run",
            run_id="t01_skill_v1_continue_compare",
            debug=False,
            compare_freeze_dir=compare_dir,
        )
    except ValueError as exc:
        assert "--compare-freeze-dir requires --continue-from-dir" in str(exc)
    else:
        raise AssertionError("expected ValueError for compare-freeze without full skill roots")


def test_skill_v1_debug_rerun_cleans_stage_root_and_perf_markers(tmp_path: Path, monkeypatch) -> None:
    road_path = tmp_path / "roads.geojson"
    node_path = tmp_path / "nodes.geojson"
    strategy_path = tmp_path / "strategy.json"
    out_root = tmp_path / "run_debug_clean"
    _write_text(road_path, "{}")
    _write_text(node_path, "{}")
    _write_text(strategy_path, "{}")
    _write_text(out_root / "debug" / "stale.flag", "stale")
    _write_text(out_root / "t01_skill_v1_perf_markers.jsonl", '{"event":"stale_marker"}\n')

    def _fake_bootstrap(**kwargs):
        nodes = tmp_path / "bootstrap_clean" / "nodes.geojson"
        roads = tmp_path / "bootstrap_clean" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(nodes_path=nodes, roads_path=roads, summary={})

    def _fake_step2(**kwargs):
        return []

    def _fake_refresh(**kwargs):
        nodes = tmp_path / "refresh_clean" / "nodes.geojson"
        roads = tmp_path / "refresh_clean" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(nodes_path=nodes, roads_path=roads)

    def _fake_step4(**kwargs):
        nodes = tmp_path / "step4_clean" / "nodes.geojson"
        roads = tmp_path / "step4_clean" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(refreshed_nodes_path=nodes, refreshed_roads_path=roads)

    def _fake_step5(**kwargs):
        nodes = tmp_path / "step5_clean" / "nodes.geojson"
        roads = tmp_path / "step5_clean" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(refreshed_nodes_path=nodes, refreshed_roads_path=roads)

    def _fake_finalize_bundle(**kwargs):
        resolved_out_root = kwargs["resolved_out_root"]
        _write_text(kwargs["final_nodes_path"], "{}")
        _write_text(kwargs["final_roads_path"], "{}")
        manifest_path = resolved_out_root / "skill_v1_manifest.json"
        summary_path = resolved_out_root / "skill_v1_bundle_summary.json"
        segment_path = resolved_out_root / "segment.geojson"
        inner_nodes_path = resolved_out_root / "inner_nodes.geojson"
        segment_error_path = resolved_out_root / "segment_error.geojson"
        step6_summary_path = resolved_out_root / "segment_summary.json"
        _write_text(manifest_path, "{}")
        _write_text(summary_path, "{}")
        _write_text(segment_path, "{}")
        _write_text(inner_nodes_path, "{}")
        _write_text(segment_error_path, "{}")
        _write_text(step6_summary_path, "{}")
        return {
            "manifest_path": str(manifest_path.resolve()),
            "summary_path": str(summary_path.resolve()),
            "segment_path": str(segment_path.resolve()),
            "inner_nodes_path": str(inner_nodes_path.resolve()),
            "segment_error_path": str(segment_error_path.resolve()),
            "step6_summary_path": str(step6_summary_path.resolve()),
        }

    monkeypatch.setattr(skill_v1, "initialize_working_layers", _fake_bootstrap)
    monkeypatch.setattr(skill_v1, "run_step2_segment_poc", _fake_step2)
    monkeypatch.setattr(skill_v1, "refresh_s2_baseline", _fake_refresh)
    monkeypatch.setattr(skill_v1, "run_step4_residual_graph", _fake_step4)
    monkeypatch.setattr(skill_v1, "run_step5_staged_residual_graph", _fake_step5)
    monkeypatch.setattr(skill_v1, "run_step5_oneway_segment_completion", _fake_oneway_passthrough)
    monkeypatch.setattr(skill_v1, "_finalize_bundle", _fake_finalize_bundle)

    skill_v1.run_t01_skill_v1(
        road_path=road_path,
        node_path=node_path,
        out_root=out_root,
        run_id="t01_skill_v1_debug_clean",
        strategy_config_path=strategy_path,
        debug=True,
    )

    assert not (out_root / "debug" / "stale.flag").exists()
    markers = [
        json.loads(line)
        for line in (out_root / "t01_skill_v1_perf_markers.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert markers[0]["event"] == "run_start"
    assert all(item["event"] != "stale_marker" for item in markers)


def test_skill_v1_can_stop_cleanly_after_step2_validation_pair_index(tmp_path: Path, monkeypatch) -> None:
    road_path = tmp_path / "roads.geojson"
    node_path = tmp_path / "nodes.geojson"
    strategy_path = tmp_path / "strategy.json"
    _write_text(road_path, "{}")
    _write_text(node_path, "{}")
    _write_text(strategy_path, "{}")

    def _fake_bootstrap(**kwargs):
        nodes = tmp_path / "bootstrap_stop" / "nodes.geojson"
        roads = tmp_path / "bootstrap_stop" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(nodes_path=nodes, roads_path=roads, summary={})

    captured_step2_kwargs: dict[str, object] = {}

    def _fake_step2(**kwargs):
        captured_step2_kwargs.update(kwargs)
        step2_root = Path(kwargs["out_root"])
        _write_text(step2_root / "S2" / "segment_summary.json", "{}")
        callback = kwargs["progress_callback"]
        callback("validation_completed", {"strategy_id": "S2", "validated_pair_count": 10, "rejected_pair_count": 0})
        return []

    def _unexpected_call(**_: object) -> object:
        raise AssertionError("partial Step2 diagnostic run should not continue past Step2")

    monkeypatch.setattr(skill_v1, "initialize_working_layers", _fake_bootstrap)
    monkeypatch.setattr(skill_v1, "run_step2_segment_poc", _fake_step2)
    monkeypatch.setattr(skill_v1, "refresh_s2_baseline", _unexpected_call)
    monkeypatch.setattr(skill_v1, "run_step4_residual_graph", _unexpected_call)
    monkeypatch.setattr(skill_v1, "run_step5_staged_residual_graph", _unexpected_call)
    monkeypatch.setattr(skill_v1, "run_step5_oneway_segment_completion", _unexpected_call)
    monkeypatch.setattr(skill_v1, "_finalize_bundle", _unexpected_call)

    artifacts = skill_v1.run_t01_skill_v1(
        road_path=road_path,
        node_path=node_path,
        out_root=tmp_path / "run_partial",
        run_id="t01_skill_v1_partial",
        strategy_config_path=strategy_path,
        debug=True,
        stop_after_step2_validation_pair_index=2000,
    )

    progress = json.loads((artifacts.out_root / "t01_skill_v1_progress.json").read_text(encoding="utf-8"))
    summary = json.loads((artifacts.out_root / "t01_skill_v1_summary.json").read_text(encoding="utf-8"))
    markers = [
        json.loads(line)
        for line in (artifacts.out_root / "t01_skill_v1_perf_markers.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert captured_step2_kwargs["validation_pair_index_end"] == 2000
    assert progress["status"] == "completed_partial"
    assert summary["status"] == "completed_partial"
    assert summary["stopped_after_stage"] == "step2"
    assert summary["stopped_after_step2_validation_pair_index"] == 2000
    assert Path(summary["partial_step2_root"]).is_dir()
    assert any(item["event"] == "run_completed_partial" for item in markers)


def test_skill_v1_runner_can_isolate_suite_case_outputs_under_run_id(tmp_path: Path, monkeypatch) -> None:
    road_path = tmp_path / "roads.geojson"
    node_path = tmp_path / "nodes.geojson"
    strategy_path = tmp_path / "strategy.json"
    _write_text(road_path, "{}")
    _write_text(node_path, "{}")
    _write_text(strategy_path, "{}")

    def _fake_bootstrap(**kwargs):
        nodes = tmp_path / "bootstrap_suite" / "nodes.geojson"
        roads = tmp_path / "bootstrap_suite" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(nodes_path=nodes, roads_path=roads, summary={})

    def _fake_step2(**kwargs):
        return []

    def _fake_refresh(**kwargs):
        nodes = tmp_path / "refresh_suite" / "nodes.geojson"
        roads = tmp_path / "refresh_suite" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(nodes_path=nodes, roads_path=roads)

    def _fake_step4(**kwargs):
        nodes = tmp_path / "step4_suite" / "nodes.geojson"
        roads = tmp_path / "step4_suite" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(refreshed_nodes_path=nodes, refreshed_roads_path=roads)

    def _fake_step5(**kwargs):
        nodes = tmp_path / "step5_suite" / "nodes.geojson"
        roads = tmp_path / "step5_suite" / "roads.geojson"
        _write_text(nodes, "{}")
        _write_text(roads, "{}")
        return SimpleNamespace(refreshed_nodes_path=nodes, refreshed_roads_path=roads)

    def _fake_finalize_bundle(**kwargs):
        resolved_out_root = kwargs["resolved_out_root"]
        _write_text(kwargs["final_nodes_path"], "{}")
        _write_text(kwargs["final_roads_path"], "{}")
        manifest_path = resolved_out_root / "skill_v1_manifest.json"
        summary_path = resolved_out_root / "skill_v1_bundle_summary.json"
        segment_path = resolved_out_root / "segment.geojson"
        inner_nodes_path = resolved_out_root / "inner_nodes.geojson"
        segment_error_path = resolved_out_root / "segment_error.geojson"
        step6_summary_path = resolved_out_root / "segment_summary.json"
        _write_text(manifest_path, "{}")
        _write_text(summary_path, "{}")
        _write_text(segment_path, "{}")
        _write_text(inner_nodes_path, "{}")
        _write_text(segment_error_path, "{}")
        _write_text(step6_summary_path, "{}")
        return {
            "manifest_path": str(manifest_path.resolve()),
            "summary_path": str(summary_path.resolve()),
            "segment_path": str(segment_path.resolve()),
            "inner_nodes_path": str(inner_nodes_path.resolve()),
            "segment_error_path": str(segment_error_path.resolve()),
            "step6_summary_path": str(step6_summary_path.resolve()),
        }

    monkeypatch.setattr(skill_v1, "initialize_working_layers", _fake_bootstrap)
    monkeypatch.setattr(skill_v1, "run_step2_segment_poc", _fake_step2)
    monkeypatch.setattr(skill_v1, "refresh_s2_baseline", _fake_refresh)
    monkeypatch.setattr(skill_v1, "run_step4_residual_graph", _fake_step4)
    monkeypatch.setattr(skill_v1, "run_step5_staged_residual_graph", _fake_step5)
    monkeypatch.setattr(skill_v1, "run_step5_oneway_segment_completion", _fake_oneway_passthrough)
    monkeypatch.setattr(skill_v1, "_finalize_bundle", _fake_finalize_bundle)

    suite_root = tmp_path / "suite_root"
    artifacts = skill_v1.run_t01_skill_v1(
        road_path=road_path,
        node_path=node_path,
        out_root=suite_root,
        run_id="XXXS7",
        per_run_subdir=True,
        strategy_config_path=strategy_path,
        debug=True,
    )

    assert artifacts.out_root == suite_root / "XXXS7"
    assert (suite_root / "XXXS7" / "t01_skill_v1_progress.json").is_file()
    assert (suite_root / "XXXS7" / "t01_skill_v1_summary.json").is_file()
    assert not (suite_root / "t01_skill_v1_progress.json").exists()


def test_stage_subprogress_callback_can_skip_perf_and_stdout(tmp_path: Path, capsys) -> None:
    progress_path = tmp_path / "progress.json"
    perf_markers_path = tmp_path / "perf_markers.jsonl"
    callback = skill_v1._make_stage_subprogress_callback(
        run_id="run-test",
        stage_name="step2",
        stage_index=2,
        total_stages=6,
        progress_path=progress_path,
        perf_markers_path=perf_markers_path,
        completed_stage_names=["bootstrap"],
    )

    callback(
        "validation_pair_state",
        {
            "pair_index": 37,
            "validation_count": 23262,
            "pair_id": "S2:10__20",
            "phase": "validation_pair_started",
            "_perf_log": False,
            "_stdout_log": False,
        },
    )

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["current_stage"] == "step2"
    assert "pair_index=37" in progress["message"]
    assert not perf_markers_path.exists()
    assert capsys.readouterr().out == ""


def test_validation_pair_state_subprogress_is_throttled_in_progress_snapshot(tmp_path: Path, capsys) -> None:
    progress_path = tmp_path / "progress.json"
    perf_markers_path = tmp_path / "perf_markers.jsonl"
    callback = skill_v1._make_stage_subprogress_callback(
        run_id="run-test",
        stage_name="step2",
        stage_index=2,
        total_stages=6,
        progress_path=progress_path,
        perf_markers_path=perf_markers_path,
        completed_stage_names=["bootstrap"],
    )

    callback(
        "validation_pair_state",
        {
            "pair_index": 51,
            "validation_count": 23262,
            "pair_id": "S2:10__20",
            "phase": "candidate_channel_built",
            "_perf_log": False,
            "_stdout_log": False,
        },
    )

    assert not progress_path.exists()
    assert not perf_markers_path.exists()
    assert capsys.readouterr().out == ""


def test_validation_pair_checkpoint_prints_stdout(tmp_path: Path, capsys) -> None:
    progress_path = tmp_path / "progress.json"
    perf_markers_path = tmp_path / "perf_markers.jsonl"
    callback = skill_v1._make_stage_subprogress_callback(
        run_id="run-test",
        stage_name="step2",
        stage_index=2,
        total_stages=6,
        progress_path=progress_path,
        perf_markers_path=perf_markers_path,
        completed_stage_names=["bootstrap"],
    )

    callback(
        "validation_pair_checkpoint",
        {
            "pair_index": 100,
            "validation_count": 23262,
            "pair_id": "S2:10__20",
            "phase": "validation_pair_started",
        },
    )

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    markers = [
        json.loads(line)
        for line in perf_markers_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "pair_index=100" in progress["message"]
    assert markers[-1]["substage_event"] == "validation_pair_checkpoint"
    stdout = capsys.readouterr().out
    assert "step2:validation_pair_checkpoint" in stdout
    assert "pair_index=100" in stdout


def test_run_stage_can_disable_tracemalloc_for_release(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.json"
    perf_markers_path = tmp_path / "perf_markers.jsonl"
    stage_timings: list[dict[str, object]] = []
    completed_stage_names: list[str] = []

    result = skill_v1._run_stage(
        name="step2",
        run_id="run-test",
        stage_index=2,
        total_stages=6,
        stage_timings=stage_timings,
        progress_path=progress_path,
        perf_markers_path=perf_markers_path,
        completed_stage_names=completed_stage_names,
        action=lambda: {"status": "ok"},
        profile_memory=False,
    )

    assert result == {"status": "ok"}
    assert completed_stage_names == ["step2"]
    assert stage_timings[0]["python_tracemalloc_peak_bytes"] == 0
    markers = [
        json.loads(line)
        for line in perf_markers_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert markers[-1]["event"] == "stage_completed"
    assert markers[-1]["python_tracemalloc_peak_bytes"] == 0


def test_resolve_out_root_defaults_to_t01_skill_eval(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    monkeypatch.setattr(skill_v1, "_find_repo_root", lambda start: repo_root)

    out_root, run_id = skill_v1._resolve_out_root(
        out_root=None,
        run_id="t01_skill_v1_test",
        cwd=repo_root,
    )

    assert run_id == "t01_skill_v1_test"
    assert out_root == repo_root / "outputs" / "_work" / "t01_skill_eval" / "t01_skill_v1_test"


def test_write_distance_gate_scope_check_marks_step2_step4_step5_as_hooked(tmp_path: Path) -> None:
    step2_root = tmp_path / "step2"
    step4_root = tmp_path / "step4"
    step5_root = tmp_path / "step5"
    (step2_root / "S2").mkdir(parents=True)
    (step4_root / "STEP4").mkdir(parents=True)
    (step5_root / "STEP5A").mkdir(parents=True)
    (step5_root / "STEP5B").mkdir(parents=True)
    (step5_root / "STEP5C").mkdir(parents=True)

    summary_doc = {
        "dual_carriageway_separation_gate_limit_m": 50.0,
        "side_access_distance_gate_limit_m": 50.0,
    }
    for path in (
        step2_root / "S2" / "segment_summary.json",
        step4_root / "STEP4" / "segment_summary.json",
        step5_root / "STEP5A" / "segment_summary.json",
        step5_root / "STEP5B" / "segment_summary.json",
        step5_root / "STEP5C" / "segment_summary.json",
    ):
        path.write_text(json.dumps(summary_doc, ensure_ascii=False), encoding="utf-8")

    out_path = skill_v1._write_distance_gate_scope_check(
        out_root=tmp_path,
        step2_root=step2_root,
        step4_root=step4_root,
        step5_root=step5_root,
    )
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert payload["step2_dual_gate_hooked"] is True
    assert payload["step2_side_gate_hooked"] is True
    assert payload["step4_dual_gate_hooked"] is True
    assert payload["step4_side_gate_hooked"] is True
    assert payload["step5a_dual_gate_hooked"] is True
    assert payload["step5a_side_gate_hooked"] is True
    assert payload["step5b_dual_gate_hooked"] is True
    assert payload["step5b_side_gate_hooked"] is True
    assert payload["step5c_present"] is True
    assert payload["step5c_dual_gate_hooked"] is True
    assert payload["step5c_side_gate_hooked"] is True


def test_write_all_stage_segment_roads_dir_copies_stage_prefixed_files(tmp_path: Path) -> None:
    def _write_geojson(path: Path, pair_id: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "MultiLineString",
                        "coordinates": [[[0.0, 0.0], [1.0, 1.0]]],
                    },
                    "properties": {
                        "pair_id": pair_id,
                        "layer_role": "segment_body",
                    },
                }
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    step2_root = tmp_path / "step2"
    step4_root = tmp_path / "step4"
    step5_root = tmp_path / "step5"
    _write_geojson(step2_root / "S2" / "segment_body_roads.geojson", "S2:10__20")
    _write_geojson(step4_root / "STEP4" / "segment_body_roads.geojson", "STEP4:30__40")
    _write_geojson(step5_root / "STEP5B" / "segment_body_roads.geojson", "STEP5B:50__60")

    out_path = skill_v1._write_all_stage_segment_roads_dir(
        out_root=tmp_path,
        step2_root=step2_root,
        step4_root=step4_root,
        step5_root=step5_root,
    )
    copied_files = sorted(path.name for path in out_path.iterdir())

    assert out_path.name == "all_stage_segment_roads"
    assert copied_files == [
        "Step2_segment_body_roads.geojson",
        "Step4_segment_body_roads.geojson",
        "Step5B_segment_body_roads.geojson",
    ]
    payload = json.loads((out_path / "Step5B_segment_body_roads.geojson").read_text(encoding="utf-8"))
    assert payload["features"][0]["properties"]["pair_id"] == "STEP5B:50__60"


def test_finalize_bundle_hides_working_mainnodeid_in_public_nodes(tmp_path: Path, monkeypatch) -> None:
    refreshed_nodes_path = tmp_path / "step5" / "nodes.geojson"
    refreshed_roads_path = tmp_path / "step5" / "roads.geojson"
    final_nodes_path = tmp_path / "final" / "nodes.geojson"
    final_roads_path = tmp_path / "final" / "roads.geojson"
    refreshed_nodes_path.parent.mkdir(parents=True, exist_ok=True)
    refreshed_roads_path.parent.mkdir(parents=True, exist_ok=True)

    write_geojson(
        refreshed_nodes_path,
        [
            {
                "properties": {
                    "id": 10,
                    "mainnodeid": 10,
                    "working_mainnodeid": 10,
                    "grade_2": 1,
                    "kind_2": 64,
                    "closed_con": 2,
                },
                "geometry": Point(0.0, 0.0),
            }
        ],
    )
    _write_text(
        refreshed_roads_path,
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [],
            },
            ensure_ascii=False,
        ),
    )

    monkeypatch.setattr(
        skill_v1,
        "run_step6_segment_aggregation_from_records",
        lambda **kwargs: SimpleNamespace(
            segment_path=tmp_path / "segment.geojson",
            inner_nodes_path=tmp_path / "inner_nodes.geojson",
            segment_error_path=tmp_path / "segment_error.geojson",
            segment_summary_path=tmp_path / "segment_summary.json",
        ),
    )
    monkeypatch.setattr(skill_v1, "_write_all_stage_segment_roads_dir", lambda **kwargs: tmp_path / "all_stage_segment_roads")
    captured_bundle_kwargs: dict[str, object] = {}

    def _fake_write_skill_v1_bundle(**kwargs):
        captured_bundle_kwargs.update(kwargs)
        return {"manifest_path": str((tmp_path / "manifest.json").resolve())}

    monkeypatch.setattr(skill_v1, "write_skill_v1_bundle", _fake_write_skill_v1_bundle)

    freeze_compare_nodes_path = tmp_path / "freeze_compare" / "nodes.geojson"
    freeze_compare_roads_path = tmp_path / "freeze_compare" / "roads.geojson"
    write_geojson(
        freeze_compare_nodes_path,
        [
            {
                "properties": {"id": 10, "mainnodeid": 10},
                "geometry": Point(0.0, 0.0),
            }
        ],
    )
    _write_text(
        freeze_compare_roads_path,
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [],
            },
            ensure_ascii=False,
        ),
    )

    skill_v1._finalize_bundle(
        resolved_out_root=tmp_path,
        step2_root=tmp_path / "step2",
        step4_root=tmp_path / "step4",
        step5_root=tmp_path / "step5",
        step5_artifacts=SimpleNamespace(
            step6_nodes=[],
            step6_roads=[],
            step6_node_properties_map={},
            step6_road_properties_map={},
            step6_mainnode_groups={},
            step6_group_to_allowed_road_ids={},
        ),
        refreshed_nodes_path=refreshed_nodes_path,
        refreshed_roads_path=refreshed_roads_path,
        final_nodes_path=final_nodes_path,
        final_roads_path=final_roads_path,
        run_id="t01_skill_v1_test",
        debug=False,
        freeze_compare_nodes_path=freeze_compare_nodes_path,
        freeze_compare_roads_path=freeze_compare_roads_path,
    )

    final_nodes_doc = json.loads(final_nodes_path.read_text(encoding="utf-8"))
    props = final_nodes_doc["features"][0]["properties"]
    assert props["mainnodeid"] == 10
    assert "working_mainnodeid" not in props
    assert captured_bundle_kwargs["refreshed_nodes_path"] == freeze_compare_nodes_path
    assert captured_bundle_kwargs["refreshed_roads_path"] == freeze_compare_roads_path
