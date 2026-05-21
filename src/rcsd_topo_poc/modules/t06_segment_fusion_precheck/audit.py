from __future__ import annotations

from collections import Counter
from typing import Any


def reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(row.get("reject_reason") or row.get("candidate_reason") or "unknown") for row in rows))


def failed_attrs(node_ids: list[str], node_index: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        node_id: {
            "has_evd": node_index.get(node_id, {}).get("has_evd"),
            "is_anchor": node_index.get(node_id, {}).get("is_anchor"),
        }
        for node_id in node_ids
    }
