from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import (
    build_association_context_from_step3_case,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import CaseSpec
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import (
    FinalizationCaseResult,
    FinalizationContext,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_outputs import (
    write_case_outputs as write_finalization_case_outputs,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_observability import (
    accumulate_duration,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_shared_layers import (
    SharedFullInputLayers,
    collect_case_features,
    resolve_representative_feature,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import (
    build_step1_context_from_features,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step2_template import (
    classify_step2_template,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import (
    build_step3_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_outputs import (
    write_case_outputs as write_step3_case_outputs,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import (
    build_association_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_geometry import (
    build_step6_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step7_acceptance import (
    build_step7_result,
)


def _build_internal_case_spec(
    *,
    case_id: str,
    internal_root: Path,
    input_paths: dict[str, Path],
) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        mainnodeid=case_id,
        case_root=internal_root,
        manifest={
            "bundle_version": 1,
            "source_mode": "t03_internal_full_input_direct_local_query",
            "mainnodeid": case_id,
        },
        size_report={
            "within_limit": True,
            "source_mode": "t03_internal_full_input_direct_local_query",
        },
        input_paths=input_paths,
    )


def run_single_case_direct(
    *,
    case_id: str,
    shared_layers: SharedFullInputLayers,
    buffer_m: float,
    patch_size_m: float,
    resolution_m: float,
    internal_root: Path,
    run_root: Path,
    step3_run_root: Path,
    input_paths: dict[str, Path],
    debug_render: bool,
    render_review_png: bool,
) -> dict[str, Any]:
    stage_timers = {
        key: 0.0
        for key in (
            "local_feature_selection",
            "step3",
            "step3_reachable_support",
            "step3_negative_masks",
            "step3_cleanup_preview",
            "step3_hard_path_validation",
            "association",
            "step6",
            "step6_mask_prep",
            "step6_directional_cut",
            "step6_finalize",
            "step6_finalize_cleanup",
            "step6_finalize_validation",
            "step6_finalize_status",
            "step7",
            "output_write",
        )
    }

    local_feature_started_perf = perf_counter()
    representative_feature = resolve_representative_feature(shared_layers, case_id)
    selected = collect_case_features(
        shared_layers=shared_layers,
        case_id=case_id,
        buffer_m=buffer_m,
        patch_size_m=patch_size_m,
    )
    selected_counts = {
        "nodes": len(selected["nodes"]),
        "roads": len(selected["roads"]),
        "drivezones": len(selected["drivezones"]),
        "rcsd_roads": len(selected["rcsd_roads"]),
        "rcsd_nodes": len(selected["rcsd_nodes"]),
    }
    accumulate_duration(stage_timers, "local_feature_selection", perf_counter() - local_feature_started_perf)

    step3_started_perf = perf_counter()
    case_spec = _build_internal_case_spec(
        case_id=case_id,
        internal_root=internal_root,
        input_paths=input_paths,
    )
    step1_context = build_step1_context_from_features(
        case_spec=case_spec,
        node_features=selected["nodes"],
        road_features=selected["roads"],
        drivezone_features=selected["drivezones"],
        rcsdroad_features=selected["rcsd_roads"],
        rcsdnode_features=selected["rcsd_nodes"],
    )
    template_result = classify_step2_template(step1_context)
    step3_case_result = build_step3_case_result(
        step1_context,
        template_result,
        stage_timers=stage_timers,
    )
    step3_row = write_step3_case_outputs(
        run_root=step3_run_root,
        context=step1_context,
        case_result=step3_case_result,
        render_review_png=render_review_png,
    )
    accumulate_duration(stage_timers, "step3", perf_counter() - step3_started_perf)

    association_started_perf = perf_counter()
    association_context = build_association_context_from_step3_case(
        step1_context=step1_context,
        template_result=template_result,
        step3_run_root=step3_run_root,
        step3_case_dir=step3_run_root / "cases" / case_id,
        step3_case_result=step3_case_result,
    )
    association_case_result = build_association_case_result(association_context)
    accumulate_duration(stage_timers, "association", perf_counter() - association_started_perf)

    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_started_perf = perf_counter()
    step6_result = build_step6_result(
        finalization_context,
        stage_timers=stage_timers,
    )
    accumulate_duration(stage_timers, "step6", perf_counter() - step6_started_perf)

    step7_started_perf = perf_counter()
    step7_result = build_step7_result(finalization_context, step6_result)
    accumulate_duration(stage_timers, "step7", perf_counter() - step7_started_perf)
    finalization_case_result = FinalizationCaseResult(
        case_id=case_id,
        template_class=association_case_result.template_class,
        association_class=association_case_result.association_class,
        association_state=association_case_result.association_state,
        step6_result=step6_result,
        step7_result=step7_result,
    )
    output_write_started_perf = perf_counter()
    finalization_row = write_finalization_case_outputs(
        run_root=run_root,
        finalization_context=finalization_context,
        case_result=finalization_case_result,
        debug_render=debug_render,
        render_review_png=render_review_png,
    )
    accumulate_duration(stage_timers, "output_write", perf_counter() - output_write_started_perf)
    return {
        "case_id": case_id,
        "representative_feature": representative_feature,
        "selection_window": selected["selection_window"],
        "selected_counts": selected_counts,
        "step3_row": step3_row,
        "step3_case_result": step3_case_result,
        "finalization_row": finalization_row,
        "finalization_case_result": finalization_case_result,
        "stage_timers": stage_timers,
    }
