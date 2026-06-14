from __future__ import annotations

from collections import defaultdict
from typing import Any

from .parsing import ParseError, parse_id_list, unique_preserve_order


def promote_isolated_attach_roads(
    *,
    candidate_rows: list[dict[str, Any]],
    replaceable_rows: list[dict[str, Any]],
    failure_business_audit_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_by_segment = {
        str((row.get("properties") or {}).get("swsd_segment_id")): row
        for row in candidate_rows
        if (row.get("properties") or {}).get("swsd_segment_id") is not None
    }
    audit_rows_by_segment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in failure_business_audit_rows:
        segment_id = (row.get("properties") or {}).get("swsd_segment_id")
        if segment_id is not None:
            audit_rows_by_segment[str(segment_id)].append(row)

    retained_owner_by_road: dict[str, set[str]] = defaultdict(set)
    requests_by_road: dict[str, set[str]] = defaultdict(set)
    row_payloads: list[tuple[dict[str, Any], str, list[str], list[str]]] = []
    for row in replaceable_rows:
        props = dict(row.get("properties") or {})
        segment_id = str(props.get("swsd_segment_id") or "")
        if not segment_id:
            continue
        current_roads = _safe_id_list(props.get("rcsd_road_ids") or props.get("retained_rcsd_road_ids"))
        lost_roads = _safe_id_list(props.get("lost_attach_road_ids"))
        row_payloads.append((row, segment_id, current_roads, lost_roads))
        for road_id in current_roads:
            retained_owner_by_road[road_id].add(segment_id)
        for road_id in lost_roads:
            requests_by_road[road_id].add(segment_id)

    promoted_refs = 0
    promoted_unique: set[str] = set()
    blocked_refs = 0
    blocked_unique: set[str] = set()
    promoted_segments = 0
    for row, segment_id, current_roads, lost_roads in row_payloads:
        promoted: list[str] = []
        blocked: list[str] = []
        for road_id in lost_roads:
            if road_id in current_roads:
                continue
            retained_owners = retained_owner_by_road.get(road_id, set()) - {segment_id}
            competing_requesters = requests_by_road.get(road_id, set()) - {segment_id}
            if retained_owners or competing_requesters:
                blocked.append(road_id)
                continue
            promoted.append(road_id)
        promoted = unique_preserve_order(promoted)
        blocked = unique_preserve_order(blocked)
        final_roads = unique_preserve_order([*current_roads, *promoted])
        status, reason = _attach_promotion_status(lost_roads=lost_roads, promoted=promoted, blocked=blocked)
        _apply_attach_promotion(row, promoted=promoted, blocked=blocked, status=status, reason=reason, final_roads=final_roads)
        candidate = candidate_by_segment.get(segment_id)
        if candidate is not None:
            _apply_attach_promotion(candidate, promoted=promoted, blocked=blocked, status=status, reason=reason)
        for audit_row in audit_rows_by_segment.get(segment_id, []):
            _apply_attach_promotion(audit_row, promoted=promoted, blocked=blocked, status=status, reason=reason)
        if promoted:
            promoted_segments += 1
            promoted_refs += len(promoted)
            promoted_unique.update(promoted)
        if blocked:
            blocked_refs += len(blocked)
            blocked_unique.update(blocked)

    return {
        "isolated_attach_promoted_segment_count": promoted_segments,
        "isolated_attach_promoted_road_reference_count": promoted_refs,
        "isolated_attach_promoted_road_unique_count": len(promoted_unique),
        "isolated_attach_blocked_road_reference_count": blocked_refs,
        "isolated_attach_blocked_road_unique_count": len(blocked_unique),
    }


def _apply_attach_promotion(
    row: dict[str, Any],
    *,
    promoted: list[str],
    blocked: list[str],
    status: str,
    reason: str,
    final_roads: list[str] | None = None,
) -> None:
    props = dict(row.get("properties") or {})
    props["promoted_attach_road_ids"] = promoted
    props["blocked_attach_road_ids"] = blocked
    props["attach_promotion_status"] = status
    props["attach_promotion_reason"] = reason
    if final_roads is not None:
        props["rcsd_road_ids"] = final_roads
    row["properties"] = props


def _attach_promotion_status(*, lost_roads: list[str], promoted: list[str], blocked: list[str]) -> tuple[str, str]:
    if not lost_roads:
        return "not_applicable", ""
    if promoted and blocked:
        return "partial_promoted", "global_unique_attach_roads_with_conflicts"
    if promoted:
        return "promoted", "global_unique_attach_roads"
    if blocked:
        return "blocked_conflict", "retained_or_requested_by_other_replaceable_segment"
    return "not_promoted", "no_promotable_attach_roads"


def _safe_id_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []
