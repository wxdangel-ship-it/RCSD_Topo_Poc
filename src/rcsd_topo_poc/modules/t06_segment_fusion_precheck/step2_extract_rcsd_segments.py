from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .buffer_segment_extraction import BufferExtractionConfig, BufferSegmentExtractor, BufferSegmentResult
from .graph_builders import NodeCanonicalizer
from .io import prepare_run_roots, read_features, write_feature_triplet, write_json
from .parsing import ParseError, directionality_from_sgrade, normalize_id, parse_id_list
from .relation_mapping import RelationRecord, accepted_base_ids, build_relation_map, check_segment_relations
from .schemas import (
    STEP2_CANDIDATE_FIELDS,
    STEP2_CANDIDATES_STEM,
    STEP2_BUFFER_REJECTED_FIELDS,
    STEP2_BUFFER_REJECTED_STEM,
    STEP2_BUFFER_SEGMENT_FIELDS,
    STEP2_BUFFER_SEGMENTS_STEM,
    STEP2_DIR,
    STEP2_REJECTED_FIELDS,
    STEP2_REJECTED_STEM,
    STEP2_REPLACEABLE_FIELDS,
    STEP2_REPLACEABLE_STEM,
    STEP2_SUMMARY,
    T06Step2Artifacts,
    feature,
)


