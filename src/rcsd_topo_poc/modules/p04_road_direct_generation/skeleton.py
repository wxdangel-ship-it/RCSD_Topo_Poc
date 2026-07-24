from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPoint

from .geometry import canonical_id, parse_patch_membership


@dataclass(frozen=True)
class SkeletonResult:
    roads: gpd.GeoDataFrame
    junctions: gpd.GeoDataFrame
    arms: gpd.GeoDataFrame
    segments: gpd.GeoDataFrame | None
    summary: dict[str, Any]


def build_swsd_skeleton(
    swsd_roads: gpd.GeoDataFrame,
    swsd_nodes: gpd.GeoDataFrame,
    *,
    patch_ids: set[str],
    run_id: str,
    t01_roads: gpd.GeoDataFrame | None = None,
    t01_segments: gpd.GeoDataFrame | None = None,
) -> SkeletonResult:
    roads = swsd_roads.copy()
    roads["swsd_unit_id"] = roads["id"].map(canonical_id)
    roads["_patch_membership"] = roads["patch_id"].map(parse_patch_membership)
    roads = roads[roads["_patch_membership"].map(lambda values: bool(values & patch_ids))].copy()
    roads["source_patch_ids"] = roads["_patch_membership"].map(
        lambda values: ",".join(sorted(values & patch_ids))
    )
    roads["all_patch_ids"] = roads["_patch_membership"].map(lambda values: ",".join(sorted(values)))
    roads["snode_id"] = roads["snodeid"].map(canonical_id)
    roads["enode_id"] = roads["enodeid"].map(canonical_id)

    nodes = swsd_nodes.copy()
    nodes["node_id"] = nodes["id"].map(canonical_id)
    nodes["mainnode_id"] = nodes["mainnodeid"].map(canonical_id)
    nodes.loc[nodes["mainnode_id"].isin([None, "0"]), "mainnode_id"] = None
    nodes["semantic_node_id"] = nodes["mainnode_id"].fillna(nodes["node_id"])
    semantic_by_physical = dict(zip(nodes["node_id"], nodes["semantic_node_id"], strict=False))
    roads["semantic_snode_id"] = roads["snode_id"].map(lambda value: semantic_by_physical.get(value, value))
    roads["semantic_enode_id"] = roads["enode_id"].map(lambda value: semantic_by_physical.get(value, value))

    if t01_roads is not None:
        t01 = t01_roads.copy()
        t01["swsd_unit_id"] = t01["id"].map(canonical_id)
        t01_columns = [
            column
            for column in ("swsd_unit_id", "segmentid", "sgrade", "segment_build_source")
            if column in t01.columns
        ]
        t01 = t01[t01_columns].drop_duplicates("swsd_unit_id")
        roads = roads.merge(t01, on="swsd_unit_id", how="left", suffixes=("", "_t01"))

    roads["run_id"] = run_id
    roads["source_object_type"] = "SWSDRoad"
    roads["source_object_ids"] = roads["swsd_unit_id"]
    roads["decision"] = "confirmed_structure"
    roads["reason_codes"] = "swsd_scope_membership"
    roads["evidence_state"] = "semantic_skeleton"
    roads["input_manifest_ref"] = "p04_input_manifest.json"
    roads["support_state"] = "sd_only"

    junctions = _build_junctions(nodes, roads, run_id=run_id)
    arms = _build_arms(roads, run_id=run_id)
    segments = _scope_segments(t01_segments, set(roads["swsd_unit_id"]), run_id=run_id)

    internal_overlap_count = int(roads["_patch_membership"].map(lambda values: len(values & patch_ids) > 1).sum())
    open_boundary_count = int(
        roads["_patch_membership"].map(lambda values: bool(values - patch_ids)).sum()
    )
    summary = {
        "road_count": len(roads),
        "junction_count": len(junctions),
        "arm_count": len(arms),
        "segment_count": len(segments) if segments is not None else 0,
        "internal_overlap_road_count": internal_overlap_count,
        "open_boundary_road_count": open_boundary_count,
        "missing_semantic_snode_count": int(roads["semantic_snode_id"].isna().sum()),
        "missing_semantic_enode_count": int(roads["semantic_enode_id"].isna().sum()),
        "t01_segment_joined_road_count": int(roads.get("segmentid", pd.Series(dtype=object)).notna().sum()),
    }
    roads = roads.drop(columns=["_patch_membership"])
    return SkeletonResult(roads=roads, junctions=junctions, arms=arms, segments=segments, summary=summary)


