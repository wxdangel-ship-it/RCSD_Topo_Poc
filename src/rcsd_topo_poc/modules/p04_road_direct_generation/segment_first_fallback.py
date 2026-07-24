from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


def audit_built_road_continuity(
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    accesses: gpd.GeoDataFrame,
    endpoint_audit: gpd.GeoDataFrame,
    *,
    run_id: str,
    maximum_endpoint_shift_m: float,
) -> gpd.GeoDataFrame:
    degree: dict[object, int] = {}
    for road in roads.itertuples():
        degree[road.snodeid] = degree.get(road.snodeid, 0) + 1
        degree[road.enodeid] = degree.get(road.enodeid, 0) + 1
    node_geometry = {row.id: row.geometry for row in nodes.itertuples()}
    node_groups: dict[object, set[str]] = {}
    for node in nodes.itertuples():
        groups = {
            value
            for value in str(
                getattr(node, "junction_group_ids", "") or ""
            ).split(",")
            if value
        }
        mainnode = str(getattr(node, "mainnodeid", "") or "")
        if mainnode and mainnode != "0":
            groups.add(mainnode)
        node_groups[node.id] = groups
    access_groups = {
        str(segment_id): set(group["junction_group_id"].astype(str))
        for segment_id, group in accesses.groupby(
            accesses["segment_id"].astype(str)
        )
    }
    shifts = {
        (str(row.road_id), str(row.endpoint)): float(row.endpoint_shift_m)
        for row in endpoint_audit.itertuples()
    }
    rows: list[dict[str, object]] = []
    for road in roads[roads["realization"].eq("built")].itertuples():
        for endpoint, node_id in (
            ("start", road.snodeid),
            ("end", road.enodeid),
        ):
            groups = node_groups.get(node_id, set())
            at_access = bool(
                groups.intersection(
                    access_groups.get(str(road.segment_id), set())
                )
            )
            incident_count = int(degree.get(node_id, 0))
            connected = incident_count > 1 or at_access
            shift = float(
                shifts.get((str(road.id), endpoint), 0.0)
            )
            shift_ok = shift <= maximum_endpoint_shift_m + 1e-9
            hard_failure = not connected or not shift_ok
            reason = (
                "built_endpoint_unconnected"
                if not connected
                else "built_endpoint_shift_exceeds_limit"
                if not shift_ok
                else "built_endpoint_continuity_pass"
            )
            rows.append(
                {
                    "run_id": run_id,
                    "segment_id": str(road.segment_id),
                    "road_id": road.id,
                    "endpoint": endpoint,
                    "node_id": node_id,
                    "node_incident_road_count": incident_count,
                    "segment_access_node": at_access,
                    "endpoint_shift_m": shift,
                    "hard_failure": hard_failure,
                    "reason_codes": reason,
                    "geometry": node_geometry.get(node_id, Point()),
                }
            )
    return gpd.GeoDataFrame(
        rows,
        geometry="geometry",
        crs=roads.crs,
    )


def same_segment_rejected_mask(
    rejected_connections: gpd.GeoDataFrame,
    assignments: gpd.GeoDataFrame,
) -> pd.Series:
    if rejected_connections.empty:
        return pd.Series(
            False,
            index=rejected_connections.index,
            dtype=bool,
        )
    selected_source = rejected_connections.get(
        "source_segment_id",
        pd.Series("", index=rejected_connections.index),
    ).fillna("").astype(str)
    selected_target = rejected_connections.get(
        "target_segment_id",
        pd.Series("", index=rejected_connections.index),
    ).fillna("").astype(str)
    selected_known = selected_source.ne("") & selected_target.ne("")
    same_segment = selected_known & selected_source.eq(selected_target)
    if (~selected_known).any():
        segments_by_patch_road = _segments_by_patch_road(assignments)
        source_keys = rejected_connections[
            "source_patch_road_key"
        ].astype(str)
        target_keys = rejected_connections[
            "target_patch_road_key"
        ].astype(str)
        inferred_same = pd.Series(
            [
                bool(
                    segments_by_patch_road.get(
                        source_key, set()
                    ).intersection(
                        segments_by_patch_road.get(
                            target_key, set()
                        )
                    )
                )
                for source_key, target_key in zip(
                    source_keys,
                    target_keys,
                )
            ],
            index=rejected_connections.index,
            dtype=bool,
        )
        same_segment = same_segment | (
            ~selected_known & inferred_same
        )
    endpoint_actionable = ~rejected_connections.get(
        "reason_codes",
        pd.Series(
            "",
            index=rejected_connections.index,
            dtype=str,
        ),
    ).eq("relation_endpoint_orientation_conflict")
    return same_segment & endpoint_actionable


def fallback_segment_ids(
    rejected_connections: gpd.GeoDataFrame,
    assignments: gpd.GeoDataFrame,
) -> set[str]:
    if rejected_connections.empty:
        return set()
    result = {
        str(value)
        for value in rejected_connections.get(
            "source_segment_id",
            pd.Series(dtype=str),
        ).fillna("").astype(str)
        if value
    }
    segments_by_patch_road = _segments_by_patch_road(assignments)
    for row in rejected_connections.itertuples():
        if str(getattr(row, "source_segment_id", "") or ""):
            continue
        result.update(
            segments_by_patch_road.get(
                str(row.source_patch_road_key),
                set(),
            ).intersection(
                segments_by_patch_road.get(
                    str(row.target_patch_road_key),
                    set(),
                )
            )
        )
    return result


def direct_build_rescue_segment_ids(
    fallback_triggers: gpd.GeoDataFrame,
    assignments: gpd.GeoDataFrame,
    *,
    direct_build_core_segment_ids: set[str],
    already_rescued_segment_ids: set[str],
) -> set[str]:
    """Select hard targets that must retry whole-Segment assembly first."""

    return (
        fallback_segment_ids(fallback_triggers, assignments)
        .intersection(direct_build_core_segment_ids)
        .difference(already_rescued_segment_ids)
    )


def with_direct_build_rescue_reference_axes(
    carrier_reference_axes: gpd.GeoDataFrame,
    resolved_reference_axes: gpd.GeoDataFrame,
    rescue_segment_ids: set[str],
) -> gpd.GeoDataFrame:
    """Add semantic ordering axes only for the hard-target rescue scope."""

    if not rescue_segment_ids or resolved_reference_axes.empty:
        return carrier_reference_axes.copy()
    selected = resolved_reference_axes[
        resolved_reference_axes["segment_id"]
        .astype(str)
        .isin(rescue_segment_ids)
        & resolved_reference_axes["reference_state"].eq("resolved")
    ].copy()
    if selected.empty:
        return carrier_reference_axes.copy()
    retained = carrier_reference_axes[
        ~carrier_reference_axes["segment_id"]
        .astype(str)
        .isin(set(selected["segment_id"].astype(str)))
    ].copy()
    return gpd.GeoDataFrame(
        pd.concat(
            [retained, selected],
            ignore_index=True,
            sort=False,
        ),
        geometry="geometry",
        crs=resolved_reference_axes.crs,
    )


def _segments_by_patch_road(
    assignments: gpd.GeoDataFrame,
) -> dict[str, set[str]]:
    return {
        str(patch_key): set(group["assigned_segment_id"].astype(str))
        for patch_key, group in assignments.groupby(
            assignments["patch_road_key"].astype(str)
        )
    }


_audit_built_road_continuity = audit_built_road_continuity
_same_segment_rejected_mask = same_segment_rejected_mask
_fallback_segment_ids = fallback_segment_ids


__all__ = [
    "audit_built_road_continuity",
    "direct_build_rescue_segment_ids",
    "fallback_segment_ids",
    "same_segment_rejected_mask",
    "with_direct_build_rescue_reference_axes",
]
