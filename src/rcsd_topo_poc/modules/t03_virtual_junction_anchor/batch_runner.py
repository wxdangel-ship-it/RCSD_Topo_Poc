from __future__ import annotations

import platform
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import build_run_id, normalize_runtime_path, write_json
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import load_case_specs
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.models import ReviewIndexRow, Step3CaseResult
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import build_step1_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step2_template import classify_step2_template
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import build_step3_case_result
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.writer import write_case_outputs, write_review_index, write_summary


DEFAULT_CASE_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor")
DEFAULT_OUT_ROOT = Path("/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a")


def _preflight_doc(*, case_root: Path, out_root: Path, selected_case_ids: list[str], case_loader_preflight: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "case_root": str(case_root),
        "out_root": str(out_root),
        "selected_case_count": len(selected_case_ids),
        "selected_case_ids": selected_case_ids,
        "loader_preflight": case_loader_preflight,
    }


def _run_single_case(spec) -> tuple[object, Step3CaseResult]:
    context = build_step1_context(spec)
    template_result = classify_step2_template(context)
    case_result = build_step3_case_result(context, template_result)
    return context, case_result


def run_t03_step3_legal_space_batch(
    *,
    case_root: str | Path = DEFAULT_CASE_ROOT,
    case_ids: list[str] | None = None,
    max_cases: int | None = None,
    workers: int = 1,
    out_root: str | Path = DEFAULT_OUT_ROOT,
    run_id: str | None = None,
    debug: bool = False,
) -> Path:
    resolved_case_root = normalize_runtime_path(case_root)
    resolved_out_root = normalize_runtime_path(out_root)
    resolved_run_id = run_id or build_run_id("t03_step3_phase_a")
    run_root = resolved_out_root / resolved_run_id
    rerun_cleaned_before_write = False
    if run_root.exists():
        shutil.rmtree(run_root)
        rerun_cleaned_before_write = True
    run_root.mkdir(parents=True, exist_ok=True)

    specs, loader_preflight = load_case_specs(case_root=resolved_case_root, case_ids=case_ids, max_cases=max_cases)
    preflight = _preflight_doc(
        case_root=resolved_case_root,
        out_root=resolved_out_root,
        selected_case_ids=[spec.case_id for spec in specs],
        case_loader_preflight=loader_preflight,
    )
    write_json(run_root / "preflight.json", preflight)

    review_rows: list[ReviewIndexRow] = []
    failed_case_ids: list[str] = []
    max_workers = max(1, int(workers or 1))
    if max_workers == 1:
        for spec in specs:
            try:
                context, case_result = _run_single_case(spec)
            except Exception:
                failed_case_ids.append(spec.case_id)
                continue
            review_rows.append(write_case_outputs(run_root=run_root, context=context, case_result=case_result))
    else:
        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="t03-step3") as executor:
            for spec in specs:
                futures[executor.submit(_run_single_case, spec)] = spec.case_id
            for future in as_completed(futures):
                case_id = futures[future]
                try:
                    context, case_result = future.result()
                except Exception:
                    failed_case_ids.append(case_id)
                    continue
                review_rows.append(write_case_outputs(run_root=run_root, context=context, case_result=case_result))
    review_rows.sort(key=lambda row: (0, int(row.case_id)) if row.case_id.isdigit() else (1, row.case_id))

    write_review_index(run_root, review_rows)
    write_summary(
        run_root,
        review_rows,
        expected_case_ids=[spec.case_id for spec in specs],
        failed_case_ids=failed_case_ids,
        rerun_cleaned_before_write=rerun_cleaned_before_write,
    )
    if debug:
        write_json(
            run_root / "debug_manifest.json",
            {
                "selected_case_ids": [row.case_id for row in review_rows],
                "review_rows": [row.__dict__ for row in review_rows],
                "failed_case_ids": failed_case_ids,
                "rerun_cleaned_before_write": rerun_cleaned_before_write,
            },
        )
    return run_root
