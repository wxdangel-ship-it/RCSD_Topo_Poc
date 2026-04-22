from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    sort_patch_key,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv

from .case_models import T04CaseResult, T04ReviewIndexRow
from .review_audit import build_case_review_audit
from .review_render import (
    render_case_overview_png,
    render_event_unit_candidate_compare_png,
    render_event_unit_review_png,
)
from .topology import build_step3_status_doc, build_unit_step3_status_doc


REVIEW_INDEX_FIELDNAMES = [
    "sequence_no",
    "case_id",
    "event_unit_id",
    "event_type",
    "review_state",
    "evidence_source",
    "position_source",
    "reverse_tip_used",
    "rcsd_consistency_result",
    "positive_rcsd_support_level",
    "positive_rcsd_consistency_level",
    "positive_rcsd_present",
    "positive_rcsd_present_reason",
    "pair_local_rcsd_empty",
    "rcsd_selection_mode",
    "local_rcsd_unit_kind",
    "local_rcsd_unit_id",
    "aggregated_rcsd_unit_id",
    "aggregated_rcsd_unit_ids",
    "axis_polarity_inverted",
    "first_hit_rcsdroad_ids",
    "selected_rcsdroad_ids",
    "selected_rcsdnode_ids",
    "primary_main_rc_node",
    "required_rcsd_node",
    "required_rcsd_node_source",
    "selected_candidate_region",
    "selected_evidence_state",
    "selected_evidence_kind",
    "primary_candidate_id",
    "primary_candidate_layer",
    "primary_candidate_layer_reason",
    "axis_position_m",
    "reference_distance_to_origin_m",
    "has_alternative_candidates",
    "candidate_pool_size",
    "selected_reference_zone",
    "selected_evidence_membership",
    "better_alternative_signal",
    "best_alternative_candidate_id",
    "best_alternative_layer",
    "best_alternative_reason",
    "shared_object_signal",
    "shared_region_signal",
    "shared_point_signal",
    "conflict_signal_level",
    "related_unit_ids",
    "key_reason",
    "needs_manual_review_focus",
    "focus_reasons",
    "ownership_signature",
    "upper_evidence_object_id",
    "local_region_id",
    "point_signature",
    "image_name",
    "image_path",
    "compare_image_name",
    "compare_image_path",
    "case_overview_path",
]


def _geometry_features_for_case(case_result: T04CaseResult):
    features: list[dict] = []
    for event_unit in case_result.event_units:
        for geometry_role, geometry in (
            ("pair_local_region_geometry", event_unit.pair_local_region_geometry),
            ("pair_local_structure_face_geometry", event_unit.pair_local_structure_face_geometry),
            ("pair_local_middle_geometry", event_unit.pair_local_middle_geometry),
            ("pair_local_throat_core_geometry", event_unit.pair_local_throat_core_geometry),
            ("selected_candidate_region_geometry", event_unit.selected_candidate_region_geometry),
            ("selected_evidence_region_geometry", event_unit.selected_evidence_region_geometry),
            ("coarse_anchor_zone_geometry", event_unit.coarse_anchor_zone_geometry),
            ("selected_component_union_geometry", event_unit.selected_component_union_geometry),
            ("localized_evidence_core_geometry", event_unit.localized_evidence_core_geometry),
            ("fact_reference_point", event_unit.fact_reference_point),
            ("review_materialized_point", event_unit.review_materialized_point),
            ("pair_local_rcsd_scope_geometry", event_unit.pair_local_rcsd_scope_geometry),
            ("first_hit_rcsd_road_geometry", event_unit.first_hit_rcsd_road_geometry),
            ("local_rcsd_unit_geometry", event_unit.local_rcsd_unit_geometry),
            ("positive_rcsd_geometry", event_unit.positive_rcsd_geometry),
            ("positive_rcsd_road_geometry", event_unit.positive_rcsd_road_geometry),
            ("positive_rcsd_node_geometry", event_unit.positive_rcsd_node_geometry),
            ("primary_main_rc_node_geometry", event_unit.primary_main_rc_node_geometry),
            ("required_rcsd_node_geometry", event_unit.required_rcsd_node_geometry),
        ):
            if geometry is None or geometry.is_empty:
                continue
            features.append(
                {
                    "properties": {
                        "case_id": case_result.case_spec.case_id,
                        "event_unit_id": event_unit.spec.event_unit_id,
                        "geometry_role": geometry_role,
                        "event_type": event_unit.spec.event_type,
                        "review_state": event_unit.review_state,
                        "candidate_id": str(event_unit.selected_evidence_summary.get("candidate_id") or ""),
                        "candidate_layer": str(event_unit.selected_evidence_summary.get("layer_label") or ""),
                    },
                    "geometry": geometry,
                }
            )
    return features


