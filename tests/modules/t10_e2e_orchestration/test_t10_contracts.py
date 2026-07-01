from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t08_preprocess.vector_io import read_vector, write_gpkg
from rcsd_topo_poc.modules.t10_e2e_orchestration import case_runner as t10_case_runner
from rcsd_topo_poc.modules.t10_e2e_orchestration import (
    T10_V1_CHAIN,
    build_t10_t06_funnel_summary,
    build_case_evidence_package,
    build_multi_case_evidence_package,
    build_multi_segment_evidence_package,
    decode_t10_case_evidence_text_bundle,
    export_t10_case_evidence_text_bundle,
    suggest_t10_cases,
    validate_t10_manifest,
    write_t10_upstream_feedback,
    write_t10_planning_outputs,
)
from rcsd_topo_poc.modules.t10_e2e_orchestration.contracts import EXTERNAL_INPUT_REQUIREMENTS, HANDOFF_REQUIREMENTS


def _write_file(path: Path, text: str = "x") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _complete_manifest(tmp_path: Path) -> dict:
    external_inputs = {
        requirement.slot: _write_file(tmp_path / "external" / f"{requirement.slot}.gpkg")
        for requirement in EXTERNAL_INPUT_REQUIREMENTS
    }
    handoffs = {
        requirement.slot: _write_file(tmp_path / "handoffs" / f"{requirement.slot}.json")
        for requirement in HANDOFF_REQUIREMENTS
    }
    return {"external_inputs": external_inputs, "handoffs": handoffs}


def _complete_vector_manifest(tmp_path: Path) -> dict:
    external_inputs = {}
    for requirement in EXTERNAL_INPUT_REQUIREMENTS:
        slot = requirement.slot
        path = tmp_path / "external_vector" / f"{slot}.gpkg"
        path.parent.mkdir(parents=True, exist_ok=True)
        if slot == "prepared_swsd_nodes":
            features = [
                {"properties": {"id": "1001", "mainnodeid": "9001"}, "geometry": Point(0.0, 0.0)},
                {"properties": {"id": "1002", "mainnodeid": "9001"}, "geometry": Point(10.0, 0.0)},
                {"properties": {"id": "2001", "mainnodeid": "2001"}, "geometry": Point(5000.0, 0.0)},
                {"properties": {"id": "3001", "mainnodeid": "3001"}, "geometry": Point(400.0, 0.0)},
            ]
        elif slot == "prepared_swsd_roads":
            features = [
                {
                    "properties": {"id": "r_near", "snodeid": "1001", "enodeid": "3001"},
                    "geometry": LineString([(0.0, 0.0), (400.0, 0.0)]),
                },
                {
                    "properties": {"id": "r_far", "snodeid": "2001", "enodeid": "2001"},
                    "geometry": LineString([(4900.0, 0.0), (5100.0, 0.0)]),
                },
            ]
        elif slot == "rcsdnode":
            features = [
                {"properties": {"id": "rc1"}, "geometry": Point(5.0, 0.0)},
                {"properties": {"id": "rc2"}, "geometry": Point(400.0, 0.0)},
                {"properties": {"id": "rc_far"}, "geometry": Point(5000.0, 0.0)},
            ]
        elif slot == "rcsdroad":
            features = [
                {
                    "properties": {"id": "rcroad_near", "snodeid": "rc1", "enodeid": "rc2"},
                    "geometry": LineString([(5.0, 0.0), (400.0, 0.0)]),
                },
                {
                    "properties": {"id": "rcroad_far", "snodeid": "rc_far", "enodeid": "rc_far"},
                    "geometry": LineString([(4900.0, 0.0), (5100.0, 0.0)]),
                },
            ]
        else:
            features = [
                {"properties": {"id": f"{slot}_near"}, "geometry": Point(5.0, 0.0)},
                {"properties": {"id": f"{slot}_far"}, "geometry": Point(5000.0, 0.0)},
            ]
        write_gpkg(path, features, crs_text="EPSG:3857", layer_name=slot)
        external_inputs[slot] = str(path)
    handoffs = {
        requirement.slot: _write_file(tmp_path / "handoffs" / f"{requirement.slot}.json")
        for requirement in HANDOFF_REQUIREMENTS
    }
    return {"external_inputs": external_inputs, "handoffs": handoffs}


