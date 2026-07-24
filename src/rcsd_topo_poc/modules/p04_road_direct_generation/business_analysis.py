from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

from .geometry import canonical_id, parse_patch_membership


@dataclass(frozen=True)
class BusinessAnalysisResult:
    summary: dict[str, Any]
    topology_links: gpd.GeoDataFrame
    patch_summary: pd.DataFrame
    reason_summary: pd.DataFrame
    unsegmented_roads: pd.DataFrame


def build_business_analysis(
    lane_next: pd.DataFrame,
    decisions: gpd.GeoDataFrame,
    road_sections: gpd.GeoDataFrame,
    *,
    run_id: str,
) -> BusinessAnalysisResult:
    """形成首里程碑的真实数据解释层，不把统计现象提升为生产规则。"""
    links = _normalize_links(lane_next)
    decision_by_lane = (
        decisions.sort_values("lane_id").drop_duplicates("lane_id").set_index("lane_id", drop=False)
    )
    road_by_id = (
        road_sections.sort_values("swsd_unit_id")
        .drop_duplicates("swsd_unit_id")
        .set_index("swsd_unit_id", drop=False)
    )
    link_rows: list[dict[str, Any]] = []
    for link in links.itertuples(index=False):
        source = decision_by_lane.loc[link.lane_id] if link.lane_id in decision_by_lane.index else None
        target = (
            decision_by_lane.loc[link.next_lane_id]
            if link.next_lane_id in decision_by_lane.index
            else None
        )
        link_rows.append(
            _audit_link(
                link,
                source=source,
                target=target,
                road_by_id=road_by_id,
                run_id=run_id,
                crs=decisions.crs,
            )
        )
    topology_links = gpd.GeoDataFrame(link_rows, geometry="geometry", crs=decisions.crs)
    patch_summary = _build_patch_summary(decisions)
    reason_summary = _build_reason_summary(decisions)
    unsegmented = road_sections[road_sections["segmentid"].isna()].copy()
    unsegmented_columns = [
        column
        for column in (
            "swsd_unit_id",
            "snode_id",
            "enode_id",
            "source_patch_ids",
            "all_patch_ids",
            "support_state",
        )
        if column in unsegmented.columns
    ]
    unsegmented_roads = unsegmented[unsegmented_columns].reset_index(drop=True)

    accepted = decisions[decisions["decision"] == "accepted"]
    owner_with_any_lane = set(decisions["swsd_unit_id"].dropna().astype(str))
    owner_with_accepted_lane = set(accepted["swsd_unit_id"].dropna().astype(str))
    endpoint_available = topology_links[topology_links["endpoint_pair"] != "missing_geometry"]
    both_accepted = topology_links[
        (topology_links["source_decision"] == "accepted")
        & (topology_links["target_decision"] == "accepted")
    ]
    cross_owner = both_accepted[both_accepted["owner_relation"] == "cross_owner"]
    width = pd.to_numeric(decisions["inferred_lane_width_m"], errors="coerce")
    owner_p90 = pd.to_numeric(decisions["owner_distance_p90_m"], errors="coerce")
    owner_margin = pd.to_numeric(decisions["owner_score_margin"], errors="coerce")
    owner_angle = pd.to_numeric(decisions["owner_direction_delta_deg"], errors="coerce")
    drivezone = pd.to_numeric(decisions["drivezone_coverage"], errors="coerce")
    intersection_mask = decisions["is_intersection_in_lane"].fillna(False) | decisions[
        "is_intersection_out_lane"
    ].fillna(False)
    summary = {
        "analysis_role": "milestone1_explanation_and_lanetopo_readiness_baseline",
        "lane_direction_evidence": {
            "link_count": int(len(topology_links)),
            "endpoint_geometry_available_count": int(len(endpoint_available)),
            "closest_endpoint_pair_counts": _counts(endpoint_available["endpoint_pair"]),
            "end_to_start_closest_count": int((endpoint_available["endpoint_pair"] == "end_start").sum()),
            "end_to_start_closest_ratio": _ratio(
                int((endpoint_available["endpoint_pair"] == "end_start").sum()),
                len(endpoint_available),
            ),
            "end_to_start_distance_m_quantiles": _quantiles(
                topology_links["end_to_start_distance_m"], (0.5, 0.9, 0.95, 0.99)
            ),
        },
        "lane_topo_readiness": {
            "both_lane_accepted_link_count": int(len(both_accepted)),
            "accepted_same_owner_link_count": int(
                (both_accepted["owner_relation"] == "same_owner").sum()
            ),
            "accepted_cross_owner_link_count": int(len(cross_owner)),
            "cross_owner_semantic_state_counts": _counts(cross_owner["semantic_relation"]),
            "topology_state_counts": _counts(topology_links["lane_topo_state"]),
            "note": "该统计仅验证 LaneTopo movement projection 的输入准备度，不发布 movement。",
        },
        "swsd_evidence_coverage": {
            "swsd_road_count": int(len(road_sections)),
            "road_with_any_lane_owner_count": int(len(owner_with_any_lane)),
            "road_with_accepted_lane_count": int(len(owner_with_accepted_lane)),
            "road_without_accepted_lane_count": int(len(road_sections) - len(owner_with_accepted_lane)),
            "t01_segment_joined_road_count": int(road_sections["segmentid"].notna().sum()),
            "t01_segment_unjoined_road_count": int(len(unsegmented_roads)),
            "t01_segment_unjoined_road_ids": unsegmented_roads.get(
                "swsd_unit_id", pd.Series(dtype=str)
            ).astype(str).tolist(),
        },
        "decision_by_context": {
            "intersection_lane_count": int(intersection_mask.sum()),
            "intersection_decision_counts": _counts(decisions.loc[intersection_mask, "decision"]),
            "non_intersection_lane_count": int((~intersection_mask).sum()),
            "non_intersection_decision_counts": _counts(decisions.loc[~intersection_mask, "decision"]),
        },
        "threshold_neighborhoods": {
            "owner_p90_18_to_22m_count": _between_count(owner_p90, 18.0, 22.0),
            "owner_margin_3_to_7_count": _between_count(owner_margin, 3.0, 7.0),
            "owner_angle_30_to_40deg_count": _between_count(owner_angle, 30.0, 40.0),
            "width_2_2_to_2_8m_count": _between_count(width, 2.2, 2.8),
            "width_4_5_to_5_5m_count": _between_count(width, 4.5, 5.5),
            "drivezone_coverage_below_0_8_count": int((drivezone < 0.8).sum()),
            "note": "阈值邻域用于暴露敏感样本，不作为自动修复或删除依据。",
        },
        "patch_summary_row_count": int(len(patch_summary)),
        "reason_code_count": int(len(reason_summary)),
    }
    return BusinessAnalysisResult(
        summary=summary,
        topology_links=topology_links,
        patch_summary=patch_summary,
        reason_summary=reason_summary,
        unsegmented_roads=unsegmented_roads,
    )


