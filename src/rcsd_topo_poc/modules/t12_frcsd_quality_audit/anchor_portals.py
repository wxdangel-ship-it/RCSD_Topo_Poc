from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import geopandas as gpd
import pandas as pd

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import (
    NodeCanonicalizer,
)

from .carrier_graph import field_name, normalize_id, parse_ids
from .models import T12ContractError


@dataclass(frozen=True)
class AnchorRecord:
    target_id: str
    base_id: str
    source_module: str
    reason: str
    scene: str
    grouped_node_ids: tuple[str, ...]


def build_anchor_map(t05_anchor_audit: pd.DataFrame) -> dict[str, AnchorRecord]:
    required = {
        name: field_name(t05_anchor_audit, name)
        for name in ("target_id", "base_id", "source_module", "status")
    }
    reason_field = _optional_field(t05_anchor_audit, "reason")
    scene_field = _optional_field(t05_anchor_audit, "scene")
    grouped_field = _optional_field(t05_anchor_audit, "grouped_rcsdnode_ids")
    anchors: dict[str, AnchorRecord] = {}
    for _, row in t05_anchor_audit.iterrows():
        status = normalize_id(row[required["status"]])
        base_id = normalize_id(row[required["base_id"]])
        target_id = normalize_id(row[required["target_id"]])
        if status != "0" or base_id in {"", "0", "-1"} or not target_id:
            continue
        if target_id in anchors:
            raise T12ContractError(
                f"successful T05 anchor target_id is not unique: {target_id}"
            )
        grouped = parse_ids(row[grouped_field]) if grouped_field else []
        grouped.append(base_id)
        anchors[target_id] = AnchorRecord(
            target_id=target_id,
            base_id=base_id,
            source_module=normalize_id(row[required["source_module"]]),
            reason=normalize_id(row[reason_field]) if reason_field else "",
            scene=normalize_id(row[scene_field]) if scene_field else "",
            grouped_node_ids=tuple(sorted(set(grouped))),
        )
    return anchors


def validate_t07_truth_anchors(
    anchors: Mapping[str, AnchorRecord],
    rcsd_intersections: gpd.GeoDataFrame,
    frcsd_nodes: gpd.GeoDataFrame,
    *,
    tolerance_m: float,
) -> dict[str, Any]:
    node_id_field = field_name(frcsd_nodes, "id")
    node_points = {
        normalize_id(row[node_id_field]): row.geometry
        for _, row in frcsd_nodes.iterrows()
        if row.geometry is not None and not row.geometry.is_empty
    }
    truth_geometry = rcsd_intersections.geometry.union_all()
    t07 = [anchor for anchor in anchors.values() if anchor.source_module == "T07"]
    missing_nodes: list[str] = []
    unmatched: list[str] = []
    distances: list[float] = []
    for anchor in t07:
        points = [
            node_points[node_id]
            for node_id in anchor.grouped_node_ids
            if node_id in node_points
        ]
        if not points:
            missing_nodes.append(anchor.target_id)
            continue
        distance_m = min(float(point.distance(truth_geometry)) for point in points)
        distances.append(distance_m)
        if distance_m > tolerance_m:
            unmatched.append(anchor.target_id)
    missing = sorted(set(missing_nodes + unmatched))
    return {
        "t07_anchor_count": len(t07),
        "rcsd_intersection_feature_count": len(rcsd_intersections),
        "truth_relation": "frcsd_anchor_node_distance_to_rcsd_intersection_surface",
        "tolerance_m": tolerance_m,
        "max_matched_distance_m": max(distances, default=None),
        "missing_raw_anchor_node_target_ids": sorted(missing_nodes),
        "unmatched_t07_target_ids": missing,
        "status": "pass" if not missing else "warning_unmatched_truth_group",
    }


def merge_anchor_groups(
    anchor: AnchorRecord,
    canonicalizer: NodeCanonicalizer,
    canonical_groups: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    raw_ids: set[str] = set(anchor.grouped_node_ids)
    for raw_id in tuple(raw_ids):
        canonical_id = canonicalizer.canonicalize(raw_id)
        raw_ids.update(canonical_groups.get(canonical_id, (raw_id,)))
    return tuple(sorted(raw_ids))


def portal_candidates(
    *,
    anchor: AnchorRecord,
    portal_point: Any,
    frcsd_nodes: gpd.GeoDataFrame,
    canonicalizer: NodeCanonicalizer,
    canonical_groups: Mapping[str, tuple[str, ...]],
    raw_node_points: Mapping[str, Any],
    eligible_canonical_ids: Iterable[str],
    radius_m: float,
    direction_role: str,
) -> list[dict[str, Any]]:
    eligible = set(eligible_canonical_ids)
    best: dict[str, dict[str, Any]] = {}
    grouped_ids = merge_anchor_groups(anchor, canonicalizer, canonical_groups)
    for raw_id in grouped_ids:
        _consider_portal(
            best,
            raw_id=raw_id,
            portal_point=portal_point,
            canonicalizer=canonicalizer,
            raw_node_points=raw_node_points,
            eligible=eligible,
            source="truth_group" if anchor.source_module == "T07" else "grouped_relation",
            direction_role=direction_role,
            enforce_radius=False,
            radius_m=radius_m,
        )
    node_id_field = field_name(frcsd_nodes, "id")
    positions = list(frcsd_nodes.sindex.query(portal_point.buffer(radius_m)))
    for position in positions:
        row = frcsd_nodes.iloc[position]
        _consider_portal(
            best,
            raw_id=normalize_id(row[node_id_field]),
            portal_point=portal_point,
            canonicalizer=canonicalizer,
            raw_node_points=raw_node_points,
            eligible=eligible,
            source="spatial_portal",
            direction_role=direction_role,
            enforce_radius=True,
            radius_m=radius_m,
        )
    return sorted(
        best.values(),
        key=lambda row: (row["distance_m"], row["canonical_id"], row["raw_id"]),
    )


def _consider_portal(
    best: dict[str, dict[str, Any]],
    *,
    raw_id: str,
    portal_point: Any,
    canonicalizer: NodeCanonicalizer,
    raw_node_points: Mapping[str, Any],
    eligible: set[str],
    source: str,
    direction_role: str,
    enforce_radius: bool,
    radius_m: float,
) -> None:
    point = raw_node_points.get(raw_id)
    if not raw_id or point is None or point.is_empty:
        return
    canonical_id = canonicalizer.canonicalize(raw_id)
    if canonical_id not in eligible:
        return
    distance_m = float(point.distance(portal_point))
    if enforce_radius and distance_m > radius_m:
        return
    candidate = {
        "canonical_id": canonical_id,
        "raw_id": raw_id,
        "distance_m": distance_m,
        "source": source,
        "direction_role": direction_role,
    }
    current = best.get(canonical_id)
    if current is None or (distance_m, raw_id) < (
        current["distance_m"],
        current["raw_id"],
    ):
        best[canonical_id] = candidate


def _optional_field(frame: pd.DataFrame, name: str) -> str:
    try:
        return field_name(frame, name)
    except T12ContractError:
        return ""