def run_t06_step2_extract_rcsd_segments(
    *,
    swsd_fusion_units_path: str | Path,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    swsd_nodes_path: str | Path,
    intersection_match_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    max_main_axis_angle_diff_deg: float = 60.0,
    min_coarse_length_ratio: float = 0.4,
    max_coarse_length_ratio: float = 2.5,
    buffer_distance_m: float = 50.0,
    min_buffer_road_overlap_ratio: float = 0.2,
    min_buffer_road_overlap_length_m: float = 1.0,
    advance_right_formway_bit: int = 128,
    progress: bool = False,
) -> T06Step2Artifacts:
    resolved_run_id, run_root, step_root = prepare_run_roots(out_root, run_id, STEP2_DIR)
    fusion_units = read_features(swsd_fusion_units_path)
    segments = _segment_index(read_features(swsd_segment_path))
    relation_map = build_relation_map(read_features(intersection_match_path, crs_override="EPSG:4326"))
    rcsd_roads = read_features(rcsdroad_path)
    rcsd_node_features = read_features(rcsdnode_path)
    rcsd_node_canonicalizer = NodeCanonicalizer.from_node_features(rcsd_node_features)
    buffer_extractor = BufferSegmentExtractor(rcsd_road_features=rcsd_roads, rcsd_node_features=rcsd_node_features)
    buffer_config = BufferExtractionConfig(
        buffer_distance_m=buffer_distance_m,
        min_road_overlap_ratio=min_buffer_road_overlap_ratio,
        min_road_overlap_length_m=min_buffer_road_overlap_length_m,
        advance_right_formway_bit=advance_right_formway_bit,
    )
    all_base_ids = accepted_base_ids(relation_map)

    candidate_rows: list[dict[str, Any]] = []
    replaceable_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    buffer_segment_rows: list[dict[str, Any]] = []
    buffer_rejected_rows: list[dict[str, Any]] = []
    relation_success_count = 0
    single_input_count = 0
    dual_input_count = 0
    junc_kind2_relation_exempt_segment_count = 0
    junc_kind2_relation_exempt_node_count = 0

    for index, unit in enumerate(fusion_units, start=1):
        if progress and index % 1000 == 0:
            print(f"[T06 Step2] processed {index}/{len(fusion_units)}", flush=True)
        props = dict(unit.get("properties") or {})
        segment_id = str(props.get("swsd_segment_id") or props.get("id") or f"segment_{index}")
        segment = segments.get(segment_id, unit)
        segment_props = dict(segment.get("properties") or {})
        pair_nodes, junc_nodes, junc_kind2_exempt_nodes, _roads, parse_reason = _parse_unit_lists(props, segment_props)
        if parse_reason is not None:
            rejected_rows.append(_reject(segment_id, None, "parse", parse_reason))
            continue
        relation_junc_nodes = _relation_required_junc_nodes(junc_nodes, junc_kind2_exempt_nodes)
        all_base_ids_for_segment = all_base_ids - _accepted_base_ids_for_nodes(junc_kind2_exempt_nodes, relation_map)
        if junc_kind2_exempt_nodes:
            junc_kind2_relation_exempt_segment_count += 1
            junc_kind2_relation_exempt_node_count += len(junc_kind2_exempt_nodes)

        relation = check_segment_relations(pair_nodes=pair_nodes, junc_nodes=relation_junc_nodes, relation_map=relation_map)
        if not relation.ok:
            rejected_rows.append(
                _reject(
                    segment_id,
                    None,
                    "relation_mapping",
                    relation.reject_reason or "relation_mapping_failed",
                    failed_pair_nodes=relation.failed_pair_nodes or [],
                    failed_junc_nodes=relation.failed_junc_nodes or [],
                    junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                )
            )
            continue
        relation_success_count += 1
        optional_allowed_rcsd_nodes = _accepted_base_ids_for_nodes_ordered(junc_kind2_exempt_nodes, relation_map)
        buffer_result = buffer_extractor.extract(
            segment_geometry=segment.get("geometry"),
            relation=relation,
            optional_allowed_rcsd_nodes=optional_allowed_rcsd_nodes,
            all_relation_base_ids=all_base_ids_for_segment,
            config=buffer_config,
        )
        directionality = directionality_from_sgrade(segment_props.get("sgrade") or props.get("sgrade")) or "unknown"
        if directionality == "single":
            single_input_count += 1
        elif directionality == "dual":
            dual_input_count += 1
        if buffer_result.ok:
            buffer_feature = feature(_buffer_segment_row(segment_id, buffer_result), buffer_result.geometry)
            buffer_segment_rows.append(buffer_feature)
            candidate_feature = feature(
                _buffer_candidate_row(
                    segment_id=segment_id,
                    props=props,
                    directionality=directionality,
                    relation=relation,
                    junc_nodes=junc_nodes,
                    junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                    result=buffer_result,
                ),
                buffer_result.geometry,
            )
            candidate_rows.append(candidate_feature)
            replaceable_rows.append(_buffer_replaceable_row(candidate_feature))
        else:
            buffer_rejected = _buffer_rejected_row(segment_id, buffer_result)
            buffer_rejected_rows.append(buffer_rejected)
            rejected_rows.append(
                _reject(
                    segment_id,
                    None,
                    "buffer_segment_extraction",
                    buffer_result.reason,
                    junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                    failed_metric_name=_buffer_failed_metric_name(buffer_result),
                    failed_metric_value=_buffer_failed_metric_value(buffer_result),
                    notes="buffer-based RCSD Segment construction failed",
                )
            )

    candidate_paths = write_feature_triplet(step_root=step_root, stem=STEP2_CANDIDATES_STEM, features=candidate_rows, fieldnames=STEP2_CANDIDATE_FIELDS)
    replaceable_paths = write_feature_triplet(step_root=step_root, stem=STEP2_REPLACEABLE_STEM, features=replaceable_rows, fieldnames=STEP2_REPLACEABLE_FIELDS)
    rejected_paths = write_feature_triplet(step_root=step_root, stem=STEP2_REJECTED_STEM, features=rejected_rows, fieldnames=STEP2_REJECTED_FIELDS)
    buffer_segment_paths = write_feature_triplet(step_root=step_root, stem=STEP2_BUFFER_SEGMENTS_STEM, features=buffer_segment_rows, fieldnames=STEP2_BUFFER_SEGMENT_FIELDS)
    buffer_rejected_paths = write_feature_triplet(step_root=step_root, stem=STEP2_BUFFER_REJECTED_STEM, features=buffer_rejected_rows, fieldnames=STEP2_BUFFER_REJECTED_FIELDS)
    summary_path = step_root / STEP2_SUMMARY
    write_json(
        summary_path,
        {
            "run_id": resolved_run_id,
            "input_paths": {
                "swsd_fusion_units_path": str(swsd_fusion_units_path),
                "swsd_segment_path": str(swsd_segment_path),
                "swsd_roads_path": str(swsd_roads_path),
                "swsd_nodes_path": str(swsd_nodes_path),
                "intersection_match_path": str(intersection_match_path),
                "rcsdroad_path": str(rcsdroad_path),
                "rcsdnode_path": str(rcsdnode_path),
            },
            "params": {
                "max_main_axis_angle_diff_deg": max_main_axis_angle_diff_deg,
                "min_coarse_length_ratio": min_coarse_length_ratio,
                "max_coarse_length_ratio": max_coarse_length_ratio,
                "buffer_distance_m": buffer_distance_m,
                "min_buffer_road_overlap_ratio": min_buffer_road_overlap_ratio,
                "min_buffer_road_overlap_length_m": min_buffer_road_overlap_length_m,
                "advance_right_formway_bit": advance_right_formway_bit,
            },
            "input_fusion_unit_count": len(fusion_units),
            "relation_success_count": relation_success_count,
            "relation_failure_count": len(fusion_units) - relation_success_count,
            "junc_kind2_relation_exempt_segment_count": junc_kind2_relation_exempt_segment_count,
            "junc_kind2_relation_exempt_node_count": junc_kind2_relation_exempt_node_count,
            "rcsd_candidate_count": len(candidate_rows),
            "replaceable_count": len(replaceable_rows),
            "rejected_count": len(rejected_rows),
            "reject_reason_counts": dict(Counter(item["properties"].get("reject_reason") for item in rejected_rows)),
            "candidate_strategy": "buffer_segment_extraction",
            "deprecated_pair_path_search_enabled": False,
            "ambiguous_candidate_count": 0,
            "single_segment_input_count": single_input_count,
            "dual_segment_input_count": dual_input_count,
            "single_segment_replaceable_count": sum(1 for item in replaceable_rows if item["properties"].get("swsd_directionality") == "single"),
            "dual_segment_replaceable_count": sum(1 for item in replaceable_rows if item["properties"].get("swsd_directionality") == "dual"),
            "buffer_segment_count": len(buffer_segment_rows),
            "buffer_rejected_count": len(buffer_rejected_rows),
            "buffer_reject_reason_counts": dict(Counter(item["properties"].get("reject_reason") for item in buffer_rejected_rows)),
            "buffer_retained_road_count_total": sum(len(item["properties"].get("retained_rcsd_road_ids") or []) for item in buffer_segment_rows),
            "buffer_excluded_advance_right_turn_road_count_total": sum(
                len(item["properties"].get("excluded_advance_right_turn_road_ids") or []) for item in buffer_segment_rows + buffer_rejected_rows
            ),
            "rcsd_semantic_node_alias_count": sum(1 for raw_id, canonical_id in rcsd_node_canonicalizer.aliases.items() if raw_id != canonical_id),
            "outputs": {
                **{f"candidates_{k}": str(v) for k, v in candidate_paths.items()},
                **{f"replaceable_{k}": str(v) for k, v in replaceable_paths.items()},
                **{f"rejected_{k}": str(v) for k, v in rejected_paths.items()},
                **{f"buffer_segments_{k}": str(v) for k, v in buffer_segment_paths.items()},
                **{f"buffer_rejected_{k}": str(v) for k, v in buffer_rejected_paths.items()},
            },
            "gis_topology_checks": {
                "crs_normalized_to": "EPSG:3857",
                "topology_consistency": "buffer-based RCSD Segment graph uses canonicalized RCSD semantic nodes and explicit component coverage checks",
                "geometry_semantics": "SWSD geometry defines the buffer window; RCSD geometry is used for intersects/overlap candidate selection and retained output geometry",
                "audit_traceability": "input paths, params, counts, reasons and outputs recorded",
                "performance_verifiable": "input counts, candidate counts and output sizes are reproducible from summary",
            },
        },
    )
    return T06Step2Artifacts(resolved_run_id, run_root, step_root, candidate_paths["gpkg"], replaceable_paths["gpkg"], rejected_paths["gpkg"], summary_path)


