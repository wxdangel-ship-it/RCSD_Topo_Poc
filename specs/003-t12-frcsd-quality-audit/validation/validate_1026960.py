#!/usr/bin/env python3
"""Materialize and validate the local 1026960 T12 acceptance case.

This is a SpecKit validation helper, not a production runner. All data roots are
explicit arguments so the same checks can be repeated without machine-specific
paths in production code.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


EXPECTED_CONFIRMED = {
    "1001432_1019757",
    "1019779_1026330",
    "1039319_1049250",
    "504597284_603597212",
    "612408195_991266",
    "84975803_1023802",
    "953923_953936",
    "991145_991164",
    "997356_1029576",
    "998051_501667982",
}


def _one_file(directory: Path, pattern: str) -> Path:
    matches = sorted(path for path in directory.glob(pattern) if path.is_file())
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one {pattern} below {directory}, found {len(matches)}"
        )
    return matches[0].resolve()


def _discover(case_root: Path, compatibility_root: Path, case_id: str) -> dict[str, Path]:
    external = case_root / "external_inputs"
    compat_case = compatibility_root / "cases" / case_id
    compatibility_manifest = compat_case / "t10_e2e_case_run_manifest.json"
    if not compatibility_manifest.is_file():
        raise RuntimeError(
            f"missing compatibility case manifest: {compatibility_manifest}"
        )
    compatibility_inputs = json.loads(
        compatibility_manifest.read_text(encoding="utf-8")
    )["external_inputs"]
    paths = {
        "case_manifest": case_root / "t10_case_evidence_manifest.json",
        "swsd_segment": compat_case / "t01" / "segment.gpkg",
        "swsd_roads": _one_file(external / "prepared_swsd_roads", "*.gpkg"),
        "swsd_nodes": _one_file(external / "prepared_swsd_nodes", "*.gpkg"),
        "frcsd_roads": _one_file(external / "rcsdroad", "*.gpkg"),
        "frcsd_nodes": _one_file(external / "rcsdnode", "*.gpkg"),
        "compat_rcsd_roads": Path(compatibility_inputs["rcsdroad"]),
        "compat_rcsd_nodes": Path(compatibility_inputs["rcsdnode"]),
        "rcsd_intersection": _one_file(
            external / "rcsd_intersection", "*.gpkg"
        ),
        "drivezone": _one_file(external / "drivezone", "*.gpkg"),
        "t05_anchor_audit": (
            compat_case
            / "t05"
            / "t05_phase2"
            / "intersection_match_all_audit.csv"
        ),
        "t06_run_root": compat_case / "t06_step12" / "t06",
    }
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        detail = ", ".join(f"{name}={paths[name]}" for name in missing)
        raise RuntimeError(f"missing validation inputs: {detail}")
    return {name: path.resolve() for name, path in paths.items()}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _materialize_case_package(
    *,
    original_manifest: Path,
    package_root: Path,
    case_id: str,
    frcsd_roads: Path,
    frcsd_nodes: Path,
    compat_rcsd_roads: Path,
    compat_rcsd_nodes: Path,
) -> Path:
    payload = json.loads(original_manifest.read_text(encoding="utf-8"))
    included: list[dict[str, Any]] = payload["included_external_inputs"]
    compatibility_overrides = {
        "rcsdroad": compat_rcsd_roads,
        "rcsdnode": compat_rcsd_nodes,
    }
    original_case_root = original_manifest.parent
    for row in included:
        package_path = original_case_root / str(row.get("package_path", ""))
        if not package_path.is_file():
            raise RuntimeError(
                f"local package payload is missing for slot {row.get('slot')}: "
                f"{package_path}"
            )
        resolved = compatibility_overrides.get(
            str(row["slot"]), package_path.resolve()
        )
        row["materialization_mode"] = "manifest_only"
        row["package_path"] = ""
        row["source_path"] = str(resolved)
        row["source_exists"] = True

    for slot, path in (
        ("frcsd_1v1_roads", frcsd_roads),
        ("frcsd_1v1_nodes", frcsd_nodes),
    ):
        included.append(
            {
                "slot": slot,
                "materialization_mode": "manifest_only",
                "package_path": "",
                "source_path": str(path),
                "source_exists": True,
                "source_size_bytes": path.stat().st_size,
                "source_sha256": _sha256(path),
            }
        )
    payload["materialization_mode"] = "manifest_only"
    payload.setdefault("qa", {})["t12_explicit_1v1_frcsd_slots"] = True
    case_dir = package_root / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    target = case_dir / "t10_case_evidence_manifest.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


def _rewrite_review_run_id(source: Path, target: Path, run_id: str) -> Path:
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 35 or len({row["candidate_id"] for row in rows}) != 35:
        raise RuntimeError("frozen review fixture must contain 35 unique candidates")
    for row in rows:
        row["run_id"] = run_id
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return target


def _run_t12(
    *,
    repo_root: Path,
    python_bin: Path,
    paths: dict[str, Path],
    output_root: Path,
    run_id: str,
    review_decisions: Path | None,
) -> dict[str, Any]:
    command = [
        str(python_bin),
        str(repo_root / "scripts" / "t12_run_frcsd_quality_audit.py"),
        "--swsd-segment",
        str(paths["swsd_segment"]),
        "--swsd-roads",
        str(paths["swsd_roads"]),
        "--swsd-nodes",
        str(paths["swsd_nodes"]),
        "--frcsd-roads",
        str(paths["frcsd_roads"]),
        "--frcsd-nodes",
        str(paths["frcsd_nodes"]),
        "--t05-anchor-audit",
        str(paths["t05_anchor_audit"]),
        "--rcsd-intersection",
        str(paths["rcsd_intersection"]),
        "--t06-run-root",
        str(paths["t06_run_root"]),
        "--drivezone",
        str(paths["drivezone"]),
        "--case-manifest",
        str(paths["case_manifest"]),
        "--out-root",
        str(output_root),
        "--run-id",
        run_id,
    ]
    if review_decisions is not None:
        command.extend(["--review-decisions", str(review_decisions)])
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def _validate_result(payload: dict[str, Any], reviewed: bool) -> dict[str, Any]:
    summary = json.loads(Path(payload["summary_json"]).read_text(encoding="utf-8"))
    expected = {
        "candidate_count": 35,
        "confirmed_quality_issue_count": 10,
        "review_exclusion_count": 25,
        "manual_review_required_count": 0,
    }
    actual = {key: int(summary["counts"][key]) for key in expected}
    if actual != expected:
        raise RuntimeError(f"unexpected T12 counts: expected={expected}, actual={actual}")
    with (Path(payload["run_root"]) / "t12_frcsd_confirmed_quality_issues.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as stream:
        confirmed_rows = list(csv.DictReader(stream))
    confirmed = {row["candidate_id"] for row in confirmed_rows}
    if confirmed != EXPECTED_CONFIRMED:
        raise RuntimeError(
            f"confirmed IDs differ: missing={sorted(EXPECTED_CONFIRMED-confirmed)}, "
            f"extra={sorted(confirmed-EXPECTED_CONFIRMED)}"
        )
    if not reviewed and {
        row.get("decision_source", "") for row in confirmed_rows
    } != {"automatic_high_confidence"}:
        raise RuntimeError("no-review confirmed rows must be automatic_high_confidence")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-root", required=True, type=Path)
    parser.add_argument("--compatibility-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--python-bin", type=Path, default=Path(sys.executable))
    parser.add_argument("--review-fixture", type=Path)
    parser.add_argument("--case-id", default="1026960")
    parser.add_argument("--materialize-only", action="store_true")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    paths = _discover(
        args.case_root.resolve(), args.compatibility_root.resolve(), args.case_id
    )
    package_manifest = _materialize_case_package(
        original_manifest=paths["case_manifest"],
        package_root=output_root / "t10_package",
        case_id=args.case_id,
        frcsd_roads=paths["frcsd_roads"],
        frcsd_nodes=paths["frcsd_nodes"],
        compat_rcsd_roads=paths["compat_rcsd_roads"],
        compat_rcsd_nodes=paths["compat_rcsd_nodes"],
    )
    report: dict[str, Any] = {
        "case_id": args.case_id,
        "resolved_inputs": {name: str(path) for name, path in paths.items()},
        "t10_case_manifest": str(package_manifest),
        "t10_package_root": str(package_manifest.parents[2]),
        "status": "materialized",
    }
    if not args.materialize_only:
        no_review = _run_t12(
            repo_root=repo_root,
            python_bin=args.python_bin.resolve(),
            paths=paths,
            output_root=output_root / "standalone",
            run_id=f"t12_{args.case_id}_no_review",
            review_decisions=None,
        )
        report["no_review"] = _validate_result(no_review, reviewed=False)
        if args.review_fixture is not None:
            t10_review_path = _rewrite_review_run_id(
                args.review_fixture.resolve(),
                output_root / "review" / "t10_review_decisions.csv",
                f"t12_{args.case_id}",
            )
            report["t10_review_decisions"] = str(t10_review_path)
            review_path = _rewrite_review_run_id(
                args.review_fixture.resolve(),
                output_root / "review" / "review_decisions.csv",
                f"t12_{args.case_id}_acceptance",
            )
            reviewed = _run_t12(
                repo_root=repo_root,
                python_bin=args.python_bin.resolve(),
                paths=paths,
                output_root=output_root / "standalone",
                run_id=f"t12_{args.case_id}_acceptance",
                review_decisions=review_path,
            )
            report["reviewed"] = _validate_result(reviewed, reviewed=True)
        report["status"] = "passed"
    report_path = output_root / "validation-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"report": str(report_path), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