def write_case_outputs(
    *,
    run_root: Path,
    case_result: T04CaseResult,
) -> list[T04ReviewIndexRow]:
    case_dir = run_root / "cases" / case_result.case_spec.case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    write_json(case_dir / "step1_status.json", case_result.admission.to_status_doc())
    write_json(case_dir / "case_meta.json", case_result.to_case_meta_doc())
    write_json(
        case_dir / "step3_status.json",
        build_step3_status_doc(
            admission=case_result.base_context.admission,
            topology_skeleton=case_result.base_context.topology_skeleton,
        ),
    )
    write_json(
        case_dir / "step3_audit.json",
        {
            "step2_local_context": case_result.base_context.local_context.to_audit_summary(),
            "step3_topology_skeleton": case_result.base_context.topology_skeleton.to_audit_summary(),
        },
    )
    write_json(
        case_dir / "step4_event_interpretation.json",
        {
            "case_id": case_result.case_spec.case_id,
            "case_review_state": case_result.case_review_state,
            "case_review_reasons": list(case_result.case_review_reasons),
            "event_units": [event_unit.to_summary_doc() for event_unit in case_result.event_units],
        },
    )
    write_json(
        case_dir / "step4_audit.json",
        {
            "case_id": case_result.case_spec.case_id,
            "step4_review_state": case_result.case_review_state,
            "step4_review_reasons": list(case_result.case_review_reasons),
            "event_units": [event_unit.to_summary_doc() for event_unit in case_result.event_units],
        },
    )
    write_vector(case_dir / "step4_event_evidence.gpkg", _geometry_features_for_case(case_result))
    audit_by_unit = build_case_review_audit(case_result)
    overview_path = case_dir / "step4_review_overview.png"
    render_case_overview_png(overview_path, case_result, audit_by_unit=audit_by_unit)

    rows: list[T04ReviewIndexRow] = []
    for event_unit in case_result.event_units:
        audit_summary = audit_by_unit.get(event_unit.spec.event_unit_id, {})
        event_unit_dir = case_dir / "event_units" / event_unit.spec.event_unit_id
        event_unit_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            event_unit_dir / "step3_status.json",
            build_unit_step3_status_doc(
                admission=event_unit.unit_context.admission,
                topology_skeleton=event_unit.unit_context.topology_skeleton,
                topology_scope=event_unit.unit_envelope.topology_scope,
                unit_population_node_ids=event_unit.unit_envelope.unit_population_node_ids,
                context_augmented_node_ids=event_unit.unit_envelope.context_augmented_node_ids,
                event_branch_ids=event_unit.unit_envelope.event_branch_ids,
                boundary_branch_ids=event_unit.unit_envelope.boundary_branch_ids,
                preferred_axis_branch_id=event_unit.unit_envelope.preferred_axis_branch_id,
                degraded_scope_reason=event_unit.unit_envelope.degraded_scope_reason,
                explicit_branch_ids=event_unit.unit_envelope.branch_ids,
                explicit_main_branch_ids=event_unit.unit_envelope.main_branch_ids,
                explicit_input_branch_ids=event_unit.unit_envelope.input_branch_ids,
                explicit_output_branch_ids=event_unit.unit_envelope.output_branch_ids,
                branch_road_memberships=event_unit.unit_envelope.branch_road_memberships,
                branch_bridge_node_ids=event_unit.unit_envelope.branch_bridge_node_ids,
            ),
        )
        write_json(
            event_unit_dir / "step4_candidates.json",
            {
                "case_id": case_result.case_spec.case_id,
                "event_unit_id": event_unit.spec.event_unit_id,
                "pair_local_summary": dict(event_unit.pair_local_summary),
                "audit_summary": dict(audit_summary),
                "selected_evidence_state": event_unit.selected_evidence_state,
                "selected_candidate_region": event_unit.selected_candidate_region,
                "pair_local_rcsd_empty": event_unit.pair_local_rcsd_empty,
                "rcsd_selection_mode": event_unit.rcsd_selection_mode,
                "local_rcsd_unit_kind": event_unit.local_rcsd_unit_kind,
                "local_rcsd_unit_id": event_unit.local_rcsd_unit_id,
                "aggregated_rcsd_unit_id": event_unit.aggregated_rcsd_unit_id,
                "aggregated_rcsd_unit_ids": list(event_unit.aggregated_rcsd_unit_ids),
                "pair_local_rcsd_road_ids": list(event_unit.pair_local_rcsd_road_ids),
                "pair_local_rcsd_node_ids": list(event_unit.pair_local_rcsd_node_ids),
                "first_hit_rcsdroad_ids": list(event_unit.first_hit_rcsdroad_ids),
                "selected_rcsdroad_ids": list(event_unit.selected_rcsdroad_ids),
                "selected_rcsdnode_ids": list(event_unit.selected_rcsdnode_ids),
                "primary_main_rc_node": event_unit.primary_main_rc_node_id,
                "positive_rcsd_present": event_unit.positive_rcsd_present,
                "positive_rcsd_present_reason": event_unit.positive_rcsd_present_reason,
                "positive_rcsd_support_level": event_unit.positive_rcsd_support_level,
                "positive_rcsd_consistency_level": event_unit.positive_rcsd_consistency_level,
                "required_rcsd_node": event_unit.required_rcsd_node,
                "required_rcsd_node_source": event_unit.required_rcsd_node_source,
                "axis_polarity_inverted": event_unit.axis_polarity_inverted,
                "positive_rcsd_audit": dict(event_unit.positive_rcsd_audit),
                "selected_evidence": dict(event_unit.selected_evidence_summary),
                "selected_candidate": dict(event_unit.selected_candidate_summary),
                "alternative_candidates": [dict(item) for item in event_unit.alternative_candidate_summaries],
                "candidate_audit_entries": [item.to_doc() for item in event_unit.candidate_audit_entries],
            },
        )
        write_json(
            event_unit_dir / "step4_evidence_audit.json",
            {
                "case_id": case_result.case_spec.case_id,
                "event_unit_id": event_unit.spec.event_unit_id,
                "audit_summary": dict(audit_summary),
                "selected_evidence_state": event_unit.selected_evidence_state,
                "selected_candidate_region": event_unit.selected_candidate_region,
                "pair_local_rcsd_empty": event_unit.pair_local_rcsd_empty,
                "rcsd_selection_mode": event_unit.rcsd_selection_mode,
                "local_rcsd_unit_kind": event_unit.local_rcsd_unit_kind,
                "local_rcsd_unit_id": event_unit.local_rcsd_unit_id,
                "aggregated_rcsd_unit_id": event_unit.aggregated_rcsd_unit_id,
                "aggregated_rcsd_unit_ids": list(event_unit.aggregated_rcsd_unit_ids),
                "pair_local_rcsd_road_ids": list(event_unit.pair_local_rcsd_road_ids),
                "pair_local_rcsd_node_ids": list(event_unit.pair_local_rcsd_node_ids),
                "first_hit_rcsdroad_ids": list(event_unit.first_hit_rcsdroad_ids),
                "selected_rcsdroad_ids": list(event_unit.selected_rcsdroad_ids),
                "selected_rcsdnode_ids": list(event_unit.selected_rcsdnode_ids),
                "primary_main_rc_node": event_unit.primary_main_rc_node_id,
                "positive_rcsd_present": event_unit.positive_rcsd_present,
                "positive_rcsd_present_reason": event_unit.positive_rcsd_present_reason,
                "positive_rcsd_support_level": event_unit.positive_rcsd_support_level,
                "positive_rcsd_consistency_level": event_unit.positive_rcsd_consistency_level,
                "required_rcsd_node": event_unit.required_rcsd_node,
                "required_rcsd_node_source": event_unit.required_rcsd_node_source,
                "axis_polarity_inverted": event_unit.axis_polarity_inverted,
                "positive_rcsd_audit": dict(event_unit.positive_rcsd_audit),
                "selected_evidence": dict(event_unit.selected_evidence_summary),
                "selected_candidate": dict(event_unit.selected_candidate_summary),
                "candidate_shortlist": [
                    item.to_doc()
                    for item in event_unit.candidate_audit_entries
                    if item.candidate_id in set(audit_summary.get("candidate_shortlist_ids", []))
                ],
                "review_reasons": list(event_unit.all_review_reasons()),
            },
        )
        png_path = event_unit_dir / "step4_review.png"
        render_event_unit_review_png(png_path, event_unit, audit_summary=audit_summary)
        compare_png_path = event_unit_dir / "step4_candidate_compare.png"
        render_event_unit_candidate_compare_png(compare_png_path, event_unit, audit_summary=audit_summary)
        event_unit.source_png_path = str(png_path)
        event_unit.compare_png_path = str(compare_png_path)
        rows.append(
            T04ReviewIndexRow(
                case_id=case_result.case_spec.case_id,
                event_unit_id=event_unit.spec.event_unit_id,
                event_type=event_unit.spec.event_type,
                review_state=event_unit.review_state,
                evidence_source=event_unit.evidence_source,
                position_source=event_unit.position_source,
                reverse_tip_used=event_unit.reverse_tip_used,
                rcsd_consistency_result=event_unit.rcsd_consistency_result,
                positive_rcsd_support_level=event_unit.positive_rcsd_support_level,
                positive_rcsd_consistency_level=event_unit.positive_rcsd_consistency_level,
                positive_rcsd_present=event_unit.positive_rcsd_present,
                positive_rcsd_present_reason=event_unit.positive_rcsd_present_reason,
                pair_local_rcsd_empty=event_unit.pair_local_rcsd_empty,
                rcsd_selection_mode=event_unit.rcsd_selection_mode,
                local_rcsd_unit_kind=str(event_unit.local_rcsd_unit_kind or ""),
                local_rcsd_unit_id=str(event_unit.local_rcsd_unit_id or ""),
                aggregated_rcsd_unit_id=str(event_unit.aggregated_rcsd_unit_id or ""),
                aggregated_rcsd_unit_ids=";".join(str(item) for item in event_unit.aggregated_rcsd_unit_ids),
                axis_polarity_inverted=bool(event_unit.axis_polarity_inverted),
                first_hit_rcsdroad_ids=";".join(event_unit.first_hit_rcsdroad_ids),
                selected_rcsdroad_ids=";".join(event_unit.selected_rcsdroad_ids),
                selected_rcsdnode_ids=";".join(event_unit.selected_rcsdnode_ids),
                primary_main_rc_node=str(event_unit.primary_main_rc_node_id or ""),
                required_rcsd_node=str(event_unit.required_rcsd_node or ""),
                required_rcsd_node_source=str(event_unit.required_rcsd_node_source or ""),
                selected_candidate_region=str(event_unit.selected_candidate_region or ""),
                selected_evidence_state=event_unit.selected_evidence_state,
                selected_evidence_kind=str(event_unit.selected_evidence_summary.get("upper_evidence_kind") or ""),
                primary_candidate_id=str(event_unit.selected_evidence_summary.get("candidate_id") or ""),
                primary_candidate_layer=str(event_unit.selected_evidence_summary.get("layer_label") or ""),
                primary_candidate_layer_reason=str(event_unit.selected_evidence_summary.get("layer_reason") or ""),
                axis_position_m=(
                    ""
                    if event_unit.selected_evidence_summary.get("axis_position_m") is None
                    else str(event_unit.selected_evidence_summary.get("axis_position_m"))
                ),
                reference_distance_to_origin_m=(
                    ""
                    if event_unit.selected_evidence_summary.get("reference_distance_to_origin_m") is None
                    else str(event_unit.selected_evidence_summary.get("reference_distance_to_origin_m"))
                ),
                has_alternative_candidates=bool(event_unit.alternative_candidate_summaries),
                candidate_pool_size=len(event_unit.candidate_audit_entries),
                selected_reference_zone=str(audit_summary.get("selected_reference_zone") or ""),
                selected_evidence_membership=str(audit_summary.get("selected_evidence_membership") or ""),
                better_alternative_signal=bool(audit_summary.get("better_alternative_signal")),
                best_alternative_candidate_id=str(audit_summary.get("best_alternative_candidate_id") or ""),
                best_alternative_layer=str(audit_summary.get("best_alternative_layer") or ""),
                best_alternative_reason=str(audit_summary.get("best_alternative_reason") or ""),
                shared_object_signal=bool(audit_summary.get("shared_object_signal")),
                shared_region_signal=bool(audit_summary.get("shared_region_signal")),
                shared_point_signal=bool(audit_summary.get("shared_point_signal")),
                conflict_signal_level=str(audit_summary.get("conflict_signal_level") or ""),
                related_unit_ids=";".join(str(item) for item in audit_summary.get("related_unit_ids", [])),
                key_reason=str(audit_summary.get("key_reason") or ""),
                needs_manual_review_focus=bool(audit_summary.get("needs_manual_review_focus")),
                focus_reasons=";".join(str(item) for item in audit_summary.get("focus_reasons", [])),
                ownership_signature=str(event_unit.selected_evidence_summary.get("ownership_signature") or ""),
                upper_evidence_object_id=str(event_unit.selected_evidence_summary.get("upper_evidence_object_id") or ""),
                local_region_id=str(event_unit.selected_evidence_summary.get("local_region_id") or ""),
                point_signature=str(event_unit.selected_evidence_summary.get("point_signature") or ""),
                image_path=str(png_path),
                compare_image_path=str(compare_png_path),
                case_overview_path=str(overview_path),
            )
        )
    return rows