def _build_junctions(
    nodes: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    *,
    run_id: str,
) -> gpd.GeoDataFrame:
    semantic_ids = set(roads["semantic_snode_id"].dropna()) | set(roads["semantic_enode_id"].dropna())
    members = nodes[nodes["semantic_node_id"].isin(semantic_ids)].copy()
    incident: dict[str, set[str]] = {semantic_id: set() for semantic_id in semantic_ids}
    for row in roads.itertuples():
        if row.semantic_snode_id is not None:
            incident.setdefault(row.semantic_snode_id, set()).add(row.swsd_unit_id)
        if row.semantic_enode_id is not None:
            incident.setdefault(row.semantic_enode_id, set()).add(row.swsd_unit_id)

    records: list[dict[str, Any]] = []
    for semantic_id in sorted(semantic_ids):
        group = members[members["semantic_node_id"] == semantic_id]
        if group.empty:
            geometry = None
            representative = {}
            member_ids: list[str] = []
        else:
            preferred = group[group["node_id"] == semantic_id]
            representative_row = (preferred.iloc[0] if not preferred.empty else group.iloc[0])
            representative = representative_row.to_dict()
            points = [geometry for geometry in group.geometry if geometry is not None and not geometry.is_empty]
            geometry = representative_row.geometry if points else None
            if geometry is None and points:
                geometry = MultiPoint(points).centroid
            member_ids = sorted(group["node_id"].dropna().astype(str).unique())
        road_ids = sorted(incident.get(semantic_id, set()))
        records.append(
            {
                "run_id": run_id,
                "junction_id": semantic_id,
                "member_node_ids": ",".join(member_ids),
                "member_node_count": len(member_ids),
                "incident_road_ids": ",".join(road_ids),
                "incident_road_count": len(road_ids),
                "kind_2": representative.get("kind_2"),
                "grade_2": representative.get("grade_2"),
                "source_object_type": "SWSDNode",
                "source_object_ids": ",".join(member_ids),
                "swsd_unit_id": semantic_id,
                "decision": "confirmed_structure",
                "reason_codes": "t01_semantic_node_group",
                "evidence_state": "semantic_skeleton",
                "input_manifest_ref": "p04_input_manifest.json",
                "geometry": geometry,
            }
        )
    return gpd.GeoDataFrame(records, geometry="geometry", crs=roads.crs)


def _build_arms(roads: gpd.GeoDataFrame, *, run_id: str) -> gpd.GeoDataFrame:
    records: list[dict[str, Any]] = []
    for row in roads.itertuples():
        direction = _coerce_int(getattr(row, "direction", None))
        if direction == 2:
            roles = (("s", row.semantic_snode_id, "outgoing"), ("e", row.semantic_enode_id, "incoming"))
        elif direction == 3:
            roles = (("s", row.semantic_snode_id, "incoming"), ("e", row.semantic_enode_id, "outgoing"))
        else:
            roles = (("s", row.semantic_snode_id, "both"), ("e", row.semantic_enode_id, "both"))
        for endpoint, junction_id, flow_role in roles:
            records.append(
                {
                    "run_id": run_id,
                    "arm_id": f"{row.swsd_unit_id}:{endpoint}",
                    "junction_id": junction_id,
                    "swsd_unit_id": row.swsd_unit_id,
                    "endpoint": endpoint,
                    "flow_role": flow_role,
                    "direction": direction,
                    "source_object_type": "SWSDRoad",
                    "source_object_ids": row.swsd_unit_id,
                    "decision": "confirmed_structure",
                    "reason_codes": "swsd_direction",
                    "evidence_state": "semantic_skeleton",
                    "input_manifest_ref": "p04_input_manifest.json",
                    "geometry": row.geometry,
                }
            )
    return gpd.GeoDataFrame(records, geometry="geometry", crs=roads.crs)


def _scope_segments(
    segments: gpd.GeoDataFrame | None,
    scope_road_ids: set[str],
    *,
    run_id: str,
) -> gpd.GeoDataFrame | None:
    if segments is None:
        return None
    frame = segments.copy()
    frame["scope_road_ids"] = frame["roads"].fillna("").astype(str).map(
        lambda value: ",".join(sorted(set(value.split(",")) & scope_road_ids))
    )
    frame = frame[frame["scope_road_ids"] != ""].copy()
    frame["scope_road_count"] = frame["scope_road_ids"].map(lambda value: len(value.split(",")))
    frame["segment_road_count"] = frame["roads"].fillna("").astype(str).map(
        lambda value: len([token for token in value.split(",") if token])
    )
    frame["partial_scope"] = frame["scope_road_count"] < frame["segment_road_count"]
    frame["run_id"] = run_id
    frame["source_object_type"] = "T01Segment"
    frame["source_object_ids"] = frame["id"].astype(str)
    frame["swsd_unit_id"] = frame["id"].astype(str)
    frame["decision"] = "confirmed_structure"
    frame["reason_codes"] = "t01_segment_contract"
    frame["evidence_state"] = "semantic_skeleton"
    frame["input_manifest_ref"] = "p04_input_manifest.json"
    return frame


def _coerce_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["SkeletonResult", "build_swsd_skeleton"]