def _write_segment_gpkg(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_gpkg(
        path,
        [
            {
                "properties": {"id": "1001_3001", "snodeid": "1001", "enodeid": "3001"},
                "geometry": LineString([(0.0, 0.0), (400.0, 0.0)]),
            },
            {
                "properties": {"id": "2001_2001", "snodeid": "2001", "enodeid": "2001"},
                "geometry": LineString([(4900.0, 0.0), (5100.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
        layer_name="segment",
    )
    return str(path)


def _write_nodes_geojson(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": "1001", "mainnodeid": "9001", "kind_2": 4},
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            },
            {
                "type": "Feature",
                "properties": {"id": "1002", "mainnodeid": "9001", "kind_2": 4},
                "geometry": {"type": "Point", "coordinates": [10.0, 0.0]},
            },
            {
                "type": "Feature",
                "properties": {"id": "2001", "mainnodeid": None, "kind_2": 2048},
                "geometry": {"type": "Point", "coordinates": [50.0, 0.0]},
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_t10_manifest_requires_explicit_file_handoffs(tmp_path: Path) -> None:
    manifest = _complete_manifest(tmp_path)
    audit = validate_t10_manifest(manifest, strict_exists=True)

    assert audit["passed"] is True

    t05_root = tmp_path / "t05_phase2_root"
    t05_root.mkdir()
    manifest["handoffs"]["t05_phase2_root"] = str(t05_root)
    audit = validate_t10_manifest(manifest, strict_exists=True)

    assert audit["passed"] is False
    assert any(issue["code"] == "directory_only_handoff" for issue in audit["issues"])


def test_t10_t05_runner_uses_explicit_files_not_run_root_handoffs(tmp_path: Path, monkeypatch) -> None:
    stage_dir = tmp_path / "stage"
    external_inputs = {
        "rcsdroad": Path(_write_file(tmp_path / "external" / "rcsdroad.gpkg")),
        "rcsdnode": Path(_write_file(tmp_path / "external" / "rcsdnode.gpkg")),
    }
    t04_case_root = tmp_path / "t04" / "cases"
    t04_case_root.mkdir(parents=True)
    handoffs = {
        "final_swsd_nodes": _write_file(tmp_path / "t04" / "nodes.gpkg"),
        "t07_surface": _write_file(tmp_path / "t07" / "t07_rcsdintersection_anchor_surface.gpkg"),
        "t07_relation_evidence": _write_file(tmp_path / "t07" / "t07_swsd_rcsd_relation_evidence.csv"),
        "t03_surface": _write_file(tmp_path / "t03" / "virtual_intersection_polygons.gpkg"),
        "t03_relation_evidence": _write_file(tmp_path / "t03" / "t03_swsd_rcsd_relation_evidence.csv"),
        "t04_surface": _write_file(tmp_path / "t04" / "divmerge_virtual_anchor_surface.gpkg"),
        "t04_relation_evidence": _write_file(tmp_path / "t04" / "t04_swsd_rcsd_relation_evidence.csv"),
        "t04_summary": _write_file(tmp_path / "t04" / "divmerge_virtual_anchor_surface_summary.json"),
        "t04_audit": _write_file(tmp_path / "t04" / "divmerge_virtual_anchor_surface_audit.gpkg"),
        "t04_case_root": str(t04_case_root),
    }
    captured: dict[str, object] = {}

    def fake_execute_command(stage_id, stage_dir, repo_root, command, env_overrides, inputs):
        captured["command"] = command
        captured["inputs"] = inputs
        _write_file(stage_dir / "t05_phase1" / "junction_anchor_surface.gpkg")
        _write_file(stage_dir / "t05_phase2" / "intersection_match_all.geojson")
        _write_file(stage_dir / "t05_phase2" / "rcsdroad_out.gpkg")
        _write_file(stage_dir / "t05_phase2" / "rcsdnode_out.gpkg")
        _write_file(stage_dir / "t05_phase2" / "summary.json")
        return {"stage_id": stage_id, "stage": stage_id, "status": "passed", "outputs": {}}

    monkeypatch.setattr(t10_case_runner, "_execute_command", fake_execute_command)

    record, _produced = t10_case_runner._run_t05(
        case_id="9001",
        stage_dir=stage_dir,
        repo_root=tmp_path,
        python_bin="python",
        external_inputs=external_inputs,
        handoffs=handoffs,
    )

    command = captured["command"]
    inputs = captured["inputs"]
    assert record["status"] == "passed"
    assert "--t07-input" in command
    assert "--t03-surface" in command
    assert "--t04-surface" in command
    assert "--t07-dir" not in command
    assert "--t03-dir" not in command
    assert "--t04-dir" not in command
    assert "t07_run_root" not in inputs
    assert "t03_run_root" not in inputs
    assert "t04_run_root" not in inputs
    assert command[command.index("--nodes") + 1] == handoffs["final_swsd_nodes"]
    assert record["execution_context"] == {"t04_case_root": str(t04_case_root)}
    assert record["outputs"]["t05_phase2_summary"].endswith("/summary.json")
    assert record["missing_outputs"] == []


def test_t10_t04_consumes_t03_nodes_and_publishes_final_nodes(tmp_path: Path, monkeypatch) -> None:
    stage_dir = tmp_path / "stage"
    external_inputs = {
        "drivezone": Path(_write_file(tmp_path / "external" / "drivezone.gpkg")),
        "divstripzone": Path(_write_file(tmp_path / "external" / "divstripzone.gpkg")),
        "rcsdroad": Path(_write_file(tmp_path / "external" / "rcsdroad.gpkg")),
        "rcsdnode": Path(_write_file(tmp_path / "external" / "rcsdnode.gpkg")),
    }
    handoffs = {
        "t03_nodes": _write_file(tmp_path / "t03" / "nodes.gpkg"),
        "t01_roads": _write_file(tmp_path / "t01" / "roads.gpkg"),
        "t03_intersection_match": _write_file(tmp_path / "t03" / "intersection_match_t03.geojson"),
    }
    captured: dict[str, object] = {}

    def fake_execute_command(stage_id, stage_dir, repo_root, command, env_overrides, inputs):
        captured["env"] = env_overrides
        captured["inputs"] = inputs
        run_root = stage_dir / "t04"
        _write_file(run_root / "nodes.gpkg")
        _write_file(run_root / "divmerge_virtual_anchor_surface.gpkg")
        _write_file(run_root / "t04_swsd_rcsd_relation_evidence.csv")
        _write_file(run_root / "intersection_match_t04.geojson")
        _write_file(run_root / "divmerge_virtual_anchor_surface_summary.json")
        _write_file(run_root / "divmerge_virtual_anchor_surface_audit.gpkg")
        (run_root / "cases").mkdir(parents=True, exist_ok=True)
        return {"stage_id": stage_id, "stage": stage_id, "status": "passed", "outputs": {}}

    monkeypatch.setattr(t10_case_runner, "_execute_command", fake_execute_command)

    record, produced = t10_case_runner._run_t04(
        case_id="9001",
        stage_dir=stage_dir,
        repo_root=tmp_path,
        external_inputs=external_inputs,
        handoffs=handoffs,
    )

    assert record["status"] == "passed"
    assert captured["env"]["NODES_PATH"] == handoffs["t03_nodes"]
    assert captured["inputs"]["t03_nodes"] == Path(handoffs["t03_nodes"])
    assert produced["t04_nodes"].endswith("/t04/nodes.gpkg")
    assert produced["final_swsd_nodes"] == produced["t04_nodes"]
    assert record["missing_outputs"] == []


def test_t10_t07_step3_compatibility_backfill_helper(tmp_path: Path, monkeypatch) -> None:
    stage_dir = tmp_path / "stage"
    t07_step2_nodes = _write_file(tmp_path / "t07" / "step2_anchor_recognition" / "nodes.gpkg")
    handoffs = {
        "t07_nodes": t07_step2_nodes,
        "t05_intersection_match_all": _write_file(tmp_path / "t05" / "intersection_match_all.geojson"),
        "t05_rcsdnode_out": _write_file(tmp_path / "t05" / "rcsdnode_out.gpkg"),
    }
    captured: dict[str, object] = {}

    def fake_execute_command(stage_id, stage_dir, repo_root, command, env_overrides, inputs):
        captured["stage_id"] = stage_id
        captured["command"] = command
        captured["env"] = env_overrides
        captured["inputs"] = inputs
        step3_root = stage_dir / "t07_step3" / "step3_intersection_match"
        _write_file(step3_root / "nodes.gpkg")
        _write_file(step3_root / "intersection_match_t07.geojson")
        _write_file(step3_root / "t07_rcsdintersection_anchor_surface.gpkg")
        _write_file(step3_root / "t07_swsd_rcsd_relation_evidence.csv")
        _write_file(step3_root / "t07_step3_summary.json")
        return {"stage_id": stage_id, "stage": stage_id, "status": "passed", "outputs": {}}

    monkeypatch.setattr(t10_case_runner, "_execute_command", fake_execute_command)

    record, produced = t10_case_runner._run_t07_step3(
        case_id="9001",
        stage_dir=stage_dir,
        repo_root=tmp_path,
        python_bin="python",
        handoffs=handoffs,
    )

    env = captured["env"]
    inputs = captured["inputs"]
    assert captured["stage_id"] == "t07_step3"
    assert captured["command"] == ["bash", "scripts/t07_run_step3_intersection_match_innernet.sh"]
    assert env["PYTHON_BIN"] == "python"
    assert env["NODES_PATH"] == t07_step2_nodes
    assert env["INTERSECTION_MATCH_ALL_PATH"] == handoffs["t05_intersection_match_all"]
    assert env["RCSDNODE_PATH"] == handoffs["t05_rcsdnode_out"]
    assert inputs["t07_nodes"] == Path(t07_step2_nodes)
    assert record["status"] == "passed"
    assert produced["t07_step2_nodes"] == t07_step2_nodes
    assert produced["t07_step3_nodes"].endswith("/t07_step3/step3_intersection_match/nodes.gpkg")
    assert "t07_nodes" not in produced
    assert produced["t07_relation_evidence"].endswith("/t07_step3/step3_intersection_match/t07_swsd_rcsd_relation_evidence.csv")
    assert record["missing_outputs"] == []


def test_t10_t06_step12_uses_final_swsd_nodes(tmp_path: Path, monkeypatch) -> None:
    stage_dir = tmp_path / "stage"
    handoffs = {
        "t01_segment": _write_file(tmp_path / "t01" / "segment.gpkg"),
        "t01_roads": _write_file(tmp_path / "t01" / "roads.gpkg"),
        "final_swsd_nodes": _write_file(tmp_path / "t04" / "nodes.gpkg"),
        "t05_intersection_match_all": _write_file(tmp_path / "t05" / "intersection_match_all.geojson"),
        "t05_rcsdroad_out": _write_file(tmp_path / "t05" / "rcsdroad_out.gpkg"),
        "t05_rcsdnode_out": _write_file(tmp_path / "t05" / "rcsdnode_out.gpkg"),
    }
    captured: dict[str, object] = {}

    def fake_execute_command(stage_id, stage_dir, repo_root, command, env_overrides, inputs):
        captured["command"] = command
        captured["inputs"] = inputs
        run_root = stage_dir / "t06"
        _write_file(run_root / "step1_identify_fusion_units" / "t06_step1_summary.json")
        _write_file(run_root / "step2_extract_rcsd_segments" / "t06_step2_summary.json")
        _write_file(run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_replaceable.gpkg")
        return {"stage_id": stage_id, "stage": stage_id, "status": "passed", "outputs": {}}

    monkeypatch.setattr(t10_case_runner, "_execute_command", fake_execute_command)

    record, _produced = t10_case_runner._run_t06_step12(
        case_id="9001",
        stage_dir=stage_dir,
        repo_root=tmp_path,
        python_bin="python",
        handoffs=handoffs,
    )

    command = captured["command"]
    assert record["status"] == "passed"
    assert captured["inputs"]["final_swsd_nodes"] == Path(handoffs["final_swsd_nodes"])
    assert command[command.index("--swsd-nodes") + 1] == handoffs["final_swsd_nodes"]
    assert record["missing_outputs"] == []


def test_t10_t06_step3_uses_replaceable_file_not_run_root_input(tmp_path: Path, monkeypatch) -> None:
    stage_dir = tmp_path / "stage"
    t06_run_root = tmp_path / "t06"
    handoffs = {
        "t06_run_root": str(t06_run_root),
        "t06_step2_replaceable": _write_file(
            t06_run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_replaceable.gpkg"
        ),
        "t01_segment": _write_file(tmp_path / "t01" / "segment.gpkg"),
        "t01_roads": _write_file(tmp_path / "t01" / "roads.gpkg"),
        "final_swsd_nodes": _write_file(tmp_path / "t04" / "nodes.gpkg"),
        "t05_rcsdroad_out": _write_file(tmp_path / "t05" / "rcsdroad_out.gpkg"),
        "t05_rcsdnode_out": _write_file(tmp_path / "t05" / "rcsdnode_out.gpkg"),
    }
    captured: dict[str, object] = {}

    def fake_execute_command(stage_id, stage_dir, repo_root, command, env_overrides, inputs):
        captured["command"] = command
        captured["inputs"] = inputs
        step3_root = t06_run_root / "step3_segment_replacement"
        _write_file(step3_root / "t06_frcsd_road.gpkg")
        _write_file(step3_root / "t06_frcsd_node.gpkg")
        _write_file(step3_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")
        _write_file(step3_root / "t06_step3_topology_connectivity_audit.gpkg")
        _write_file(step3_root / "t06_step3_summary.json")
        return {"stage_id": stage_id, "stage": stage_id, "status": "passed", "outputs": {}}

    monkeypatch.setattr(t10_case_runner, "_execute_command", fake_execute_command)

    record, _produced = t10_case_runner._run_t06_step3(
        case_id="9001",
        stage_dir=stage_dir,
        repo_root=tmp_path,
        python_bin="python",
        handoffs=handoffs,
    )

    command = captured["command"]
    inputs = captured["inputs"]
    assert record["status"] == "passed"
    assert "--t06-run-root" in command
    assert command[command.index("--swsd-nodes") + 1] == handoffs["final_swsd_nodes"]
    assert "t06_step2_replaceable" in inputs
    assert "t06_run_root" not in inputs
    assert record["execution_context"] == {"t06_run_root": str(t06_run_root)}
    assert record["missing_outputs"] == []


def test_t10_innernet_full_pipeline_passes_surface_inputs_to_t06_step3() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "t10_run_innernet_full_pipeline.sh"
    script = script_path.read_text(encoding="utf-8")
    t06_step3_region = script.split("if should_run_stage t06_step3; then", 1)[1].split("T09_OUT_ROOT=", 1)[0]

    assert 'T05_JUNCTION_SURFACE="$(manifest_get outputs t05_junction_surface' in script
    assert '"outputs.junction_surface=$T05_JUNCTION_SURFACE"' in script
    assert '        "t05_junction_surface": ("t05", "junction_surface"),' in script
    assert '        "t06_surface_topology_audit": ("t06_step3", "surface_topology_audit"),' in script
    assert '--t07-surface "$T07_STEP2_SURFACE"' in t06_step3_region
    assert '--t03-surface "$T03_SURFACE"' in t06_step3_region
    assert '--t04-surface "$T04_SURFACE"' in t06_step3_region
    assert '--t04-audit "$T04_AUDIT"' in t06_step3_region
    assert '--t05-surface "$T05_JUNCTION_SURFACE"' in t06_step3_region
    assert "--surface-topology-closure" in t06_step3_region
    assert '"inputs.t05_surface=$T05_JUNCTION_SURFACE"' in t06_step3_region
    assert '"outputs.surface_topology_audit=$T06_SURFACE_TOPOLOGY_AUDIT"' in t06_step3_region


def test_t10_planning_outputs_keep_t08_outside_v1_chain(tmp_path: Path) -> None:
    artifacts = write_t10_planning_outputs(
        manifest=_complete_manifest(tmp_path),
        out_root=tmp_path / "out",
        run_id="plan_001",
        strict_exists=True,
    )

    plan = json.loads(artifacts.workflow_plan_json.read_text(encoding="utf-8"))
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))

    assert tuple(plan["chain"]) == T10_V1_CHAIN
    assert "t08_preprocess" not in plan["chain"]
    assert summary["execution_mode"] == "contract_validation"
    assert summary["passed"] is True
    assert "independent" in summary["t08_policy"].lower()


def test_case_evidence_package_uses_external_inputs_and_excludes_intermediate_handoffs(tmp_path: Path) -> None:
    manifest = _complete_manifest(tmp_path)
    artifacts = build_case_evidence_package(
        manifest=manifest,
        out_root=tmp_path / "packages",
        semantic_junction_id="622700016",
        radius_m=250.0,
        package_id="case_622700016",
        include_files=True,
        materialization_mode="copy_full",
    )

    package_manifest = json.loads(artifacts.manifest_json.read_text(encoding="utf-8"))
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))

    assert package_manifest["scope"]["swsd_semantic_junction_id"] == "622700016"
    assert package_manifest["scope"]["radius_m"] == 250.0
    assert len(package_manifest["included_external_inputs"]) == len(EXTERNAL_INPUT_REQUIREMENTS)
    assert len(package_manifest["excluded_intermediate_handoffs"]) == len(HANDOFF_REQUIREMENTS)
    assert summary["materialized_file_count"] == len(EXTERNAL_INPUT_REQUIREMENTS)
    assert all(entry["package_path"].startswith("external_inputs/") for entry in package_manifest["included_external_inputs"])


def test_suggest_t10_cases_maps_selector_evidence_to_swsd_semantic_junctions(tmp_path: Path) -> None:
    manifest = _complete_manifest(tmp_path)
    manifest["external_inputs"]["prepared_swsd_nodes"] = _write_nodes_geojson(tmp_path / "input" / "nodes.geojson")
    selector_csv = tmp_path / "selector" / "node_error_tool6.csv"
    selector_csv.parent.mkdir(parents=True, exist_ok=True)
    selector_csv.write_text(
        "target_id,node_id,error_type\n"
        "9001,,错误交叉路口_T型路口\n"
        ",2001,错误T型路口\n",
        encoding="utf-8",
    )

    suggestions = suggest_t10_cases(
        manifest=manifest,
        selector_evidence={"t08_tool6": str(selector_csv)},
    )

    candidates = {candidate["case_id"]: candidate for candidate in suggestions["candidates"]}
    assert suggestions["candidate_count"] == 2
    assert candidates["9001"]["candidate_status"] == "problem_candidate"
    assert candidates["9001"]["member_node_ids"] == ["1001", "1002"]
    assert candidates["2001"]["candidate_status"] == "problem_candidate"
    assert candidates["2001"]["selector_evidence"][0]["matched_field"] == "node_id"


def test_suggest_t10_cases_without_selector_returns_inventory_only(tmp_path: Path) -> None:
    manifest = _complete_manifest(tmp_path)
    manifest["external_inputs"]["prepared_swsd_nodes"] = _write_nodes_geojson(tmp_path / "input" / "nodes.geojson")

    suggestions = suggest_t10_cases(manifest=manifest)

    assert suggestions["candidate_count"] == 2
    assert suggestions["problem_candidate_count"] == 0
    assert {candidate["candidate_status"] for candidate in suggestions["candidates"]} == {"inventory_only"}


def test_multi_case_package_splits_and_decodes_by_case_id_directory(tmp_path: Path) -> None:
    manifest = _complete_manifest(tmp_path)
    artifacts = build_multi_case_evidence_package(
        manifest=manifest,
        out_root=tmp_path / "packages",
        semantic_junction_ids=["9001", "2001"],
        radius_m=300.0,
        package_id="bundle_001",
        include_files=True,
        materialization_mode="copy_full",
    )

    assert (artifacts.package_dir / "cases" / "9001" / "t10_case_evidence_manifest.json").is_file()
    assert (artifacts.package_dir / "cases" / "2001" / "t10_case_evidence_manifest.json").is_file()

    bundle = export_t10_case_evidence_text_bundle(
        package_dir=artifacts.package_dir,
        out_txt=tmp_path / "bundle" / "t10_bundle.txt",
        max_text_size_bytes=6000,
    )
    assert len(bundle.part_txt_paths) > 1

    decoded = decode_t10_case_evidence_text_bundle(
        bundle_txt=bundle.part_txt_paths[-1],
        out_dir=tmp_path / "decoded",
    )
    decoded_manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))
    assert decoded_manifest["case_count"] == 2
    assert (decoded.out_dir / "cases" / "9001" / "t10_case_evidence_manifest.json").is_file()
    assert (decoded.out_dir / "cases" / "2001" / "t10_case_evidence_summary.json").is_file()


def test_multi_case_package_materializes_spatial_slices_by_case_id(tmp_path: Path) -> None:
    manifest = _complete_vector_manifest(tmp_path)
    artifacts = build_multi_case_evidence_package(
        manifest=manifest,
        out_root=tmp_path / "packages",
        semantic_junction_ids=["9001", "2001"],
        radius_m=100.0,
        package_id="spatial_bundle_001",
        include_files=True,
    )

    case_9001_manifest_path = artifacts.package_dir / "cases" / "9001" / "t10_case_evidence_manifest.json"
    case_9001_manifest = json.loads(case_9001_manifest_path.read_text(encoding="utf-8"))
    case_9001_summary = json.loads(
        (artifacts.package_dir / "cases" / "9001" / "t10_case_evidence_summary.json").read_text(encoding="utf-8")
    )
    assert case_9001_manifest["materialization_mode"] == "spatial_slice"
    assert case_9001_manifest["scope"]["selection_status"] == "spatial_slice_completed"
    assert case_9001_manifest["scope"]["center"] == {"x": 5.0, "y": 0.0}
    assert case_9001_summary["materialized_file_count"] == len(EXTERNAL_INPUT_REQUIREMENTS)

    slot_entries = {entry["slot"]: entry for entry in case_9001_manifest["included_external_inputs"]}
    nodes_slice = artifacts.package_dir / "cases" / "9001" / slot_entries["prepared_swsd_nodes"]["package_path"]
    roads_slice = artifacts.package_dir / "cases" / "9001" / slot_entries["prepared_swsd_roads"]["package_path"]
    assert nodes_slice.name == "prepared_swsd_nodes_slice.gpkg"
    assert roads_slice.name == "prepared_swsd_roads_slice.gpkg"
    assert slot_entries["prepared_swsd_nodes"]["source_sha256"] == ""
    assert slot_entries["prepared_swsd_nodes"]["slice_sha256"]

    node_result = read_vector(nodes_slice, target_epsg=3857)
    road_result = read_vector(roads_slice, target_epsg=3857)
    assert len(node_result.features) == 3
    assert len(road_result.features) == 1
    minx, _miny, maxx, _maxy = road_result.features[0].geometry.bounds
    assert minx == 0.0
    assert maxx == 400.0

    package_summary = case_9001_manifest["spatial_slice_summary"]
    assert package_summary["dependency_audit"]["topology_dependency_complete"] is True
    assert package_summary["dependency_audit"]["swsd_missing_road_endpoint_node_count"] == 0
    assert package_summary["dependency_audit"]["rcsd_missing_road_endpoint_node_count"] == 0

    case_2001_manifest = json.loads(
        (artifacts.package_dir / "cases" / "2001" / "t10_case_evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert case_2001_manifest["scope"]["center"] == {"x": 5000.0, "y": 0.0}


def test_multi_segment_package_uses_t10_run_evidence_and_segment_scope(tmp_path: Path) -> None:
    manifest = _complete_vector_manifest(tmp_path)
    segment_path = _write_segment_gpkg(tmp_path / "t01" / "segment.gpkg")
    run_root = tmp_path / "t10_run"
    problem_csv = (
        run_root
        / "cases"
        / "1885118"
        / "t06_step12"
        / "t06"
        / "step2_extract_rcsd_segments"
        / "t06_segment_replacement_problem_registry.csv"
    )
    problem_csv.parent.mkdir(parents=True)
    problem_csv.write_text(
        "swsd_segment_id,problem_status,reject_reason,swsd_pair_nodes,rcsd_pair_nodes,pair_anchor_bridge_road_ids\n"
        "1001_3001,requires_upstream_iteration,missing_pair_relation,"
        "\"['1001','3001']\",\"['rc1','rc2']\",\"['rcroad_far']\"\n",
        encoding="utf-8",
    )
    (run_root / "t10_t06_visual_check_summary.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "case_id": "1885118",
                        "t01_segment_gpkg": segment_path,
                        "t06_segment_replacement_problem_registry_gpkg": str(problem_csv),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    artifacts = build_multi_segment_evidence_package(
        manifest=manifest,
        out_root=tmp_path / "packages",
        swsd_segment_ids=["1001_3001", "2001_2001"],
        t10_run_root=run_root,
        package_id="segments_001",
        include_files=True,
    )

    multi_manifest = json.loads(artifacts.manifest_json.read_text(encoding="utf-8"))
    assert multi_manifest["segment_buffer_m"] == 200.0
    assert multi_manifest["cases"][0]["case_dir"] == "1001_3001"
    assert not (artifacts.package_dir / "cases").exists()

    case_dir = artifacts.package_dir / "1001_3001"
    case_manifest = json.loads((case_dir / "t10_case_evidence_manifest.json").read_text(encoding="utf-8"))
    case_summary = json.loads((case_dir / "t10_case_evidence_summary.json").read_text(encoding="utf-8"))
    assert case_manifest["package_type"] == "t10_segment_evidence"
    assert case_manifest["scope"]["scope_type"] == "swsd_segment"
    assert case_manifest["scope"]["case_id"] == "segment_1001_3001"
    assert case_manifest["scope"]["swsd_segment_id"] == "1001_3001"
    assert "radius_m" not in case_manifest["scope"]
    assert case_manifest["scope"]["buffer_m"] == 200.0
    assert case_manifest["scope"]["center"] == {"x": 200.0, "y": 0.0}
    assert case_manifest["scope"]["segment_endpoint_node_ids"] == ["1001", "3001"]
    assert case_manifest["spatial_slice_summary"]["selection_mode"] == "swsd_segment_geometry_buffer"
    assert "dependency_context" not in case_manifest["spatial_slice_summary"]
    assert case_summary["segment_buffer_m"] == 200.0
    assert case_summary["matched_evidence_artifact_count"] == 1

    evidence_artifacts = {
        item["role"]: item for item in case_manifest["segment_evidence"]["artifacts"] if item["matched_row_count"]
    }
    assert evidence_artifacts["t06_segment_replacement_problem_registry"]["matched_rows"][0]["reject_reason"] == (
        "missing_pair_relation"
    )

    slot_entries = {entry["slot"]: entry for entry in case_manifest["included_external_inputs"]}
    nodes_slice = case_dir / slot_entries["prepared_swsd_nodes"]["package_path"]
    roads_slice = case_dir / slot_entries["prepared_swsd_roads"]["package_path"]
    rcsd_roads_slice = case_dir / slot_entries["rcsdroad"]["package_path"]
    assert nodes_slice.is_file()
    assert roads_slice.is_file()
    node_ids = {
        str(feature.properties["id"])
        for feature in read_vector(nodes_slice, target_epsg=3857).features
    }
    assert node_ids == {"1001", "1002", "3001"}
    assert len(read_vector(roads_slice, target_epsg=3857).features) == 1
    rcsd_road_ids = {
        str(feature.properties["id"])
        for feature in read_vector(rcsd_roads_slice, target_epsg=3857).features
    }
    assert rcsd_road_ids == {"rcroad_near"}

    bundle = export_t10_case_evidence_text_bundle(
        package_dir=artifacts.package_dir,
        out_txt=tmp_path / "bundle" / "t10_segment_bundle.txt",
        max_text_size_bytes=6000,
    )
    decoded = decode_t10_case_evidence_text_bundle(
        bundle_txt=bundle.part_txt_paths[-1],
        out_dir=tmp_path / "decoded_segments",
    )
    decoded_manifest = json.loads(decoded.manifest_path.read_text(encoding="utf-8"))
    assert decoded_manifest["package_type"] == "t10_segment_evidence"
    assert (decoded.out_dir / "1001_3001" / "t10_case_evidence_manifest.json").is_file()


def test_t10_t06_funnel_summary_reads_step_summaries(tmp_path: Path) -> None:
    t06_root = tmp_path / "t06"
    step1 = t06_root / "step1_identify_fusion_units"
    step2 = t06_root / "step2_extract_rcsd_segments"
    step3 = t06_root / "step3_segment_replacement"
    step1.mkdir(parents=True)
    step2.mkdir(parents=True)
    step3.mkdir(parents=True)
    (step1 / "t06_step1_summary.json").write_text(
        json.dumps(
            {
                "input_segment_count": 10,
                "evd_candidate_count": 6,
                "swsd_candidate_count": 5,
                "final_fusion_unit_count": 4,
                "swsd_final_fusion_unit_count": 4,
                "reject_reason_counts": {"no_evd": 1},
            }
        ),
        encoding="utf-8",
    )
    (step2 / "t06_step2_summary.json").write_text(
        json.dumps(
            {
                "input_fusion_unit_count": 4,
                "rcsd_candidate_count": 3,
                "replaceable_count": 2,
                "rejected_count": 1,
                "buffer_segment_count": 8,
                "buffer_rejected_count": 2,
                "reject_reason_counts": {"no_relation": 1},
                "buffer_reject_reason_counts": {"short_overlap": 2},
            }
        ),
        encoding="utf-8",
    )
    (step3 / "t06_step3_summary.json").write_text(
        json.dumps(
            {
                "input_replaceable_count": 2,
                "replacement_unit_success_count": 2,
                "replacement_unit_failure_count": 0,
                "removed_swsd_road_count": 4,
                "removed_swsd_node_count": 2,
                "added_rcsd_road_count": 6,
                "added_rcsd_node_count": 3,
                "frcsd_road_count": 20,
                "frcsd_node_count": 12,
                "segment_relation_count": 10,
                "road_id_collision_count": 0,
                "node_id_collision_count": 1,
                "segment_relation_failed_count": 0,
            }
        ),
        encoding="utf-8",
    )

    summary = build_t10_t06_funnel_summary(
        case_id="9001",
        t06_run_root=t06_root,
        stage_records=[
            {"stage_id": "t06_step12", "status": "passed"},
            {"stage_id": "t06_step3", "status": "passed"},
        ],
        handoffs={"t06_run_root": str(t06_root)},
    )

    metrics = {(row["stage"], row["metric"]): row["value"] for row in summary["metrics"]}
    assert summary["status"] == "completed"
    assert metrics[("T06 Step1", "input_segment_count")] == 10
    assert metrics[("T06 Step2", "replaceable_count")] == 2
    assert metrics[("T06 Step3", "frcsd_road_count")] == 20
    assert summary["reject_reason_counts"]["step2_buffer"] == {"short_overlap": 2}
    assert summary["replacement_quality"]["node_id_collision_count"] == 1


def test_t10_upstream_feedback_aggregates_problem_registry(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    registry = (
        run_root
        / "cases"
        / "9001"
        / "t06_step12"
        / "t06"
        / "step2_extract_rcsd_segments"
        / "t06_segment_replacement_problem_registry.csv"
    )
    registry.parent.mkdir(parents=True)
    registry_fields = [
        "swsd_segment_id",
        "problem_status",
        "recommended_module",
        "upstream_issue_owner",
        "failure_business_category",
        "reject_reason",
        "root_cause_category",
        "feedback_action",
        "manual_review_required",
        "rcsd_pair_nodes",
        "candidate_rcsd_pair_node_sets",
        "pair_anchor_error_swsd_nodes",
        "pair_anchor_error_original_rcsd_nodes",
        "pair_anchor_error_candidate_rcsd_nodes",
        "pair_anchor_endpoint_cluster_nodes",
        "pair_anchor_bridge_road_ids",
        "pair_anchor_bridge_length_m",
        "pair_anchor_diagnostic_source",
        "pair_anchor_diagnostic_reason",
        "evidence_artifacts",
    ]
    registry_rows = [
        {
            "swsd_segment_id": "n1_s1",
            "problem_status": "requires_upstream_iteration",
            "recommended_module": "T03/T04/T05",
            "upstream_issue_owner": "T05",
            "failure_business_category": "pair_anchor_mismatch",
            "reject_reason": "missing_pair_relation",
            "feedback_action": "rerun",
            "manual_review_required": "true",
            "rcsd_pair_nodes": "[1]",
            "candidate_rcsd_pair_node_sets": "[2]",
            "evidence_artifacts": "audit",
        },
        {
            "swsd_segment_id": "s2",
            "problem_status": "covered_by_replacement_plan",
            "recommended_module": "T06",
            "upstream_issue_owner": "T06",
            "failure_business_category": "geometry_shape_mismatch",
            "reject_reason": "ok",
            "feedback_action": "none",
            "manual_review_required": "false",
            "rcsd_pair_nodes": "[]",
            "candidate_rcsd_pair_node_sets": "[]",
            "evidence_artifacts": "audit",
        },
        {
            "swsd_segment_id": "s3",
            "problem_status": "requires_upstream_iteration",
            "recommended_module": "T03/T04/T05",
            "upstream_issue_owner": "T05",
            "failure_business_category": "pair_anchor_mismatch",
            "reject_reason": "missing_pair_relation",
            "feedback_action": "rerun",
            "manual_review_required": "true",
            "rcsd_pair_nodes": "[3]",
            "candidate_rcsd_pair_node_sets": "[4]",
            "evidence_artifacts": "audit",
        },
        {
            "swsd_segment_id": "s4_s5",
            "problem_status": "requires_upstream_side_group_or_rcsd_directionality_review",
            "recommended_module": "T03/T04/T05_or_RCSD_source_review",
            "upstream_issue_owner": "T03/T04/T05_or_RCSD_directionality_review",
            "failure_business_category": "directionality_mismatch_fixable",
            "reject_reason": "rcsd_not_bidirectional_for_swsd_dual",
            "root_cause_category": "full_rcsd_graph_one_direction_only",
            "feedback_action": "review",
            "manual_review_required": "true",
            "rcsd_pair_nodes": "['5','7']",
            "candidate_rcsd_pair_node_sets": "[['6','8']]",
            "pair_anchor_error_swsd_nodes": "['s5']",
            "pair_anchor_error_original_rcsd_nodes": "['7']",
            "pair_anchor_error_candidate_rcsd_nodes": "['8']",
            "pair_anchor_endpoint_cluster_nodes": "[['5'],['7','8']]",
            "pair_anchor_bridge_road_ids": "['rr_bridge']",
            "pair_anchor_bridge_length_m": "6.5",
            "pair_anchor_diagnostic_source": "buffer_only_endpoint_cluster",
            "pair_anchor_diagnostic_reason": "short_connected_endpoint_cluster",
            "evidence_artifacts": "audit",
        },
    ]
    with registry.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=registry_fields)
        writer.writeheader()
        for row in registry_rows:
            writer.writerow({field: row.get(field, "") for field in registry_fields})
    relation_audit = run_root / "cases" / "9001" / "t05" / "t05_phase2" / "relation_graph_consumability_audit.csv"
    relation_audit.parent.mkdir(parents=True)
    relation_audit.write_text(
        "\n".join(
            [
                "target_id,base_id,relation_status,graph_consumable,graph_consumability_status,matched_rcsdnode_ids,incident_rcsdnode_ids,source_modules,source_case_ids,scenes,reasons,recommended_action",
                "n1,900,0,0,base_id_not_found_in_rcsdnode_out,,,T07,n1,direct_existing_rcsd_junction,existing_rcsdintersection_matched,upstream_relation_or_junctionization_review",
                "n2,901,0,1,base_node_graph_incident,901,901,T07,n2,direct_existing_rcsd_junction,existing_rcsdintersection_matched,consume_as_relation",
            ]
        ),
        encoding="utf-8",
    )

    artifacts = write_t10_upstream_feedback(
        run_root=run_root,
        case_results=[{"case_id": "9001", "case_run_dir": str(run_root / "cases" / "9001")}],
    )

    segments = json.loads(artifacts.segments_json.read_text(encoding="utf-8"))
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    side_group_candidates = json.loads(artifacts.side_group_candidates_json.read_text(encoding="utf-8"))
    side_group_endpoint_candidates = json.loads(artifacts.side_group_endpoint_candidates_json.read_text(encoding="utf-8"))
    pair_anchor_endpoint_clusters = json.loads(
        artifacts.pair_anchor_endpoint_clusters_json.read_text(encoding="utf-8")
    )
    relations = json.loads(artifacts.relations_json.read_text(encoding="utf-8"))
    relation_summary = json.loads(artifacts.relation_summary_json.read_text(encoding="utf-8"))
    assert artifacts.segment_count == 3
    assert artifacts.side_group_candidate_count == 1
    assert artifacts.side_group_endpoint_candidate_count == 2
    assert artifacts.pair_anchor_endpoint_cluster_count == 2
    assert segments["rows"][0]["swsd_segment_id"] == "n1_s1"
    assert segments["rows"][0]["problem_registry_path"] == str(registry)
    side_group_segment = [row for row in segments["rows"] if row["swsd_segment_id"] == "s4_s5"][0]
    assert side_group_segment["pair_anchor_endpoint_cluster_nodes"] == "[['5'],['7','8']]"
    assert side_group_segment["pair_anchor_diagnostic_source"] == "buffer_only_endpoint_cluster"
    assert summary["rows"][0]["recommended_module"] == "T03/T04/T05"
    assert summary["rows"][0]["count"] == 2
    assert any(
        row["problem_status"] == "requires_upstream_side_group_or_rcsd_directionality_review"
        for row in segments["rows"]
    )
    assert side_group_candidates["rows"][0]["swsd_segment_id"] == "s4_s5"
    assert side_group_candidates["rows"][0]["swsd_endpoint_node_ids"] == "s4|s5"
    assert side_group_candidates["rows"][0]["rcsd_primary_pair_node_ids"] == "5|7"
    assert side_group_candidates["rows"][0]["candidate_group_rcsdnode_ids"] == "5|7|6|8"
    assert side_group_candidates["rows"][0]["side_group_action"] == (
        "evaluate_virtual_junction_grouping_before_rcsd_directionality_review"
    )
    endpoint_rows = {row["target_id"]: row for row in side_group_endpoint_candidates["rows"]}
    assert endpoint_rows["s4"]["candidate_rcsdnode_ids"] == "5|6"
    assert endpoint_rows["s5"]["candidate_rcsdnode_ids"] == "7|8"
    assert endpoint_rows["s4"]["side_group_action"] == "supplement_existing_relation_with_endpoint_rcsdnode_grouping"
    cluster_rows = {row["target_id"]: row for row in pair_anchor_endpoint_clusters["rows"]}
    assert cluster_rows["s4"]["endpoint_cluster_rcsdnode_ids"] == "5"
    assert cluster_rows["s5"]["endpoint_cluster_rcsdnode_ids"] == "7|8"
    assert cluster_rows["s5"]["candidate_rcsdnode_ids_from_pair_sets"] == "8"
    assert cluster_rows["s5"]["pair_anchor_bridge_road_ids"] == "['rr_bridge']"
    assert cluster_rows["s5"]["pair_anchor_diagnostic_source"] == "buffer_only_endpoint_cluster"
    assert cluster_rows["s5"]["auto_consumable_by_t05"] == "false"
    assert artifacts.relation_count == 1
    assert relations["rows"][0]["target_id"] == "n1"
    assert relations["rows"][0]["recommended_module"] == "T05|T07"
    assert relations["rows"][0]["affected_problem_segment_count"] == "1"
    assert relations["rows"][0]["affected_problem_segment_ids"] == "n1_s1"
    assert relations["rows"][0]["relation_graph_consumability_audit_path"] == str(relation_audit)
    assert relation_summary["rows"][0]["failure_business_category"] == "relation_graph_unconsumable"
    assert relation_summary["rows"][0]["count"] == 1
    assert summary["qa"]["topology_consistency"] == "No topology mutation or silent repair is performed."


def test_t10_upstream_feedback_endpoint_candidates_exclude_unstable_required_node_failures(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    registry = (
        run_root
        / "cases"
        / "9001"
        / "t06_step12"
        / "t06"
        / "step2_extract_rcsd_segments"
        / "t06_segment_replacement_problem_registry.csv"
    )
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "\n".join(
            [
                "swsd_segment_id,problem_status,recommended_module,upstream_issue_owner,"
                "failure_business_category,reject_reason,root_cause_category,feedback_action,"
                "manual_review_required,swsd_pair_nodes,rcsd_pair_nodes,candidate_rcsd_pair_node_sets,"
                "evidence_artifacts",
                "s1_s2,requires_upstream_iteration,T03/T04/T05,T05,"
                "multi_anchor_ambiguous,required_semantic_nodes_not_connected_in_buffer,"
                "buffer_candidate_required_nodes_disconnected,rerun,true,"
                "\"['s1','s2']\",\"['100','200']\",\"[['101','201'],['102','202']]\",audit",
            ]
        ),
        encoding="utf-8",
    )

    artifacts = write_t10_upstream_feedback(
        run_root=run_root,
        case_results=[{"case_id": "9001", "case_run_dir": str(run_root / "cases" / "9001")}],
    )

    endpoint_rows = json.loads(artifacts.side_group_endpoint_candidates_json.read_text(encoding="utf-8"))["rows"]
    assert artifacts.side_group_endpoint_candidate_count == 0
    assert endpoint_rows == []


def test_t10_pair_anchor_endpoint_cluster_marks_safe_rows_consumable_by_t05(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    registry = (
        run_root
        / "cases"
        / "9001"
        / "t06_step12"
        / "t06"
        / "step2_extract_rcsd_segments"
        / "t06_segment_replacement_problem_registry.csv"
    )
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "\n".join(
            [
                "swsd_segment_id,problem_status,recommended_module,upstream_issue_owner,"
                "failure_business_category,reject_reason,root_cause_category,feedback_action,"
                "manual_review_required,swsd_pair_nodes,rcsd_pair_nodes,candidate_rcsd_pair_node_sets,"
                "pair_anchor_endpoint_cluster_nodes,pair_anchor_bridge_road_ids,pair_anchor_bridge_length_m,"
                "pair_anchor_diagnostic_source,pair_anchor_diagnostic_reason,evidence_artifacts",
                "s6_s7,requires_upstream_iteration,T03/T04/T05,T05,"
                "pair_anchor_mismatch,rcsd_pair_nodes_not_distinct,,rerun,true,"
                "\"['s6','s7']\",\"['60','70']\",\"[['60','71']]\","
                "\"[['60'],['70','71']]\",['rr_bridge'],12.5,"
                "buffer_only_endpoint_cluster,short_connected_endpoint_cluster,audit",
            ]
        ),
        encoding="utf-8",
    )

    artifacts = write_t10_upstream_feedback(
        run_root=run_root,
        case_results=[{"case_id": "9001", "case_run_dir": str(run_root / "cases" / "9001")}],
    )

    cluster_rows = {
        row["target_id"]: row
        for row in json.loads(artifacts.pair_anchor_endpoint_clusters_json.read_text(encoding="utf-8"))["rows"]
    }
    assert cluster_rows["s6"]["auto_consumable_by_t05"] == "false"
    assert cluster_rows["s7"]["auto_consumable_by_t05"] == "true"
    assert cluster_rows["s7"]["pair_anchor_cluster_action"] == (
        "supplement_existing_relation_with_pair_anchor_endpoint_cluster"
    )


def test_t10_side_group_endpoint_candidates_exclude_opposite_primary_anchor(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    registry = (
        run_root
        / "cases"
        / "9001"
        / "t06_step12"
        / "t06"
        / "step2_extract_rcsd_segments"
        / "t06_segment_replacement_problem_registry.csv"
    )
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "\n".join(
            [
                "swsd_segment_id,problem_status,recommended_module,upstream_issue_owner,"
                "failure_business_category,reject_reason,root_cause_category,feedback_action,"
                "manual_review_required,swsd_pair_nodes,rcsd_pair_nodes,candidate_rcsd_pair_node_sets,"
                "evidence_artifacts",
                "s1_s2,requires_upstream_side_group_or_rcsd_directionality_review,T03/T04/T05,T05,"
                "directionality_mismatch_fixable,rcsd_not_bidirectional_for_swsd_dual,"
                "full_rcsd_graph_one_direction_only,review,true,"
                "\"['s1','s2']\",\"['p1','p2']\",\"[['x1','p1']]\",audit",
            ]
        ),
        encoding="utf-8",
    )

    artifacts = write_t10_upstream_feedback(
        run_root=run_root,
        case_results=[{"case_id": "9001", "case_run_dir": str(run_root / "cases" / "9001")}],
    )

    side_group_rows = json.loads(artifacts.side_group_candidates_json.read_text(encoding="utf-8"))["rows"]
    endpoint_rows = json.loads(artifacts.side_group_endpoint_candidates_json.read_text(encoding="utf-8"))["rows"]

    assert artifacts.side_group_candidate_count == 1
    assert artifacts.side_group_endpoint_candidate_count == 1
    assert side_group_rows[0]["candidate_group_rcsdnode_ids"] == "p1|p2|x1"
    assert endpoint_rows[0]["target_id"] == "s1"
    assert endpoint_rows[0]["candidate_rcsdnode_ids"] == "p1|x1"


def test_t10_relation_graph_bridge_candidate_extends_existing_side_group(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    case_run_dir = run_root / "cases" / "9001"
    registry = (
        case_run_dir
        / "t06_step12"
        / "t06"
        / "step2_extract_rcsd_segments"
        / "t06_segment_replacement_problem_registry.csv"
    )
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "\n".join(
            [
                "swsd_segment_id,problem_status,recommended_module,upstream_issue_owner,"
                "failure_business_category,reject_reason,root_cause_category,feedback_action,"
                "manual_review_required,swsd_pair_nodes,rcsd_pair_nodes,candidate_rcsd_pair_node_sets,"
                "evidence_artifacts",
                "s1_s2,requires_upstream_side_group_or_rcsd_directionality_review,T03/T04/T05,T05,"
                "directionality_mismatch_fixable,rcsd_not_bidirectional_for_swsd_dual,"
                "full_rcsd_graph_one_direction_only,review,true,"
                "\"['s1','s2']\",\"['p1','p2']\",\"[['p1','p2']]\",audit",
            ]
        ),
        encoding="utf-8",
    )
    probe = registry.parent / "t06_rcsd_buffer_only_probe.csv"
    probe.write_text(
        "\n".join(
            [
                "swsd_segment_id,probe_status,buffer_only_candidate_status,failure_business_category,"
                "original_rcsd_pair_nodes,candidate_rcsd_node_ids",
                "s1_s2,completed,corridor_found,directionality_mismatch_fixable,"
                "\"['p1','p2']\",\"['p1','p2','bridge','noise']\"",
            ]
        ),
        encoding="utf-8",
    )

    t05_dir = case_run_dir / "t05" / "t05_phase2"
    t05_dir.mkdir(parents=True)
    (t05_dir / "relation_graph_consumability_audit.csv").write_text(
        "\n".join(
            [
                "target_id,base_id,relation_status,graph_consumable,graph_consumability_status,"
                "matched_rcsdnode_ids,incident_rcsdnode_ids,source_modules,source_case_ids,scenes,reasons,"
                "recommended_action",
                "s1,p1,0,1,base_node_graph_incident,p1,p1,T07,s1,direct,matched,consume_as_relation",
                "s2,p2,0,1,base_node_graph_incident,p2,p2,T07,s2,direct,matched,consume_as_relation",
                "side,bridge,0,1,base_node_graph_incident,bridge,bridge,T07,side,direct,matched,consume_as_relation",
                "mid,mid_base,0,1,base_node_group_graph_incident,"
                "mid_group|mid_context|mid_base,mid_group|mid_context,T07|T10_SIDE_GROUP,"
                "mid|9001,direct,multiple_base_id_merged,consume_as_relation",
            ]
        ),
        encoding="utf-8",
    )
    (t05_dir / "rcsd_junctionization_audit.csv").write_text(
        "\n".join(
            [
                "target_id,surface_id,source_module,source_case_id,scene,action,status,base_id,reason,"
                "original_rcsdroad_ids,new_rcsdroad_ids,original_rcsdnode_ids,new_rcsdnode_ids,"
                "grouped_rcsdnode_ids,selected_main_rcsdnode_id,projection_point_count,split_point_count,"
                "skipped_reason,geometry_mode,multi_base_relation,blocking_error",
                "mid,JAS:mid,T07|T10_SIDE_GROUP,mid|9001,direct,group_existing_rcsd_nodes,0,"
                "mid_base,multiple_base_id_merged,,,mid_group|mid_base,,mid_group|mid_base,"
                "mid_base,0,0,,success_line,1,0",
            ]
        ),
        encoding="utf-8",
    )
    write_gpkg(
        t05_dir / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "r1", "snodeid": "p2", "enodeid": "bridge"}, "geometry": LineString([(0, 0), (1, 0)])},
            {"properties": {"id": "r2", "snodeid": "bridge", "enodeid": "x1"}, "geometry": LineString([(1, 0), (2, 0)])},
            {"properties": {"id": "r3", "snodeid": "x1", "enodeid": "x2"}, "geometry": LineString([(2, 0), (3, 0)])},
            {"properties": {"id": "r4", "snodeid": "x2", "enodeid": "mid_context"}, "geometry": LineString([(3, 0), (4, 0)])},
            {"properties": {"id": "r5", "snodeid": "p2", "enodeid": "noise"}, "geometry": LineString([(0, 1), (1, 1)])},
        ],
        crs_text="EPSG:3857",
        layer_name="rcsdroad_out",
    )

    artifacts = write_t10_upstream_feedback(
        run_root=run_root,
        case_results=[{"case_id": "9001", "case_run_dir": str(case_run_dir)}],
    )

    endpoint_rows = json.loads(artifacts.side_group_endpoint_candidates_json.read_text(encoding="utf-8"))["rows"]
    assert artifacts.side_group_endpoint_candidate_count == 1
    assert endpoint_rows[0]["swsd_segment_id"] == "s1_s2"
    assert endpoint_rows[0]["target_id"] == "mid"
    assert endpoint_rows[0]["endpoint_index"] == "1"
    assert endpoint_rows[0]["rcsd_primary_node_id"] == "mid_base"
    assert endpoint_rows[0]["candidate_rcsdnode_ids"] == "mid_base|bridge"
    assert endpoint_rows[0]["side_group_action"] == "supplement_existing_relation_with_relation_graph_bridge"


def test_t10_upstream_feedback_excludes_side_group_without_new_rcsd_nodes(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    registry = (
        run_root
        / "cases"
        / "9001"
        / "t06_step12"
        / "t06"
        / "step2_extract_rcsd_segments"
        / "t06_segment_replacement_problem_registry.csv"
    )
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "\n".join(
            [
                "swsd_segment_id,problem_status,recommended_module,upstream_issue_owner,"
                "failure_business_category,reject_reason,root_cause_category,feedback_action,"
                "manual_review_required,swsd_pair_nodes,rcsd_pair_nodes,candidate_rcsd_pair_node_sets,"
                "evidence_artifacts",
                "s1_s2,requires_upstream_side_group_or_rcsd_directionality_review,T03/T04/T05,T05,"
                "directionality_mismatch_fixable,rcsd_not_bidirectional_for_swsd_dual,"
                "full_rcsd_graph_one_direction_only,review,true,"
                "\"['s1','s2']\",\"['100','200']\",\"[['100','200']]\",audit",
                "s3_s4,requires_upstream_side_group_or_rcsd_directionality_review,T03/T04/T05,T05,"
                "directionality_mismatch_fixable,rcsd_not_bidirectional_for_swsd_dual,"
                "full_rcsd_graph_one_direction_only,review,true,"
                "\"['s3','s4']\",\"['300','400']\",\"[['300','401']]\",audit",
            ]
        ),
        encoding="utf-8",
    )

    artifacts = write_t10_upstream_feedback(
        run_root=run_root,
        case_results=[{"case_id": "9001", "case_run_dir": str(run_root / "cases" / "9001")}],
    )

    segments = json.loads(artifacts.segments_json.read_text(encoding="utf-8"))["rows"]
    side_group_rows = json.loads(artifacts.side_group_candidates_json.read_text(encoding="utf-8"))["rows"]
    endpoint_rows = json.loads(artifacts.side_group_endpoint_candidates_json.read_text(encoding="utf-8"))["rows"]

    assert {row["swsd_segment_id"] for row in segments} == {"s1_s2", "s3_s4"}
    assert artifacts.side_group_candidate_count == 1
    assert artifacts.side_group_endpoint_candidate_count == 1
    assert side_group_rows[0]["swsd_segment_id"] == "s3_s4"
    assert {row["target_id"] for row in endpoint_rows} == {"s4"}
    assert {row["swsd_segment_id"] for row in endpoint_rows} == {"s3_s4"}


def test_t10_case_runner_blocks_downstream_after_failed_stage(tmp_path: Path, monkeypatch) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "cases" / "9001"
    case_dir.mkdir(parents=True)
    (case_dir / "t10_case_evidence_manifest.json").write_text(
        json.dumps({"scope": {"case_id": "9001"}, "included_external_inputs": []}),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_run_stage(**kwargs):
        stage_id = kwargs["stage_id"]
        calls.append(stage_id)
        assert stage_id == "t01"
        return (
            {
                "stage_id": "t01",
                "stage": "t01",
                "module_id": "t01_data_preprocess",
                "status": "failed",
                "outputs": {"t01_roads": str(tmp_path / "partial_roads.gpkg")},
            },
            {"t01_roads": str(tmp_path / "partial_roads.gpkg")},
        )

    monkeypatch.setattr(t10_case_runner, "_run_stage", fake_run_stage)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="run_001",
        stop_after="t03",
        continue_on_error=True,
        exit_on_incomplete=True,
    )

    case_summary_path = artifacts.run_root / "cases" / "9001" / "t10_e2e_case_run_summary.json"
    case_summary = json.loads(case_summary_path.read_text(encoding="utf-8"))
    t07_stage = json.loads((artifacts.run_root / "cases" / "9001" / "t07" / "t07_stage.json").read_text(encoding="utf-8"))

    assert calls == ["t01"]
    assert case_summary["overall_status"] == "failed"
    assert case_summary["stage_statuses"] == {"t01": "failed", "t07": "blocked", "t03": "blocked"}
    assert t07_stage["stage"] == "t07"
    assert t07_stage["blocked_reason"] == "Previous stage did not produce required handoff."


def test_t10_case_runner_discovers_flat_multi_case_package(tmp_path: Path) -> None:
    package_dir = tmp_path / "flat_package"
    for case_id in ("9001", "2001"):
        case_dir = package_dir / case_id
        case_dir.mkdir(parents=True)
        (case_dir / "t10_case_evidence_manifest.json").write_text(
            json.dumps({"scope": {"case_id": case_id}, "included_external_inputs": []}),
            encoding="utf-8",
        )
    (package_dir / "_source_bundles").mkdir()

    case_dirs = t10_case_runner._discover_case_dirs(package_root=package_dir, case_ids=None)
    selected_case_dirs = t10_case_runner._discover_case_dirs(package_root=package_dir, case_ids=["9001"])

    assert [path.name for path in case_dirs] == ["2001", "9001"]
    assert [path.name for path in selected_case_dirs] == ["9001"]


def test_t10_feedback_iteration_passes_endpoint_candidates_and_keeps_no_regression_guard(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "cases" / "9001"
    case_dir.mkdir(parents=True)
    (case_dir / "t10_case_evidence_manifest.json").write_text(
        json.dumps({"scope": {"case_id": "9001"}, "included_external_inputs": []}),
        encoding="utf-8",
    )
    calls: list[Path | None] = []

    def fake_run_one_case(**kwargs):
        run_root = kwargs["run_root"]
        side_group_endpoint_candidate_path = kwargs.get("side_group_endpoint_candidate_path")
        calls.append(side_group_endpoint_candidate_path)
        case_run_dir = run_root / "cases" / "9001"
        _write_feedback_iteration_case_outputs(
            case_run_dir,
            replaced_segments=["old_segment", "new_segment"] if side_group_endpoint_candidate_path else ["old_segment"],
            emit_side_group_problem=side_group_endpoint_candidate_path is None,
        )
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="feedback_run",
        feedback_iterations=1,
        continue_on_error=False,
        exit_on_incomplete=True,
    )

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    comparison = summary["feedback_comparison"]
    assert calls[0] is None
    assert calls[1] is not None
    assert calls[1].name == "t10_upstream_side_group_endpoint_candidates.csv"
    assert summary["passed"] is True
    assert summary["feedback_regression_guard_passed"] is True
    assert comparison["removed_replaced_segment_ids"] == []
    assert comparison["added_replaced_segment_ids"] == ["new_segment"]
    assert summary["feedback_iteration_completed_count"] == 1


def test_t10_feedback_iteration_stops_when_endpoint_candidates_converge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "cases" / "9001"
    case_dir.mkdir(parents=True)
    (case_dir / "t10_case_evidence_manifest.json").write_text(
        json.dumps({"scope": {"case_id": "9001"}, "included_external_inputs": []}),
        encoding="utf-8",
    )
    calls: list[Path | None] = []

    def fake_run_one_case(**kwargs):
        run_root = kwargs["run_root"]
        side_group_endpoint_candidate_path = kwargs.get("side_group_endpoint_candidate_path")
        calls.append(side_group_endpoint_candidate_path)
        case_run_dir = run_root / "cases" / "9001"
        _write_feedback_iteration_case_outputs(
            case_run_dir,
            replaced_segments=["kept_segment"],
            emit_side_group_problem=True,
        )
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="feedback_run",
        feedback_iterations=2,
        continue_on_error=False,
        exit_on_incomplete=True,
    )

    manifest = json.loads(artifacts.manifest_json.read_text(encoding="utf-8"))
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))

    assert len(calls) == 2
    assert calls[0] is None
    assert calls[1] is not None
    assert summary["feedback_iteration_pass_count"] == 2
    assert summary["feedback_iteration_completed_count"] == 1
    assert manifest["final_iteration"]["feedback_stop_reason"] == "feedback_candidates_converged"


