from __future__ import annotations

from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from .buffer_segment_extraction import BufferExtractionConfig, BufferSegmentExtractor, BufferSegmentResult
from .graph_builders import NodeCanonicalizer
from .io import prepare_run_roots, read_features, write_feature_triplet, write_json
from .parsing import ParseError, directionality_from_sgrade, normalize_id, parse_id_list, unique_preserve_order
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
    STEP2_SPECIAL_JUNCTION_GROUP_FIELDS,
    STEP2_SPECIAL_JUNCTION_GROUPS_STEM,
    STEP2_SUMMARY,
    T06Step2Artifacts,
    feature,
)

SPECIAL_JUNCTION_KIND_TYPES = {64: "roundabout", 128: "complex"}


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
    swsd_roads = _segment_index(read_features(swsd_roads_path))
    swsd_node_features = read_features(swsd_nodes_path)
    swsd_node_canonicalizer = NodeCanonicalizer.from_node_features(swsd_node_features)
    special_swsd_junction_types = _special_swsd_junction_types(swsd_node_features, swsd_node_canonicalizer)
    relation_map = build_relation_map(read_features(intersection_match_path, crs_override="EPSG:4326"))
    rcsd_roads = read_features(rcsdroad_path)
    rcsd_node_features = read_features(rcsdnode_path)
    rcsd_node_canonicalizer = NodeCanonicalizer.from_node_features(rcsd_node_features)
    rcsd_junction_node_ids = _rcsd_semantic_node_ids(rcsd_node_features, rcsd_node_canonicalizer)
    rcsd_junction_road_ids = _rcsd_internal_road_ids(rcsd_roads, rcsd_node_canonicalizer)
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
    segment_special_junctions: dict[str, list[str]] = {}
    special_junction_segments: dict[str, list[str]] = defaultdict(list)

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
        special_junction_ids = _segment_special_junction_ids(
            [*pair_nodes, *junc_nodes],
            special_swsd_junction_types,
            swsd_node_canonicalizer,
        )
        segment_special_junctions[segment_id] = special_junction_ids
        for special_junction_id in special_junction_ids:
            if segment_id not in special_junction_segments[special_junction_id]:
                special_junction_segments[special_junction_id].append(segment_id)
        relation_junc_nodes = _relation_required_junc_nodes(junc_nodes, junc_kind2_exempt_nodes)
        all_base_ids_for_segment = all_base_ids - _accepted_base_ids_for_nodes(junc_kind2_exempt_nodes, relation_map)
        unexpected_base_ids_for_segment = _unexpected_base_ids_for_segment([*pair_nodes, *junc_nodes], relation_map)
        if junc_kind2_exempt_nodes:
            junc_kind2_relation_exempt_segment_count += 1
            junc_kind2_relation_exempt_node_count += len(junc_kind2_exempt_nodes)
        directionality = directionality_from_sgrade(segment_props.get("sgrade") or props.get("sgrade")) or "unknown"

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
        if directionality == "single":
            single_input_count += 1
        elif directionality == "dual":
            dual_input_count += 1

        directed_swsd_pair_nodes: list[str] = []
        directed_rcsd_pair_nodes: list[str] = []
        if directionality == "single":
            directed_swsd_pair_nodes, direction_reason = _resolve_swsd_single_directed_pair(
                pair_nodes=pair_nodes,
                road_ids=_roads,
                swsd_roads=swsd_roads,
                swsd_node_canonicalizer=swsd_node_canonicalizer,
            )
            if direction_reason is not None:
                rejected_rows.append(
                    _reject(
                        segment_id,
                        None,
                        "swsd_direction_resolution",
                        direction_reason,
                        failed_pair_nodes=pair_nodes,
                        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                        failed_metric_name="swsd_road_direction",
                        failed_metric_value=_roads,
                        notes="single SWSD Segment direction must be resolved from SWSDRoad snodeid/enodeid/direction",
                    )
                )
                continue
            directed_rcsd_pair_nodes = _map_directed_swsd_pair_to_rcsd(
                pair_nodes=pair_nodes,
                rcsd_pair_nodes=relation.rcsd_pair_nodes,
                directed_swsd_pair_nodes=directed_swsd_pair_nodes,
            )
            if len(directed_rcsd_pair_nodes) != 2:
                rejected_rows.append(
                    _reject(
                        segment_id,
                        None,
                        "swsd_direction_resolution",
                        "swsd_single_direction_relation_mismatch",
                        failed_pair_nodes=pair_nodes,
                        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                        failed_metric_name="directed_swsd_pair_nodes",
                        failed_metric_value=directed_swsd_pair_nodes,
                        notes="resolved SWSD directed pair cannot be mapped to relation RCSD pair nodes",
                    )
                )
                continue
        optional_allowed_rcsd_nodes = _accepted_base_ids_for_nodes_ordered(junc_kind2_exempt_nodes, relation_map)
        buffer_result = buffer_extractor.extract(
            segment_geometry=segment.get("geometry"),
            relation=relation,
            optional_allowed_rcsd_nodes=optional_allowed_rcsd_nodes,
            all_relation_base_ids=all_base_ids_for_segment,
            unexpected_relation_base_ids=unexpected_base_ids_for_segment,
            directed_pair_nodes=directed_rcsd_pair_nodes,
            require_directed_pair=directionality == "single",
            require_bidirectional=directionality == "dual",
            config=buffer_config,
        )
        if buffer_result.ok:
            buffer_feature = feature(_buffer_segment_row(segment_id, buffer_result), buffer_result.geometry)
            buffer_segment_rows.append(buffer_feature)
            candidate_feature = feature(
                _buffer_candidate_row(
                    segment_id=segment_id,
                    props=props,
                    directionality=directionality,
                    directed_swsd_pair_nodes=directed_swsd_pair_nodes,
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

    special_group_rows, blocked_segment_ids, removed_replaceable_segment_ids, blocking_groups_by_segment = _special_junction_gate(
        special_junction_segments=special_junction_segments,
        special_swsd_junction_types=special_swsd_junction_types,
        replaceable_rows=replaceable_rows,
        relation_map=relation_map,
        rcsd_junction_node_ids=rcsd_junction_node_ids,
        rcsd_junction_road_ids=rcsd_junction_road_ids,
    )
    _annotate_special_junction_gate(
        candidate_rows,
        segment_special_junctions=segment_special_junctions,
        special_swsd_junction_types=special_swsd_junction_types,
        blocked_segment_ids=blocked_segment_ids,
        blocking_groups_by_segment=blocking_groups_by_segment,
    )
    _annotate_special_junction_gate(
        replaceable_rows,
        segment_special_junctions=segment_special_junctions,
        special_swsd_junction_types=special_swsd_junction_types,
        blocked_segment_ids=blocked_segment_ids,
        blocking_groups_by_segment=blocking_groups_by_segment,
    )
    if removed_replaceable_segment_ids:
        replaceable_rows = [
            row for row in replaceable_rows if (row.get("properties") or {}).get("swsd_segment_id") not in removed_replaceable_segment_ids
        ]
        rejected_rows.extend(
            _reject(
                segment_id,
                None,
                "special_junction_group_gate",
                "special_junction_group_not_fully_replaceable",
                failed_metric_name="special_junction_group_ids",
                failed_metric_value=blocking_groups_by_segment.get(segment_id, []),
                notes="roundabout or complex junction group has at least one associated Segment that is not replaceable",
            )
            for segment_id in sorted(removed_replaceable_segment_ids)
        )

    candidate_paths = write_feature_triplet(step_root=step_root, stem=STEP2_CANDIDATES_STEM, features=candidate_rows, fieldnames=STEP2_CANDIDATE_FIELDS)
    replaceable_paths = write_feature_triplet(step_root=step_root, stem=STEP2_REPLACEABLE_STEM, features=replaceable_rows, fieldnames=STEP2_REPLACEABLE_FIELDS)
    rejected_paths = write_feature_triplet(step_root=step_root, stem=STEP2_REJECTED_STEM, features=rejected_rows, fieldnames=STEP2_REJECTED_FIELDS)
    buffer_segment_paths = write_feature_triplet(step_root=step_root, stem=STEP2_BUFFER_SEGMENTS_STEM, features=buffer_segment_rows, fieldnames=STEP2_BUFFER_SEGMENT_FIELDS)
    buffer_rejected_paths = write_feature_triplet(step_root=step_root, stem=STEP2_BUFFER_REJECTED_STEM, features=buffer_rejected_rows, fieldnames=STEP2_BUFFER_REJECTED_FIELDS)
    special_group_paths = write_feature_triplet(
        step_root=step_root,
        stem=STEP2_SPECIAL_JUNCTION_GROUPS_STEM,
        features=special_group_rows,
        fieldnames=STEP2_SPECIAL_JUNCTION_GROUP_FIELDS,
    )
    rcsd_road_stats = _rcsd_road_coverage_stats(rcsd_roads=rcsd_roads, replaceable_rows=replaceable_rows)
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
            "special_junction_group_count": len(special_group_rows),
            "special_junction_group_passed_count": sum(1 for item in special_group_rows if item["properties"].get("gate_status") == "passed"),
            "special_junction_group_blocked_count": sum(1 for item in special_group_rows if item["properties"].get("gate_status") == "blocked"),
            "special_junction_blocked_segment_count": len(blocked_segment_ids),
            "special_junction_gate_removed_replaceable_count": len(removed_replaceable_segment_ids),
            "special_junction_group_type_counts": dict(Counter(item["properties"].get("special_junction_type") for item in special_group_rows)),
            **rcsd_road_stats,
            "rcsd_semantic_node_alias_count": sum(1 for raw_id, canonical_id in rcsd_node_canonicalizer.aliases.items() if raw_id != canonical_id),
            "rcsd_semantic_node_group_count": len(rcsd_node_canonicalizer.semantic_node_ids),
            "outputs": {
                **{f"candidates_{k}": str(v) for k, v in candidate_paths.items()},
                **{f"replaceable_{k}": str(v) for k, v in replaceable_paths.items()},
                **{f"rejected_{k}": str(v) for k, v in rejected_paths.items()},
                **{f"buffer_segments_{k}": str(v) for k, v in buffer_segment_paths.items()},
                **{f"buffer_rejected_{k}": str(v) for k, v in buffer_rejected_paths.items()},
                **{f"special_junction_group_audit_{k}": str(v) for k, v in special_group_paths.items()},
            },
            "gis_topology_checks": {
                "crs_normalized_to": "EPSG:3857",
                "topology_consistency": "buffer-based RCSD Segment graph uses canonicalized RCSD semantic nodes, explicit component coverage checks and special junction group gating",
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


def _special_swsd_junction_types(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> dict[str, str]:
    by_node: dict[str, set[str]] = defaultdict(set)
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            semantic_id = canonicalizer.canonicalize(props.get("id"))
        except ParseError:
            continue
        kind_2 = _coerce_int(props.get("kind_2"))
        special_type = SPECIAL_JUNCTION_KIND_TYPES.get(kind_2)
        if special_type is not None:
            by_node[semantic_id].add(special_type)
    return {
        node_id: next(iter(types)) if len(types) == 1 else "mixed"
        for node_id, types in by_node.items()
    }


def _segment_special_junction_ids(
    semantic_node_ids: list[str],
    special_swsd_junction_types: dict[str, str],
    canonicalizer: NodeCanonicalizer,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for node_id in semantic_node_ids:
        try:
            semantic_id = canonicalizer.canonicalize(node_id)
        except ParseError:
            continue
        if semantic_id not in special_swsd_junction_types or semantic_id in seen:
            continue
        seen.add(semantic_id)
        result.append(semantic_id)
    return result


def _rcsd_semantic_node_ids(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            node_id = normalize_id(props.get("id"))
            semantic_id = canonicalizer.canonicalize(node_id)
        except ParseError:
            continue
        if node_id not in result[semantic_id]:
            result[semantic_id].append(node_id)
    return dict(result)


def _rcsd_internal_road_ids(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            source = canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            target = canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
        except (KeyError, ParseError):
            continue
        if source != target or road_id in result[source]:
            continue
        result[source].append(road_id)
    return dict(result)


def _special_junction_gate(
    *,
    special_junction_segments: dict[str, list[str]],
    special_swsd_junction_types: dict[str, str],
    replaceable_rows: list[dict[str, Any]],
    relation_map: dict[str, RelationRecord],
    rcsd_junction_node_ids: dict[str, list[str]],
    rcsd_junction_road_ids: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], set[str], set[str], dict[str, list[str]]]:
    replaceable_segment_ids = {
        str((row.get("properties") or {}).get("swsd_segment_id"))
        for row in replaceable_rows
        if (row.get("properties") or {}).get("swsd_segment_id") is not None
    }
    rows: list[dict[str, Any]] = []
    blocked_segment_ids: set[str] = set()
    removed_replaceable_segment_ids: set[str] = set()
    blocking_groups_by_segment: dict[str, list[str]] = defaultdict(list)

    for special_junction_id, associated_segment_ids in sorted(special_junction_segments.items()):
        associated = unique_preserve_order(associated_segment_ids)
        replaceable = [segment_id for segment_id in associated if segment_id in replaceable_segment_ids]
        missing = [segment_id for segment_id in associated if segment_id not in replaceable_segment_ids]
        gate_status = "passed" if not missing else "blocked"
        if missing:
            blocked_segment_ids.update(associated)
            for segment_id in associated:
                if special_junction_id not in blocking_groups_by_segment[segment_id]:
                    blocking_groups_by_segment[segment_id].append(special_junction_id)
            removed_replaceable_segment_ids.update(segment_id for segment_id in associated if segment_id in replaceable_segment_ids)

        relation = relation_map.get(special_junction_id)
        rcsd_junction_id = ""
        relation_status = "missing_relation"
        if relation is not None:
            if relation.status == 0 and relation.base_id > 0:
                rcsd_junction_id = str(relation.base_id)
                relation_status = "accepted"
            else:
                relation_status = "invalid_relation_status"
        rows.append(
            feature(
                {
                    "special_junction_id": special_junction_id,
                    "special_junction_type": special_swsd_junction_types.get(special_junction_id, "unknown"),
                    "gate_status": gate_status,
                    "relation_status": relation_status,
                    "rcsd_junction_id": rcsd_junction_id,
                    "associated_segment_ids": associated,
                    "associated_segment_count": len(associated),
                    "replaceable_segment_ids": replaceable,
                    "replaceable_segment_count": len(replaceable),
                    "missing_replaceable_segment_ids": missing,
                    "removed_replaceable_segment_ids": [segment_id for segment_id in associated if segment_id in removed_replaceable_segment_ids],
                    "rcsd_junction_node_ids": rcsd_junction_node_ids.get(rcsd_junction_id, []),
                    "rcsd_junction_road_ids": rcsd_junction_road_ids.get(rcsd_junction_id, []),
                    "notes": "all associated Segments are replaceable" if gate_status == "passed" else "at least one associated Segment is not replaceable",
                },
                None,
            )
        )
    return rows, blocked_segment_ids, removed_replaceable_segment_ids, dict(blocking_groups_by_segment)


def _annotate_special_junction_gate(
    rows: list[dict[str, Any]],
    *,
    segment_special_junctions: dict[str, list[str]],
    special_swsd_junction_types: dict[str, str],
    blocked_segment_ids: set[str],
    blocking_groups_by_segment: dict[str, list[str]],
) -> None:
    for row in rows:
        props = row.get("properties") or {}
        segment_id = str(props.get("swsd_segment_id") or "")
        group_ids = segment_special_junctions.get(segment_id, [])
        if not group_ids:
            gate_status = "not_applicable"
        elif segment_id in blocked_segment_ids:
            gate_status = "blocked"
        else:
            gate_status = "passed"
        props["special_junction_group_ids"] = group_ids
        props["special_junction_group_types"] = [special_swsd_junction_types.get(group_id, "unknown") for group_id in group_ids]
        props["special_junction_gate_status"] = gate_status
        props["special_junction_blocking_group_ids"] = blocking_groups_by_segment.get(segment_id, [])
        row["properties"] = props


def _rcsd_road_coverage_stats(*, rcsd_roads: list[dict[str, Any]], replaceable_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rcsd_road_by_id = _segment_index(rcsd_roads)
    replaceable_reference_ids: list[str] = []
    for row in replaceable_rows:
        props = dict(row.get("properties") or {})
        try:
            replaceable_reference_ids.extend(parse_id_list(props.get("rcsd_road_ids"), allow_empty=True))
        except ParseError:
            continue
    replaceable_unique_ids = unique_preserve_order(
        road_id for road_id in replaceable_reference_ids if road_id in rcsd_road_by_id
    )
    return {
        "rcsd_road_total_count": len(rcsd_road_by_id),
        "rcsd_road_total_length_m": _round_length(sum(_feature_length(feature) for feature in rcsd_road_by_id.values())),
        "replaceable_rcsd_road_unique_count": len(replaceable_unique_ids),
        "replaceable_rcsd_road_unique_length_m": _round_length(
            sum(_feature_length(rcsd_road_by_id[road_id]) for road_id in replaceable_unique_ids)
        ),
        "replaceable_rcsd_road_reference_count": len(replaceable_reference_ids),
        "replaceable_rcsd_road_reference_length_m": _round_length(
            sum(_feature_length(rcsd_road_by_id[road_id]) for road_id in replaceable_reference_ids if road_id in rcsd_road_by_id)
        ),
        "replaceable_rcsd_road_missing_count": sum(1 for road_id in replaceable_reference_ids if road_id not in rcsd_road_by_id),
        "rcsd_road_coverage_stats_basis": "unique_count_and_length_from_final_replaceable_rcsd_road_ids",
    }


def _feature_length(feature: dict[str, Any]) -> float:
    geometry = feature.get("geometry")
    if geometry is None or getattr(geometry, "is_empty", False):
        return 0.0
    return float(getattr(geometry, "length", 0.0) or 0.0)


def _round_length(value: float) -> float:
    return round(float(value), 3)


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


def _resolve_swsd_single_directed_pair(
    *,
    pair_nodes: list[str],
    road_ids: list[str],
    swsd_roads: dict[str, dict[str, Any]],
    swsd_node_canonicalizer: NodeCanonicalizer,
) -> tuple[list[str], str | None]:
    if len(pair_nodes) != 2:
        return [], "invalid_pair_nodes"

    canonical_pair_nodes = _canonical_swsd_pair_nodes(pair_nodes, swsd_node_canonicalizer)
    adjacency: dict[str, set[str]] = defaultdict(set)
    resolved_edge_count = 0
    for road_id in road_ids:
        road = swsd_roads.get(road_id)
        if road is None:
            continue
        endpoints = _swsd_road_canonical_endpoints(road, swsd_node_canonicalizer)
        if endpoints is None:
            continue
        source, target = endpoints
        if source == target:
            continue
        direction = _coerce_int((road.get("properties") or {}).get("direction"))
        added = False
        if direction in {0, 1, 2}:
            adjacency[source].add(target)
            added = True
        if direction in {0, 1, 3}:
            adjacency[target].add(source)
            added = True
        if added:
            resolved_edge_count += 1

    if resolved_edge_count == 0:
        return [], "swsd_single_direction_unresolved"

    first, second = canonical_pair_nodes
    forward = _directed_reachable(adjacency, first, second)
    reverse = _directed_reachable(adjacency, second, first)
    if forward and not reverse:
        return [pair_nodes[0], pair_nodes[1]], None
    if reverse and not forward:
        return [pair_nodes[1], pair_nodes[0]], None
    if forward and reverse:
        return [], "swsd_single_direction_ambiguous"
    return [], "swsd_single_direction_unresolved"


def _canonical_swsd_pair_nodes(pair_nodes: list[str], swsd_node_canonicalizer: NodeCanonicalizer) -> list[str]:
    result: list[str] = []
    for node_id in pair_nodes:
        try:
            result.append(swsd_node_canonicalizer.canonicalize(node_id))
        except ParseError:
            result.append(node_id)
    return result


def _swsd_road_canonical_endpoints(
    road: dict[str, Any],
    swsd_node_canonicalizer: NodeCanonicalizer,
) -> tuple[str, str] | None:
    props = dict(road.get("properties") or {})
    try:
        source = swsd_node_canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
        target = swsd_node_canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
    except (KeyError, ParseError):
        return None
    return source, target


def _map_directed_swsd_pair_to_rcsd(
    *,
    pair_nodes: list[str],
    rcsd_pair_nodes: list[str],
    directed_swsd_pair_nodes: list[str],
) -> list[str]:
    if len(pair_nodes) != 2 or len(rcsd_pair_nodes) != 2 or len(directed_swsd_pair_nodes) != 2:
        return []
    mapping = {pair_nodes[0]: rcsd_pair_nodes[0], pair_nodes[1]: rcsd_pair_nodes[1]}
    result: list[str] = []
    for node_id in directed_swsd_pair_nodes:
        rcsd_node = mapping.get(node_id)
        if rcsd_node is None:
            return []
        result.append(rcsd_node)
    return result


def _first_present(props: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in props and props.get(name) is not None:
            return props[name]
    raise KeyError(names[0])


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _directed_reachable(adjacency: dict[str, set[str]], source: str, target: str) -> bool:
    seen = {source}
    queue: deque[str] = deque([source])
    while queue:
        node = queue.popleft()
        if node == target:
            return True
        for neighbor in adjacency.get(node, set()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)
    return False


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


def _unexpected_base_ids_for_segment(allowed_node_ids: list[str], relation_map: dict[str, RelationRecord]) -> set[str]:
    allowed = set(allowed_node_ids)
    result: set[str] = set()
    for target_id, relation in relation_map.items():
        if target_id in allowed or relation.status != 0 or relation.base_id <= 0:
            continue
        result.add(str(relation.base_id))
    return result


def _buffer_segment_row(segment_id: str, result: BufferSegmentResult) -> dict[str, Any]:
    return {
        "swsd_segment_id": segment_id,
        "buffer_candidate_id": f"{segment_id}_buffer_segment",
        "buffer_status": "passed",
        "buffer_reason": result.reason,
        "required_rcsd_nodes": result.required_rcsd_nodes,
        "optional_allowed_rcsd_nodes": result.optional_allowed_rcsd_nodes,
        "directed_rcsd_pair_nodes": result.directed_rcsd_pair_nodes,
        "retained_rcsd_road_ids": result.retained_road_ids,
        "candidate_rcsd_road_ids": result.candidate_road_ids,
        "candidate_rcsd_node_ids": result.candidate_node_ids,
        "excluded_advance_right_turn_road_ids": result.excluded_advance_right_turn_road_ids,
        "retained_node_ids": result.retained_node_ids,
        "inner_node_ids": result.inner_node_ids,
        "out_node_ids": result.out_node_ids,
        "unexpected_endpoint_node_ids": result.unexpected_endpoint_node_ids,
        "unexpected_mapped_semantic_node_ids": result.unexpected_mapped_semantic_node_ids,
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
    directed_swsd_pair_nodes: list[str],
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
        "directed_swsd_pair_nodes": directed_swsd_pair_nodes,
        "rcsd_pair_nodes": relation.rcsd_pair_nodes,
        "directed_rcsd_pair_nodes": result.directed_rcsd_pair_nodes,
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
        "unexpected_mapped_semantic_node_ids": result.unexpected_mapped_semantic_node_ids,
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
            "directed_swsd_pair_nodes": props.get("directed_swsd_pair_nodes"),
            "rcsd_pair_nodes": props.get("rcsd_pair_nodes"),
            "directed_rcsd_pair_nodes": props.get("directed_rcsd_pair_nodes"),
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
            "unexpected_mapped_semantic_node_ids": props.get("unexpected_mapped_semantic_node_ids"),
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
            "directed_rcsd_pair_nodes": result.directed_rcsd_pair_nodes,
            "missing_required_node_ids": result.missing_required_node_ids,
            "retained_rcsd_road_ids": result.retained_road_ids,
            "candidate_rcsd_road_ids": result.candidate_road_ids,
            "candidate_rcsd_node_ids": result.candidate_node_ids,
            "excluded_advance_right_turn_road_ids": result.excluded_advance_right_turn_road_ids,
            "retained_node_ids": result.retained_node_ids,
            "inner_node_ids": result.inner_node_ids,
            "out_node_ids": result.out_node_ids,
            "unexpected_endpoint_node_ids": result.unexpected_endpoint_node_ids,
            "unexpected_mapped_semantic_node_ids": result.unexpected_mapped_semantic_node_ids,
            "selected_component_id": result.selected_component_id,
            "candidate_road_count": result.candidate_road_count,
            "retained_road_count": result.retained_road_count,
            "candidate_node_count": result.candidate_node_count,
            "retained_node_count": result.retained_node_count,
        },
        None,
    )


def _buffer_failed_metric_name(result: BufferSegmentResult) -> str | None:
    if result.unexpected_mapped_semantic_node_ids:
        return "unexpected_mapped_semantic_node_ids"
    if result.unexpected_endpoint_node_ids:
        return "unexpected_endpoint_node_ids"
    if result.reason in {"rcsd_not_bidirectional_for_swsd_dual", "rcsd_directed_path_missing"}:
        return "rcsd_pair_directionality"
    if result.out_node_ids:
        return "out_node_ids"
    if result.inner_node_ids:
        return "inner_node_ids"
    return None


def _buffer_failed_metric_value(result: BufferSegmentResult) -> list[str] | None:
    if result.unexpected_mapped_semantic_node_ids:
        return result.unexpected_mapped_semantic_node_ids
    if result.unexpected_endpoint_node_ids:
        return result.unexpected_endpoint_node_ids
    if result.reason in {"rcsd_not_bidirectional_for_swsd_dual", "rcsd_directed_path_missing"}:
        return result.directed_rcsd_pair_nodes or result.required_rcsd_nodes[:2]
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
