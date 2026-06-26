from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .audit import failed_attrs
from .io import prepare_run_roots, read_features, write_csv, write_feature_triplet, write_json
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
    STEP1_STATS_CSV,
    STEP1_STATS_FIELDS,
    STEP1_SUMMARY,
    T06Step1Artifacts,
    feature,
)


JUNC_NODE_KIND2_STEP1_EXEMPT_VALUES = {1, 4096, 8192}
STEP1_DETACHED_JUNC_BLOCKED_KIND2_VALUES = {64, 128}
STEP2_PROBE_RELAXED_PAIR_KIND2_VALUES = {2048}
STEP2_PROBE_RELAXED_PAIR_FAIL1_KIND2_VALUES = {4}
STEP2_PROBE_RELAXED_JUNC_KIND2_VALUES = {16, 2048}


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
    sgrade_order: list[str] = []
    total_by_sgrade: Counter[str] = Counter()
    evd_by_sgrade: Counter[str] = Counter()
    final_by_sgrade: Counter[str] = Counter()

    for index, segment in enumerate(segments, start=1):
        if progress and index % 1000 == 0:
            print(f"[T06 Step1] processed {index}/{len(segments)}", flush=True)
        props = dict(segment.get("properties") or {})
        segment_id = _segment_id(props, index)
        sgrade_key = _sgrade_key(props.get("sgrade"))
        if sgrade_key not in total_by_sgrade:
            sgrade_order.append(sgrade_key)
        total_by_sgrade[sgrade_key] += 1
        parsed = _parse_segment_lists(segment_id, props, segment.get("geometry"))
        if parsed["reject"] is not None:
            rejected.append(parsed["reject"])
            continue
        pair_nodes = parsed["pair_nodes"]
        if len(set(pair_nodes)) != 2:
            rejected.append(
                _rejected(
                    segment_id,
                    "before_evd",
                    "swsd_pair_nodes_not_distinct",
                    pair_nodes,
                    props,
                    segment.get("geometry"),
                    node_index,
                )
            )
            continue
        junc_nodes = parsed["junc_nodes"]
        semantic_nodes = unique_preserve_order(pair_nodes + junc_nodes)
        missing = [node_id for node_id in semantic_nodes if node_id not in node_index]
        if missing:
            rejected.append(_rejected(segment_id, "before_evd", "missing_node_reference", missing, props, segment.get("geometry"), node_index))
            continue
        junc_kind2_exempt_nodes = _junc_kind2_exempt_nodes(junc_nodes, node_index)
        junc_kind2_exempt_node_set = set(junc_kind2_exempt_nodes)
        detached_junc_reasons: dict[str, str] = {}
        non_exempt_junc_nodes = [node_id for node_id in junc_nodes if node_id not in junc_kind2_exempt_node_set]

        pair_has_evd_missing = [node_id for node_id in pair_nodes if node_index[node_id].get("has_evd") in (None, "")]
        if pair_has_evd_missing:
            rejected.append(_rejected(segment_id, "before_evd", "has_evd_missing", pair_has_evd_missing, props, segment.get("geometry"), node_index))
            continue
        pair_has_evd_failed = [node_id for node_id in pair_nodes if not yes_value(node_index[node_id].get("has_evd"))]
        if pair_has_evd_failed:
            rejected.append(_rejected(segment_id, "before_evd", "has_evd_not_yes", pair_has_evd_failed, props, segment.get("geometry"), node_index))
            continue

        junc_has_evd_missing = [node_id for node_id in non_exempt_junc_nodes if node_index[node_id].get("has_evd") in (None, "")]
        blocked_junc_missing = _record_detached_junc_failures(
            detached_junc_reasons=detached_junc_reasons,
            failed_nodes=junc_has_evd_missing,
            pair_nodes=pair_nodes,
            node_index=node_index,
            sgrade=sgrade_key,
            reason="has_evd_missing",
        )
        if blocked_junc_missing:
            rejected.append(_rejected(segment_id, "before_evd", "has_evd_missing", blocked_junc_missing, props, segment.get("geometry"), node_index))
            continue
        junc_has_evd_failed = [
            node_id
            for node_id in non_exempt_junc_nodes
            if node_id not in detached_junc_reasons and not yes_value(node_index[node_id].get("has_evd"))
        ]
        blocked_junc_failed = _record_detached_junc_failures(
            detached_junc_reasons=detached_junc_reasons,
            failed_nodes=junc_has_evd_failed,
            pair_nodes=pair_nodes,
            node_index=node_index,
            sgrade=sgrade_key,
            reason="has_evd_not_yes",
        )
        if blocked_junc_failed:
            rejected.append(_rejected(segment_id, "before_evd", "has_evd_not_yes", blocked_junc_failed, props, segment.get("geometry"), node_index))
            continue

        kept_junc_nodes = _kept_junc_nodes(junc_nodes, detached_junc_reasons)
        semantic_nodes = unique_preserve_order(pair_nodes + kept_junc_nodes)
        row = _fusion_row(
            segment_id,
            props,
            pair_nodes,
            kept_junc_nodes,
            semantic_nodes,
            junc_kind2_exempt_nodes,
            detached_junc_reasons,
        )
        row["has_fail4_fallback"] = any(
            str(node_index[node_id].get("is_anchor") or "").strip().lower() == "fail4_fallback"
            for node_id in semantic_nodes
        )
        evd_candidates.append(feature(row, segment.get("geometry")))
        evd_by_sgrade[sgrade_key] += 1

        anchor_required_nodes = [
            node_id
            for node_id in unique_preserve_order(
                pair_nodes + [junc_id for junc_id in kept_junc_nodes if junc_id not in junc_kind2_exempt_node_set]
            )
            if not _step2_probe_relaxation_allowed(
                node_id=node_id,
                pair_nodes=pair_nodes,
                node_index=node_index,
                sgrade=sgrade_key,
            )
        ]
        anchor_missing = [node_id for node_id in anchor_required_nodes if node_index[node_id].get("is_anchor") in (None, "")]
        if anchor_missing:
            blocked_anchor_missing = _record_detached_junc_failures(
                detached_junc_reasons=detached_junc_reasons,
                failed_nodes=[node_id for node_id in anchor_missing if node_id not in set(pair_nodes)],
                pair_nodes=pair_nodes,
                node_index=node_index,
                sgrade=sgrade_key,
                reason="is_anchor_missing",
            )
            pair_anchor_missing = [node_id for node_id in anchor_missing if node_id in set(pair_nodes)]
            if not pair_anchor_missing and not blocked_anchor_missing:
                kept_junc_nodes = _kept_junc_nodes(junc_nodes, detached_junc_reasons)
                anchor_required_nodes = [
                    node_id
                    for node_id in unique_preserve_order(
                        pair_nodes + [junc_id for junc_id in kept_junc_nodes if junc_id not in junc_kind2_exempt_node_set]
                    )
                    if not _step2_probe_relaxation_allowed(
                        node_id=node_id,
                        pair_nodes=pair_nodes,
                        node_index=node_index,
                        sgrade=sgrade_key,
                    )
                ]
                anchor_missing = []
            else:
                anchor_missing = unique_preserve_order(pair_anchor_missing + blocked_anchor_missing)
        if anchor_missing:
            candidate_not_final.append(segment_id)
            rejected.append(_rejected(segment_id, "after_evd", "is_anchor_missing", anchor_missing, props, segment.get("geometry"), node_index))
            continue
        if detached_junc_reasons:
            kept_junc_nodes = _kept_junc_nodes(junc_nodes, detached_junc_reasons)
            semantic_nodes = unique_preserve_order(pair_nodes + kept_junc_nodes)
            row = _fusion_row(
                segment_id,
                props,
                pair_nodes,
                kept_junc_nodes,
                semantic_nodes,
                junc_kind2_exempt_nodes,
                detached_junc_reasons,
            )
            row["has_fail4_fallback"] = any(
                str(node_index[node_id].get("is_anchor") or "").strip().lower() == "fail4_fallback"
                for node_id in semantic_nodes
            )
        anchor_failed = [node_id for node_id in anchor_required_nodes if not anchor_eligible(node_index[node_id].get("is_anchor"))]
        if anchor_failed:
            blocked_anchor_failed = _record_detached_junc_failures(
                detached_junc_reasons=detached_junc_reasons,
                failed_nodes=[node_id for node_id in anchor_failed if node_id not in set(pair_nodes)],
                pair_nodes=pair_nodes,
                node_index=node_index,
                sgrade=sgrade_key,
                reason="is_anchor_not_eligible",
            )
            pair_anchor_failed = [node_id for node_id in anchor_failed if node_id in set(pair_nodes)]
            if not pair_anchor_failed and not blocked_anchor_failed:
                kept_junc_nodes = _kept_junc_nodes(junc_nodes, detached_junc_reasons)
                semantic_nodes = unique_preserve_order(pair_nodes + kept_junc_nodes)
                row = _fusion_row(
                    segment_id,
                    props,
                    pair_nodes,
                    kept_junc_nodes,
                    semantic_nodes,
                    junc_kind2_exempt_nodes,
                    detached_junc_reasons,
                )
                row["has_fail4_fallback"] = any(
                    str(node_index[node_id].get("is_anchor") or "").strip().lower() == "fail4_fallback"
                    for node_id in semantic_nodes
                )
                fusion_units.append(feature(row, segment.get("geometry")))
                final_by_sgrade[sgrade_key] += 1
                continue
            anchor_failed = unique_preserve_order(pair_anchor_failed + blocked_anchor_failed)
        if anchor_failed:
            candidate_not_final.append(segment_id)
            rejected.append(_rejected(segment_id, "after_evd", "is_anchor_not_eligible", anchor_failed, props, segment.get("geometry"), node_index))
            continue
        fusion_units.append(feature(row, segment.get("geometry")))
        final_by_sgrade[sgrade_key] += 1

    _remove_legacy_duplicate_outputs(step_root)
    candidate_paths = write_feature_triplet(step_root=step_root, stem=STEP1_CANDIDATES_STEM, features=evd_candidates, fieldnames=FUSION_UNIT_FIELDS)
    final_fusion_paths = write_feature_triplet(step_root=step_root, stem=STEP1_FINAL_FUSION_STEM, features=fusion_units, fieldnames=FUSION_UNIT_FIELDS)
    rejected_paths = write_feature_triplet(step_root=step_root, stem=STEP1_REJECTED_STEM, features=rejected, fieldnames=STEP1_REJECTED_FIELDS)
    stats_path = step_root / STEP1_STATS_CSV
    write_csv(
        stats_path,
        _stats_rows(
            sgrade_order=sgrade_order,
            total_by_sgrade=total_by_sgrade,
            evd_by_sgrade=evd_by_sgrade,
            final_by_sgrade=final_by_sgrade,
        ),
        STEP1_STATS_FIELDS,
    )
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
            "detached_junc_segment_count": sum(1 for item in fusion_units if item["properties"].get("detached_junc_nodes")),
            "detached_junc_node_count": sum(len(item["properties"].get("detached_junc_nodes") or []) for item in fusion_units),
            "detached_junc_reason_counts": _detached_junc_reason_counts(fusion_units),
            "has_fail4_fallback_segment_count": sum(1 for item in fusion_units if item["properties"].get("has_fail4_fallback")),
            "outputs": {
                **{f"swsd_candidates_{k}": str(v) for k, v in candidate_paths.items()},
                **{f"swsd_final_fusion_units_{k}": str(v) for k, v in final_fusion_paths.items()},
                **{f"rejected_{k}": str(v) for k, v in rejected_paths.items()},
                "segment_stats_csv": str(stats_path),
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
        candidate_paths["gpkg"],
        final_fusion_paths["gpkg"],
        rejected_paths["gpkg"],
        summary_path,
        candidate_paths["gpkg"],
        final_fusion_paths["gpkg"],
        stats_path,
    )


