from __future__ import annotations

import json
import platform
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    build_run_id,
    normalize_runtime_path,
    write_json,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import (
    DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_loader import (
    load_step45_case_specs,
    load_step45_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_rcsd_association import (
    build_step45_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_acceptance import (
    build_step7_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_geometry import (
    build_step6_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_models import (
    Step67CaseResult,
    Step67Context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_writer import (
    materialize_review_gallery,
    write_case_outputs,
    write_review_index,
    write_summary,
)


DEFAULT_CASE_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor")
DEFAULT_STEP3_ROOT = Path("/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003")
DEFAULT_OUT_ROOT = Path("/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step67_phase")


def _preflight_doc(
    *,
    case_root: Path,
    step3_root: Path,
    out_root: Path,
    selected_case_ids: list[str],
    case_loader_preflight: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "case_root": str(case_root),
        "step3_root": str(step3_root),
        "out_root": str(out_root),
        "run_root": None,
        "raw_case_count": case_loader_preflight.get("raw_case_count"),
        "raw_case_ids": case_loader_preflight.get("raw_case_ids", []),
        "default_formal_case_count": case_loader_preflight.get("default_formal_case_count"),
        "default_formal_case_ids": case_loader_preflight.get("default_formal_case_ids", []),
        "formal_full_batch_case_count": case_loader_preflight.get("formal_full_batch_case_count"),
        "formal_full_batch_case_ids": case_loader_preflight.get("formal_full_batch_case_ids", []),
        "explicit_case_selection": case_loader_preflight.get("explicit_case_selection", False),
        "selected_case_count": len(selected_case_ids),
        "selected_case_ids": selected_case_ids,
        "default_full_batch_excluded_case_ids": case_loader_preflight.get("default_full_batch_excluded_case_ids", []),
        "excluded_case_ids": case_loader_preflight.get("excluded_case_ids", case_loader_preflight.get("applied_excluded_case_ids", [])),
        "effective_case_count": case_loader_preflight.get("effective_case_count", len(selected_case_ids)),
        "effective_case_ids": case_loader_preflight.get("effective_case_ids", selected_case_ids),
        "missing_case_ids": case_loader_preflight.get("missing_case_ids", []),
        "failed_case_ids": case_loader_preflight.get("failed_case_ids", []),
        "formal_acceptance_scope": (
            "explicit_case_selection"
            if case_loader_preflight.get("explicit_case_selection")
            else "default_full_batch"
        ),
        "loader_preflight": case_loader_preflight,
        "step45_source_mode": "recomputed_from_case_root_and_step3_root",
    }


def _run_single_case(spec, *, step3_root: Path):
    step45_context = load_step45_context(case_spec=spec, step3_root=step3_root)
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)
    step7_result = build_step7_result(step67_context, step6_result)
    case_result = Step67CaseResult(
        case_id=spec.case_id,
        template_class=step45_case_result.template_class,
        association_class=step45_case_result.association_class,
        step45_state=step45_case_result.step45_state,
        step6_result=step6_result,
        step7_result=step7_result,
    )
    return step67_context, case_result


def run_t03_step67_batch(
    *,
    case_root: str | Path = DEFAULT_CASE_ROOT,
    step3_root: str | Path = DEFAULT_STEP3_ROOT,
    case_ids: list[str] | None = None,
    max_cases: int | None = None,
    workers: int = 1,
    out_root: str | Path = DEFAULT_OUT_ROOT,
    run_id: str | None = None,
    debug: bool = False,
    debug_render: bool = False,
) -> Path:
    resolved_case_root = normalize_runtime_path(case_root)
    resolved_step3_root = normalize_runtime_path(step3_root)
    resolved_out_root = normalize_runtime_path(out_root)
    resolved_run_id = run_id or build_run_id("t03_step67_phase")
    run_root = resolved_out_root / resolved_run_id
    rerun_cleaned_before_write = False
    if run_root.exists():
        shutil.rmtree(run_root)
        rerun_cleaned_before_write = True
    run_root.mkdir(parents=True, exist_ok=True)

    specs, loader_preflight = load_step45_case_specs(
        case_root=resolved_case_root,
        case_ids=case_ids,
        max_cases=max_cases,
        exclude_case_ids=DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS,
    )
    preflight = _preflight_doc(
        case_root=resolved_case_root,
        step3_root=resolved_step3_root,
        out_root=resolved_out_root,
        selected_case_ids=[spec.case_id for spec in specs],
        case_loader_preflight=loader_preflight,
    )
    preflight["run_root"] = str(run_root)
    write_json(run_root / "preflight.json", preflight)

    review_rows = []
    failed_case_ids: list[str] = []
    max_workers = max(1, int(workers or 1))
    if max_workers == 1:
        for spec in specs:
            try:
                step67_context, case_result = _run_single_case(spec, step3_root=resolved_step3_root)
            except Exception:
                failed_case_ids.append(spec.case_id)
                continue
            review_rows.append(
                write_case_outputs(
                    run_root=run_root,
                    step67_context=step67_context,
                    case_result=case_result,
                    debug_render=debug_render,
                )
            )
    else:
        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="t03-step67") as executor:
            for spec in specs:
                futures[executor.submit(_run_single_case, spec, step3_root=resolved_step3_root)] = spec.case_id
            for future in as_completed(futures):
                case_id = futures[future]
                try:
                    step67_context, case_result = future.result()
                except Exception:
                    failed_case_ids.append(case_id)
                    continue
                review_rows.append(
                    write_case_outputs(
                        run_root=run_root,
                        step67_context=step67_context,
                        case_result=case_result,
                        debug_render=debug_render,
                    )
                )

    review_rows = materialize_review_gallery(run_root, review_rows)
    write_review_index(run_root, review_rows)
    summary_path = write_summary(
        run_root,
        review_rows,
        expected_case_ids=[spec.case_id for spec in specs],
        raw_case_count=loader_preflight.get("raw_case_count", len(specs)),
        default_formal_case_count=loader_preflight.get("default_formal_case_count", len(specs)),
        effective_case_ids=loader_preflight.get("effective_case_ids", [spec.case_id for spec in specs]),
        raw_case_ids=loader_preflight.get("raw_case_ids", []),
        default_formal_case_ids=loader_preflight.get("default_formal_case_ids", []),
        default_full_batch_excluded_case_ids=loader_preflight.get("default_full_batch_excluded_case_ids", []),
        excluded_case_ids=loader_preflight.get("applied_excluded_case_ids", []),
        explicit_case_selection=loader_preflight.get("explicit_case_selection", False),
        failed_case_ids=failed_case_ids,
        rerun_cleaned_before_write=rerun_cleaned_before_write,
    )
    summary_doc = json.loads(summary_path.read_text(encoding="utf-8"))
    preflight.update(
        {
            "excluded_case_ids": summary_doc.get("excluded_case_ids", preflight.get("excluded_case_ids", [])),
            "missing_case_ids": summary_doc.get("missing_case_ids", []),
            "failed_case_ids": summary_doc.get("failed_case_ids", []),
            "effective_case_ids": summary_doc.get("effective_case_ids", preflight.get("effective_case_ids", [])),
        }
    )
    write_json(run_root / "preflight.json", preflight)

    if debug:
        write_json(
            run_root / "debug_manifest.json",
            {
                "selected_case_ids": [row.case_id for row in review_rows],
                "review_rows": [row.__dict__ for row in review_rows],
                "excluded_case_ids": loader_preflight.get("applied_excluded_case_ids", []),
                "failed_case_ids": failed_case_ids,
                "rerun_cleaned_before_write": rerun_cleaned_before_write,
                "debug_render": debug_render,
            },
        )
    return run_root
