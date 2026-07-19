#!/usr/bin/env python3
"""Replay T12 for Segment packages with topology-complete source slices."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

import geopandas as gpd
import pandas as pd

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.carrier_graph import (
    field_name,
    normalize_id,
)


def _one_gpkg(case_dir: Path, slot: str) -> Path:
    matches = sorted((case_dir / "external_inputs" / slot).glob("*.gpkg"))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one GPKG for {case_dir.name}/{slot}, found {len(matches)}"
        )
    return matches[0].resolve()


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str).fillna("") if path.is_file() else pd.DataFrame()


def _target_row(frame: pd.DataFrame, segment_id: str) -> dict[str, str] | None:
    if frame.empty:
        return None
    candidate_field = field_name(frame, "candidate_id")
    matches = frame.loc[frame[candidate_field].map(normalize_id) == segment_id]
    if len(matches) > 1:
        raise RuntimeError(f"duplicate candidate row for {segment_id}")
    return None if matches.empty else {str(key): str(value) for key, value in matches.iloc[0].items()}


def _target_segment_exists(segment_path: Path, segment_id: str) -> bool:
    frame = gpd.read_file(segment_path)
    id_field = field_name(frame, "id")
    return segment_id in set(frame[id_field].map(normalize_id))


def _run_case(
    *,
    repo_root: Path,
    python_bin: Path,
    package_case_dir: Path,
    e2e_case_dir: Path,
    out_root: Path,
) -> dict[str, Any]:
    manifest = json.loads(
        (package_case_dir / "t10_case_evidence_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    segment_id = normalize_id(manifest["scope"]["swsd_segment_id"])
    run_id = f"t12_{segment_id}_before_compat"
    segment_path = e2e_case_dir / "t01" / "segment.gpkg"
    required_paths = {
        "swsd_segment": segment_path,
        "swsd_roads": e2e_case_dir / "t01" / "roads.gpkg",
        "swsd_nodes": e2e_case_dir / "t04" / "t04" / "nodes.gpkg",
        "frcsd_roads": _one_gpkg(package_case_dir, "rcsdroad"),
        "frcsd_nodes": _one_gpkg(package_case_dir, "rcsdnode"),
        "t05_anchor_audit": (
            e2e_case_dir
            / "t05"
            / "t05_phase2"
            / "intersection_match_all_audit.csv"
        ),
        "rcsd_intersection": _one_gpkg(package_case_dir, "rcsd_intersection"),
        "t06_run_root": e2e_case_dir / "t06_step12" / "t06",
        "drivezone": _one_gpkg(package_case_dir, "drivezone"),
    }
    missing = [name for name, path in required_paths.items() if not path.exists()]
    if missing:
        return {
            "segment_id": segment_id,
            "status": "not_assessable",
            "reason": "missing_replay_inputs:" + "|".join(missing),
        }
    if not _target_segment_exists(segment_path, segment_id):
        return {
            "segment_id": segment_id,
            "status": "not_assessable",
            "reason": "target_segment_missing_after_t01",
        }

    command = [
        str(python_bin),
        str(repo_root / "scripts" / "t12_run_frcsd_quality_audit.py"),
        "--run-id",
        run_id,
        "--out-root",
        str(out_root),
        "--swsd-segment",
        str(required_paths["swsd_segment"]),
        "--swsd-roads",
        str(required_paths["swsd_roads"]),
        "--swsd-nodes",
        str(required_paths["swsd_nodes"]),
        "--frcsd-roads",
        str(required_paths["frcsd_roads"]),
        "--frcsd-nodes",
        str(required_paths["frcsd_nodes"]),
        "--t05-anchor-audit",
        str(required_paths["t05_anchor_audit"]),
        "--rcsd-intersection",
        str(required_paths["rcsd_intersection"]),
        "--t06-run-root",
        str(required_paths["t06_run_root"]),
        "--drivezone",
        str(required_paths["drivezone"]),
    ]
    log_root = out_root / "_logs"
    log_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    duration = round(time.perf_counter() - started, 6)
    (log_root / f"{run_id}.stdout.log").write_text(
        completed.stdout,
        encoding="utf-8",
    )
    (log_root / f"{run_id}.stderr.log").write_text(
        completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return {
            "segment_id": segment_id,
            "status": "not_assessable",
            "reason": "t12_replay_failed",
            "return_code": completed.returncode,
            "stderr_tail": " | ".join(completed.stderr.splitlines()[-5:]),
            "duration_seconds": duration,
        }

    run_root = out_root / run_id
    candidates = _read_csv(run_root / "t12_frcsd_quality_candidates.csv")
    confirmed = _read_csv(run_root / "t12_frcsd_confirmed_quality_issues.csv")
    exclusions = _read_csv(run_root / "t12_frcsd_quality_review_exclusions.csv")
    target_candidate = _target_row(candidates, segment_id)
    target_confirmed = _target_row(confirmed, segment_id)
    target_excluded = _target_row(exclusions, segment_id)
    summary = json.loads(
        (run_root / "t12_frcsd_quality_audit_summary.json").read_text(
            encoding="utf-8"
        )
    )
    if target_confirmed is not None:
        target_status = "confirmed_quality_issue"
        target_result = target_confirmed
    elif target_excluded is not None:
        target_status = "excluded_false_positive"
        target_result = target_excluded
    elif target_candidate is not None:
        target_status = "candidate_without_final_partition"
        target_result = target_candidate
    else:
        target_status = "not_candidate_after_local_rebuild"
        target_result = {}
    return {
        "segment_id": segment_id,
        "status": "passed",
        "reason": "",
        "target_status": target_status,
        "run_root": str(run_root),
        "duration_seconds": duration,
        "candidate_count": int(summary["counts"]["candidate_count"]),
        "confirmed_count": int(summary["counts"]["confirmed_quality_issue_count"]),
        "excluded_count": int(summary["counts"]["review_exclusion_count"]),
        "target_result": target_result,
        "topology_source": "compatibility_frcsd_source_slice",
        "case_manifest_crop_gate_used": False,
        "silent_fix": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--e2e-run-root", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--python-bin", type=Path, default=Path(".venv/bin/python"))
    args = parser.parse_args(argv)

    package_root = args.package_root.resolve()
    e2e_run_root = args.e2e_run_root.resolve()
    out_root = args.out_root.resolve()
    if out_root.exists():
        raise RuntimeError(f"out-root already exists: {out_root}")
    out_root.mkdir(parents=True)
    case_dirs = sorted(
        path
        for path in package_root.iterdir()
        if path.is_dir() and (path / "t10_case_evidence_manifest.json").is_file()
    )
    rows = []
    for package_case_dir in case_dirs:
        manifest = json.loads(
            (package_case_dir / "t10_case_evidence_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        case_id = normalize_id(manifest["scope"]["case_id"])
        rows.append(
            _run_case(
                repo_root=args.repo_root.resolve(),
                python_bin=args.python_bin.resolve(),
                package_case_dir=package_case_dir,
                e2e_case_dir=e2e_run_root / "cases" / case_id,
                out_root=out_root,
            )
        )

    flat_rows = []
    for row in rows:
        flat = {key: value for key, value in row.items() if key != "target_result"}
        for key, value in row.get("target_result", {}).items():
            flat[f"target_{key}"] = value
        flat_rows.append(flat)
    csv_path = out_root / "t12_segment_replay_summary.csv"
    json_path = out_root / "t12_segment_replay_summary.json"
    pd.DataFrame(flat_rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    payload = {
        "status": "passed" if all(row["status"] == "passed" for row in rows) else "partial",
        "package_root": str(package_root),
        "e2e_run_root": str(e2e_run_root),
        "case_count": len(rows),
        "passed_replay_count": sum(row["status"] == "passed" for row in rows),
        "not_assessable_count": sum(row["status"] == "not_assessable" for row in rows),
        "qa": {
            "processing_crs": "EPSG:3857",
            "topology_silent_fix": False,
            "geometry_semantics": (
                "T12 replays the topology-complete compatibility FRCSD source "
                "slice only after package topology equivalence gates pass."
            ),
            "audit_traceability": str(csv_path),
            "performance_seconds": round(
                sum(float(row.get("duration_seconds") or 0.0) for row in rows),
                6,
            ),
        },
        "rows": rows,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"summary": str(json_path), **payload}, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
