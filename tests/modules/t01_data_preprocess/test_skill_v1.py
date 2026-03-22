from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from shapely.geometry import Point

from rcsd_topo_poc.modules.t01_data_preprocess import skill_v1
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_geojson


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    monkeypatch.setattr(
        skill_v1,
        "write_skill_v1_bundle",
        lambda **kwargs: {"manifest_path": str((tmp_path / "manifest.json").resolve())},
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
    )

    final_nodes_doc = json.loads(final_nodes_path.read_text(encoding="utf-8"))
    props = final_nodes_doc["features"][0]["properties"]
    assert props["mainnodeid"] == 10
    assert "working_mainnodeid" not in props
