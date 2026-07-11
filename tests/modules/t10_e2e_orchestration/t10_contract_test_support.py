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


__all__ = [name for name in globals() if not name.startswith("__")]