def _normalize_links(lane_next: pd.DataFrame) -> pd.DataFrame:
    links = lane_next.copy()
    links["link_id"] = links["Id"].map(canonical_id)
    links["lane_id"] = links["LaneId"].map(canonical_id)
    links["next_lane_id"] = links["NextLaneId"].map(canonical_id)
    links["source_patch_ids"] = links["patch_id"].astype(str)
    links = links.dropna(subset=["lane_id", "next_lane_id"])
    links = links.sort_values(["link_id", "source_patch_ids"], na_position="last")
    links = links.drop_duplicates(["link_id", "lane_id", "next_lane_id"])
    return links[["link_id", "lane_id", "next_lane_id", "IsMeet", "source_patch_ids"]]


def _audit_link(
    link: Any,
    *,
    source: pd.Series | None,
    target: pd.Series | None,
    road_by_id: pd.DataFrame,
    run_id: str,
    crs: Any,
) -> dict[str, Any]:
    del crs
    source_geometry = None if source is None else source.geometry
    target_geometry = None if target is None else target.geometry
    endpoint_pair, minimum_distance, end_to_start_distance, geometry = _endpoint_metrics(
        source_geometry, target_geometry
    )
    source_decision = None if source is None else str(source["decision"])
    target_decision = None if target is None else str(target["decision"])
    source_owner = None if source is None else canonical_id(source["swsd_unit_id"])
    target_owner = None if target is None else canonical_id(target["swsd_unit_id"])
    if source_owner is None or target_owner is None:
        owner_relation = "owner_missing"
    elif source_owner == target_owner:
        owner_relation = "same_owner"
    else:
        owner_relation = "cross_owner"
    semantic_relation = _semantic_relation(source_owner, target_owner, road_by_id)
    if endpoint_pair == "missing_geometry":
        state = "missing_lane_geometry"
    elif source_decision != "accepted" or target_decision != "accepted":
        state = "lane_decision_not_both_accepted"
    elif owner_relation == "same_owner":
        state = "intra_swsd_owner_confirmed"
    elif semantic_relation == "directed_end_to_start":
        state = "cross_owner_directed_node_supported"
    elif semantic_relation == "shared_node_other_orientation":
        state = "cross_owner_shared_node_review"
    else:
        state = "cross_owner_semantic_unconnected_review"
    return {
        "run_id": run_id,
        "source_patch_ids": link.source_patch_ids,
        "source_object_type": "LaneNextLane",
        "source_object_ids": link.link_id,
        "link_id": link.link_id,
        "lane_id": link.lane_id,
        "next_lane_id": link.next_lane_id,
        "is_meet": bool(link.IsMeet),
        "source_decision": source_decision,
        "target_decision": target_decision,
        "source_owner": source_owner,
        "target_owner": target_owner,
        "owner_relation": owner_relation,
        "semantic_relation": semantic_relation,
        "lane_topo_state": state,
        "endpoint_pair": endpoint_pair,
        "endpoint_min_distance_m": minimum_distance,
        "end_to_start_distance_m": end_to_start_distance,
        "decision": "confirmed_input" if state.endswith("confirmed") or state.endswith("supported") else "review_or_defer",
        "reason_codes": state,
        "evidence_state": "lanetopo_readiness_audit",
        "input_manifest_ref": "p04_input_manifest.json",
        "geometry": geometry,
    }


