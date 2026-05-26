from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .audit import failed_attrs
from .io import prepare_run_roots, read_features, write_feature_triplet, write_json
from .parsing import ParseError, anchor_eligible, normalize_id, parse_id_list, unique_preserve_order, yes_value
from .schemas import (
    FUSION_UNIT_FIELDS,
    STEP1_CANDIDATES_STEM,
    STEP1_DIR,
    STEP1_EVD_STEM,
    STEP1_FINAL_FUSION_STEM,
    STEP1_FUSION_STEM,
    STEP1_REJECTED_FIELDS,
    STEP1_REJECTED_STEM,
    STEP1_SUMMARY,
    T06Step1Artifacts,
    feature,
)


JUNC_NODE_KIND2_STEP1_EXEMPT_VALUES = {1, 4096, 8192}


def run_t06_step1_identify_fusion_units(
    *,
    swsd_segment_path: str | Path,
    swsd_nodes_path: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    progress: bool = False,
) -> T06Step1Artifacts:
    resolved_run_id, run_root, step_root = prepare_run_roots(out_root, run_id, STEP1_DIR)
    segments = read_features(swsd_segment_path)
    nodes = read_features(swsd_nodes_path)
    node_index = _node_index(nodes)

    evd_candidates: list[dict[str, Any]] = []
    fusion_units: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    candidate_not_final: list[str] = []

    for index, segment in enumerate(segments, start=1):
        if progress and index % 1000 == 0:
            print(f"[T06 Step1] processed {index}/{len(segments)}", flush=True)
        props = dict(segment.get("properties") or {})
        segment_id = _segment_id(props, index)
        parsed = _parse_segment_lists(segment_id, props, segment.get("geometry"))
        if parsed["reject"] is not None:
            rejected.append(parsed["reject"])
            continue
        pair_nodes = parsed["pair_nodes"]
        junc_nodes = parsed["junc_nodes"]
        semantic_nodes = unique_preserve_order(pair_nodes + junc_nodes)
        missing = [node_id for node_id in semantic_nodes if node_id not in node_index]
        if missing:
            rejected.append(_rejected(segment_id, "before_evd", "missing_node_reference", missing, props, segment.get("geometry"), node_index))
            continue
        junc_kind2_exempt_nodes = _junc_kind2_exempt_nodes(junc_nodes, node_index)
        junc_kind2_exempt_node_set = set(junc_kind2_exempt_nodes)
        eligibility_nodes = unique_preserve_order(
            pair_nodes + [node_id for node_id in junc_nodes if node_id not in junc_kind2_exempt_node_set]
        )
        has_evd_missing = [node_id for node_id in eligibility_nodes if node_index[node_id].get("has_evd") in (None, "")]
        if has_evd_missing:
            rejected.append(_rejected(segment_id, "before_evd", "has_evd_missing", has_evd_missing, props, segment.get("geometry"), node_index))
            continue
        has_evd_failed = [node_id for node_id in eligibility_nodes if not yes_value(node_index[node_id].get("has_evd"))]
        if has_evd_failed:
            rejected.append(_rejected(segment_id, "before_evd", "has_evd_not_yes", has_evd_failed, props, segment.get("geometry"), node_index))
            continue

        row = _fusion_row(segment_id, props, pair_nodes, junc_nodes, semantic_nodes, junc_kind2_exempt_nodes)
        row["has_fail4_fallback"] = any(
            str(node_index[node_id].get("is_anchor") or "").strip().lower() == "fail4_fallback"
            for node_id in semantic_nodes
        )
        evd_candidates.append(feature(row, segment.get("geometry")))

        anchor_missing = [node_id for node_id in eligibility_nodes if node_index[node_id].get("is_anchor") in (None, "")]
        if anchor_missing:
            candidate_not_final.append(segment_id)
            rejected.append(_rejected(segment_id, "after_evd", "is_anchor_missing", anchor_missing, props, segment.get("geometry"), node_index))
            continue
        anchor_failed = [node_id for node_id in eligibility_nodes if not anchor_eligible(node_index[node_id].get("is_anchor"))]
        if anchor_failed:
            candidate_not_final.append(segment_id)
            rejected.append(_rejected(segment_id, "after_evd", "is_anchor_not_eligible", anchor_failed, props, segment.get("geometry"), node_index))
            continue
        fusion_units.append(feature(row, segment.get("geometry")))

    evd_paths = write_feature_triplet(step_root=step_root, stem=STEP1_EVD_STEM, features=evd_candidates, fieldnames=FUSION_UNIT_FIELDS)
    candidate_paths = write_feature_triplet(step_root=step_root, stem=STEP1_CANDIDATES_STEM, features=evd_candidates, fieldnames=FUSION_UNIT_FIELDS)
    fusion_paths = write_feature_triplet(step_root=step_root, stem=STEP1_FUSION_STEM, features=fusion_units, fieldnames=FUSION_UNIT_FIELDS)
    final_fusion_paths = write_feature_triplet(step_root=step_root, stem=STEP1_FINAL_FUSION_STEM, features=fusion_units, fieldnames=FUSION_UNIT_FIELDS)
    rejected_paths = write_feature_triplet(step_root=step_root, stem=STEP1_REJECTED_STEM, features=rejected, fieldnames=STEP1_REJECTED_FIELDS)
    reject_counts = Counter((item["properties"].get("reject_reason") for item in rejected))
    summary_path = step_root / STEP1_SUMMARY
    write_json(
        summary_path,
        {
            "run_id": resolved_run_id,
            "input_paths": {"swsd_segment_path": str(swsd_segment_path), "swsd_nodes_path": str(swsd_nodes_path)},
            "input_segment_count": len(segments),
            "evd_candidate_count": len(evd_candidates),
            "final_fusion_unit_count": len(fusion_units),
            "rejected_before_evd_count": sum(1 for item in rejected if item["properties"].get("reject_stage") == "before_evd"),
            "rejected_after_evd_count": sum(1 for item in rejected if item["properties"].get("reject_stage") == "after_evd"),
            "swsd_candidate_count": len(evd_candidates),
            "swsd_final_fusion_unit_count": len(fusion_units),
            "reject_reason_counts": dict(reject_counts),
            "candidate_not_final_segment_ids": candidate_not_final,
            "junc_kind2_exempt_segment_count": sum(1 for item in fusion_units if item["properties"].get("junc_kind2_exempt_nodes")),
            "junc_kind2_exempt_node_count": sum(len(item["properties"].get("junc_kind2_exempt_nodes") or []) for item in fusion_units),
            "has_fail4_fallback_segment_count": sum(1 for item in fusion_units if item["properties"].get("has_fail4_fallback")),
            "outputs": {
                **{f"evd_candidates_{k}": str(v) for k, v in evd_paths.items()},
                **{f"swsd_candidates_{k}": str(v) for k, v in candidate_paths.items()},
                **{f"fusion_units_{k}": str(v) for k, v in fusion_paths.items()},
                **{f"swsd_final_fusion_units_{k}": str(v) for k, v in final_fusion_paths.items()},
                **{f"rejected_{k}": str(v) for k, v in rejected_paths.items()},
            },
            "gis_topology_checks": {
                "crs_normalized_to": "EPSG:3857",
                "topology_consistency": "input geometries are not silently repaired",
                "geometry_semantics": "Step1 geometry is carried for audit only",
                "audit_traceability": "input paths, counts, reasons and outputs recorded",
                "performance_verifiable": "input and output counts recorded",
            },
        },
    )
    return T06Step1Artifacts(
        resolved_run_id,
        run_root,
        step_root,
        evd_paths["gpkg"],
        fusion_paths["gpkg"],
        rejected_paths["gpkg"],
        summary_path,
        candidate_paths["gpkg"],
        final_fusion_paths["gpkg"],
    )


