from __future__ import annotations

import math

import geopandas as gpd
import pandas as pd

from .segment_first_skeleton import canonical_id, parse_id_list


def build_road_lane_relation(
    relations: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    *,
    maximum_distance_m: float = 20.0,
    maximum_direction_angle_deg: float = 75.0,
) -> gpd.GeoDataFrame:
    """Compile local, directional Lane-to-published-Road lineage.

    A Patch Road/LaneGroup identity supplies candidates only.  A relation is
    published when the Lane is locally close to, longitudinally overlaps, and
    follows the direction of the final Road part.  This prevents one Patch Road
    lineage from attaching every Lane to both directional or distant Road parts.
    """
    if relations.empty or roads.empty:
        return _empty_result(relations)

    relation_groups = {
        str(patch_road_key): group.copy()
        for patch_road_key, group in relations.groupby(
            relations["patch_road_key"].astype(str),
            sort=False,
        )
    }
    lane_groups = {
        canonical_id(lane_id): group.copy()
        for lane_id, group in relations.groupby(
            relations["lane_id"].map(canonical_id),
            sort=False,
        )
    }
    rows: list[dict[str, object]] = []
    for road in roads.itertuples(index=False):
        patch_keys = set(
            parse_id_list(
                getattr(road, "source_patch_road_keys", "")
                or getattr(road, "patch_road_key", "")
            )
        )
        direct_lane_ids = set(
            parse_id_list(getattr(road, "source_lane_ids", ""))
        )
        candidate_indexes: set[object] = set()
        for patch_key in sorted(patch_keys):
            group = relation_groups.get(patch_key)
            if group is not None:
                candidate_indexes.update(group.index)
        for lane_id in sorted(direct_lane_ids):
            group = lane_groups.get(canonical_id(lane_id))
            if group is not None:
                candidate_indexes.update(group.index)

        for relation_index in sorted(candidate_indexes, key=str):
            relation = relations.loc[relation_index]
            fit = _local_directional_fit(
                road.geometry,
                relation.geometry,
                maximum_distance_m=maximum_distance_m,
                maximum_direction_angle_deg=maximum_direction_angle_deg,
            )
            if fit is None:
                continue
            lane_id = canonical_id(relation.get("lane_id"))
            row = relation.to_dict()
            row.update(
                {
                    "road_id": road.id,
                    "relation_state": "published_built_road_lane",
                    "relation_basis": (
                        "direct_lane_lineage"
                        if lane_id in direct_lane_ids
                        else "patch_lane_group_directional_fit"
                    ),
                    **fit,
                }
            )
            rows.append(row)

    if not rows:
        return _empty_result(relations)
    return gpd.GeoDataFrame(
        rows,
        geometry="geometry",
        crs=relations.crs,
    ).sort_values(
        ["road_id", "patch_road_key", "lane_id"],
        kind="stable",
    ).reset_index(drop=True)


def _local_directional_fit(
    road_geometry: object,
    lane_geometry: object,
    *,
    maximum_distance_m: float,
    maximum_direction_angle_deg: float,
) -> dict[str, float] | None:
    if (
        road_geometry is None
        or lane_geometry is None
        or road_geometry.is_empty
        or lane_geometry.is_empty
        or road_geometry.geom_type != "LineString"
        or lane_geometry.geom_type != "LineString"
        or road_geometry.length <= 1e-6
        or lane_geometry.length <= 1e-6
    ):
        return None
    distance_m = float(road_geometry.distance(lane_geometry))
    if distance_m > maximum_distance_m + 1e-9:
        return None

    road_measure = float(
        road_geometry.project(
            lane_geometry.interpolate(0.5, normalized=True)
        )
    )
    lane_measure = float(
        lane_geometry.project(road_geometry.interpolate(road_measure))
    )
    direction_angle_deg = _directed_angle_deg(
        _line_tangent(road_geometry, road_measure),
        _line_tangent(lane_geometry, lane_measure),
    )
    if direction_angle_deg > maximum_direction_angle_deg + 1e-9:
        return None

    overlap_length_m = float(
        lane_geometry.intersection(
            road_geometry.buffer(maximum_distance_m, cap_style=2)
        ).length
    )
    minimum_overlap_m = min(
        2.0,
        0.25 * min(float(road_geometry.length), float(lane_geometry.length)),
    )
    if overlap_length_m + 1e-9 < minimum_overlap_m:
        return None
    return {
        "road_lane_distance_m": distance_m,
        "direction_angle_deg": direction_angle_deg,
        "local_overlap_length_m": overlap_length_m,
    }


def _line_tangent(line: object, measure: float) -> tuple[float, float]:
    delta = min(3.0, max(0.25, float(line.length) * 0.05))
    start = max(0.0, float(measure) - delta)
    end = min(float(line.length), float(measure) + delta)
    if end - start <= 1e-9:
        start = 0.0
        end = float(line.length)
    first = line.interpolate(start)
    last = line.interpolate(end)
    return float(last.x - first.x), float(last.y - first.y)


def _directed_angle_deg(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    left_norm = math.hypot(*left)
    right_norm = math.hypot(*right)
    if left_norm <= 1e-9 or right_norm <= 1e-9:
        return 180.0
    cosine = max(
        -1.0,
        min(
            1.0,
            (left[0] * right[0] + left[1] * right[1])
            / (left_norm * right_norm),
        ),
    )
    return math.degrees(math.acos(cosine))


def _empty_result(relations: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = relations.iloc[0:0].copy()
    result["relation_state"] = pd.Series(dtype=str)
    result["relation_basis"] = pd.Series(dtype=str)
    result["road_lane_distance_m"] = pd.Series(dtype=float)
    result["direction_angle_deg"] = pd.Series(dtype=float)
    result["local_overlap_length_m"] = pd.Series(dtype=float)
    return result
