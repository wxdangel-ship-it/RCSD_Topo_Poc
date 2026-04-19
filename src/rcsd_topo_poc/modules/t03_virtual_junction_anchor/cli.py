from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_batch_runner import (
    DEFAULT_CASE_ROOT,
    DEFAULT_OUT_ROOT,
    run_t03_step3_legal_space_batch,
)


def run_t03_step3_legal_space_cli(args) -> int:
    run_root = run_t03_step3_legal_space_batch(
        case_root=args.case_root or DEFAULT_CASE_ROOT,
        case_ids=list(args.case_id or []),
        max_cases=args.max_cases,
        workers=args.workers,
        out_root=args.out_root or DEFAULT_OUT_ROOT,
        run_id=args.run_id,
        debug=args.debug,
    )
    print(f"T03 Step3 legal-space baseline completed: {Path(run_root)}")
    return 0