def test_t10_feedback_iteration_accumulates_endpoint_candidates_across_passes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "cases" / "9001"
    case_dir.mkdir(parents=True)
    (case_dir / "t10_case_evidence_manifest.json").write_text(
        json.dumps({"scope": {"case_id": "9001"}, "included_external_inputs": []}),
        encoding="utf-8",
    )
    calls: list[Path | None] = []

    def fake_run_one_case(**kwargs):
        run_root = kwargs["run_root"]
        side_group_endpoint_candidate_path = kwargs.get("side_group_endpoint_candidate_path")
        calls.append(side_group_endpoint_candidate_path)
        case_run_dir = run_root / "cases" / "9001"
        if len(calls) == 1:
            _write_feedback_iteration_case_outputs(
                case_run_dir,
                replaced_segments=["kept_segment"],
                emit_side_group_problem=True,
                side_group_segment_id="a1_a2",
                side_group_candidate_pair="101|201",
            )
        elif len(calls) == 2:
            _write_feedback_iteration_case_outputs(
                case_run_dir,
                replaced_segments=["kept_segment", "first_feedback_segment"],
                emit_side_group_problem=True,
                side_group_segment_id="b1_b2",
                side_group_candidate_pair="301|401",
            )
        else:
            _write_feedback_iteration_case_outputs(
                case_run_dir,
                replaced_segments=["kept_segment", "first_feedback_segment", "second_feedback_segment"],
                emit_side_group_problem=False,
            )
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="feedback_run",
        feedback_iterations=2,
        continue_on_error=False,
        exit_on_incomplete=True,
    )

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert len(calls) == 3
    assert calls[0] is None
    assert calls[1] is not None
    assert calls[2] is not None
    cumulative_rows = list(csv.DictReader(calls[2].open(newline="", encoding="utf-8")))
    assert {row["swsd_segment_id"] for row in cumulative_rows} == {"a1_a2", "b1_b2"}
    assert summary["feedback_comparison"]["added_replaced_segment_ids"] == [
        "first_feedback_segment",
        "second_feedback_segment",
    ]
    assert summary["feedback_regression_guard_passed"] is True


