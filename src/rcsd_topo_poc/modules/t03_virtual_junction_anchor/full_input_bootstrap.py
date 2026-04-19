from __future__ import annotations

import platform
import sys
from typing import Any


def build_shared_memory_summary() -> dict[str, Any]:
    return {
        "enabled": False,
        "node_group_lookup": False,
        "shared_local_layer_query": False,
        "layers": {},
    }


def select_candidate_case_ids(
    *,
    discovered_case_ids: list[str],
    excluded_case_ids: list[str],
    max_cases: int | None,
) -> dict[str, list[str]]:
    excluded_case_id_set = set(excluded_case_ids)
    eligible_case_ids = [
        case_id for case_id in discovered_case_ids if case_id not in excluded_case_id_set
    ]
    selected_case_ids = eligible_case_ids[:max_cases] if max_cases is not None else list(eligible_case_ids)
    return {
        "eligible_case_ids": list(eligible_case_ids),
        "selected_case_ids": list(selected_case_ids),
    }


def build_full_input_preflight_doc(
    *,
    nodes_path: str,
    roads_path: str,
    drivezone_path: str,
    rcsdroad_path: str,
    rcsdnode_path: str,
    out_root: str,
    run_root: str,
    visual_check_dir: str,
    discovered_case_ids: list[str],
    default_formal_case_ids: list[str],
    selected_case_ids: list[str],
    excluded_case_ids: list[str],
    review_mode: bool,
    now_text: str,
) -> dict[str, Any]:
    return {
        "generated_at": now_text,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
        "out_root": out_root,
        "run_root": run_root,
        "visual_check_dir": visual_check_dir,
        "raw_case_count": len(discovered_case_ids),
        "raw_case_ids": list(discovered_case_ids),
        "default_formal_case_count": len(default_formal_case_ids),
        "default_formal_case_ids": list(default_formal_case_ids),
        "formal_full_batch_case_count": len(default_formal_case_ids),
        "formal_full_batch_case_ids": list(default_formal_case_ids),
        "selected_case_count": len(selected_case_ids),
        "selected_case_ids": list(selected_case_ids),
        "effective_case_count": len(selected_case_ids),
        "effective_case_ids": list(selected_case_ids),
        "excluded_case_ids": list(excluded_case_ids),
        "default_full_batch_excluded_case_ids": list(excluded_case_ids),
        "explicit_case_selection": False,
        "execution_mode": "direct_shared_handle_local_query",
        "review_mode_requested": review_mode,
        "review_mode_effective": False,
    }


def build_step3_preflight_doc(
    *,
    case_root: str,
    step3_run_root: str,
    selected_case_ids: list[str],
    discovered_case_ids: list[str],
    default_formal_case_ids: list[str],
    excluded_case_ids: list[str],
    now_text: str,
) -> dict[str, Any]:
    return {
        "generated_at": now_text,
        "case_root": case_root,
        "run_root": step3_run_root,
        "execution_mode": "direct_shared_handle_local_query",
        "selected_case_ids": list(selected_case_ids),
        "raw_case_count": len(discovered_case_ids),
        "default_formal_case_count": len(default_formal_case_ids),
        "excluded_case_ids": list(excluded_case_ids),
    }


__all__ = [
    "build_full_input_preflight_doc",
    "build_shared_memory_summary",
    "build_step3_preflight_doc",
    "select_candidate_case_ids",
]
