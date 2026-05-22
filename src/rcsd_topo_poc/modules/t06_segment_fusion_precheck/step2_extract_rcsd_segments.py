from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .direction_inference import infer_swsd_oneway_direction
from .graph_builders import build_road_graph
from .io import prepare_run_roots, read_features, write_feature_triplet, write_json
from .parsing import ParseError, directionality_from_sgrade, normalize_id, parse_id_list
from .rcsd_candidate_extraction import extract_rcsd_candidates
from .relation_mapping import RelationRecord, accepted_base_ids, build_relation_map, check_segment_relations
from .schemas import (
    STEP2_CANDIDATE_FIELDS,
    STEP2_CANDIDATES_STEM,
    STEP2_DIR,
    STEP2_REJECTED_FIELDS,
    STEP2_REJECTED_STEM,
    STEP2_REPLACEABLE_FIELDS,
    STEP2_REPLACEABLE_STEM,
    STEP2_SUMMARY,
    T06Step2Artifacts,
    feature,
)
from .trend_filters import evaluate_candidate


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
    progress: bool = False,
) -> T06Step2Artifacts:
    resolved_run_id, run_root, step_root = prepare_run_roots(out_root, run_id, STEP2_DIR)
    fusion_units = read_features(swsd_fusion_units_path)
    segments = _segment_index(read_features(swsd_segment_path))
    swsd_roads = read_features(swsd_roads_path)
    swsd_nodes = _node_geometry_index(read_features(swsd_nodes_path))
    relation_map = build_relation_map(read_features(intersection_match_path, crs_override="EPSG:4326"))
    rcsd_roads = read_features(rcsdroad_path)
    rcsd_nodes = _node_geometry_index(read_features(rcsdnode_path))
    rcsd_graph = build_road_graph(rcsd_roads)
    all_base_ids = accepted_base_ids(relation_map)

    candidate_rows: list[dict[str, Any]] = []
    replaceable_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    relation_success_count = 0
    single_input_count = 0
    dual_input_count = 0
    ambiguous_count = 0
    junc_kind2_relation_exempt_segment_count = 0
    junc_kind2_relation_exempt_node_count = 0

    for index, unit in enumerate(fusion_units, start=1):
        if progress and index % 1000 == 0:
            print(f"[T06 Step2] processed {index}/{len(fusion_units)}", flush=True)
        props = dict(unit.get("properties") or {})
        segment_id = str(props.get("swsd_segment_id") or props.get("id") or f"segment_{index}")
        segment = segments.get(segment_id, unit)
        segment_props = dict(segment.get("properties") or {})
        pair_nodes, junc_nodes, junc_kind2_exempt_nodes, roads, parse_reason = _parse_unit_lists(props, segment_props)
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

        directionality = directionality_from_sgrade(segment_props.get("sgrade") or props.get("sgrade"))
        if directionality is None:
            rejected_rows.append(
                _reject(
                    segment_id,
                    None,
                    "swsd_direction_inference",
                    "missing_swsd_oneway_direction",
                    junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                )
            )
            continue
        swsd_to_rcsd = {swsd: rcsd for swsd, rcsd in zip(pair_nodes, relation.rcsd_pair_nodes)}
        if directionality == "single":
            single_input_count += 1
            inference = infer_swsd_oneway_direction(pair_nodes=pair_nodes, segment_road_ids=roads, swsd_road_features=swsd_roads)
            if inference.status != "unique" or inference.source_node is None or inference.target_node is None:
                rejected_rows.append(
                    _reject(
                        segment_id,
                        None,
                        "swsd_direction_inference",
                        inference.reject_reason or "missing_swsd_oneway_direction",
                        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                    )
                )
                continue
            swsd_pair_order = [inference.source_node, inference.target_node]
        else:
            dual_input_count += 1
            inference = None
            swsd_pair_order = list(pair_nodes)

        rcsd_pair_order = [swsd_to_rcsd[swsd_pair_order[0]], swsd_to_rcsd[swsd_pair_order[1]]]
        extraction = extract_rcsd_candidates(
            graph=rcsd_graph,
            source_node=rcsd_pair_order[0],
            target_node=rcsd_pair_order[1],
            swsd_directionality=directionality,
        )
        if extraction.reject_reason is not None:
            rejected_rows.append(
                _reject(
                    segment_id,
                    None,
                    "rcsd_candidate_connectivity",
                    extraction.reject_reason,
                    junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                )
            )
            continue

        passed_candidates: list[dict[str, Any]] = []
        for candidate in extraction.candidates:
            trend = evaluate_candidate(
                candidate=candidate,
                swsd_directionality=directionality,
                swsd_pair_nodes=swsd_pair_order,
                swsd_junc_nodes=relation_junc_nodes,
                rcsd_pair_nodes=rcsd_pair_order,
                rcsd_junc_nodes=relation.rcsd_junc_nodes,
                all_relation_base_ids=all_base_ids_for_segment,
                swsd_geometry=segment.get("geometry"),
                swsd_node_geometries=swsd_nodes,
                rcsd_node_geometries=rcsd_nodes,
                max_main_axis_angle_diff_deg=max_main_axis_angle_diff_deg,
                min_coarse_length_ratio=min_coarse_length_ratio,
                max_coarse_length_ratio=max_coarse_length_ratio,
            )
            row = _candidate_row(segment_id, props, directionality, inference, relation, candidate, trend)
            row["swsd_pair_nodes"] = pair_nodes
            row["swsd_junc_nodes"] = junc_nodes
            row["junc_kind2_exempt_nodes"] = junc_kind2_exempt_nodes
            candidate_rows.append(feature(row, candidate.path.geometry))
            if trend.passed:
                passed_candidates.append(feature(row, candidate.path.geometry))
            else:
                rejected_rows.append(
                    _reject(
                        segment_id,
                        candidate.candidate_id,
                        "trend_filter",
                        trend.reason,
                        failed_metric_name=_metric_name(trend.reason),
                        failed_metric_value=_metric_value(trend.metrics, trend.reason),
                        junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                    )
                )

        if len(passed_candidates) > 1:
            ambiguous_count += 1
            rejected_rows.append(
                _reject(
                    segment_id,
                    None,
                    "uniqueness_filter",
                    "ambiguous_rcsd_candidates",
                    junc_kind2_exempt_nodes=junc_kind2_exempt_nodes,
                )
            )
            continue
        if len(passed_candidates) == 1:
            replaceable_rows.append(_replaceable_row(passed_candidates[0]))

    candidate_paths = write_feature_triplet(step_root=step_root, stem=STEP2_CANDIDATES_STEM, features=candidate_rows, fieldnames=STEP2_CANDIDATE_FIELDS)
    replaceable_paths = write_feature_triplet(step_root=step_root, stem=STEP2_REPLACEABLE_STEM, features=replaceable_rows, fieldnames=STEP2_REPLACEABLE_FIELDS)
    rejected_paths = write_feature_triplet(step_root=step_root, stem=STEP2_REJECTED_STEM, features=rejected_rows, fieldnames=STEP2_REJECTED_FIELDS)
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
            "ambiguous_candidate_count": ambiguous_count,
            "single_segment_input_count": single_input_count,
            "dual_segment_input_count": dual_input_count,
            "single_segment_replaceable_count": sum(1 for item in replaceable_rows if item["properties"].get("swsd_directionality") == "single"),
            "dual_segment_replaceable_count": sum(1 for item in replaceable_rows if item["properties"].get("swsd_directionality") == "dual"),
            "outputs": {**{f"candidates_{k}": str(v) for k, v in candidate_paths.items()}, **{f"replaceable_{k}": str(v) for k, v in replaceable_paths.items()}, **{f"rejected_{k}": str(v) for k, v in rejected_paths.items()}},
            "gis_topology_checks": {
                "crs_normalized_to": "EPSG:3857",
                "topology_consistency": "connectivity, junc pass-through and semantic-junction crossing are explicit filters",
                "geometry_semantics": "geometry is used only for trend filters after relation and direction filters",
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


def _node_geometry_index(features: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for feature in features:
        props = dict(feature.get("properties") or {})
        for field in ("id", "mainnodeid"):
            try:
                result.setdefault(normalize_id(props.get(field)), feature.get("geometry"))
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


def _candidate_row(segment_id: str, props: dict[str, Any], directionality: str, inference: Any, relation: Any, candidate: Any, trend: Any) -> dict[str, Any]:
    metrics = trend.metrics
    return {
        "swsd_segment_id": segment_id,
        "rcsd_candidate_id": candidate.candidate_id,
        "swsd_sgrade": props.get("sgrade"),
        "swsd_directionality": directionality,
        "swsd_oneway_source_node": getattr(inference, "source_node", None),
        "swsd_oneway_target_node": getattr(inference, "target_node", None),
        "swsd_direction_inference": getattr(inference, "status", "not_required"),
        "rcsd_directionality": candidate.directionality,
        "swsd_pair_nodes": props.get("pair_nodes"),
        "rcsd_pair_nodes": relation.rcsd_pair_nodes,
        "swsd_junc_nodes": props.get("junc_nodes"),
        "junc_kind2_exempt_nodes": props.get("junc_kind2_exempt_nodes"),
        "rcsd_junc_nodes": relation.rcsd_junc_nodes,
        "rcsd_road_ids": candidate.road_ids,
        "rcsd_node_path": candidate.path.node_path,
        "rcsd_forward_reachable": candidate.forward_reachable,
        "rcsd_reverse_reachable": candidate.reverse_reachable,
        "directionality_trend_pass": metrics.get("directionality_trend_pass"),
        "oneway_direction_trend_pass": metrics.get("oneway_direction_trend_pass"),
        "semantic_junc_order_trend_pass": metrics.get("semantic_junc_order_trend_pass"),
        "main_axis_angle_diff_deg": metrics.get("main_axis_angle_diff_deg"),
        "main_axis_trend_pass": metrics.get("main_axis_trend_pass"),
        "length_ratio": metrics.get("length_ratio"),
        "coarse_length_trend_pass": metrics.get("coarse_length_trend_pass"),
        "candidate_status": "passed" if trend.passed else "rejected",
        "candidate_reason": trend.reason,
    }


def _replaceable_row(candidate_feature: dict[str, Any]) -> dict[str, Any]:
    props = dict(candidate_feature["properties"])
    return feature(
        {
            "swsd_segment_id": props.get("swsd_segment_id"),
            "rcsd_candidate_id": props.get("rcsd_candidate_id"),
            "replacement_ready": True,
            "swsd_sgrade": props.get("swsd_sgrade"),
            "swsd_directionality": props.get("swsd_directionality"),
            "rcsd_directionality": props.get("rcsd_directionality"),
            "swsd_pair_nodes": props.get("swsd_pair_nodes"),
            "rcsd_pair_nodes": props.get("rcsd_pair_nodes"),
            "swsd_junc_nodes": props.get("swsd_junc_nodes"),
            "junc_kind2_exempt_nodes": props.get("junc_kind2_exempt_nodes"),
            "rcsd_junc_nodes": props.get("rcsd_junc_nodes"),
            "rcsd_road_ids": props.get("rcsd_road_ids"),
            "trend_filter_passed": True,
            "hard_filter_passed": True,
        },
        candidate_feature.get("geometry"),
    )


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


def _metric_name(reason: str) -> str | None:
    return {
        "main_axis_trend_mismatch": "main_axis_angle_diff_deg",
        "coarse_length_trend_mismatch": "length_ratio",
    }.get(reason)


def _metric_value(metrics: dict[str, Any], reason: str) -> Any:
    name = _metric_name(reason)
    return metrics.get(name) if name else None
