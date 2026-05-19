#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rcsd_topo_poc.modules.t05_junction_surface_fusion.t03_relation_evidence_backfill import (  # noqa: E402
    backfill_t03_relation_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill T03 relation evidence for T05 Phase 2 by reading per-case "
            "step6_status/step6_audit outputs from an existing T03 run root."
        )
    )
    parser.add_argument("--t03-run-root", required=True, help="T03 run root containing relation evidence and cases/<case_id>/ outputs.")
    parser.add_argument("--out-root", default=None, help="Output directory. Defaults to <t03-run-root>/t05_phase2_handoff.")
    parser.add_argument(
        "--relation-evidence-path",
        default=None,
        help="Optional explicit t03_swsd_rcsd_relation_evidence.csv/json path.",
    )
    parser.add_argument("--case-id", action="append", default=[], help="Case id to include. Can be repeated.")
    parser.add_argument("--case-id-file", default=None, help="Optional text file with case ids separated by comma, whitespace, or newline.")
    parser.add_argument("--accepted-only", action="store_true", help="Keep only accepted rows when step7_state is available.")
    args = parser.parse_args()

    case_ids = list(args.case_id or [])
    if args.case_id_file:
        case_ids.extend(_read_case_id_file(Path(args.case_id_file)))

    artifacts = backfill_t03_relation_evidence(
        t03_run_root=args.t03_run_root,
        out_root=args.out_root,
        relation_evidence_path=args.relation_evidence_path,
        case_ids=case_ids,
        accepted_only=args.accepted_only,
    )
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _read_case_id_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [part.strip() for part in text.replace(",", " ").split() if part.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
