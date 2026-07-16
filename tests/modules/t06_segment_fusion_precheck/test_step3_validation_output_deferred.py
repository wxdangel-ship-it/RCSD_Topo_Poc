from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.parallel_output import FeatureTripletJob
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_final_topology_gate import (
    final_topology_gate_decision,
    topology_fail_keys,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_surface_runtime import (
    Step3SurfaceRuntimeState,
    normalize_step3_surface_runtime_state,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_validation_output_deferred as deferred


def _feature(properties: dict) -> dict:
    return {"properties": properties, "geometry": None}


def _runtime_state(tmp_path: Path) -> Step3SurfaceRuntimeState:
    return Step3SurfaceRuntimeState(
        step_root=tmp_path / "validation" / "step3",
        swsd_segments=[],
        swsd_roads=[],
        swsd_nodes=[],
        step2_replaceable_rows=[],
        frcsd_roads=[_feature({"id": "road", "source": 1})],
        frcsd_nodes=[_feature({"id": "node", "source": 1, "surface_flag": "kept"})],
        segment_relation_rows=[_feature({"swsd_segment_id": "segment", "relation_status": "replaced"})],
        semantic_junction_group_rows=[],
        advance_right_audit_rows=[],
        connectivity_supplement_road_ids=set(),
        deferred_publish_jobs={
            "replacement_unit": FeatureTripletJob(
                "t06_step3_replacement_units",
                [_feature({"replacement_unit_id": "unit"})],
                ["replacement_unit_id"],
            ),
        },
        surface_topology_audit_rows=[_feature({"audit_layer": "surface", "audit_status": "pass"})],
        topology_connectivity_audit_rows=[
            _feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": "fail",
                    "audit_reason": "junction_incident_segment_mapped_points_diverged",
                    "counts_in_final_frcsd_topology_fail": True,
                    "final_topology_category": "segment_transition",
                    "final_topology_object_key": "transition:node",
                    "swsd_node_id": "node",
                    "swsd_segment_ids": ["segment"],
                    "source_mix": "source_1+source_2",
                }
            )
        ],
        authoritative_transition_closure_rows=[_feature({"swsd_node_id": "node", "audit_status": "applied"})],
    )


def test_final_publish_materializes_deferred_runtime_outputs_once(monkeypatch, tmp_path: Path) -> None:
    observed: dict[str, object] = {}
    json_outputs: list[tuple[Path, list[dict]]] = []

    def fake_publish(*, step_root, jobs, max_workers=1):
        observed.update({"step_root": step_root, "jobs": jobs, "max_workers": max_workers})
        return {name: {"gpkg": step_root / f"{job.stem}.gpkg"} for name, job in jobs.items()}

    monkeypatch.setattr(deferred, "publish_feature_triplets", fake_publish)
    monkeypatch.setattr(
        deferred,
        "_write_deferred_feature_json",
        lambda path, rows: json_outputs.append((path, rows)),
    )
    state = _runtime_state(tmp_path)
    state.publish_topology_connectivity_json = True
    final_root = tmp_path / "final" / "step3"

    paths = deferred.publish_deferred_validation_outputs(state, final_root)

    jobs = observed["jobs"]
    assert observed["step_root"] == final_root
    assert observed["max_workers"] == 2
    assert set(jobs) == {
        "replacement_unit",
        "road",
        "node",
        "segment_relation",
        "surface_topology",
        "topology_connectivity",
        "authoritative_transition_closure",
    }
    assert jobs["road"].features is state.frcsd_roads
    assert jobs["node"].features is state.frcsd_nodes
    assert jobs["node"].fieldnames == ["id", "source", "surface_flag"]
    assert jobs["segment_relation"].features is state.segment_relation_rows
    assert paths["topology_connectivity"]["gpkg"].name.endswith("topology_connectivity_audit.gpkg")
    assert [path.name for path, _rows in json_outputs] == [
        "t06_step3_topology_connectivity_audit.json",
        "t06_step3_authoritative_transition_closure_audit.json",
    ]


def test_final_publish_materializes_empty_authoritative_audit(monkeypatch, tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    def fake_publish(*, step_root, jobs, max_workers=1):
        observed["jobs"] = jobs
        return {}

    monkeypatch.setattr(deferred, "publish_feature_triplets", fake_publish)
    state = _runtime_state(tmp_path)
    state.authoritative_transition_closure_rows = []
    state.topology_connectivity_audit_rows[0]["properties"]["topology_road_lineage_id"] = "[]"

    deferred.publish_deferred_validation_outputs(state, tmp_path / "final")

    job = observed["jobs"]["authoritative_transition_closure"]
    assert job.features == []
    topology_job = observed["jobs"]["topology_connectivity"]
    assert topology_job.features[0]["properties"]["topology_road_lineage_id"] == ""


def test_final_publish_can_defer_ownership_rewritten_outputs(monkeypatch, tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    def fake_publish(*, step_root, jobs, max_workers=1):
        observed["jobs"] = jobs
        return {}

    monkeypatch.setattr(deferred, "publish_feature_triplets", fake_publish)
    deferred.publish_deferred_validation_outputs(
        _runtime_state(tmp_path),
        tmp_path / "final",
        excluded_job_names={"road", "segment_relation"},
    )

    assert "road" not in observed["jobs"]
    assert "segment_relation" not in observed["jobs"]
    assert "node" in observed["jobs"]


def test_runtime_normalization_matches_empty_scalar_lineage_round_trip(tmp_path: Path) -> None:
    state = _runtime_state(tmp_path)
    state.topology_connectivity_audit_rows[0]["properties"]["swsd_segment_ids"] = ["segment"]
    for value in ([], "[]"):
        state.topology_connectivity_audit_rows[0]["properties"]["topology_road_lineage_id"] = value
        normalize_step3_surface_runtime_state(state)
        assert state.topology_connectivity_audit_rows[0]["properties"]["topology_road_lineage_id"] == ""
        assert state.topology_connectivity_audit_rows[0]["properties"]["swsd_segment_ids"] == ["segment"]


def test_final_topology_decisions_accept_in_memory_rows_without_gpkg(tmp_path: Path) -> None:
    state = _runtime_state(tmp_path)
    plan_rows = [
        _feature(
            {
                "replacement_plan_id": "plan",
                "plan_status": "ready",
                "execution_action": "replace",
                "swsd_segment_id": "segment",
            }
        )
    ]

    fail_keys = topology_fail_keys(
        tmp_path,
        audit_rows=state.topology_connectivity_audit_rows,
    )
    decision = final_topology_gate_decision(
        tmp_path,
        plan_rows,
        audit_rows=state.topology_connectivity_audit_rows,
    )

    assert fail_keys == {
        (
            "segment_junction_connectivity",
            '["segment"]',
            "node",
            'segment_transition:["segment_junction_connectivity","node",["segment"],'
            '"junction_incident_segment_mapped_points_diverged"]',
            "junction_incident_segment_mapped_points_diverged",
        )
    }
    assert decision["rollback_plan_ids"] == ["plan"]
