from __future__ import annotations

from collections.abc import Sequence

import torch


ANCHOR_CANDIDATE_RELATION_DIM = 8


def anchor_candidate_relation_matrix(
    candidate_ids: Sequence[str],
) -> torch.Tensor:
    """Encode truth-free member relations without embedding raw identifiers."""
    if not candidate_ids:
        raise ValueError("anchor candidate relation matrix requires candidates")
    parsed = tuple(_candidate_members(value) for value in candidate_ids)
    rows: list[list[tuple[float, ...]]] = []
    for left_type, left_members in parsed:
        row: list[tuple[float, ...]] = []
        for right_type, right_members in parsed:
            same_type = left_type == right_type
            intersection = left_members & right_members if same_type else set()
            union = left_members | right_members if same_type else set()
            left_only = left_members - right_members if same_type else left_members
            right_only = right_members - left_members if same_type else right_members
            row.append(
                (
                    float(same_type),
                    float(same_type and left_members == right_members),
                    float(
                        same_type
                        and left_members < right_members
                    ),
                    float(
                        same_type
                        and left_members > right_members
                    ),
                    len(intersection) / max(len(union), 1),
                    len(left_members) / 16.0,
                    len(right_members) / 16.0,
                    (len(left_only) + len(right_only))
                    / max(len(union), 1),
                )
            )
        rows.append(row)
    return torch.tensor(rows, dtype=torch.float32)


def _candidate_members(candidate_id: str) -> tuple[str, set[str]]:
    text = str(candidate_id).strip()
    candidate_type, separator, payload = text.partition(":")
    if not separator:
        candidate_type = "UNKNOWN"
        payload = text
    members = {
        value.strip()
        for value in payload.split("|")
        if value.strip()
    }
    if not members:
        members = {f"EMPTY:{candidate_type}"}
    return candidate_type, members


__all__ = [
    "ANCHOR_CANDIDATE_RELATION_DIM",
    "anchor_candidate_relation_matrix",
]
