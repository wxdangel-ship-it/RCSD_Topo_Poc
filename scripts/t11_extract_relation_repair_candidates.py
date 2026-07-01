#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rcsd_topo_poc.modules.t11_manual_relation_review import extract_t11_relation_repair_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract T11 manual relation repair candidates from a T10 case root.")
    parser.add_argument("--t10-case-root", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--case-id", default="605415675")
    parser.add_argument("--existing-manual-csv", default=None, type=Path)
    args = parser.parse_args()

    artifacts = extract_t11_relation_repair_candidates(
        t10_case_root=args.t10_case_root,
        out_root=args.out_root,
        case_id=args.case_id,
        existing_manual_csv_path=args.existing_manual_csv,
    )
    print(
        json.dumps(
            {
                "run_root": str(artifacts.run_root),
                "candidate_count": artifacts.candidate_count,
                "candidates_csv": str(artifacts.candidates_csv),
                "manual_template_csv": str(artifacts.manual_template_csv),
                "anchor_audit_csv": str(artifacts.anchor_audit_csv) if artifacts.anchor_audit_csv else None,
                "anchor_manual_template_csv": (
                    str(artifacts.anchor_manual_template_csv) if artifacts.anchor_manual_template_csv else None
                ),
                "all_1v1_not_replaced_csv": (
                    str(artifacts.all_1v1_not_replaced_csv) if artifacts.all_1v1_not_replaced_csv else None
                ),
                "all_1v1_not_replaced_gpkg": (
                    str(artifacts.all_1v1_not_replaced_gpkg) if artifacts.all_1v1_not_replaced_gpkg else None
                ),
                "all_1v1_not_replaced_xlsx": (
                    str(artifacts.all_1v1_not_replaced_xlsx) if artifacts.all_1v1_not_replaced_xlsx else None
                ),
                "unreplaced_relation_gap_csv": (
                    str(artifacts.unreplaced_relation_gap_csv) if artifacts.unreplaced_relation_gap_csv else None
                ),
                "unreplaced_relation_gap_gpkg": (
                    str(artifacts.unreplaced_relation_gap_gpkg) if artifacts.unreplaced_relation_gap_gpkg else None
                ),
                "unreplaced_relation_gap_xlsx": (
                    str(artifacts.unreplaced_relation_gap_xlsx) if artifacts.unreplaced_relation_gap_xlsx else None
                ),
                "all_evidence_relation_gap_xlsx": (
                    str(artifacts.all_evidence_relation_gap_xlsx)
                    if artifacts.all_evidence_relation_gap_xlsx
                    else None
                ),
                "no_evidence_relation_gap_xlsx": (
                    str(artifacts.no_evidence_relation_gap_xlsx)
                    if artifacts.no_evidence_relation_gap_xlsx
                    else None
                ),
                "summary_json": str(artifacts.summary_json),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
