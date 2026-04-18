from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_batch_runner import (
    DEFAULT_CASE_ROOT,
    DEFAULT_OUT_ROOT,
    DEFAULT_STEP3_ROOT,
    run_t03_step45_rcsd_association_batch,
)


def run_t03_step45_rcsd_association_cli(args) -> int:
    run_root = run_t03_step45_rcsd_association_batch(
        case_root=args.case_root or DEFAULT_CASE_ROOT,
        step3_root=args.step3_root or DEFAULT_STEP3_ROOT,
        case_ids=list(args.case_id or []),
        max_cases=args.max_cases,
        workers=args.workers,
        out_root=args.out_root or DEFAULT_OUT_ROOT,
        run_id=args.run_id,
        debug=args.debug,
        debug_render=args.debug_render,
    )
    print(f"T03 Step4-5 RCSD association completed: {Path(run_root)}")
    return 0