def _segment_index(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for feature in features:
        try:
            result[normalize_id((feature.get("properties") or {}).get("id"))] = feature
        except ParseError:
            continue
    return result


def _parse_unit_lists(props: dict[str, Any], segment_props: dict[str, Any]) -> tuple[list[str], list[str], list[str], list[str], str | None]:
    try:
        pair_nodes = parse_id_list(props.get("pair_nodes", segment_props.get("pair_nodes")), allow_empty=False)
        if len(pair_nodes) != 2:
            return [], [], [], [], "invalid_pair_nodes"
    except ParseError:
        return [], [], [], [], "invalid_pair_nodes"
    try:
        junc_nodes = parse_id_list(props.get("junc_nodes", segment_props.get("junc_nodes")), allow_empty=True)
    except ParseError:
        return [], [], [], [], "invalid_junc_nodes"
    try:
        junc_kind2_exempt_nodes = parse_id_list(props.get("junc_kind2_exempt_nodes"), allow_empty=True)
    except ParseError:
        junc_kind2_exempt_nodes = []
    try:
        roads = parse_id_list(props.get("roads", segment_props.get("roads")), allow_empty=True)
    except ParseError:
        roads = []
    return pair_nodes, junc_nodes, junc_kind2_exempt_nodes, roads, None


def _relation_required_junc_nodes(junc_nodes: list[str], junc_kind2_exempt_nodes: list[str]) -> list[str]:
    exempt = set(junc_kind2_exempt_nodes)
    return [node_id for node_id in junc_nodes if node_id not in exempt]


def _accepted_base_ids_for_nodes(node_ids: list[str], relation_map: dict[str, RelationRecord]) -> set[str]:
    result: set[str] = set()
    for node_id in node_ids:
        relation = relation_map.get(node_id)
        if relation is None or relation.status != 0 or relation.base_id <= 0:
            continue
        result.add(str(relation.base_id))
    return result


def _accepted_base_ids_for_nodes_ordered(node_ids: list[str], relation_map: dict[str, RelationRecord]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for node_id in node_ids:
        relation = relation_map.get(node_id)
        if relation is None or relation.status != 0 or relation.base_id <= 0:
            continue
        base_id = str(relation.base_id)
        if base_id in seen:
            continue
        seen.add(base_id)
        result.append(base_id)
    return result


def _buffer_segment_row(segment_id: str, result: BufferSegmentResult) -> dict[str, Any]:
    return {
        "swsd_segment_id": segment_id,
        "buffer_candidate_id": f"{segment_id}_buffer_segment",
        "buffer_status": "passed",
        "buffer_reason": result.reason,
        "required_rcsd_nodes": result.required_rcsd_nodes,
        "optional_allowed_rcsd_nodes": result.optional_allowed_rcsd_nodes,
        "retained_rcsd_road_ids": result.retained_road_ids,
        "candidate_rcsd_road_ids": result.candidate_road_ids,
        "candidate_rcsd_node_ids": result.candidate_node_ids,
        "excluded_advance_right_turn_road_ids": result.excluded_advance_right_turn_road_ids,
        "retained_node_ids": result.retained_node_ids,
        "inner_node_ids": result.inner_node_ids,
        "out_node_ids": result.out_node_ids,
        "unexpected_endpoint_node_ids": result.unexpected_endpoint_node_ids,
        "selected_component_id": result.selected_component_id,
        "candidate_road_count": result.candidate_road_count,
        "retained_road_count": result.retained_road_count,
        "candidate_node_count": result.candidate_node_count,
        "retained_node_count": result.retained_node_count,
    }


def _buffer_candidate_row(
    *,
    segment_id: str,
    props: dict[str, Any],
    directionality: str,
    relation: Any,
    junc_nodes: list[str],
    junc_kind2_exempt_nodes: list[str],
    result: BufferSegmentResult,
) -> dict[str, Any]:
    return {
        "swsd_segment_id": segment_id,
        "rcsd_candidate_id": f"{segment_id}_buffer_segment",
        "candidate_strategy": "buffer_segment_extraction",
        "candidate_status": "passed",
        "candidate_reason": result.reason,
        "swsd_sgrade": props.get("sgrade"),
        "swsd_directionality": directionality,
        "swsd_pair_nodes": props.get("pair_nodes"),
        "rcsd_pair_nodes": relation.rcsd_pair_nodes,
        "swsd_junc_nodes": junc_nodes,
        "junc_kind2_exempt_nodes": junc_kind2_exempt_nodes,
        "rcsd_junc_nodes": relation.rcsd_junc_nodes,
        "required_rcsd_nodes": result.required_rcsd_nodes,
        "optional_allowed_rcsd_nodes": result.optional_allowed_rcsd_nodes,
        "candidate_rcsd_road_ids": result.candidate_road_ids,
        "candidate_rcsd_node_ids": result.candidate_node_ids,
        "retained_rcsd_road_ids": result.retained_road_ids,
        "retained_node_ids": result.retained_node_ids,
        "inner_node_ids": result.inner_node_ids,
        "out_node_ids": result.out_node_ids,
        "unexpected_endpoint_node_ids": result.unexpected_endpoint_node_ids,
        "excluded_advance_right_turn_road_ids": result.excluded_advance_right_turn_road_ids,
        "selected_component_id": result.selected_component_id,
        "candidate_road_count": result.candidate_road_count,
        "retained_road_count": result.retained_road_count,
        "candidate_node_count": result.candidate_node_count,
        "retained_node_count": result.retained_node_count,
    }


def _buffer_replaceable_row(candidate_feature: dict[str, Any]) -> dict[str, Any]:
    props = dict(candidate_feature["properties"])
    return feature(
        {
            "swsd_segment_id": props.get("swsd_segment_id"),
            "rcsd_candidate_id": props.get("rcsd_candidate_id"),
            "replacement_ready": True,
            "replacement_strategy": props.get("candidate_strategy"),
            "swsd_sgrade": props.get("swsd_sgrade"),
            "swsd_directionality": props.get("swsd_directionality"),
            "swsd_pair_nodes": props.get("swsd_pair_nodes"),
            "rcsd_pair_nodes": props.get("rcsd_pair_nodes"),
            "swsd_junc_nodes": props.get("swsd_junc_nodes"),
            "junc_kind2_exempt_nodes": props.get("junc_kind2_exempt_nodes"),
            "rcsd_junc_nodes": props.get("rcsd_junc_nodes"),
            "rcsd_road_ids": props.get("retained_rcsd_road_ids"),
            "required_rcsd_nodes": props.get("required_rcsd_nodes"),
            "optional_allowed_rcsd_nodes": props.get("optional_allowed_rcsd_nodes"),
            "retained_node_ids": props.get("retained_node_ids"),
            "inner_node_ids": props.get("inner_node_ids"),
            "out_node_ids": props.get("out_node_ids"),
            "unexpected_endpoint_node_ids": props.get("unexpected_endpoint_node_ids"),
            "excluded_advance_right_turn_road_ids": props.get("excluded_advance_right_turn_road_ids"),
            "hard_filter_passed": True,
        },
        candidate_feature.get("geometry"),
    )


def _buffer_rejected_row(segment_id: str, result: BufferSegmentResult) -> dict[str, Any]:
    return feature(
        {
            "swsd_segment_id": segment_id,
            "reject_stage": "buffer_segment_extraction",
            "reject_reason": result.reason,
            "required_rcsd_nodes": result.required_rcsd_nodes,
            "optional_allowed_rcsd_nodes": result.optional_allowed_rcsd_nodes,
            "missing_required_node_ids": result.missing_required_node_ids,
            "retained_rcsd_road_ids": result.retained_road_ids,
            "candidate_rcsd_road_ids": result.candidate_road_ids,
            "candidate_rcsd_node_ids": result.candidate_node_ids,
            "excluded_advance_right_turn_road_ids": result.excluded_advance_right_turn_road_ids,
            "retained_node_ids": result.retained_node_ids,
            "inner_node_ids": result.inner_node_ids,
            "out_node_ids": result.out_node_ids,
            "unexpected_endpoint_node_ids": result.unexpected_endpoint_node_ids,
            "selected_component_id": result.selected_component_id,
            "candidate_road_count": result.candidate_road_count,
            "retained_road_count": result.retained_road_count,
            "candidate_node_count": result.candidate_node_count,
            "retained_node_count": result.retained_node_count,
        },
        None,
    )


def _buffer_failed_metric_name(result: BufferSegmentResult) -> str | None:
    if result.unexpected_endpoint_node_ids:
        return "unexpected_endpoint_node_ids"
    if result.out_node_ids:
        return "out_node_ids"
    if result.inner_node_ids:
        return "inner_node_ids"
    return None


def _buffer_failed_metric_value(result: BufferSegmentResult) -> list[str] | None:
    if result.unexpected_endpoint_node_ids:
        return result.unexpected_endpoint_node_ids
    if result.out_node_ids:
        return result.out_node_ids
    if result.inner_node_ids:
        return result.inner_node_ids
    return None


def _reject(
    segment_id: str,
    candidate_id: str | None,
    stage: str,
    reason: str,
    *,
    failed_pair_nodes: list[str] | None = None,
    failed_junc_nodes: list[str] | None = None,
    junc_kind2_exempt_nodes: list[str] | None = None,
    failed_metric_name: str | None = None,
    failed_metric_value: Any = None,
    threshold_value: Any = None,
    notes: str | None = None,
) -> dict[str, Any]:
    return feature(
        {
            "swsd_segment_id": segment_id,
            "rcsd_candidate_id": candidate_id,
            "reject_stage": stage,
            "reject_reason": reason,
            "failed_pair_nodes": failed_pair_nodes or [],
            "failed_junc_nodes": failed_junc_nodes or [],
            "junc_kind2_exempt_nodes": junc_kind2_exempt_nodes or [],
            "failed_metric_name": failed_metric_name,
            "failed_metric_value": failed_metric_value,
            "threshold_value": threshold_value,
            "notes": notes,
        },
        None,
    )
