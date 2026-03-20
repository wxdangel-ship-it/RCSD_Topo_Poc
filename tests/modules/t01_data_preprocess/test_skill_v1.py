from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rcsd_topo_poc.modules.t01_data_preprocess import skill_v1


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

    def _fake_step2(**kwargs):
        callback = kwargs["progress_callback"]
        callback("candidate_search_completed", {"strategy_id": "S2", "candidate_pair_count": 3})
        callback("validation_completed", {"strategy_id": "S2", "validated_pair_count": 2, "rejected_pair_count": 1})
        return []

    def _fake_refresh(**kwargs):
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
        _write_text(manifest_path, "{}")
        _write_text(summary_path, "{}")
        return {
            "manifest_path": str(manifest_path.resolve()),
            "summary_path": str(summary_path.resolve()),
        }

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
    markers = [
        json.loads(line)
        for line in (artifacts.out_root / "t01_skill_v1_perf_markers.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert progress["status"] == "completed"
    subprogress_events = [item for item in markers if item["event"] == "stage_subprogress"]
    assert any(item["stage_name"] == "step2" for item in subprogress_events)
    assert any(item["substage_event"] == "validation_completed" for item in subprogress_events)
