from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def run_t11_stage(
    case_id: str,
    case_run_dir: Path,
    stage_dir: Path,
    repo_root: Path,
    python_bin: Path | str,
    handoffs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    from . import case_runner as facade

    inputs = {
        "t10_case_root": case_run_dir,
        "t06_step3_summary": facade._path_from(handoffs.get("t06_step3_summary")),
        "t06_frcsd_road": facade._path_from(handoffs.get("t06_frcsd_road")),
        "t06_frcsd_node": facade._path_from(handoffs.get("t06_frcsd_node")),
        "t06_segment_relation": facade._path_from(handoffs.get("t06_swsd_frcsd_segment_relation")),
    }
    required_files = {key: value for key, value in inputs.items() if key != "t10_case_root"}
    missing = facade._missing_files(required_files)
    if not case_run_dir.is_dir():
        missing.insert(0, "t10_case_root")
    if missing:
        return facade._blocked_record(
            "t11",
            stage_dir,
            "Missing T11 candidate extraction inputs.",
            inputs=inputs,
            missing=missing,
        ), {}

    command = [
        str(python_bin),
        "scripts/t11_extract_relation_repair_candidates.py",
        "--t10-case-root",
        str(case_run_dir),
        "--out-root",
        str(stage_dir),
        "--case-id",
        case_id,
    ]
    record = facade._execute_command("t11", stage_dir, repo_root, command, {}, inputs)
    run_root = _run_root_from_stdout(stage_dir / "stdout.log") or _latest_run_root(stage_dir)
    produced = {
        "t11_run_root": facade._path_text(run_root),
        "t11_candidates_csv": facade._path_text(
            run_root / "t11_relation_repair_candidates.csv" if run_root else None
        ),
        "t11_candidates_gpkg": facade._path_text(
            run_root / "t11_relation_repair_candidates.gpkg" if run_root else None
        ),
        "t11_manual_template_csv": facade._path_text(
            run_root / "t11_manual_relation_template.csv" if run_root else None
        ),
        "t11_summary_json": facade._path_text(
            run_root / "t11_relation_repair_candidate_summary.json" if run_root else None
        ),
    }
    facade._attach_outputs(record, produced)
    if record.get("status") == "passed" and record.get("missing_outputs"):
        missing_outputs = ", ".join(record["missing_outputs"])
        message = f"T11 command returned 0 but required outputs are missing: {missing_outputs}"
        record["status"] = "failed"
        record["message"] = message
        record["failure_reason"] = message
    return record, produced


def _run_root_from_stdout(path: Path) -> Path | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    json_start = text.find("{")
    if json_start < 0:
        return None
    try:
        payload = json.loads(text[json_start:])
    except json.JSONDecodeError:
        return None
    value = payload.get("run_root")
    run_root = Path(value) if value else None
    return run_root if run_root and run_root.is_dir() else None


def _latest_run_root(stage_dir: Path) -> Path | None:
    candidates = sorted(path for path in stage_dir.glob("run_*") if path.is_dir())
    return candidates[-1] if candidates else None
