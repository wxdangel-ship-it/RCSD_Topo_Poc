#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Sequence

from rcsd_topo_poc.modules.t11_manual_relation_review import extract_t11_relation_repair_candidates


DEFAULT_BATCH_CASE_IDS = (
    "1885118",
    "605415675",
    "609214532",
    "706247",
    "74155468",
    "991176",
)


def _worker_count(value: str) -> int:
    workers = int(value)
    if not 1 <= workers <= 8:
        raise argparse.ArgumentTypeError("workers must be between 1 and 8")
    return workers


def _artifact_payload(artifacts: Any) -> dict[str, Any]:
    return {
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
            str(artifacts.all_evidence_relation_gap_xlsx) if artifacts.all_evidence_relation_gap_xlsx else None
        ),
        "no_evidence_relation_gap_xlsx": (
            str(artifacts.no_evidence_relation_gap_xlsx) if artifacts.no_evidence_relation_gap_xlsx else None
        ),
        "summary_json": str(artifacts.summary_json),
    }


def _run_case(*, t10_case_root: Path, out_root: Path, case_id: str, existing_manual_csv: Path | None) -> Any:
    return extract_t11_relation_repair_candidates(
        t10_case_root=t10_case_root,
        out_root=out_root,
        case_id=case_id,
        existing_manual_csv_path=existing_manual_csv,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract T11 manual relation repair candidates from a T10 case root.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--t10-case-root", type=Path)
    source.add_argument("--t10-suite-root", type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--case-id", default="605415675")
    parser.add_argument("--case-ids", nargs="+", default=None)
    parser.add_argument("--workers", type=_worker_count, default=2)
    parser.add_argument("--existing-manual-csv", default=None, type=Path)
    args = parser.parse_args(argv)

    if args.t10_case_root is not None:
        if args.case_ids is not None:
            parser.error("--case-ids can only be used with --t10-suite-root")
        artifacts = _run_case(
            t10_case_root=args.t10_case_root,
            out_root=args.out_root,
            case_id=args.case_id,
            existing_manual_csv=args.existing_manual_csv,
        )
        print(json.dumps(_artifact_payload(artifacts), ensure_ascii=False, indent=2))
        return 0

    if args.existing_manual_csv is not None:
        parser.error("--existing-manual-csv is only supported in single-case mode")
    case_ids = tuple(dict.fromkeys(args.case_ids or DEFAULT_BATCH_CASE_IDS))
    missing = [case_id for case_id in case_ids if not (args.t10_suite_root / case_id).is_dir()]
    if missing:
        parser.error(f"missing T10 case roots under --t10-suite-root: {', '.join(missing)}")

    def extract_case(case_id: str) -> Any:
        return _run_case(
            t10_case_root=args.t10_suite_root / case_id,
            out_root=args.out_root / case_id,
            case_id=case_id,
            existing_manual_csv=None,
        )

    with ThreadPoolExecutor(max_workers=min(args.workers, len(case_ids))) as pool:
        artifacts_by_case = list(pool.map(extract_case, case_ids))
    print(
        json.dumps(
            {
                "mode": "batch",
                "t10_suite_root": str(args.t10_suite_root),
                "out_root": str(args.out_root),
                "workers": min(args.workers, len(case_ids)),
                "case_count": len(case_ids),
                "cases": [
                    {"case_id": case_id, **_artifact_payload(artifacts)}
                    for case_id, artifacts in zip(case_ids, artifacts_by_case)
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