def materialize_review_gallery(run_root: Path, rows: list[T04ReviewIndexRow]) -> list[T04ReviewIndexRow]:
    flat_dir = run_root / "step4_review_flat"
    flat_dir.mkdir(parents=True, exist_ok=True)
    for png_path in flat_dir.glob("*.png"):
        if png_path.is_file():
            png_path.unlink()

    ordered_rows = sorted(rows, key=lambda row: (sort_patch_key(row.case_id), row.event_unit_id))
    materialized_rows: list[T04ReviewIndexRow] = []
    overview_flat_paths: dict[str, str] = {}
    for index, row in enumerate(ordered_rows, start=1):
        source_path = Path(row.image_path) if row.image_path else run_root / "cases" / row.case_id / "event_units" / row.event_unit_id / "step4_review.png"
        compare_source_path = (
            Path(row.compare_image_path)
            if row.compare_image_path
            else run_root / "cases" / row.case_id / "event_units" / row.event_unit_id / "step4_candidate_compare.png"
        )
        overview_source_path = (
            Path(row.case_overview_path)
            if row.case_overview_path
            else run_root / "cases" / row.case_id / "step4_review_overview.png"
        )
        if row.case_id not in overview_flat_paths and overview_source_path.is_file():
            overview_name = f"case__{row.case_id}__overview.png"
            overview_flat_path = flat_dir / overview_name
            shutil.copy2(overview_source_path, overview_flat_path)
            overview_flat_paths[row.case_id] = str(overview_flat_path)
        image_name = f"{index:04d}__{row.case_id}__{row.event_unit_id}__main.png"
        image_path = flat_dir / image_name
        if source_path.is_file():
            shutil.copy2(source_path, image_path)
        compare_image_name = f"{index:04d}__{row.case_id}__{row.event_unit_id}__compare.png"
        compare_image_path = flat_dir / compare_image_name
        if compare_source_path.is_file():
            shutil.copy2(compare_source_path, compare_image_path)
        row.sequence_no = index
        row.image_name = image_name
        row.image_path = str(image_path)
        row.compare_image_name = compare_image_name
        row.compare_image_path = str(compare_image_path)
        row.case_overview_path = overview_flat_paths.get(row.case_id, str(overview_source_path))
        materialized_rows.append(row)
    return materialized_rows


