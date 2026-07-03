#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rcsd_topo_poc.modules.t11_manual_relation_review.manual_rerun import (  # noqa: E402
    build_t05_manual_relation_final_rejected_reports,
    compare_t06_run_metrics,
    import_t11_manual_review_xlsx_to_csv,
    resolve_rcsd_inputs_from_case_root,
    resolve_t11_manual_review_xlsx_paths,
)


def main() -> int:
    args = _parse_args()
    case_root = args.case_root
    manual_audit_root = args.manual_audit_root
    run_root = _prepare_run_root(args.out_root)
    manual_csv = run_root / "t11_manual_relation_merged.csv"

    xlsx_paths = resolve_t11_manual_review_xlsx_paths(
        manual_audit_root=manual_audit_root,
        all_1v1_xlsx=args.all_1v1_xlsx,
        all_evidence_xlsx=args.all_evidence_xlsx,
        no_evidence_xlsx=args.no_evidence_xlsx,
    )
    import_artifacts = import_t11_manual_review_xlsx_to_csv(
        xlsx_paths=xlsx_paths,
        out_csv=manual_csv,
        case_id=args.case_id,
    )
    rcsdroad, rcsdnode = resolve_rcsd_inputs_from_case_root(case_root)

    t05_root = run_root / "t05"
    t06_out_root = run_root / "t06_step12"
    _run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "t05_innernet_experiment.py"),
            "--t07-input",
            str(case_root / "t07" / "t07" / "step2_anchor_recognition" / "t07_rcsdintersection_anchor_surface.gpkg"),
            "--t07-evidence",
            str(case_root / "t07" / "t07" / "step2_anchor_recognition" / "t07_swsd_rcsd_relation_evidence.csv"),
            "--t03-surface",
            str(case_root / "t03" / "t03" / "virtual_intersection_polygons.gpkg"),
            "--t03-evidence",
            str(case_root / "t03" / "t03" / "t03_swsd_rcsd_relation_evidence.csv"),
            "--t04-surface",
            str(case_root / "t04" / "t04" / "divmerge_virtual_anchor_surface.gpkg"),
            "--t04-evidence",
            str(case_root / "t04" / "t04" / "t04_swsd_rcsd_relation_evidence.csv"),
            "--t04-summary",
            str(case_root / "t04" / "t04" / "divmerge_virtual_anchor_surface_summary.csv"),
            "--t04-audit",
            str(case_root / "t04" / "t04" / "divmerge_virtual_anchor_surface_audit.gpkg"),
            "--t04-case-root",
            str(case_root / "t04" / "t04" / "cases"),
            "--rcsdroad",
            str(rcsdroad),
            "--rcsdnode",
            str(rcsdnode),
            "--nodes",
            str(case_root / "t04" / "t04" / "nodes.gpkg"),
            "--t11-manual-relation",
            str(manual_csv),
            "--out-root",
            str(t05_root),
            "--phase1-run-id",
            "t05_phase1",
            "--phase2-run-id",
            "t05_phase2",
            "--readonly-workers",
            str(args.readonly_workers),
            "--progress-interval",
            str(args.progress_interval),
        ]
    )
    final_rejected_artifacts = build_t05_manual_relation_final_rejected_reports(
        manual_relation_csv=manual_csv,
        t05_phase2_root=t05_root / "t05_phase2",
    )
    _run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "t06_run_innernet_precheck.py"),
            "--swsd-segment",
            str(case_root / "t01" / "segment.gpkg"),
            "--swsd-roads",
            str(case_root / "t01" / "roads.gpkg"),
            "--swsd-nodes",
            str(case_root / "t04" / "t04" / "nodes.gpkg"),
            "--t05-phase2-root",
            str(t05_root / "t05_phase2"),
            "--out-root",
            str(t06_out_root),
            "--run-id",
            "t06",
            "--progress",
            "--no-write-json-outputs",
        ]
    )
    _run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "t06_run_step3_segment_replacement.py"),
            "--t06-run-root",
            str(t06_out_root / "t06"),
            "--t05-phase2-root",
            str(t05_root / "t05_phase2"),
            "--swsd-segment",
            str(case_root / "t01" / "segment.gpkg"),
            "--swsd-roads",
            str(case_root / "t01" / "roads.gpkg"),
            "--swsd-nodes",
            str(case_root / "t04" / "t04" / "nodes.gpkg"),
            "--t07-surface",
            str(case_root / "t07" / "t07" / "step2_anchor_recognition" / "t07_rcsdintersection_anchor_surface.gpkg"),
            "--t03-surface",
            str(case_root / "t03" / "t03" / "virtual_intersection_polygons.gpkg"),
            "--t04-surface",
            str(case_root / "t04" / "t04" / "divmerge_virtual_anchor_surface.gpkg"),
            "--t04-audit",
            str(case_root / "t04" / "t04" / "divmerge_virtual_anchor_surface_audit.gpkg"),
            "--t05-surface",
            str(t05_root / "t05_phase1" / "junction_anchor_surface.gpkg"),
            "--out-root",
            str(t06_out_root),
            "--run-id",
            "t06",
            "--progress",
        ]
    )
    compare = compare_t06_run_metrics(
        before_t06_root=case_root / "t06_step12" / "t06",
        after_t06_root=t06_out_root / "t06",
        out_json=run_root / "manual_rerun_metric_compare.json",
    )
    payload = {
        "run_root": str(run_root),
        "manual_relation_csv": str(import_artifacts.manual_relation_csv),
        "manual_relation_import_summary": str(import_artifacts.summary_json),
        "t05_phase2_root": str(t05_root / "t05_phase2"),
        "t05_manual_relation_final_rejected_summary": str(final_rejected_artifacts.summary_json),
        "t05_manual_relation_final_rejected_csv": str(final_rejected_artifacts.rejected_csv),
        "t05_manual_relation_graph_unconsumable_reference_csv": str(
            final_rejected_artifacts.graph_unconsumable_reference_csv
        ),
        "t06_run_root": str(t06_out_root / "t06"),
        "metric_compare_json": str(run_root / "manual_rerun_metric_compare.json"),
        "manual_import": import_artifacts.summary,
        "t05_manual_relation_final_rejected": final_rejected_artifacts.summary,
        "metric_compare": compare,
    }
    (run_root / "t11_manual_rerun_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import T11 manual review Excel files and rerun T05/T06 for one T10 case.")
    parser.add_argument("--case-root", required=True, type=Path, help="T10 case root, for example <run>/cases/605415675.")
    parser.add_argument("--manual-audit-root", required=True, type=Path, help="T11 manual audit run root containing the three Excel review files.")
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--case-id", default="605415675")
    parser.add_argument("--all-1v1-xlsx", default=None, type=Path)
    parser.add_argument("--all-evidence-xlsx", default=None, type=Path)
    parser.add_argument("--no-evidence-xlsx", default=None, type=Path)
    parser.add_argument("--readonly-workers", type=int, default=4)
    parser.add_argument("--progress-interval", type=int, default=100)
    return parser.parse_args()


def _prepare_run_root(out_root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = out_root / f"run_{stamp}"
    run_root.mkdir(parents=True, exist_ok=False)
    return run_root


def _run(command: list[str]) -> None:
    print("[RUN] " + " ".join(command), flush=True)
    subprocess.run(command, cwd=REPO_ROOT, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
