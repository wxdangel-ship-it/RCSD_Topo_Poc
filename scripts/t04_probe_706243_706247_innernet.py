#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CASE_IDS = ("706243", "706247")
CASE_ROOT_CANDIDATES = (
    Path("/mnt/d/TestData/POC_Data/T02/Anchor_2"),
    Path("/mnt/e/TestData/POC_Data/T02/Anchor_2"),
    Path("/mnt/c/TestData/POC_Data/T02/Anchor_2"),
)


def _run_cmd(args: list[str], cwd: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
        return {
            "cmd": args,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as exc:
        return {"cmd": args, "error": repr(exc)}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_json_load_error": repr(exc), "_path": str(path)}


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _geo_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "path": str(path)}
    try:
        import geopandas as gpd

        gdf = gpd.read_file(path)
        return {
            "exists": True,
            "path": str(path),
            "crs": str(gdf.crs),
            "rows": int(len(gdf)),
            "geom_types": sorted({str(item) for item in gdf.geometry.geom_type}),
            "valid_all": bool(gdf.geometry.is_valid.all()) if len(gdf) else True,
            "area_sum": float(gdf.geometry.area.sum()) if len(gdf) else 0.0,
            "bounds": [float(item) for item in gdf.total_bounds] if len(gdf) else [],
        }
    except Exception as exc:
        return {"exists": True, "path": str(path), "error": repr(exc)}


def _first_unit(doc: dict[str, Any], key: str) -> dict[str, Any]:
    values = doc.get(key) or []
    if values and isinstance(values[0], dict):
        return values[0]
    return {}


def _candidate_summary(row: dict[str, Any]) -> dict[str, Any]:
    summary = row.get("candidate_summary") or row
    return {
        "candidate_id": row.get("candidate_id") or summary.get("candidate_id"),
        "selection_status": row.get("selection_status") or summary.get("selection_status"),
        "decision_reason": row.get("decision_reason") or summary.get("decision_reason"),
        "candidate_scope": summary.get("candidate_scope"),
        "upper_evidence_kind": summary.get("upper_evidence_kind"),
        "source_mode": summary.get("source_mode"),
        "layer": summary.get("layer"),
        "layer_label": summary.get("layer_label"),
        "axis_signature": summary.get("axis_signature"),
        "axis_position_m": summary.get("axis_position_m"),
        "reference_distance_to_origin_m": summary.get("reference_distance_to_origin_m"),
        "point_signature": summary.get("point_signature"),
        "primary_eligible": summary.get("primary_eligible"),
        "node_fallback_only": summary.get("node_fallback_only"),
        "positive_rcsd_present": summary.get("positive_rcsd_present"),
        "positive_rcsd_present_reason": summary.get("positive_rcsd_present_reason"),
        "positive_rcsd_support_level": summary.get("positive_rcsd_support_level"),
        "positive_rcsd_consistency_level": summary.get("positive_rcsd_consistency_level"),
        "required_rcsd_node": summary.get("required_rcsd_node"),
        "rcsd_selection_mode": summary.get("rcsd_selection_mode"),
    }


def _candidate_report(path: Path) -> dict[str, Any]:
    doc = _load_json(path)
    if not doc:
        return {"exists": False, "path": str(path)}
    rows = doc.get("candidate_audit_entries") or doc.get("candidates") or doc.get("rows") or []
    return {
        "exists": True,
        "path": str(path),
        "candidate_count": len(rows),
        "top_candidates": [_candidate_summary(row) for row in rows[:30] if isinstance(row, dict)],
    }


def _compact_positive_rcsd(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "operational_event_type": audit.get("operational_event_type"),
        "rcsd_decision_reason": audit.get("rcsd_decision_reason"),
        "published_rcsd_selection_mode": audit.get("published_rcsd_selection_mode"),
        "published_rcsdroad_ids": audit.get("published_rcsdroad_ids"),
        "published_rcsdnode_ids": audit.get("published_rcsdnode_ids"),
        "first_hit_rcsdroad_ids": audit.get("first_hit_rcsdroad_ids"),
        "selected_unit_role_assignments": audit.get("selected_unit_role_assignments"),
        "local_rcsd_units": audit.get("local_rcsd_units"),
        "aggregated_rcsd_units": audit.get("aggregated_rcsd_units"),
    }


def _case_report(run_root: Path, case_id: str) -> dict[str, Any]:
    case_dir = run_root / "cases" / case_id
    unit_dir = case_dir / "event_units" / "event_unit_01"
    step3 = _load_json(case_dir / "step3_status.json")
    step4 = _load_json(case_dir / "step4_event_interpretation.json")
    step4_audit = _load_json(case_dir / "step4_audit.json")
    step5 = _load_json(case_dir / "step5_status.json")
    step6 = _load_json(case_dir / "step6_status.json")
    step7 = _load_json(case_dir / "step7_status.json")
    unit4 = _first_unit(step4, "event_units")
    unit5 = _first_unit(step5, "unit_results")
    audit_unit = _first_unit(step4_audit, "event_units")
    selected = unit4.get("selected_evidence") or {}
    positive_audit = unit4.get("positive_rcsd_audit") or {}
    audit_positive = audit_unit.get("positive_rcsd_audit") or {}
    return {
        "case_id": case_id,
        "case_dir_exists": case_dir.is_dir(),
        "step3": step3,
        "step4_core": {
            "review_state": unit4.get("review_state"),
            "review_reasons": unit4.get("review_reasons"),
            "evidence_source": unit4.get("evidence_source"),
            "position_source": unit4.get("position_source"),
            "main_evidence_type": unit4.get("main_evidence_type"),
            "surface_scenario_type": unit4.get("surface_scenario_type"),
            "section_reference_source": unit4.get("section_reference_source"),
            "surface_generation_mode": unit4.get("surface_generation_mode"),
            "reference_point_present": unit4.get("reference_point_present"),
            "reference_point_source": unit4.get("reference_point_source"),
            "no_reference_point_reason": unit4.get("no_reference_point_reason"),
            "required_rcsd_node": unit4.get("required_rcsd_node"),
            "rcsd_match_type": unit4.get("rcsd_match_type"),
            "rcsd_selection_mode": unit4.get("rcsd_selection_mode"),
            "positive_rcsd_present": unit4.get("positive_rcsd_present"),
            "positive_rcsd_present_reason": unit4.get("positive_rcsd_present_reason"),
            "positive_rcsd_support_level": unit4.get("positive_rcsd_support_level"),
            "positive_rcsd_consistency_level": unit4.get("positive_rcsd_consistency_level"),
            "first_hit_rcsdroad_ids": unit4.get("first_hit_rcsdroad_ids"),
            "selected_rcsdroad_ids": unit4.get("selected_rcsdroad_ids"),
            "selected_rcsdnode_ids": unit4.get("selected_rcsdnode_ids"),
        },
        "selected_evidence": {
            "candidate_id": selected.get("candidate_id"),
            "candidate_scope": selected.get("candidate_scope"),
            "upper_evidence_kind": selected.get("upper_evidence_kind"),
            "source_mode": selected.get("source_mode"),
            "layer": selected.get("layer"),
            "layer_label": selected.get("layer_label"),
            "axis_signature": selected.get("axis_signature"),
            "axis_position_m": selected.get("axis_position_m"),
            "reference_distance_to_origin_m": selected.get("reference_distance_to_origin_m"),
            "point_signature": selected.get("point_signature"),
            "primary_eligible": selected.get("primary_eligible"),
            "node_fallback_only": selected.get("node_fallback_only"),
            "road_surface_fork_binding": selected.get("road_surface_fork_binding"),
        },
        "positive_rcsd_audit_from_step4": _compact_positive_rcsd(positive_audit),
        "positive_rcsd_audit_from_step4_audit": _compact_positive_rcsd(audit_positive),
        "step4_candidates": _candidate_report(unit_dir / "step4_candidates.json"),
        "step4_evidence_audit_keys": sorted((_load_json(unit_dir / "step4_evidence_audit.json") or {}).keys()),
        "step5": {
            "surface_scenario_type": unit5.get("surface_scenario_type"),
            "section_reference_source": unit5.get("section_reference_source"),
            "surface_generation_mode": unit5.get("surface_generation_mode"),
            "surface_fill_mode": unit5.get("surface_fill_mode"),
            "must_cover_components": unit5.get("must_cover_components"),
            "unit_must_cover_domain": unit5.get("unit_must_cover_domain"),
            "unit_allowed_growth_domain": unit5.get("unit_allowed_growth_domain"),
            "fallback_rcsdroad_localized": unit5.get("fallback_rcsdroad_localized"),
            "no_virtual_reference_point_guard": unit5.get("no_virtual_reference_point_guard"),
            "support_domain_from_reference_kind": unit5.get("support_domain_from_reference_kind"),
        },
        "step6": {
            "assembly_state": step6.get("assembly_state"),
            "review_reasons": step6.get("review_reasons"),
            "final_case_polygon_component_count": step6.get("final_case_polygon_component_count"),
            "single_connected_case_surface_ok": step6.get("single_connected_case_surface_ok"),
            "b_node_gate_applicable": step6.get("b_node_gate_applicable"),
            "b_node_gate_skip_reason": step6.get("b_node_gate_skip_reason"),
            "b_node_target_covered": step6.get("b_node_target_covered"),
            "post_cleanup_allowed_growth_ok": step6.get("post_cleanup_allowed_growth_ok"),
            "post_cleanup_forbidden_ok": step6.get("post_cleanup_forbidden_ok"),
            "post_cleanup_terminal_cut_ok": step6.get("post_cleanup_terminal_cut_ok"),
            "post_cleanup_lateral_limit_ok": step6.get("post_cleanup_lateral_limit_ok"),
            "final_case_polygon": step6.get("final_case_polygon"),
        },
        "step7": {
            "final_state": step7.get("final_state"),
            "reject_reason": step7.get("reject_reason"),
            "reject_reason_detail": step7.get("reject_reason_detail"),
            "publish_target": step7.get("publish_target"),
        },
        "output_geometries": {
            "final_case_polygon": _geo_summary(case_dir / "final_case_polygon.gpkg"),
            "step5_domains": _geo_summary(case_dir / "step5_domains.gpkg"),
            "step4_event_evidence": _geo_summary(case_dir / "step4_event_evidence.gpkg"),
        },
        "artifact_paths": {
            "case_dir": str(case_dir),
            "final_review_png": str(case_dir / "final_review.png"),
            "step4_review_png": str(unit_dir / "step4_review.png"),
            "step4_positive_rcsd_review_png": str(unit_dir / "step4_positive_rcsd_review.png"),
        },
    }


def _top_level_report(run_root: Path) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for name in (
        "summary.json",
        "divmerge_virtual_anchor_surface_summary.json",
        "step7_consistency_report.json",
        "nodes_anchor_update_audit.json",
        "step4_road_surface_fork_binding.json",
    ):
        doc = _load_json(run_root / name)
        report[name] = {
            key: doc.get(key)
            for key in (
                "failed_case_ids",
                "row_count",
                "accepted_count",
                "rejected_count",
                "step7_accepted_count",
                "step7_rejected_count",
                "passed",
                "nodes_consistency_passed",
                "updated_to_yes_count",
                "updated_to_fail4_count",
                "nodes_updated_to_yes_count",
                "nodes_updated_to_fail4_count",
                "no_surface_reference_accepted_case_ids",
                "step6_guard_field_missing_case_ids",
                "nodes_mismatch_case_ids",
            )
            if key in doc
        } if doc else {"missing": True, "path": str(run_root / name)}
    return report


def _resolve_case_root(value: str | None) -> Path | None:
    if value:
        path = Path(value).resolve()
        return path if path.is_dir() else None
    return next((path for path in CASE_ROOT_CANDIDATES if path.is_dir()), None)


def _print_json(title: str, value: Any) -> None:
    print("\n" + "=" * 100)
    print(title)
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run or inspect T04 706243/706247 innernet diagnostics."
    )
    parser.add_argument("--case-root", default="", help="Anchor_2 case root. Auto-detects /mnt/d,/mnt/e,/mnt/c if omitted.")
    parser.add_argument("--run-root", default="", help="Existing T04 run root to inspect without rerun.")
    parser.add_argument("--case-ids", nargs="*", default=list(DEFAULT_CASE_IDS), help="Case ids to inspect.")
    parser.add_argument("--out-root", default="", help="Output root for a fresh rerun.")
    args = parser.parse_args()

    repo = Path.cwd().resolve()
    case_ids = [str(item) for item in args.case_ids]
    preflight = {
        "repo": str(repo),
        "python": sys.version,
        "platform": platform.platform(),
        "git_branch": _run_cmd(["git", "branch", "--show-current"], repo),
        "git_head": _run_cmd(["git", "log", "-1", "--oneline", "--decorate"], repo),
        "git_status": _run_cmd(["git", "status", "--short"], repo),
        "case_root_candidates": [{"path": str(path), "exists": path.is_dir()} for path in CASE_ROOT_CANDIDATES],
        "key_file_sha256": {
            "step4_road_surface_fork_binding.py": _sha256(repo / "src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding.py"),
            "event_interpretation_selection.py": _sha256(repo / "src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/event_interpretation_selection.py"),
            "support_domain.py": _sha256(repo / "src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain.py"),
            "polygon_assembly.py": _sha256(repo / "src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly.py"),
            "final_publish.py": _sha256(repo / "src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/final_publish.py"),
        },
    }
    _print_json("PREFLIGHT", preflight)

    if args.run_root:
        run_root = Path(args.run_root).resolve()
        if not run_root.is_dir():
            raise SystemExit(f"run root does not exist: {run_root}")
        out_root = run_root / "_probe_706243_706247"
        out_root.mkdir(parents=True, exist_ok=True)
        run_info = {"mode": "inspect_existing_run", "run_root": str(run_root), "out_root": str(out_root)}
    else:
        case_root = _resolve_case_root(args.case_root or None)
        if case_root is None:
            raise SystemExit("case root not found; pass --case-root explicitly")
        missing = [case_id for case_id in case_ids if not (case_root / case_id).is_dir()]
        if missing:
            raise SystemExit(f"missing case directories under {case_root}: {missing}")
        _print_json(
            "INPUT_GPKG",
            {
                case_id: {
                    "drivezone": _geo_summary(case_root / case_id / "drivezone.gpkg"),
                    "roads": _geo_summary(case_root / case_id / "roads.gpkg"),
                    "divstripzone": _geo_summary(case_root / case_id / "divstripzone.gpkg"),
                    "rcsdroad": _geo_summary(case_root / case_id / "rcsdroad.gpkg"),
                    "rcsdnode": _geo_summary(case_root / case_id / "rcsdnode.gpkg"),
                    "nodes": _geo_summary(case_root / case_id / "nodes.gpkg"),
                }
                for case_id in case_ids
            },
        )
        from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_step14_batch

        started = time.time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_root = Path(args.out_root).resolve() if args.out_root else repo / "outputs/_work" / f"t04_probe_706243_706247_deep_{timestamp}"
        try:
            run_root = run_t04_step14_batch(
                case_root=case_root,
                case_ids=case_ids,
                out_root=out_root,
                run_id=f"t04_probe_706243_706247_deep_{timestamp}",
            )
            run_error = None
        except Exception:
            run_root = out_root
            run_error = traceback.format_exc()
        run_info = {
            "mode": "fresh_rerun",
            "case_root": str(case_root),
            "case_ids": case_ids,
            "run_root": str(run_root),
            "out_root": str(out_root),
            "elapsed_s": round(time.time() - started, 3),
            "run_error": run_error,
        }
        if run_error:
            _print_json("RUN_FAILED", run_info)
            return 4

    _print_json("RUN", run_info)
    report = {
        "preflight": preflight,
        "run": run_info,
        "top_level": _top_level_report(run_root),
        "cases": {case_id: _case_report(run_root, case_id) for case_id in case_ids},
    }
    for case_id, case_report in report["cases"].items():
        _print_json(f"CASE_REPORT_{case_id}", case_report)

    report_path = out_root / "analysis_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _print_json("DONE", {"run_root": str(run_root), "report": str(report_path)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
