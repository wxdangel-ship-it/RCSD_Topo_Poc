from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_surface_aware_plan_release as release
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_validation_publish import (
    are_step3_auxiliary_audits_deferred,
    decision_only_validation_step3_run,
    is_decision_only_validation_step3_run,
    is_step3_initial_topology_audit_deferred,
    is_validation_step3_run,
    promote_validation_step3_outputs,
    select_step3_publish_jobs,
    validation_step3_run,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.schemas import T06Step3Artifacts
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_surface_runtime import (
    Step3SurfaceRuntimeState,
    publish_step3_surface_runtime_state,
    take_step3_surface_runtime_state,
)


def test_validation_context_keeps_promotable_publish_jobs_and_restores_state() -> None:
    jobs = {
        "road": object(),
        "node": object(),
        "segment_relation": object(),
        "semantic_junction_group": object(),
        "right_attach": object(),
        "advance_right_closure": object(),
        "replacement_unit": object(),
        "collision": object(),
    }

    assert select_step3_publish_jobs(jobs) == jobs
    with validation_step3_run():
        assert is_validation_step3_run()
        assert select_step3_publish_jobs(jobs) == jobs
    assert not is_validation_step3_run()


def test_decision_only_validation_publishes_only_surface_topology_inputs() -> None:
    jobs = {
        "road": object(),
        "node": object(),
        "segment_relation": object(),
        "semantic_junction_group": object(),
        "right_attach": object(),
        "advance_right_closure": object(),
        "replacement_unit": object(),
        "collision": object(),
    }

    with decision_only_validation_step3_run():
        assert is_decision_only_validation_step3_run()
        assert select_step3_publish_jobs(jobs) == {}
    assert not is_decision_only_validation_step3_run()


def test_run_step3_validation_uses_internal_context(monkeypatch) -> None:
    observed: list[bool] = []

    def fake_runner(**_kwargs):
        observed.append(is_validation_step3_run())
        assert are_step3_auxiliary_audits_deferred()
        assert is_step3_initial_topology_audit_deferred()
        return object()

    monkeypatch.setattr(release, "run_t06_step3_segment_replacement", fake_runner)

    release._run_step3(validation_only=True, write_feature_json_outputs=False)

    assert observed == [True]
    assert not is_validation_step3_run()


def test_surface_runtime_state_is_single_use_and_step_scoped(tmp_path: Path) -> None:
    state = Step3SurfaceRuntimeState(
        step_root=tmp_path / "step3",
        swsd_segments=[],
        swsd_roads=[],
        swsd_nodes=[],
        step2_replaceable_rows=[],
        frcsd_roads=[],
        frcsd_nodes=[],
        segment_relation_rows=[],
        semantic_junction_group_rows=[],
        advance_right_audit_rows=[],
        connectivity_supplement_road_ids=set(),
    )
    publish_step3_surface_runtime_state(state)

    assert take_step3_surface_runtime_state(state.step_root) is state
    assert take_step3_surface_runtime_state(state.step_root) is None


def test_run_surface_validation_skips_auxiliary_refresh(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    class Artifacts:
        step_root = tmp_path
        summary_path = tmp_path / "t06_step3_summary.json"

    monkeypatch.setattr(
        release,
        "_run_surface_topology_postprocess",
        lambda **_kwargs: {"status": "ok"},
    )
    monkeypatch.setattr(
        release,
        "refresh_semantic_junction_topology_audit",
        lambda **_kwargs: {"status": "ok"},
    )
    monkeypatch.setattr(
        release,
        "refresh_rcsd_road_ownership_after_surface",
        lambda **_kwargs: calls.append("ownership"),
    )
    monkeypatch.setattr(
        release,
        "refresh_segment_construction_audit_after_surface",
        lambda **_kwargs: calls.append("construction"),
    )

    result = release._run_surface(
        Artifacts(),
        swsd_segment_path=tmp_path / "segment.gpkg",
        swsd_roads_path=tmp_path / "roads.gpkg",
        surface_inputs={"t05_surface_path": tmp_path / "surface.gpkg"},
        surface_topology_closure=True,
        validation_only=True,
    )

    assert calls == []
    assert result == {
        "status": "ok",
        "semantic_junction_topology_refresh": {"status": "ok"},
    }


def test_promote_validation_outputs_copies_and_rebases_paths(tmp_path: Path) -> None:
    source_step_root = tmp_path / "scratch" / "run" / "step3"
    final_step_root = tmp_path / "final" / "run" / "step3"
    source_step_root.mkdir(parents=True)
    (source_step_root / "road.gpkg").write_bytes(b"gpkg")
    summary_path = source_step_root / "summary.json"
    summary_path.write_text(
        '{"output_path": "' + str(source_step_root).replace("\\", "\\\\") + '/road.gpkg"}',
        encoding="utf-8",
    )
    artifacts = T06Step3Artifacts(
        run_id="run",
        run_root=source_step_root.parent,
        step_root=source_step_root,
        frcsd_road_gpkg_path=source_step_root / "road.gpkg",
        frcsd_node_gpkg_path=source_step_root / "node.gpkg",
        replacement_units_gpkg_path=source_step_root / "unit.gpkg",
        swsd_frcsd_segment_relation_gpkg_path=source_step_root / "relation.gpkg",
        junction_rebuild_audit_gpkg_path=source_step_root / "junction.gpkg",
        summary_path=summary_path,
    )

    promoted = promote_validation_step3_outputs(artifacts, final_step_root)

    assert promoted.run_root == final_step_root.resolve().parent
    assert promoted.step_root == final_step_root.resolve()
    assert promoted.frcsd_road_gpkg_path.read_bytes() == b"gpkg"
    assert str(final_step_root.resolve()) in promoted.summary_path.read_text(encoding="utf-8")
    assert str(source_step_root.resolve()) not in promoted.summary_path.read_text(encoding="utf-8")