def write_review_index(run_root: Path, rows: list[T04ReviewIndexRow]) -> Path:
    output_path = run_root / "step4_review_index.csv"
    write_csv(output_path, [row.to_csv_row() for row in rows], REVIEW_INDEX_FIELDNAMES)
    return output_path


def write_review_summary(run_root: Path, rows: list[T04ReviewIndexRow]) -> Path:
    flat_dir = run_root / "step4_review_flat"
    positive_rcsd_support_counts = Counter(row.positive_rcsd_support_level or "unknown" for row in rows)
    positive_rcsd_consistency_counts = Counter(row.positive_rcsd_consistency_level or "unknown" for row in rows)
    positive_rcsd_present_counts = Counter("yes" if row.positive_rcsd_present else "no" for row in rows)
    pair_local_rcsd_empty_counts = Counter("yes" if row.pair_local_rcsd_empty else "no" for row in rows)
    local_rcsd_unit_kind_counts = Counter(row.local_rcsd_unit_kind or "none" for row in rows)
    axis_polarity_inverted_counts = Counter("yes" if row.axis_polarity_inverted else "no" for row in rows)
    selected_reference_zone_counts = Counter(row.selected_reference_zone or "missing" for row in rows)
    conflict_signal_level_counts = Counter(row.conflict_signal_level or "none" for row in rows)
    focus_reason_counts = Counter(
        reason
        for row in rows
        for reason in str(row.focus_reasons or "").split(";")
        if reason
    )
    summary = {
        "total_case_count": len({row.case_id for row in rows}),
        "total_event_unit_count": len(rows),
        "STEP4_OK": sum(1 for row in rows if row.review_state == "STEP4_OK"),
        "STEP4_REVIEW": sum(1 for row in rows if row.review_state == "STEP4_REVIEW"),
        "STEP4_FAIL": sum(1 for row in rows if row.review_state == "STEP4_FAIL"),
        "selected_evidence_none_count": sum(1 for row in rows if row.selected_evidence_state == "none"),
        "selected_layer_1_count": sum(1 for row in rows if row.primary_candidate_layer == "Layer 1"),
        "selected_layer_2_count": sum(1 for row in rows if row.primary_candidate_layer == "Layer 2"),
        "selected_layer_3_count": sum(1 for row in rows if row.primary_candidate_layer == "Layer 3"),
        "manual_focus_count": sum(1 for row in rows if row.needs_manual_review_focus),
        "better_alternative_signal_count": sum(1 for row in rows if row.better_alternative_signal),
        "shared_object_signal_count": sum(1 for row in rows if row.shared_object_signal),
        "shared_region_signal_count": sum(1 for row in rows if row.shared_region_signal),
        "shared_point_signal_count": sum(1 for row in rows if row.shared_point_signal),
        "required_rcsd_node_count": sum(1 for row in rows if row.required_rcsd_node),
        "positive_rcsd_present_count": sum(1 for row in rows if row.positive_rcsd_present),
        "pair_local_rcsd_empty_count": sum(1 for row in rows if row.pair_local_rcsd_empty),
        "flat_png_count": (
            len([entry for entry in flat_dir.iterdir() if entry.is_file() and entry.suffix.lower() == ".png"])
            if flat_dir.is_dir()
            else 0
        ),
        "positive_rcsd_support_level_counts": dict(sorted(positive_rcsd_support_counts.items())),
        "positive_rcsd_consistency_level_counts": dict(sorted(positive_rcsd_consistency_counts.items())),
        "positive_rcsd_present_counts": dict(sorted(positive_rcsd_present_counts.items())),
        "pair_local_rcsd_empty_counts": dict(sorted(pair_local_rcsd_empty_counts.items())),
        "local_rcsd_unit_kind_counts": dict(sorted(local_rcsd_unit_kind_counts.items())),
        "axis_polarity_inverted_counts": dict(sorted(axis_polarity_inverted_counts.items())),
        "selected_reference_zone_counts": dict(sorted(selected_reference_zone_counts.items())),
        "conflict_signal_level_counts": dict(sorted(conflict_signal_level_counts.items())),
        "top_focus_reasons": [
            {"reason": reason, "count": count}
            for reason, count in focus_reason_counts.most_common(10)
        ],
        "cases_with_multiple_event_units": sorted(
            case_id
            for case_id in {row.case_id for row in rows}
            if sum(1 for row in rows if row.case_id == case_id) > 1
        ),
    }
    output_path = run_root / "step4_review_summary.json"
    write_json(output_path, summary)
    return output_path


def write_summary(
    *,
    run_root: Path,
    rows: list[T04ReviewIndexRow],
    preflight: dict,
    failed_case_ids: list[str],
    rerun_cleaned_before_write: bool,
) -> Path:
    cases_dir = run_root / "cases"
    summary = {
        "total_case_count": len({row.case_id for row in rows}),
        "total_event_unit_count": len(rows),
        "selected_case_count": preflight.get("selected_case_count"),
        "selected_case_ids": preflight.get("selected_case_ids", []),
        "failed_case_ids": failed_case_ids,
        "rerun_cleaned_before_write": rerun_cleaned_before_write,
        "run_root": str(run_root),
        "cases_dir": str(cases_dir),
        "step4_review_index_csv": str(run_root / "step4_review_index.csv"),
        "step4_review_summary_json": str(run_root / "step4_review_summary.json"),
        "step4_review_flat_dir": str(run_root / "step4_review_flat"),
    }
    output_path = run_root / "summary.json"
    write_json(output_path, summary)
    return output_path