def _remove_legacy_duplicate_outputs(step_root: Path) -> None:
    for stem in (STEP1_EVD_STEM, STEP1_FUSION_STEM):
        for suffix in (".gpkg", ".csv", ".json"):
            path = step_root / f"{stem}{suffix}"
            if path.exists():
                path.unlink()


def _sgrade_key(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "__MISSING__"


def _stats_rows(
    *,
    sgrade_order: list[str],
    total_by_sgrade: Counter[str],
    evd_by_sgrade: Counter[str],
    final_by_sgrade: Counter[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "sgrade": "__TOTAL__",
            "total_segment_count": sum(total_by_sgrade.values()),
            "evd_candidate_count": sum(evd_by_sgrade.values()),
            "final_fusion_unit_count": sum(final_by_sgrade.values()),
        }
    ]
    rows.extend(
        {
            "sgrade": sgrade,
            "total_segment_count": total_by_sgrade[sgrade],
            "evd_candidate_count": evd_by_sgrade[sgrade],
            "final_fusion_unit_count": final_by_sgrade[sgrade],
        }
        for sgrade in sgrade_order
    )
    return rows


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


def _step2_probe_relaxation_allowed(
    *,
    node_id: str,
    pair_nodes: list[str],
    node_index: dict[str, dict[str, Any]],
    sgrade: str,
) -> bool:
    attrs = node_index[node_id]
    if not yes_value(attrs.get("has_evd")):
        return False
    if attrs.get("is_anchor") in (None, "") or anchor_eligible(attrs.get("is_anchor")):
        return False
    kind2 = _parse_kind2(attrs.get("kind_2"))
    pair_node_set = set(pair_nodes)
    anchor_state = str(attrs.get("is_anchor") or "").strip().lower()
    if _is_high_grade_sgrade(sgrade) and node_id in pair_node_set:
        if anchor_state == "fail1":
            return kind2 in STEP2_PROBE_RELAXED_PAIR_FAIL1_KIND2_VALUES
        return kind2 in STEP2_PROBE_RELAXED_PAIR_KIND2_VALUES
    if _is_high_grade_sgrade(sgrade):
        return kind2 in STEP2_PROBE_RELAXED_JUNC_KIND2_VALUES
    if node_id in pair_node_set and _is_virtual_t_pair_probe_sgrade(sgrade):
        return kind2 in STEP2_PROBE_RELAXED_PAIR_KIND2_VALUES and _all_pair_nodes_are_virtual_t(pair_nodes, node_index)
    return False


def _is_high_grade_sgrade(value: Any) -> bool:
    text = str(value or "").strip()
    return text.startswith("0-0") or text.startswith("0-1")


def _is_virtual_t_pair_probe_sgrade(value: Any) -> bool:
    text = str(value or "").strip()
    return text.startswith("0-2") and "双" in text


def _all_pair_nodes_are_virtual_t(pair_nodes: list[str], node_index: dict[str, dict[str, Any]]) -> bool:
    if len(pair_nodes) != 2:
        return False
    return all(_parse_kind2(node_index[node_id].get("kind_2")) in STEP2_PROBE_RELAXED_PAIR_KIND2_VALUES for node_id in pair_nodes)


def _record_detached_junc_failures(
    *,
    detached_junc_reasons: dict[str, str],
    failed_nodes: list[str],
    pair_nodes: list[str],
    node_index: dict[str, dict[str, Any]],
    sgrade: str,
    reason: str,
) -> list[str]:
    blocked: list[str] = []
    pair_node_set = set(pair_nodes)
    for node_id in failed_nodes:
        if node_id in pair_node_set or not _step1_detached_junc_allowed(node_id=node_id, node_index=node_index, sgrade=sgrade):
            blocked.append(node_id)
            continue
        detached_junc_reasons.setdefault(node_id, reason)
    return blocked


def _step1_detached_junc_allowed(
    *,
    node_id: str,
    node_index: dict[str, dict[str, Any]],
    sgrade: str,
) -> bool:
    if not _is_high_grade_sgrade(sgrade):
        return False
    kind2 = _parse_kind2(node_index[node_id].get("kind_2"))
    if kind2 is None:
        return False
    return kind2 not in STEP1_DETACHED_JUNC_BLOCKED_KIND2_VALUES


def _kept_junc_nodes(junc_nodes: list[str], detached_junc_reasons: dict[str, str]) -> list[str]:
    detached = set(detached_junc_reasons)
    return [node_id for node_id in junc_nodes if node_id not in detached]


def _detached_reason_entries(detached_junc_reasons: dict[str, str]) -> list[str]:
    return [f"{node_id}:{reason}" for node_id, reason in detached_junc_reasons.items()]


def _detached_junc_reason_counts(fusion_units: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in fusion_units:
        for entry in item["properties"].get("detached_junc_reasons") or []:
            text = str(entry)
            reason = text.split(":", 1)[1] if ":" in text else text
            counts[reason] += 1
    return dict(counts)


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
    detached_junc_reasons: dict[str, str] | None = None,
) -> dict[str, Any]:
    roads = []
    try:
        roads = parse_id_list(props.get("roads"), allow_empty=True)
    except ParseError:
        roads = []
    detached_junc_reasons = detached_junc_reasons or {}
    detached_junc_nodes = list(detached_junc_reasons)
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
        "detached_junc_nodes": detached_junc_nodes,
        "detached_junc_reasons": _detached_reason_entries(detached_junc_reasons),
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
