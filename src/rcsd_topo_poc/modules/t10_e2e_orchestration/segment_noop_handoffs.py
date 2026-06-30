from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

import fiona


T03_RELATION_FIELDS = (
    "target_id",
    "case_id",
    "junction_type",
    "template_class",
    "association_class",
    "required_rcsdnode_ids",
    "required_rcsdroad_ids",
    "support_rcsdnode_ids",
    "support_rcsdroad_ids",
    "excluded_rcsdnode_ids",
    "excluded_rcsdroad_ids",
    "nonsemantic_connector_rcsdnode_ids",
    "true_foreign_rcsdnode_ids",
    "degree2_merged_rcsdroad_groups",
    "step7_state",
    "surface_candidate_present",
    "base_id_candidate",
    "status_suggested",
    "relation_state",
    "reason",
    "level",
    "is_highway",
    "swsd_point_x",
    "swsd_point_y",
    "rcsd_point_x",
    "rcsd_point_y",
)

T04_RELATION_FIELDS = (
    "target_id",
    "case_id",
    "junction_type",
    "scene_type",
    "final_state",
    "swsd_relation_type",
    "required_rcsd_node_ids",
    "semantic_required_rcsd_node_ids",
    "selected_rcsdnode_ids",
    "selected_rcsdroad_ids",
    "rcsd_profile",
    "has_c_unit",
    "surface_candidate_present",
    "base_id_candidate",
    "status_suggested",
    "relation_state",
    "reason",
    "level",
    "is_highway",
    "patch_id",
    "swsd_point_x",
    "swsd_point_y",
    "rcsd_point_x",
    "rcsd_point_y",
)

T04_SUMMARY_FIELDS = (
    "case_id",
    "anchor_id",
    "mainnodeid",
    "source_module",
    "scene_family",
    "scene_type",
    "junction_type",
    "kind_2",
    "patch_id",
    "patch_id_source",
    "final_state",
)


def try_segment_no_candidate_handoff(
    stage_id: str,
    case_id: str,
    stage_dir: Path,
    record: dict[str, Any],
    inputs: Mapping[str, Path | None],
    produced: Mapping[str, str],
) -> dict[str, str] | None:
    if not case_id.startswith("segment_") or record.get("status") == "passed":
        return None
    if not _is_no_candidate_stdout(record):
        return None
    if stage_id == "t03":
        _write_t03_noop(stage_dir=stage_dir, inputs=inputs)
        result = _t03_outputs(stage_dir)
    elif stage_id == "t04":
        _write_t04_noop(stage_dir=stage_dir, inputs=inputs)
        result = _t04_outputs(stage_dir)
    else:
        return None
    record["status"] = "passed"
    record["return_code"] = 0
    record["segment_no_candidate_handoff"] = True
    record["message"] = "Segment package has no eligible candidates for this stage; wrote explicit empty handoff."
    record["noop_reason"] = "no_eligible_candidates_in_segment_dependency_closure"
    return {**produced, **result}


def _is_no_candidate_stdout(record: Mapping[str, Any]) -> bool:
    text = "\n".join(str(line) for line in record.get("stdout_tail") or [])
    if "No eligible T03 internal full-input cases were discovered" in text:
        return True
    return "No eligible T04 candidates were discovered" in text


def _write_t03_noop(*, stage_dir: Path, inputs: Mapping[str, Path | None]) -> None:
    run_root = stage_dir / "t03"
    run_root.mkdir(parents=True, exist_ok=True)
    _copy_nodes(inputs.get("t07_nodes"), run_root / "nodes.gpkg")
    _write_empty_gpkg(run_root / "virtual_intersection_polygons.gpkg", ("mainnodeid", "status"))
    _write_csv_header(run_root / "t03_swsd_rcsd_relation_evidence.csv", T03_RELATION_FIELDS)
    _write_json(run_root / "t03_swsd_rcsd_relation_evidence.json", {"rows": [], "row_count": 0})
    _write_empty_geojson(run_root / "intersection_match_t03.geojson")
    _write_json(run_root / "summary.json", {"status": "passed", "noop": True, "candidate_count": 0})


def _write_t04_noop(*, stage_dir: Path, inputs: Mapping[str, Path | None]) -> None:
    run_root = stage_dir / "t04"
    run_root.mkdir(parents=True, exist_ok=True)
    _copy_nodes(inputs.get("t03_nodes"), run_root / "nodes.gpkg")
    _write_empty_gpkg(run_root / "divmerge_virtual_anchor_surface.gpkg", ("case_id", "mainnodeid", "final_state"))
    _write_empty_gpkg(run_root / "divmerge_virtual_anchor_surface_audit.gpkg", ("case_id", "reject_reason"))
    _write_csv_header(run_root / "t04_swsd_rcsd_relation_evidence.csv", T04_RELATION_FIELDS)
    _write_json(run_root / "t04_swsd_rcsd_relation_evidence.json", {"rows": [], "row_count": 0})
    _write_empty_geojson(run_root / "intersection_match_t04.geojson")
    _write_csv_header(run_root / "divmerge_virtual_anchor_surface_summary.csv", T04_SUMMARY_FIELDS)
    (run_root / "cases").mkdir(exist_ok=True)


def _t03_outputs(stage_dir: Path) -> dict[str, str]:
    run_root = stage_dir / "t03"
    return {
        "t03_run_root": str(run_root),
        "t03_nodes": str(run_root / "nodes.gpkg"),
        "t03_surface": str(run_root / "virtual_intersection_polygons.gpkg"),
        "t03_relation_evidence": str(run_root / "t03_swsd_rcsd_relation_evidence.csv"),
        "t03_intersection_match": str(run_root / "intersection_match_t03.geojson"),
    }


def _t04_outputs(stage_dir: Path) -> dict[str, str]:
    run_root = stage_dir / "t04"
    return {
        "t04_run_root": str(run_root),
        "t04_nodes": str(run_root / "nodes.gpkg"),
        "final_swsd_nodes": str(run_root / "nodes.gpkg"),
        "t04_surface": str(run_root / "divmerge_virtual_anchor_surface.gpkg"),
        "t04_relation_evidence": str(run_root / "t04_swsd_rcsd_relation_evidence.csv"),
        "t04_intersection_match": str(run_root / "intersection_match_t04.geojson"),
        "t04_summary": str(run_root / "divmerge_virtual_anchor_surface_summary.csv"),
        "t04_audit": str(run_root / "divmerge_virtual_anchor_surface_audit.gpkg"),
        "t04_case_root": str(run_root / "cases"),
    }


def _copy_nodes(source: Path | None, target: Path) -> None:
    if source is None or not Path(source).is_file():
        raise FileNotFoundError(f"missing noop nodes source: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _write_empty_gpkg(path: Path, fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    schema = {"geometry": "Unknown", "properties": {field: "str" for field in fields}}
    with fiona.open(
        str(path),
        mode="w",
        driver="GPKG",
        layer=path.stem,
        schema=schema,
        crs="EPSG:3857",
        encoding="utf-8",
    ):
        pass


def _write_csv_header(path: Path, fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        csv.DictWriter(fp, fieldnames=fields).writeheader()


def _write_empty_geojson(path: Path) -> None:
    _write_json(
        path,
        {
            "type": "FeatureCollection",
            "name": path.stem,
            "crs": {"type": "name", "properties": {"name": "CRS84"}},
            "features": [],
        },
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
