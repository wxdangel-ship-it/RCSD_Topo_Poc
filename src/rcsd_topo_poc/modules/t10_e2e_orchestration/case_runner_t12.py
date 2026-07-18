from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def run_t12_stage(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    python_bin: Path | str,
    external_inputs: Mapping[str, Path],
    handoffs: Mapping[str, str],
    *,
    case_manifest_path: Path | None = None,
    review_decisions_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    from . import case_runner as facade

    t05_phase2_root = facade._path_from(handoffs.get("t05_phase2_root"))
    t05_anchor_audit = (
        t05_phase2_root / "intersection_match_all_audit.csv"
        if t05_phase2_root is not None
        else None
    )
    t06_run_root = facade._path_from(handoffs.get("t06_run_root"))
    inputs = {
        "swsd_segment": facade._path_from(handoffs.get("t01_segment")),
        "swsd_roads": facade._path_from(handoffs.get("t01_roads")),
        "swsd_nodes": facade._path_from(
            handoffs.get("final_swsd_nodes") or handoffs.get("t04_nodes")
        ),
        "frcsd_1v1_roads": external_inputs.get("frcsd_1v1_roads"),
        "frcsd_1v1_nodes": external_inputs.get("frcsd_1v1_nodes"),
        "t05_anchor_audit": t05_anchor_audit,
        "rcsd_intersection": external_inputs.get("rcsd_intersection"),
        "t06_run_root": t06_run_root,
        "drivezone": external_inputs.get("drivezone"),
        "case_manifest": case_manifest_path,
        "review_decisions": review_decisions_path,
    }
    required_files = {
        key: value
        for key, value in inputs.items()
        if key not in {"t06_run_root", "drivezone", "case_manifest", "review_decisions"}
    }
    missing = facade._missing_files(required_files)
    if t06_run_root is None or not t06_run_root.is_dir():
        missing.append("t06_run_root")
    for optional_file in (case_manifest_path, review_decisions_path):
        if optional_file is not None and not optional_file.is_file():
            missing.append(
                "case_manifest"
                if optional_file == case_manifest_path
                else "review_decisions"
            )
    if missing:
        return facade._blocked_record(
            "t12",
            stage_dir,
            "Missing T12 FRCSD quality-audit inputs.",
            inputs=inputs,
            missing=missing,
        ), {}

    run_id = f"t12_{facade._safe_case_id(case_id)}"
    command = [
        str(python_bin),
        "scripts/t12_run_frcsd_quality_audit.py",
        "--run-id",
        run_id,
        "--out-root",
        str(stage_dir),
        "--swsd-segment",
        str(inputs["swsd_segment"]),
        "--swsd-roads",
        str(inputs["swsd_roads"]),
        "--swsd-nodes",
        str(inputs["swsd_nodes"]),
        "--frcsd-roads",
        str(inputs["frcsd_1v1_roads"]),
        "--frcsd-nodes",
        str(inputs["frcsd_1v1_nodes"]),
        "--t05-anchor-audit",
        str(inputs["t05_anchor_audit"]),
        "--rcsd-intersection",
        str(inputs["rcsd_intersection"]),
        "--t06-run-root",
        str(inputs["t06_run_root"]),
    ]
    if inputs["drivezone"] is not None:
        command.extend(["--drivezone", str(inputs["drivezone"])])
    if inputs["case_manifest"] is not None:
        command.extend(["--case-manifest", str(inputs["case_manifest"])])
    if inputs["review_decisions"] is not None:
        command.extend(["--review-decisions", str(inputs["review_decisions"])])

    record = facade._execute_command("t12", stage_dir, repo_root, command, {}, inputs)
    run_root = stage_dir / run_id
    produced = {
        "t12_run_root": facade._path_text(run_root),
        "t12_manifest_json": facade._path_text(
            run_root / "t12_frcsd_quality_audit_manifest.json"
        ),
        "t12_summary_json": facade._path_text(
            run_root / "t12_frcsd_quality_audit_summary.json"
        ),
        "t12_candidates_csv": facade._path_text(
            run_root / "t12_frcsd_quality_candidates.csv"
        ),
        "t12_candidates_gpkg": facade._path_text(
            run_root / "t12_frcsd_quality_candidates.gpkg"
        ),
        "t12_confirmed_csv": facade._path_text(
            run_root / "t12_frcsd_confirmed_quality_issues.csv"
        ),
        "t12_confirmed_gpkg": facade._path_text(
            run_root / "t12_frcsd_confirmed_quality_issues.gpkg"
        ),
        "t12_review_exclusions_csv": facade._path_text(
            run_root / "t12_frcsd_quality_review_exclusions.csv"
        ),
        "t12_manual_review_csv": facade._path_text(
            run_root / "t12_frcsd_quality_manual_review_required.csv"
        ),
    }
    facade._attach_outputs(record, produced)
    if record.get("status") == "passed" and record.get("missing_outputs"):
        missing_outputs = ", ".join(record["missing_outputs"])
        message = f"T12 command returned 0 but outputs are missing: {missing_outputs}"
        record["status"] = "failed"
        record["message"] = message
        record["failure_reason"] = message
    record["audit_only"] = True
    return record, produced
