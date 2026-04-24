from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_json

from .case_models import T04CaseBundle, T04CaseSpec
from .event_interpretation import build_case_result
from .full_input_shared_layers import T04SharedFullInputLayers, collect_case_features
from .outputs import write_case_outputs
from .step4_rcsd_anchored_reverse import apply_rcsd_anchored_reverse_lookup
from .step4_final_conflict_resolver import resolve_step4_final_conflicts
from .step4_road_surface_fork_binding import apply_road_surface_fork_binding


def build_case_bundle_from_shared(
    *,
    case_id: str,
    shared_layers: T04SharedFullInputLayers,
    input_paths: dict[str, Path],
    run_root: Path,
    local_query_buffer_m: float,
) -> tuple[T04CaseBundle, dict[str, Any]]:
    selected = collect_case_features(
        layers=shared_layers,
        case_id=case_id,
        local_query_buffer_m=local_query_buffer_m,
    )
    case_spec = T04CaseSpec(
        case_id=str(case_id),
        mainnodeid=str(case_id),
        case_root=run_root / "cases" / str(case_id),
        manifest={
            "bundle_version": 1,
            "source_mode": "t04_internal_full_input_direct_shared_layers",
            "mainnodeid": str(case_id),
            "epsg": 3857,
        },
        size_report={
            "within_limit": True,
            "source_mode": "t04_internal_full_input_direct_shared_layers",
        },
        input_paths={key: Path(value) for key, value in input_paths.items()},
    )
    bundle = T04CaseBundle(
        case_spec=case_spec,
        nodes=tuple(selected["nodes"]),
        roads=tuple(selected["roads"]),
        rcsd_roads=tuple(selected["rcsd_roads"]),
        rcsd_nodes=tuple(selected["rcsd_nodes"]),
        drivezone_features=tuple(selected["drivezone_features"]),
        divstrip_features=tuple(selected["divstrip_features"]),
        representative_node=selected["representative_node"],
        group_nodes=tuple(selected["group_nodes"]),
    )
    return bundle, selected


def run_single_case_direct(
    *,
    case_id: str,
    shared_layers: T04SharedFullInputLayers,
    input_paths: dict[str, Path],
    run_root: Path,
    local_query_buffer_m: float,
) -> dict[str, Any]:
    stage_timers = {
        "local_feature_selection": 0.0,
        "step1_4": 0.0,
        "same_case_resolution": 0.0,
        "step5_7_output_write": 0.0,
    }

    started = perf_counter()
    bundle, selected = build_case_bundle_from_shared(
        case_id=case_id,
        shared_layers=shared_layers,
        input_paths=input_paths,
        run_root=run_root,
        local_query_buffer_m=local_query_buffer_m,
    )
    stage_timers["local_feature_selection"] = round(perf_counter() - started, 6)

    step14_started = perf_counter()
    case_result = build_case_result(bundle)
    stage_timers["step1_4"] = round(perf_counter() - step14_started, 6)

    resolution_started = perf_counter()
    resolved_results, resolution_doc = resolve_step4_final_conflicts([case_result])
    surface_results, surface_binding_doc = apply_road_surface_fork_binding(resolved_results)
    reverse_results, reverse_doc = apply_rcsd_anchored_reverse_lookup(surface_results)
    resolved_case_result = reverse_results[0] if reverse_results else case_result
    stage_timers["same_case_resolution"] = round(perf_counter() - resolution_started, 6)

    output_started = perf_counter()
    case_dir = run_root / "cases" / str(case_id)
    write_json(case_dir / "step4_road_surface_fork_binding.json", surface_binding_doc)
    write_json(case_dir / "step4_rcsd_anchored_reverse.json", reverse_doc)
    review_rows, step7_artifact = write_case_outputs(
        run_root=run_root,
        case_result=resolved_case_result,
    )
    stage_timers["step5_7_output_write"] = round(perf_counter() - output_started, 6)

    return {
        "case_id": str(case_id),
        "case_dir": str(case_dir),
        "selected_counts": dict(selected["selected_counts"]),
        "selection_window_bounds": [round(float(value), 6) for value in selected["selection_window"].bounds],
        "resolution_doc": resolution_doc,
        "road_surface_fork_binding_doc": surface_binding_doc,
        "rcsd_anchored_reverse_doc": reverse_doc,
        "review_rows": review_rows,
        "step7_artifact": step7_artifact,
        "final_state": step7_artifact.final_state,
        "reject_reasons": list(step7_artifact.reject_reasons),
        "stage_timers": stage_timers,
    }


__all__ = [
    "build_case_bundle_from_shared",
    "run_single_case_direct",
]