def _junc_kind2_exempt_nodes(junc_nodes: list[str], node_index: dict[str, dict[str, Any]]) -> list[str]:
    return [
        node_id
        for node_id in junc_nodes
        if _parse_kind2(node_index[node_id].get("kind_2")) in JUNC_NODE_KIND2_STEP1_EXEMPT_VALUES
    ]


def _parse_kind2(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _node_index(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for node in nodes:
        props = dict(node.get("properties") or {})
        try:
            node_id = normalize_id(props.get("id"))
        except ParseError:
            continue
        index.setdefault(node_id, props)
    for node in nodes:
        props = dict(node.get("properties") or {})
        try:
            node_id = normalize_id(props.get("mainnodeid"))
        except ParseError:
            continue
        index.setdefault(node_id, props)
    return index


def _segment_id(props: dict[str, Any], index: int) -> str:
    try:
        return normalize_id(props.get("id"))
    except ParseError:
        return f"segment_{index}"


def _parse_segment_lists(segment_id: str, props: dict[str, Any], geometry: Any) -> dict[str, Any]:
    try:
        pair_nodes = parse_id_list(props.get("pair_nodes"), allow_empty=False)
    except ParseError:
        return {"reject": _rejected(segment_id, "before_evd", "invalid_pair_nodes", [], props, geometry, {})}
    if len(pair_nodes) != 2:
        return {"reject": _rejected(segment_id, "before_evd", "invalid_pair_nodes", [], props, geometry, {})}
    try:
        junc_nodes = parse_id_list(props.get("junc_nodes"), allow_empty=True)
    except ParseError:
        return {"reject": _rejected(segment_id, "before_evd", "invalid_junc_nodes", [], props, geometry, {})}
    return {"reject": None, "pair_nodes": pair_nodes, "junc_nodes": junc_nodes}


def _fusion_row(
    segment_id: str,
    props: dict[str, Any],
    pair_nodes: list[str],
    junc_nodes: list[str],
    semantic_nodes: list[str],
    junc_kind2_exempt_nodes: list[str],
) -> dict[str, Any]:
    roads = []
    try:
        roads = parse_id_list(props.get("roads"), allow_empty=True)
    except ParseError:
        roads = []
    return {
        "swsd_segment_id": segment_id,
        "sgrade": props.get("sgrade"),
        "pair_nodes": pair_nodes,
        "junc_nodes": junc_nodes,
        "semantic_node_set": semantic_nodes,
        "roads": roads,
        "pair_node_count": len(pair_nodes),
        "junc_node_count": len(junc_nodes),
        "junc_kind2_exempt_nodes": junc_kind2_exempt_nodes,
        "has_fail4_fallback": False,
    }


def _rejected(
    segment_id: str,
    stage: str,
    reason: str,
    failed_nodes: list[str],
    props: dict[str, Any],
    geometry: Any,
    node_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return feature(
        {
            "swsd_segment_id": segment_id,
            "reject_stage": stage,
            "reject_reason": reason,
            "failed_node_ids": failed_nodes,
            "failed_node_attrs": failed_attrs(failed_nodes, node_index),
            "junc_kind2_exempt_nodes": _junc_kind2_exempt_nodes_from_props(props, node_index),
            "pair_nodes": props.get("pair_nodes"),
            "junc_nodes": props.get("junc_nodes"),
            "sgrade": props.get("sgrade"),
        },
        geometry,
    )


def _junc_kind2_exempt_nodes_from_props(props: dict[str, Any], node_index: dict[str, dict[str, Any]]) -> list[str]:
    try:
        junc_nodes = parse_id_list(props.get("junc_nodes"), allow_empty=True)
    except ParseError:
        return []
    return [
        node_id
        for node_id in junc_nodes
        if node_id in node_index and _parse_kind2(node_index[node_id].get("kind_2")) in JUNC_NODE_KIND2_STEP1_EXEMPT_VALUES
    ]
