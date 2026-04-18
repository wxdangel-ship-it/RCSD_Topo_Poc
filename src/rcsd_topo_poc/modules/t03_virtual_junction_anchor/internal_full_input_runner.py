from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
    sort_patch_key,
    write_json,
)
from rcsd_topo_poc.modules.t02_junction_anchor.text_bundle import (
    run_t02_decode_text_bundle,
    run_t02_export_text_bundle,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_full_input_poc import (
    _discover_candidate_mainnodeids,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.batch_runner import (
    run_t03_step3_legal_space_batch,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import (
    DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_batch_runner import (
    run_t03_step67_batch,
)


@dataclass(frozen=True)
class T03Step67InternalFullInputArtifacts:
    run_root: Path
    visual_check_dir: Path
    internal_root: Path
    case_root: Path
    step3_run_root: Path
    selected_case_ids: tuple[str, ...]
    discovered_case_ids: tuple[str, ...]
    excluded_case_ids: tuple[str, ...]


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_case_ids(case_ids: list[str]) -> list[str]:
    return sorted({str(case_id) for case_id in case_ids}, key=sort_patch_key)


def _write_internal_case_progress(
    *,
    case_progress_root: Path,
    case_id: str,
    state: str,
    current_stage: str,
    reason: str,
    detail: str,
    **extra: Any,
) -> None:
    case_progress_root.mkdir(parents=True, exist_ok=True)
    write_json(
        case_progress_root / f"{case_id}.json",
        {
            "case_id": str(case_id),
            "state": state,
            "current_stage": current_stage,
            "reason": reason,
            "detail": detail,
            "updated_at": _now_text(),
            **extra,
        },
    )


def _write_internal_progress(
    *,
    internal_root: Path,
    run_root: Path,
    phase: str,
    status: str,
    message: str,
    selected_case_ids: list[str],
    discovered_case_ids: list[str],
    excluded_case_ids: list[str],
    prepared_case_ids: list[str] | None = None,
    step3_run_root: Path | None = None,
    **extra: Any,
) -> None:
    payload = {
        "updated_at": _now_text(),
        "phase": phase,
        "status": status,
        "message": message,
        "run_root": str(run_root),
        "internal_root": str(internal_root),
        "selected_case_count": len(selected_case_ids),
        "selected_case_ids": list(selected_case_ids),
        "discovered_case_count": len(discovered_case_ids),
        "discovered_case_ids": list(discovered_case_ids),
        "default_full_batch_excluded_case_count": len(excluded_case_ids),
        "default_full_batch_excluded_case_ids": list(excluded_case_ids),
        "prepared_case_count": len(prepared_case_ids or []),
        "prepared_case_ids": list(prepared_case_ids or []),
        "step3_run_root": str(step3_run_root) if step3_run_root is not None else None,
        **extra,
    }
    write_json(internal_root / "internal_full_input_progress.json", payload)


def _prepare_case_package(
    *,
    case_id: str,
    nodes_path: Path,
    roads_path: Path,
    drivezone_path: Path,
    rcsdroad_path: Path,
    rcsdnode_path: Path,
    buffer_m: float,
    patch_size_m: float,
    resolution_m: float,
    bundle_root: Path,
    case_root: Path,
) -> dict[str, Any]:
    bundle_path = bundle_root / f"{case_id}.txt"
    artifacts = run_t02_export_text_bundle(
        nodes_path=nodes_path,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        mainnodeid=case_id,
        out_txt=bundle_path,
        buffer_m=buffer_m,
        patch_size_m=patch_size_m,
        resolution_m=resolution_m,
    )
    if not artifacts.success:
        detail = artifacts.failure_detail or artifacts.failure_reason or "bundle export failed"
        raise ValueError(f"case_id={case_id}: {detail}")

    decode_root = case_root / case_id
    if decode_root.exists():
        shutil.rmtree(decode_root)
    decoded = run_t02_decode_text_bundle(bundle_txt=bundle_path, out_dir=decode_root)
    return {
        "case_id": case_id,
        "bundle_txt_path": str(bundle_path),
        "decoded_case_root": str(decoded.out_dir),
        "bundle_size_bytes": artifacts.bundle_size_bytes,
    }


def _mirror_visual_checks(*, source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        same_dir = source_dir.resolve() == target_dir.resolve()
    except FileNotFoundError:
        same_dir = False
    if same_dir:
        return

    for png_path in sorted(source_dir.glob("*.png"), key=lambda path: sort_patch_key(path.name)):
        shutil.copy2(png_path, target_dir / png_path.name)


def run_t03_step67_internal_full_input(
    *,
    nodes_path: str | Path,
    roads_path: str | Path,
    drivezone_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str,
    workers: int = 1,
    max_cases: int | None = None,
    buffer_m: float = 100.0,
    patch_size_m: float = 200.0,
    resolution_m: float = 0.2,
    debug: bool = False,
    review_mode: bool = False,
    visual_check_dir: str | Path | None = None,
) -> T03Step67InternalFullInputArtifacts:
    resolved_nodes_path = normalize_runtime_path(nodes_path)
    resolved_roads_path = normalize_runtime_path(roads_path)
    resolved_drivezone_path = normalize_runtime_path(drivezone_path)
    resolved_rcsdroad_path = normalize_runtime_path(rcsdroad_path)
    resolved_rcsdnode_path = normalize_runtime_path(rcsdnode_path)
    resolved_out_root = normalize_runtime_path(out_root)
    resolved_visual_check_dir = (
        normalize_runtime_path(visual_check_dir)
        if visual_check_dir is not None
        else resolved_out_root / run_id / "visual_checks"
    )
    run_root = resolved_out_root / run_id

    discovered_case_ids = _stable_case_ids(
        _discover_candidate_mainnodeids(
            nodes_path=resolved_nodes_path,
            nodes_layer=None,
            nodes_crs=None,
        )
    )
    excluded_case_ids = _stable_case_ids(list(DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS))
    eligible_case_ids = [case_id for case_id in discovered_case_ids if case_id not in set(excluded_case_ids)]
    selected_case_ids = eligible_case_ids[:max_cases] if max_cases is not None else eligible_case_ids
    if not selected_case_ids:
        raise ValueError(
            "No eligible Step67 full-input cases were discovered after applying "
            "has_evd=yes, is_anchor=no, kind_2 in {4, 2048} and the default T03 excluded-case set."
        )

    internal_root = resolved_out_root / "_internal" / run_id
    bundle_root = internal_root / "bundles"
    case_root = internal_root / "case_packages"
    case_progress_root = internal_root / "case_progress"
    step3_out_root = internal_root / "step3_runs"
    if internal_root.exists():
        shutil.rmtree(internal_root)
    bundle_root.mkdir(parents=True, exist_ok=True)
    case_root.mkdir(parents=True, exist_ok=True)
    case_progress_root.mkdir(parents=True, exist_ok=True)
    step3_out_root.mkdir(parents=True, exist_ok=True)
    resolved_visual_check_dir.mkdir(parents=True, exist_ok=True)

    for case_id in selected_case_ids:
        _write_internal_case_progress(
            case_progress_root=case_progress_root,
            case_id=case_id,
            state="pending",
            current_stage="candidate_selection",
            reason="selected_for_step67_full_input",
            detail="eligible full-input candidate discovered and queued for internal preparation",
        )
    _write_internal_progress(
        internal_root=internal_root,
        run_root=run_root,
        phase="candidate_selection",
        status="running",
        message="Selected full-input candidates for T03 Step67 internal execution.",
        selected_case_ids=selected_case_ids,
        discovered_case_ids=discovered_case_ids,
        excluded_case_ids=excluded_case_ids,
    )

    prep_rows: list[dict[str, Any]] = []
    prep_failures: list[str] = []
    max_workers = max(1, int(workers or 1))
    _write_internal_progress(
        internal_root=internal_root,
        run_root=run_root,
        phase="case_package_prepare",
        status="running",
        message="Preparing T03 case-packages from shared full-input sources.",
        selected_case_ids=selected_case_ids,
        discovered_case_ids=discovered_case_ids,
        excluded_case_ids=excluded_case_ids,
        prepared_case_ids=[],
    )
    if max_workers == 1:
        for case_id in selected_case_ids:
            try:
                prepared_row = _prepare_case_package(
                        case_id=case_id,
                        nodes_path=resolved_nodes_path,
                        roads_path=resolved_roads_path,
                        drivezone_path=resolved_drivezone_path,
                        rcsdroad_path=resolved_rcsdroad_path,
                        rcsdnode_path=resolved_rcsdnode_path,
                        buffer_m=buffer_m,
                        patch_size_m=patch_size_m,
                        resolution_m=resolution_m,
                        bundle_root=bundle_root,
                        case_root=case_root,
                    )
                prep_rows.append(prepared_row)
                _write_internal_case_progress(
                    case_progress_root=case_progress_root,
                    case_id=case_id,
                    state="prepared",
                    current_stage="case_package_prepare",
                    reason="case_package_prepared",
                    detail=f"bundle prepared and decoded into internal case root ({prepared_row['bundle_size_bytes']} bytes)",
                )
                _write_internal_progress(
                    internal_root=internal_root,
                    run_root=run_root,
                    phase="case_package_prepare",
                    status="running",
                    message=f"Prepared case-package for case_id={case_id}.",
                    selected_case_ids=selected_case_ids,
                    discovered_case_ids=discovered_case_ids,
                    excluded_case_ids=excluded_case_ids,
                    prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
                    current_case_id=case_id,
                )
            except Exception as exc:
                prep_failures.append(f"{case_id}: {exc}")
                _write_internal_case_progress(
                    case_progress_root=case_progress_root,
                    case_id=case_id,
                    state="failed",
                    current_stage="case_package_prepare",
                    reason="case_package_prepare_failed",
                    detail=str(exc),
                )
    else:
        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="t03-full-input") as executor:
            for case_id in selected_case_ids:
                futures[
                    executor.submit(
                        _prepare_case_package,
                        case_id=case_id,
                        nodes_path=resolved_nodes_path,
                        roads_path=resolved_roads_path,
                        drivezone_path=resolved_drivezone_path,
                        rcsdroad_path=resolved_rcsdroad_path,
                        rcsdnode_path=resolved_rcsdnode_path,
                        buffer_m=buffer_m,
                        patch_size_m=patch_size_m,
                        resolution_m=resolution_m,
                        bundle_root=bundle_root,
                        case_root=case_root,
                    )
                ] = case_id
            for future in as_completed(futures):
                case_id = futures[future]
                try:
                    prepared_row = future.result()
                    prep_rows.append(prepared_row)
                    _write_internal_case_progress(
                        case_progress_root=case_progress_root,
                        case_id=case_id,
                        state="prepared",
                        current_stage="case_package_prepare",
                        reason="case_package_prepared",
                        detail=f"bundle prepared and decoded into internal case root ({prepared_row['bundle_size_bytes']} bytes)",
                    )
                    _write_internal_progress(
                        internal_root=internal_root,
                        run_root=run_root,
                        phase="case_package_prepare",
                        status="running",
                        message=f"Prepared case-package for case_id={case_id}.",
                        selected_case_ids=selected_case_ids,
                        discovered_case_ids=discovered_case_ids,
                        excluded_case_ids=excluded_case_ids,
                        prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
                        current_case_id=case_id,
                    )
                except Exception as exc:
                    prep_failures.append(f"{case_id}: {exc}")
                    _write_internal_case_progress(
                        case_progress_root=case_progress_root,
                        case_id=case_id,
                        state="failed",
                        current_stage="case_package_prepare",
                        reason="case_package_prepare_failed",
                        detail=str(exc),
                    )
    if prep_failures:
        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase="case_package_prepare",
            status="failed",
            message="Failed to prepare one or more case-packages.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
            failures=prep_failures,
        )
        raise ValueError("Failed to prepare T03 full-input case-packages: " + " | ".join(prep_failures))

    _write_internal_progress(
        internal_root=internal_root,
        run_root=run_root,
        phase="step3_batch",
        status="running",
        message="Running frozen T03 Step3 baseline on prepared case-packages.",
        selected_case_ids=selected_case_ids,
        discovered_case_ids=discovered_case_ids,
        excluded_case_ids=excluded_case_ids,
        prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
    )
    try:
        step3_run_root = run_t03_step3_legal_space_batch(
            case_root=case_root,
            workers=max_workers,
            out_root=step3_out_root,
            run_id=f"{run_id}__step3",
            debug=debug,
        )
    except Exception as exc:
        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase="step3_batch",
            status="failed",
            message="T03 Step3 batch failed before Step67 could start.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
            failure=str(exc),
        )
        raise
    for case_id in selected_case_ids:
        step3_status_path = step3_run_root / "cases" / case_id / "step3_status.json"
        if step3_status_path.is_file():
            step3_status_doc = json.loads(step3_status_path.read_text(encoding="utf-8"))
            _write_internal_case_progress(
                case_progress_root=case_progress_root,
                case_id=case_id,
                state="step3_ready",
                current_stage="step3_batch",
                reason=str(step3_status_doc.get("reason") or step3_status_doc.get("step3_state") or "step3_ready"),
                detail="step3 prerequisite outputs are ready for Step67 batch execution",
                step3_state=step3_status_doc.get("step3_state"),
            )
        else:
            _write_internal_case_progress(
                case_progress_root=case_progress_root,
                case_id=case_id,
                state="failed",
                current_stage="step3_batch",
                reason="step3_output_missing",
                detail="step3_status.json was not written for the prepared case",
            )
    _write_internal_progress(
        internal_root=internal_root,
        run_root=run_root,
        phase="step67_batch",
        status="running",
        message="Running T03 Step67 batch on top of prepared case-packages and Step3 outputs.",
        selected_case_ids=selected_case_ids,
        discovered_case_ids=discovered_case_ids,
        excluded_case_ids=excluded_case_ids,
        prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
        step3_run_root=step3_run_root,
    )
    try:
        run_root = run_t03_step67_batch(
            case_root=case_root,
            step3_root=step3_run_root,
            workers=max_workers,
            out_root=resolved_out_root,
            run_id=run_id,
            debug=debug,
            debug_render=debug,
        )
    except Exception as exc:
        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase="step67_batch",
            status="failed",
            message="T03 Step67 batch failed before summary was written.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
            step3_run_root=step3_run_root,
            failure=str(exc),
        )
        raise
    _mirror_visual_checks(
        source_dir=run_root / "step67_review_flat",
        target_dir=resolved_visual_check_dir,
    )
    _write_internal_progress(
        internal_root=internal_root,
        run_root=run_root,
        phase="completed",
        status="completed",
        message="T03 Step67 internal full-input execution completed.",
        selected_case_ids=selected_case_ids,
        discovered_case_ids=discovered_case_ids,
        excluded_case_ids=excluded_case_ids,
        prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
        step3_run_root=step3_run_root,
    )

    write_json(
        internal_root / "internal_full_input_manifest.json",
        {
            "run_id": run_id,
            "nodes_path": str(resolved_nodes_path),
            "roads_path": str(resolved_roads_path),
            "drivezone_path": str(resolved_drivezone_path),
            "rcsdroad_path": str(resolved_rcsdroad_path),
            "rcsdnode_path": str(resolved_rcsdnode_path),
            "out_root": str(resolved_out_root),
            "run_root": str(run_root),
            "case_root": str(case_root),
            "step3_run_root": str(step3_run_root),
            "visual_check_dir": str(resolved_visual_check_dir),
            "workers": max_workers,
            "max_cases": max_cases,
            "buffer_m": buffer_m,
            "patch_size_m": patch_size_m,
            "resolution_m": resolution_m,
            "debug": debug,
            "review_mode_requested": review_mode,
            "review_mode_effective": False,
            "review_mode_note": (
                "accepted for parameter compatibility only; "
                "T03 internal full-input runner keeps formal Step67 semantics unchanged"
            ),
            "discovered_case_ids": discovered_case_ids,
            "default_full_batch_excluded_case_ids": excluded_case_ids,
            "selected_case_ids": list(selected_case_ids),
            "prepared_cases": sorted(prep_rows, key=lambda row: sort_patch_key(str(row["case_id"]))),
            "progress_path": str(internal_root / "internal_full_input_progress.json"),
            "case_progress_root": str(case_progress_root),
        },
    )

    return T03Step67InternalFullInputArtifacts(
        run_root=run_root,
        visual_check_dir=resolved_visual_check_dir,
        internal_root=internal_root,
        case_root=case_root,
        step3_run_root=step3_run_root,
        selected_case_ids=tuple(selected_case_ids),
        discovered_case_ids=tuple(discovered_case_ids),
        excluded_case_ids=tuple(excluded_case_ids),
    )