def test_t10_feedback_iteration_passes_pair_anchor_endpoint_clusters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "cases" / "9001"
    case_dir.mkdir(parents=True)
    (case_dir / "t10_case_evidence_manifest.json").write_text(
        json.dumps({"scope": {"case_id": "9001"}, "included_external_inputs": []}),
        encoding="utf-8",
    )
    calls: list[Path | None] = []

    def fake_run_one_case(**kwargs):
        run_root = kwargs["run_root"]
        pair_anchor_endpoint_cluster_path = kwargs.get("pair_anchor_endpoint_cluster_path")
        calls.append(pair_anchor_endpoint_cluster_path)
        case_run_dir = run_root / "cases" / "9001"
        _write_feedback_iteration_case_outputs(
            case_run_dir,
            replaced_segments=["old_segment", "pair_anchor_feedback_segment"]
            if pair_anchor_endpoint_cluster_path
            else ["old_segment"],
            emit_side_group_problem=False,
            emit_pair_anchor_problem=pair_anchor_endpoint_cluster_path is None,
        )
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="feedback_run",
        feedback_iterations=1,
        continue_on_error=False,
        exit_on_incomplete=True,
    )

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert calls[0] is None
    assert calls[1] is not None
    assert calls[1].name == "iteration_00_auto_pair_anchor_endpoint_clusters.csv"
    assert summary["feedback_comparison"]["added_replaced_segment_ids"] == ["pair_anchor_feedback_segment"]
    assert summary["feedback_regression_guard_passed"] is True


def test_t10_feedback_regression_guard_detects_removed_replaced_segment(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    _write_feedback_iteration_case_outputs(
        baseline / "cases" / "9001",
        replaced_segments=["kept_segment", "removed_segment"],
        emit_side_group_problem=False,
    )
    _write_feedback_iteration_case_outputs(
        final / "cases" / "9001",
        replaced_segments=["kept_segment"],
        emit_side_group_problem=False,
    )

    comparison = t10_case_runner._compare_feedback_iteration_outputs(
        baseline_run_root=baseline,
        final_run_root=final,
    )

    assert comparison["removed_replaced_segment_ids"] == ["removed_segment"]
    assert comparison["added_replaced_segment_ids"] == []


def test_t10_case_runner_summary_exposes_completion_status(tmp_path: Path, monkeypatch) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "9001"
    case_dir.mkdir(parents=True)

    def fake_discover_case_dirs(*, package_root, case_ids):
        return [case_dir]

    def fake_run_one_case(**kwargs):
        case_run_dir = kwargs["run_root"] / "cases" / "9001"
        case_run_dir.mkdir(parents=True)
        (case_run_dir / "t10_e2e_case_run_manifest.json").write_text("{}", encoding="utf-8")
        (case_run_dir / "t10_t06_funnel.json").write_text("{}", encoding="utf-8")
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {"t09_step3": "passed"},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    def fake_write_upstream_feedback(*, run_root, case_results):
        for name in [
            "segments",
            "summary",
            "relations",
            "relation_summary",
            "side_group_candidates",
            "side_group_endpoint_candidates",
            "pair_anchor_endpoint_clusters",
        ]:
            (run_root / f"{name}.csv").write_text("", encoding="utf-8")
            (run_root / f"{name}.json").write_text("[]", encoding="utf-8")
        return SimpleNamespace(
            segments_csv=run_root / "segments.csv",
            segments_json=run_root / "segments.json",
            summary_csv=run_root / "summary.csv",
            summary_json=run_root / "summary.json",
            relations_csv=run_root / "relations.csv",
            relations_json=run_root / "relations.json",
            relation_summary_csv=run_root / "relation_summary.csv",
            relation_summary_json=run_root / "relation_summary.json",
            side_group_candidates_csv=run_root / "side_group_candidates.csv",
            side_group_candidates_json=run_root / "side_group_candidates.json",
            side_group_endpoint_candidates_csv=run_root / "side_group_endpoint_candidates.csv",
            side_group_endpoint_candidates_json=run_root / "side_group_endpoint_candidates.json",
            pair_anchor_endpoint_clusters_csv=run_root / "pair_anchor_endpoint_clusters.csv",
            pair_anchor_endpoint_clusters_json=run_root / "pair_anchor_endpoint_clusters.json",
            segment_count=0,
            summary_count=0,
            relation_count=0,
            relation_summary_count=0,
            side_group_candidate_count=0,
            side_group_endpoint_candidate_count=0,
            pair_anchor_endpoint_cluster_count=0,
        )

    monkeypatch.setattr(t10_case_runner, "_discover_case_dirs", fake_discover_case_dirs)
    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)
    monkeypatch.setattr(t10_case_runner, "write_t10_upstream_feedback", fake_write_upstream_feedback)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="status_run",
    )

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    manifest = json.loads(artifacts.manifest_json.read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert summary["passed"] is True
    assert summary["completed_case_count"] == 1
    assert summary["duration_seconds"] >= 0
    assert manifest["status"] == "passed"
    assert manifest["passed"] is True


def test_t10_case_runner_writes_t06_visual_check_summary(tmp_path: Path, monkeypatch) -> None:
    package_dir = tmp_path / "package"
    case_dir = package_dir / "9001"
    case_dir.mkdir(parents=True)

    def fake_discover_case_dirs(*, package_root, case_ids):
        return [case_dir]

    def fake_run_one_case(**kwargs):
        case_run_dir = kwargs["run_root"] / "cases" / "9001"
        step2 = case_run_dir / "t06_step12" / "t06" / "step2_extract_rcsd_segments"
        step3 = case_run_dir / "t06_step12" / "t06" / "step3_segment_replacement"
        t07 = case_run_dir / "t07" / "t07" / "step2_anchor_recognition"
        t03 = case_run_dir / "t03" / "t03"
        t04 = case_run_dir / "t04" / "t04"
        t05 = case_run_dir / "t05" / "t05_phase1"
        for path in [case_run_dir / "t01", step2, step3, t07, t03, t04, t05]:
            path.mkdir(parents=True, exist_ok=True)
        write_gpkg(
            case_run_dir / "t01" / "segment.gpkg",
            [{"properties": {"id": "s1_s2"}, "geometry": LineString([(0, 0), (10, 0)])}],
            crs_text="EPSG:3857",
            layer_name="segment",
        )
        write_gpkg(
            case_run_dir / "t01" / "roads.gpkg",
            [{"properties": {"id": "sw1", "snodeid": "s1", "enodeid": "s2"}, "geometry": LineString([(0, 0), (10, 0)])}],
            crs_text="EPSG:3857",
            layer_name="roads",
        )
        write_gpkg(
            t07 / "nodes.gpkg",
            [
                {"properties": {"id": "s1"}, "geometry": Point(0, 0)},
                {"properties": {"id": "s2"}, "geometry": Point(10, 0)},
            ],
            crs_text="EPSG:3857",
            layer_name="nodes",
        )
        for path in [
            t07 / "t07_rcsdintersection_anchor_surface.gpkg",
            t03 / "virtual_intersection_polygons.gpkg",
            t04 / "divmerge_virtual_anchor_surface.gpkg",
            t04 / "divmerge_virtual_anchor_surface_audit.gpkg",
            t05 / "junction_anchor_surface.gpkg",
        ]:
            write_gpkg(
                path,
                [{"properties": {"id": "surface1"}, "geometry": LineString([(0, 0), (10, 0)])}],
                crs_text="EPSG:3857",
                layer_name=path.stem,
            )
        for name in [
            "t06_rcsd_segment_replaceable.gpkg",
            "t06_segment_replacement_plan.gpkg",
            "t06_segment_replacement_problem_registry.gpkg",
        ]:
            write_gpkg(
                step2 / name,
                [{"properties": {"swsd_segment_id": "s1_s2"}, "geometry": LineString([(0, 0), (10, 0)])}],
                crs_text="EPSG:3857",
                layer_name=Path(name).stem,
            )
        write_gpkg(
            step3 / "t06_frcsd_road.gpkg",
            [
                {
                    "properties": {"id": "rc_right", "snodeid": "r1", "enodeid": "r2", "source": 1, "formway": 128},
                    "geometry": LineString([(0, 0), (10, 0)]),
                },
                {
                    "properties": {"id": "sw_right", "snodeid": "s1", "enodeid": "s2", "source": 2, "formway": 128},
                    "geometry": LineString([(0, 0), (10, 0)]),
                },
            ],
            crs_text="EPSG:3857",
            layer_name="t06_frcsd_road",
        )
        write_gpkg(
            step3 / "t06_frcsd_node.gpkg",
            [
                {"properties": {"id": "r1"}, "geometry": Point(0, 0)},
                {"properties": {"id": "r2"}, "geometry": Point(10, 0)},
                {"properties": {"id": "s1"}, "geometry": Point(0, 0)},
                {"properties": {"id": "s2"}, "geometry": Point(10, 0)},
            ],
            crs_text="EPSG:3857",
            layer_name="t06_frcsd_node",
        )
        write_gpkg(
            step3 / "t06_step3_swsd_frcsd_segment_relation.gpkg",
            [{"properties": {"swsd_segment_id": "s1_s2", "relation_status": "replaced"}, "geometry": LineString([(0, 0), (10, 0)])}],
            crs_text="EPSG:3857",
            layer_name="t06_step3_swsd_frcsd_segment_relation",
        )
        for path in [
            step3 / "t06_step3_topology_connectivity_audit.gpkg",
            step3 / "t06_step3_surface_topology_audit.gpkg",
        ]:
            write_gpkg(
                path,
                [{"properties": {"audit_status": "pass"}, "geometry": LineString([(0, 0), (10, 0)])}],
                crs_text="EPSG:3857",
                layer_name=path.stem,
            )
        (step2 / "t06_step2_summary.json").write_text(
            json.dumps(
                {
                    "replaceable_count": 1,
                    "replacement_plan_count": 1,
                    "replacement_plan_ready_count": 1,
                    "problem_registry_count": 0,
                    "rejected_count": 0,
                }
            ),
            encoding="utf-8",
        )
        (step3 / "t06_step3_summary.json").write_text(
            json.dumps(
                {
                    "replacement_unit_success_count": 1,
                    "replacement_unit_failure_count": 0,
                    "removed_swsd_road_count": 1,
                    "added_rcsd_road_count": 1,
                    "frcsd_road_count": 2,
                    "frcsd_node_count": 4,
                }
            ),
            encoding="utf-8",
        )
        (case_run_dir / "t10_e2e_case_run_manifest.json").write_text("{}", encoding="utf-8")
        (case_run_dir / "t10_t06_funnel.json").write_text("{}", encoding="utf-8")
        return {
            "case_id": "9001",
            "case_dir": str(case_dir),
            "case_run_dir": str(case_run_dir),
            "case_run_manifest_path": str(case_run_dir / "t10_e2e_case_run_manifest.json"),
            "case_run_summary_path": str(case_run_dir / "t10_e2e_case_run_summary.json"),
            "overall_status": "passed",
            "stage_statuses": {"t06_step3": "passed"},
            "t06_funnel_json": str(case_run_dir / "t10_t06_funnel.json"),
        }

    def fake_write_upstream_feedback(*, run_root, case_results):
        for name in [
            "segments",
            "summary",
            "relations",
            "relation_summary",
            "side_group_candidates",
            "side_group_endpoint_candidates",
            "pair_anchor_endpoint_clusters",
        ]:
            (run_root / f"{name}.csv").write_text("", encoding="utf-8")
            (run_root / f"{name}.json").write_text("[]", encoding="utf-8")
        return SimpleNamespace(
            segments_csv=run_root / "segments.csv",
            segments_json=run_root / "segments.json",
            summary_csv=run_root / "summary.csv",
            summary_json=run_root / "summary.json",
            relations_csv=run_root / "relations.csv",
            relations_json=run_root / "relations.json",
            relation_summary_csv=run_root / "relation_summary.csv",
            relation_summary_json=run_root / "relation_summary.json",
            side_group_candidates_csv=run_root / "side_group_candidates.csv",
            side_group_candidates_json=run_root / "side_group_candidates.json",
            side_group_endpoint_candidates_csv=run_root / "side_group_endpoint_candidates.csv",
            side_group_endpoint_candidates_json=run_root / "side_group_endpoint_candidates.json",
            pair_anchor_endpoint_clusters_csv=run_root / "pair_anchor_endpoint_clusters.csv",
            pair_anchor_endpoint_clusters_json=run_root / "pair_anchor_endpoint_clusters.json",
            segment_count=0,
            summary_count=0,
            relation_count=0,
            relation_summary_count=0,
            side_group_candidate_count=0,
            side_group_endpoint_candidate_count=0,
            pair_anchor_endpoint_cluster_count=0,
        )

    monkeypatch.setattr(t10_case_runner, "_discover_case_dirs", fake_discover_case_dirs)
    monkeypatch.setattr(t10_case_runner, "_run_one_case", fake_run_one_case)
    monkeypatch.setattr(t10_case_runner, "write_t10_upstream_feedback", fake_write_upstream_feedback)

    artifacts = t10_case_runner.run_t10_e2e_cases_from_package(
        package_dir=package_dir,
        out_root=tmp_path / "runs",
        run_id="visual_check_run",
    )

    run_summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    visual_summary = json.loads(artifacts.t06_visual_check_summary_json.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(artifacts.t06_visual_check_summary_csv.open(newline="", encoding="utf-8")))
    row = rows[0]

    assert Path(run_summary["t06_visual_check_summary_json"]).is_file()
    assert visual_summary["case_count"] == 1
    assert row["case_id"] == "9001"
    assert row["crs_status"] == "passed"
    assert row["missing_visual_layer_count"] == "0"
    assert row["advance_right_count"] == "2"
    assert row["advance_right_rcsd_count"] == "1"
    assert row["advance_right_swsd_count"] == "1"
    assert row["swsd_advance_duplicate_ge20pct_count"] == "1"
    assert row["advance_endpoint_missing_road_count"] == "0"
    assert row["spatial_check_status"] == "passed"


def test_t10_t06_visual_check_tolerates_geometryless_plan_rows(tmp_path: Path) -> None:
    import fiona

    road = tmp_path / "t06_frcsd_road.gpkg"
    node = tmp_path / "t06_frcsd_node.gpkg"
    plan = tmp_path / "t06_segment_replacement_plan.gpkg"
    write_gpkg(
        road,
        [{"properties": {"id": "r1", "snodeid": "n1", "enodeid": "n2", "source": 1, "formway": 128}, "geometry": LineString([(0, 0), (1, 0)])}],
        crs_text="EPSG:3857",
        layer_name="t06_frcsd_road",
    )
    write_gpkg(
        node,
        [
            {"properties": {"id": "n1"}, "geometry": Point(0, 0)},
            {"properties": {"id": "n2"}, "geometry": Point(1, 0)},
        ],
        crs_text="EPSG:3857",
        layer_name="t06_frcsd_node",
    )
    with fiona.open(
        plan,
        "w",
        driver="GPKG",
        layer="t06_segment_replacement_plan",
        crs="EPSG:3857",
        schema={"geometry": "None", "properties": {"swsd_segment_id": "str"}},
    ) as collection:
        collection.write({"properties": {"swsd_segment_id": "s1_s2"}, "geometry": None})

    metrics = t10_case_runner._t06_visual_spatial_metrics(
        {
            "t06_frcsd_road_gpkg": road,
            "t06_frcsd_node_gpkg": node,
            "t06_segment_replacement_plan_gpkg": plan,
        }
    )

    assert metrics["crs_status"] == "passed"
    assert metrics["spatial_check_status"] == "passed"
    assert metrics["advance_right_count"] == 1
    assert metrics["advance_endpoint_missing_road_count"] == 0


def test_t10_innernet_full_pipeline_finalize_existing_run_root(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    run_root = tmp_path / "t10_existing_run"
    t06_step3 = run_root / "t06_segment_fusion_precheck" / "t06_innernet_precheck" / "step3_segment_replacement"
    t09_step3 = run_root / "t09_swsd_field_rule_restoration" / "t09_step3"
    t06_step3.mkdir(parents=True)
    t09_step3.mkdir(parents=True)
    frcsd_road = t06_step3 / "t06_frcsd_road.gpkg"
    frcsd_node = t06_step3 / "t06_frcsd_node.gpkg"
    frcsd_restriction = t09_step3 / "frcsd_restriction.gpkg"
    frcsd_road.touch()
    frcsd_node.touch()
    frcsd_restriction.touch()
    manifest = {
        "run_id": run_root.name,
        "run_root": str(run_root),
        "repo_dir": str(repo_root),
        "created_at_utc": "2026-06-20T00:00:00+00:00",
        "status": "running",
        "passed": False,
        "inputs": {},
        "outputs": {},
        "stage_order": ["t06_step3", "t09"],
        "stages": {
            "t06_step3": {
                "stage_id": "t06_step3",
                "module_id": "T06",
                "status": "passed",
                "outputs": {
                    "frcsd_road": str(frcsd_road),
                    "frcsd_node": str(frcsd_node),
                },
            },
            "t09": {
                "stage_id": "t09",
                "module_id": "T09",
                "status": "passed",
                "outputs": {
                    "frcsd_restriction": str(frcsd_restriction),
                },
            },
        },
    }
    (run_root / "t10_innernet_full_pipeline_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/t10_run_innernet_full_pipeline.sh"],
        cwd=repo_root,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHON_BIN": sys.executable,
            "REPO_DIR": str(repo_root),
            "FINALIZE_EXISTING": "1",
            "RESUME_RUN_ROOT": str(run_root),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    summary = json.loads((run_root / "t10_innernet_full_pipeline_summary.json").read_text(encoding="utf-8"))
    updated_manifest = json.loads(
        (run_root / "t10_innernet_full_pipeline_manifest.json").read_text(encoding="utf-8")
    )
    assert summary["status"] == "passed"
    assert summary["passed"] is True
    assert summary["missing_final_outputs"] == []
    assert summary["t06_frcsd_road"] == str(frcsd_road)
    assert summary["t06_frcsd_node"] == str(frcsd_node)
    assert summary["t09_frcsd_restriction"] == str(frcsd_restriction)
    assert updated_manifest["status"] == "passed"
    assert updated_manifest["passed"] is True


def _write_feedback_iteration_case_outputs(
    case_run_dir: Path,
    *,
    replaced_segments: list[str],
    emit_side_group_problem: bool,
    side_group_segment_id: str = "n1_n2",
    side_group_candidate_pair: str = "101|201",
    emit_pair_anchor_problem: bool = False,
) -> None:
    step2 = case_run_dir / "t06_step12" / "t06" / "step2_extract_rcsd_segments"
    step3 = case_run_dir / "t06_step12" / "t06" / "step3_segment_replacement"
    step2.mkdir(parents=True, exist_ok=True)
    step3.mkdir(parents=True, exist_ok=True)
    plan_lines = ["swsd_segment_id,plan_status"]
    relation_lines = ["swsd_segment_id,relation_status"]
    for segment_id in replaced_segments:
        plan_lines.append(f"{segment_id},ready")
        relation_lines.append(f"{segment_id},replaced")
    (step2 / "t06_segment_replacement_plan.csv").write_text("\n".join(plan_lines) + "\n", encoding="utf-8")
    (step3 / "t06_step3_swsd_frcsd_segment_relation.csv").write_text(
        "\n".join(relation_lines) + "\n",
        encoding="utf-8",
    )
    registry_lines = [
        "swsd_segment_id,problem_status,recommended_module,upstream_issue_owner,"
        "failure_business_category,reject_reason,root_cause_category,feedback_action,"
        "manual_review_required,swsd_pair_nodes,rcsd_pair_nodes,candidate_rcsd_pair_node_sets,"
        "pair_anchor_endpoint_cluster_nodes,pair_anchor_bridge_road_ids,pair_anchor_bridge_length_m,"
        "pair_anchor_diagnostic_source,pair_anchor_diagnostic_reason,evidence_artifacts"
    ]
    if emit_side_group_problem:
        left, right = side_group_segment_id.split("_", 1)
        candidate_left, candidate_right = side_group_candidate_pair.split("|", 1)
        primary_left, primary_right = ("100", "200")
        registry_lines.append(
            f"{side_group_segment_id},requires_upstream_side_group_or_rcsd_directionality_review,"
            "T03/T04/T05_or_RCSD_source_review,T03/T04/T05_or_RCSD_directionality_review,"
            "directionality_mismatch_fixable,rcsd_not_bidirectional_for_swsd_dual,"
            "full_rcsd_graph_one_direction_only,review,true,"
            f"\"['{left}','{right}']\",\"['{primary_left}','{primary_right}']\","
            f"\"[['{candidate_left}','{candidate_right}']]\",,,,,,audit"
        )
    if emit_pair_anchor_problem:
        registry_lines.append(
            "p1_p2,requires_upstream_iteration,T03/T04/T05,T05,"
            "pair_anchor_mismatch,rcsd_pair_nodes_not_distinct,,rerun,true,"
            "\"['p1','p2']\",\"['501','601']\",\"[['501','602']]\","
            "\"[['501'],['601','602']]\",['rr_bridge'],10.0,"
            "buffer_only_endpoint_cluster,short_connected_endpoint_cluster,audit"
        )
    (step2 / "t06_segment_replacement_problem_registry.csv").write_text(
        "\n".join(registry_lines) + "\n",
        encoding="utf-8",
    )
    (case_run_dir / "t10_t06_funnel.json").write_text(
        json.dumps({"case_id": "9001", "status": "completed", "metrics": []}),
        encoding="utf-8",
    )
    (case_run_dir / "t10_e2e_case_run_manifest.json").write_text(
        json.dumps({"case_id": "9001", "overall_status": "passed"}),
        encoding="utf-8",
    )
    (case_run_dir / "t10_e2e_case_run_summary.json").write_text(
        json.dumps({"case_id": "9001", "overall_status": "passed", "passed": True}),
        encoding="utf-8",
    )
