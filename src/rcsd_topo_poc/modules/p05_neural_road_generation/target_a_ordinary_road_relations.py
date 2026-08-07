from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


ROAD_RELATION_FEATURE_NAMES = (
    "shares_endpoint_node_id",
    "same_source",
    "both_rcsd",
    "both_swsd",
    "mixed_source",
    "distance_similarity_6m",
    "distance_le_1m",
    "distance_le_3m",
    "distance_le_6m",
    "distance_le_12m",
    "distance_le_25m",
    "orientation_known",
    "absolute_chord_cosine",
)
ROAD_RELATION_MAX_DISTANCE_M = 25.0


def build_sparse_road_relation_rows(
    candidate_rows: Sequence[Mapping[str, Any]],
    *,
    raw_road_by_id: Mapping[str, Any],
    swsd_road_by_id: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Build truth-free sparse pair relations without absolute coordinates."""
    records = []
    for row in candidate_rows:
        road_id = str(row["road_id"])
        source = str(row.get("source") or "")
        source_rows = (
            raw_road_by_id if source == "RCSD" else swsd_road_by_id
        )
        record = source_rows.get(road_id)
        if record is None:
            raise ValueError(
                f"ordinary Road relation geometry is missing: {source}/{road_id}"
            )
        records.append(record)
    result = []
    for left in range(len(candidate_rows)):
        left_row = candidate_rows[left]
        left_record = records[left]
        for right in range(left + 1, len(candidate_rows)):
            right_row = candidate_rows[right]
            right_record = records[right]
            shares_endpoint = bool(
                {
                    str(left_row["start_node_id"]),
                    str(left_row["end_node_id"]),
                }
                & {
                    str(right_row["start_node_id"]),
                    str(right_row["end_node_id"]),
                }
            )
            distance = float(
                left_record.geometry.distance(right_record.geometry)
            )
            if (
                distance > ROAD_RELATION_MAX_DISTANCE_M
                and not shares_endpoint
            ):
                continue
            left_vector = _chord_vector(left_record.geometry)
            right_vector = _chord_vector(right_record.geometry)
            orientation_known = (
                left_vector is not None and right_vector is not None
            )
            absolute_cosine = (
                abs(
                    left_vector[0] * right_vector[0]
                    + left_vector[1] * right_vector[1]
                )
                if orientation_known
                else 0.0
            )
            left_source = str(left_row.get("source") or "")
            right_source = str(right_row.get("source") or "")
            values = [
                float(shares_endpoint),
                float(left_source == right_source),
                float(left_source == right_source == "RCSD"),
                float(left_source == right_source == "SWSD"),
                float(left_source != right_source),
                1.0 / (1.0 + distance / 6.0),
                float(distance <= 1.0),
                float(distance <= 3.0),
                float(distance <= 6.0),
                float(distance <= 12.0),
                float(distance <= 25.0),
                float(orientation_known),
                absolute_cosine,
            ]
            result.append(
                {
                    "left_index": left,
                    "right_index": right,
                    "feature_values": values,
                }
            )
    return result


def _chord_vector(geometry: Any) -> tuple[float, float] | None:
    if geometry.geom_type != "LineString":
        return None
    coordinates = list(geometry.coords)
    if len(coordinates) < 2:
        return None
    delta_x = float(coordinates[-1][0] - coordinates[0][0])
    delta_y = float(coordinates[-1][1] - coordinates[0][1])
    length = math.hypot(delta_x, delta_y)
    if length <= 1e-9:
        return None
    return delta_x / length, delta_y / length


__all__ = [
    "ROAD_RELATION_FEATURE_NAMES",
    "ROAD_RELATION_MAX_DISTANCE_M",
    "build_sparse_road_relation_rows",
]
