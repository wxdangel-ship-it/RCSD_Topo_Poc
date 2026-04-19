from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor import step6_geometry
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import (
    load_step45_case_specs,
    load_step45_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import Step67Context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import (
    build_step45_case_result,
)
from tests.modules.t03_virtual_junction_anchor._step45_helpers import (
    build_single_sided_parallel_support_case,
)


def _build_step67_context(case_root: Path, step3_root: Path, case_id: str) -> Step67Context:
    specs, _ = load_step45_case_specs(
        case_root=case_root,
        case_ids=[case_id],
        exclude_case_ids=["922217", "54265667", "502058682"],
    )
    step45_context = load_step45_context(case_spec=specs[0], step3_root=step3_root)
    step45_case_result = build_step45_case_result(step45_context)
    return Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )


def _same_geometry(left, right) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return left.equals_exact(right, 1e-6) or left.equals(right)


def test_build_step6_result_cache_preserves_semantics_and_records_stage_timers(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_single_sided_parallel_support_case(case_root, step3_root, case_id="100006")
    step67_context = _build_step67_context(case_root, step3_root, "100006")

    uncached_result = step6_geometry.build_step6_result(
        step67_context,
        use_step6_geometry_cache=False,
    )
    cached_stage_timers: dict[str, float] = {}
    cached_result = step6_geometry.build_step6_result(
        step67_context,
        stage_timers=cached_stage_timers,
        use_step6_geometry_cache=True,
    )

    assert cached_result.step6_state == uncached_result.step6_state
    assert cached_result.geometry_established == uncached_result.geometry_established
    assert cached_result.problem_geometry == uncached_result.problem_geometry
    assert cached_result.reason == uncached_result.reason
    assert cached_result.primary_root_cause == uncached_result.primary_root_cause
    assert cached_result.secondary_root_cause == uncached_result.secondary_root_cause
    assert cached_result.review_signals == uncached_result.review_signals
    assert cached_result.key_metrics == uncached_result.key_metrics
    assert cached_result.audit_doc == uncached_result.audit_doc
    assert cached_result.extra_status_fields == uncached_result.extra_status_fields
    assert _same_geometry(
        cached_result.output_geometries.polygon_seed_geometry,
        uncached_result.output_geometries.polygon_seed_geometry,
    )
    assert _same_geometry(
        cached_result.output_geometries.polygon_final_geometry,
        uncached_result.output_geometries.polygon_final_geometry,
    )
    assert _same_geometry(
        cached_result.output_geometries.foreign_mask_geometry,
        uncached_result.output_geometries.foreign_mask_geometry,
    )
    assert _same_geometry(
        cached_result.output_geometries.must_cover_geometry,
        uncached_result.output_geometries.must_cover_geometry,
    )
    assert set(cached_stage_timers) >= {
        "step6_mask_prep",
        "step6_directional_cut",
        "step6_finalize",
        "step6_finalize_cleanup",
        "step6_finalize_validation",
        "step6_finalize_status",
    }
    assert cached_stage_timers["step6_mask_prep"] >= 0.0
    assert cached_stage_timers["step6_directional_cut"] >= 0.0
    assert cached_stage_timers["step6_finalize"] >= 0.0
    assert cached_stage_timers["step6_finalize_cleanup"] >= 0.0
    assert cached_stage_timers["step6_finalize_validation"] >= 0.0
    assert cached_stage_timers["step6_finalize_status"] >= 0.0


def test_directional_cut_cache_reuses_single_sided_trace_preparation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    case_root = tmp_path / "cases"
    step3_root = tmp_path / "step3"
    build_single_sided_parallel_support_case(case_root, step3_root, case_id="100006")
    step67_context = _build_step67_context(case_root, step3_root, "100006")
    allowed_space = step6_geometry._clean_geometry(step67_context.step45_context.step3_allowed_space_geometry)
    bridge_geometry = step6_geometry._step3_two_node_t_bridge_geometry(step67_context, allowed_space)

    original_trace_candidates = step6_geometry._single_sided_trace_candidate_rcsdroad_records
    counts = {"trace_candidates": 0}

    def _count_trace_candidates(*args, **kwargs):
        counts["trace_candidates"] += 1
        return original_trace_candidates(*args, **kwargs)

    monkeypatch.setattr(
        step6_geometry,
        "_single_sided_trace_candidate_rcsdroad_records",
        _count_trace_candidates,
    )

    uncached_results = [
        step6_geometry._build_directional_cut_geometry(
            step67_context,
            allowed_space,
            step3_two_node_t_bridge_geometry=bridge_geometry,
        ),
        step6_geometry._build_directional_cut_geometry(
            step67_context,
            allowed_space,
            step3_two_node_t_bridge_geometry=bridge_geometry,
            force_preserve_single_sided_horizontal_pair=True,
        ),
        step6_geometry._build_directional_cut_geometry(
            step67_context,
            allowed_space,
            step3_two_node_t_bridge_geometry=bridge_geometry,
            force_preserve_all_branches=True,
        ),
    ]
    assert counts["trace_candidates"] == 3

    counts["trace_candidates"] = 0
    geometry_cache = step6_geometry._Step6GeometryCache()
    cached_results = [
        step6_geometry._build_directional_cut_geometry(
            step67_context,
            allowed_space,
            geometry_cache=geometry_cache,
            step3_two_node_t_bridge_geometry=bridge_geometry,
        ),
        step6_geometry._build_directional_cut_geometry(
            step67_context,
            allowed_space,
            geometry_cache=geometry_cache,
            step3_two_node_t_bridge_geometry=bridge_geometry,
            force_preserve_single_sided_horizontal_pair=True,
        ),
        step6_geometry._build_directional_cut_geometry(
            step67_context,
            allowed_space,
            geometry_cache=geometry_cache,
            step3_two_node_t_bridge_geometry=bridge_geometry,
            force_preserve_all_branches=True,
        ),
    ]
    assert counts["trace_candidates"] == 1

    for uncached_result, cached_result in zip(uncached_results, cached_results, strict=True):
        assert _same_geometry(cached_result[0], uncached_result[0])
        assert _same_geometry(cached_result[1], uncached_result[1])
        assert cached_result[2] == uncached_result[2]