def _endpoint_metrics(source: Any, target: Any) -> tuple[str, float | None, float | None, Any]:
    if (
        source is None
        or target is None
        or source.is_empty
        or target.is_empty
        or not hasattr(source, "coords")
        or not hasattr(target, "coords")
    ):
        return "missing_geometry", None, None, None
    source_start = source.coords[0]
    source_end = source.coords[-1]
    target_start = target.coords[0]
    target_end = target.coords[-1]
    pairs = {
        "start_start": _xy_distance(source_start, target_start),
        "start_end": _xy_distance(source_start, target_end),
        "end_start": _xy_distance(source_end, target_start),
        "end_end": _xy_distance(source_end, target_end),
    }
    closest = min(pairs, key=pairs.get)
    return (
        closest,
        float(pairs[closest]),
        float(pairs["end_start"]),
        _topology_geometry(source, target),
    )


def _topology_geometry(source: Any, target: Any) -> LineString | None:
    source_tail = source.interpolate(max(float(source.length) - 2.0, 0.0)).coords[0]
    target_head = target.interpolate(min(2.0, float(target.length))).coords[0]
    raw = [source_tail[:2], source.coords[-1][:2], target.coords[0][:2], target_head[:2]]
    coordinates: list[tuple[float, float]] = []
    for value in raw:
        coordinate = (float(value[0]), float(value[1]))
        if not coordinates or coordinate != coordinates[-1]:
            coordinates.append(coordinate)
    if len(coordinates) < 2:
        return None
    return LineString(coordinates)


def _semantic_relation(source_owner: str | None, target_owner: str | None, roads: pd.DataFrame) -> str:
    if source_owner is None or target_owner is None:
        return "owner_missing"
    if source_owner == target_owner:
        return "same_owner"
    if source_owner not in roads.index or target_owner not in roads.index:
        return "road_missing"
    source = roads.loc[source_owner]
    target = roads.loc[target_owner]
    source_start = _semantic_node(source, "semantic_snode_id", "snode_id")
    source_end = _semantic_node(source, "semantic_enode_id", "enode_id")
    target_start = _semantic_node(target, "semantic_snode_id", "snode_id")
    target_end = _semantic_node(target, "semantic_enode_id", "enode_id")
    if source_end is not None and source_end == target_start:
        return "directed_end_to_start"
    source_nodes = {value for value in (source_start, source_end) if value is not None}
    target_nodes = {value for value in (target_start, target_end) if value is not None}
    if source_nodes & target_nodes:
        return "shared_node_other_orientation"
    return "no_shared_swsd_node"


def _semantic_node(row: pd.Series, semantic_field: str, physical_field: str) -> str | None:
    semantic = canonical_id(row.get(semantic_field))
    return semantic if semantic is not None else canonical_id(row.get(physical_field))


def _build_patch_summary(decisions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    patch_ids = sorted(
        {
            patch_id
            for value in decisions["source_patch_ids"]
            for patch_id in parse_patch_membership(value)
        }
    )
    for patch_id in patch_ids:
        selected = decisions[
            decisions["source_patch_ids"].map(lambda value: patch_id in parse_patch_membership(value))
        ]
        row: dict[str, Any] = {"patch_id": patch_id, "lane_count": int(len(selected))}
        for state in ("accepted", "review_required", "insufficient_evidence"):
            row[f"decision_{state}_count"] = int((selected["decision"] == state).sum())
        for state in (
            "nominal",
            "narrow_candidate",
            "wide_or_boundary_gap",
            "unstable",
            "partial",
            "insufficient_evidence",
        ):
            row[f"width_{state}_count"] = int((selected["width_state"] == state).sum())
        row["drivezone_below_0_8_count"] = int(
            (pd.to_numeric(selected["drivezone_coverage"], errors="coerce") < 0.8).sum()
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _build_reason_summary(decisions: pd.DataFrame) -> pd.DataFrame:
    counter: Counter[str] = Counter()
    for value in decisions["reason_codes"].dropna():
        counter.update(token for token in str(value).split(";") if token)
    return pd.DataFrame(
        [
            {"reason_code": reason, "lane_count": count}
            for reason, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        ]
    )


def _xy_distance(first: Any, second: Any) -> float:
    return float(np.hypot(float(first[0]) - float(second[0]), float(first[1]) - float(second[1])))


def _counts(series: pd.Series) -> dict[str, int]:
    return {str(key): int(value) for key, value in series.value_counts(dropna=False).items()}


def _ratio(numerator: int, denominator: int) -> float | None:
    return float(numerator / denominator) if denominator else None


def _between_count(series: pd.Series, lower: float, upper: float) -> int:
    return int(series.between(lower, upper, inclusive="both").sum())


def _quantiles(series: pd.Series, values: tuple[float, ...]) -> dict[str, float]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    return {f"p{int(value * 100):02d}": float(numeric.quantile(value)) for value in values}


__all__ = ["BusinessAnalysisResult", "build_business_analysis"]
