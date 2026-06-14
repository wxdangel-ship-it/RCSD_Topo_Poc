from __future__ import annotations

from typing import Any

from .parsing import directionality_from_sgrade


def annotate_rejected_swsd_context(
    rejected_rows: list[dict[str, Any]],
    *,
    fusion_units: list[dict[str, Any]],
    segments: dict[str, dict[str, Any]],
) -> None:
    context_by_segment: dict[str, dict[str, Any]] = {}
    for unit in fusion_units:
        props = dict(unit.get("properties") or {})
        segment_id = str(props.get("swsd_segment_id") or props.get("id") or "").strip()
        if segment_id:
            context_by_segment[segment_id] = props
    for segment_id, segment in segments.items():
        props = dict(segment.get("properties") or {})
        context = context_by_segment.setdefault(str(segment_id), {})
        for key, value in props.items():
            if context.get(key) in (None, "") and value not in (None, ""):
                context[key] = value
    for row in rejected_rows:
        props = row.get("properties") or {}
        segment_id = str(props.get("swsd_segment_id") or "").strip()
        context = context_by_segment.get(segment_id, {})
        sgrade = props.get("swsd_sgrade") or context.get("sgrade")
        props["swsd_sgrade"] = sgrade or ""
        props["swsd_directionality"] = props.get("swsd_directionality") or directionality_from_sgrade(sgrade) or "unknown"
        row["properties"] = props
