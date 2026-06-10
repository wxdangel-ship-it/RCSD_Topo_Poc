from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t08_preprocess.vector_io import read_vector, write_gpkg
from rcsd_topo_poc.modules.t10_e2e_orchestration import (
    T10_V1_CHAIN,
    build_case_evidence_package,
    build_multi_case_evidence_package,
    decode_t10_case_evidence_text_bundle,
    export_t10_case_evidence_text_bundle,
    suggest_t10_cases,
    validate_t10_manifest,
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
            ]
        elif slot == "prepared_swsd_roads":
            features = [
                {"properties": {"id": "r_near"}, "geometry": LineString([(-200.0, 0.0), (200.0, 0.0)])},
                {"properties": {"id": "r_far"}, "geometry": LineString([(4900.0, 0.0), (5100.0, 0.0)])},
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
    assert len(node_result.features) == 2
    assert len(road_result.features) == 1
    minx, _miny, maxx, _maxy = road_result.features[0].geometry.bounds
    assert minx >= -95.0
    assert maxx <= 105.0

    case_2001_manifest = json.loads(
        (artifacts.package_dir / "cases" / "2001" / "t10_case_evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert case_2001_manifest["scope"]["center"] == {"x": 5000.0, "y": 0.0}
