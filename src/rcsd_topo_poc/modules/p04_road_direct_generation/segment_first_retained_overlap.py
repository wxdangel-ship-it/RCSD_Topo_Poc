from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from .segment_first_config import SegmentFirstConfig
from .segment_first_fallback import _audit_built_road_continuity
from .segment_first_geometry import RoadGeometryResult
from .segment_first_nodes import NodeBuildResult
from .segment_first_physical_handoff import (
    normalize_segment_main_handoffs,
)
from .segment_first_swsd_topology import audit_swsd_access_direction_topology


@dataclass(frozen=True)
class RedundantRetainedAuditResult:
    audit: gpd.GeoDataFrame
    suppressed_road_ids: frozenset[str]
    suppressed_segment_ids: frozenset[str]


@dataclass(frozen=True)
class RedundantRetainedSuppressionResult:
    geometry: RoadGeometryResult
    node_build: NodeBuildResult
    continuity_audit: gpd.GeoDataFrame
    audit: gpd.GeoDataFrame
    summary: dict[str, object]


def audit_redundant_retained_roads(
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    carriers: gpd.GeoDataFrame,
    *,
    run_id: str,
    segment_accesses: gpd.GeoDataFrame | None = None,
    overlap_buffer_m: float = 2.0,
    minimum_overlap_ratio: float = 0.65,
    maximum_through_access_count: int = 1,
) -> RedundantRetainedAuditResult:
    """Find retained semantic carriers already realized by a built main graph.

    Spatial overlap alone is not sufficient.  The built main-Road component
    must also expose both physical Junction groups used by the retained Road.
    """

    if roads.empty:
        return RedundantRetainedAuditResult(
            _empty_audit(roads.crs),
            frozenset(),
            frozenset(),
        )
    realization = roads.get(
        "realization",
        pd.Series("", index=roads.index, dtype=str),
    ).fillna("").astype(str)
    carrier_roles = roads.get(
        "carrier_role",
        pd.Series("", index=roads.index, dtype=str),
    ).fillna("").astype(str)
    segment_ids = roads.get(
        "segment_id",
        pd.Series("", index=roads.index, dtype=str),
    ).fillna("").astype(str)
    retained = roads[
        realization.eq("retained")
        & carrier_roles.eq("semantic_carrier")
        & segment_ids.ne("")
    ].copy()
    built_main = roads[
        realization.eq("built")
        & carrier_roles.isin({"main_forward", "main_reverse", "main_oneway"})
        & segment_ids.ne("")
    ].copy()
    if retained.empty or built_main.empty:
        return RedundantRetainedAuditResult(
            _empty_audit(roads.crs),
            frozenset(),
            frozenset(),
        )

    node_groups = _node_group_index(nodes)
    protected_carrier_ids = _through_function_carrier_ids(carriers)
    through_access_count = _through_access_counts(segment_accesses)
    built_by_segment = {
        str(segment_id): group.copy()
        for segment_id, group in built_main.groupby("segment_id", sort=False)
    }
    rows: list[dict[str, object]] = []
    suppressed_road_ids: set[str] = set()
    suppressed_segment_ids: set[str] = set()
    for road in retained.itertuples():
        segment_id = str(road.segment_id)
        built = built_by_segment.get(segment_id)
        start_groups = node_groups.get(str(road.snodeid), set())
        end_groups = node_groups.get(str(road.enodeid), set())
        built_roles = (
            set(built["carrier_role"].fillna("").astype(str))
            if built is not None
            else set()
        )
        directional_contract = (
            "main_oneway" in built_roles
            or {"main_forward", "main_reverse"}.issubset(built_roles)
        )
        path_spans = bool(
            built is not None
            and start_groups
            and end_groups
            and start_groups.isdisjoint(end_groups)
            and _component_spans_groups(
                built,
                node_groups,
                start_groups,
                end_groups,
            )
        )
        overlap_ratio = _overlap_ratio(
            road.geometry,
            built,
            buffer_m=overlap_buffer_m,
        )
        carrier_id = str(getattr(road, "carrier_id", "") or "")
        protected = carrier_id in protected_carrier_ids
        segment_through_count = through_access_count.get(segment_id, 0)
        simple_access_contract = (
            segment_through_count <= maximum_through_access_count
        )
        eligible = bool(
            simple_access_contract
            and directional_contract
            and path_spans
            and overlap_ratio >= minimum_overlap_ratio
            and not protected
        )
        reason = (
            "protected_through_function"
            if protected
            else "complex_segment_access_contract"
            if not simple_access_contract
            else "built_directional_contract_missing"
            if not directional_contract
            else "built_path_does_not_span_retained_accesses"
            if not path_spans
            else "built_overlap_below_threshold"
            if overlap_ratio < minimum_overlap_ratio
            else "built_main_graph_replaces_retained_carrier"
        )
        road_id = str(road.id)
        if eligible:
            suppressed_road_ids.add(road_id)
            suppressed_segment_ids.add(segment_id)
        rows.append(
            {
                "run_id": run_id,
                "road_id": road.id,
                "segment_id": segment_id,
                "carrier_id": carrier_id,
                "start_junction_group_ids": ",".join(sorted(start_groups)),
                "end_junction_group_ids": ",".join(sorted(end_groups)),
                "built_carrier_roles": ",".join(sorted(built_roles)),
                "through_access_count": int(segment_through_count),
                "maximum_through_access_count": int(
                    maximum_through_access_count
                ),
                "built_path_spans_retained_accesses": path_spans,
                "overlap_buffer_m": float(overlap_buffer_m),
                "overlap_ratio": float(overlap_ratio),
                "minimum_overlap_ratio": float(minimum_overlap_ratio),
                "suppression_eligible": eligible,
                "reason_codes": reason,
                "geometry": road.geometry,
            }
        )
    audit = gpd.GeoDataFrame(rows, geometry="geometry", crs=roads.crs)
    return RedundantRetainedAuditResult(
        audit,
        frozenset(suppressed_road_ids),
        frozenset(suppressed_segment_ids),
    )


def try_suppress_redundant_retained_roads(
    geometry: RoadGeometryResult,
    node_build: NodeBuildResult,
    continuity_audit: gpd.GeoDataFrame,
    carriers: gpd.GeoDataFrame,
    segment_units: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    swsd_nodes: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
    *,
    config: SegmentFirstConfig,
    overlap_buffer_m: float = 2.0,
    minimum_overlap_ratio: float = 0.65,
) -> RedundantRetainedSuppressionResult:
    """Apply suppression only when all downstream hard contracts still pass."""

    node_build = normalize_segment_main_handoffs(
        node_build,
        config=config,
    )
    geometry_summary = dict(geometry.summary)
    geometry_summary.update(
        {
            "road_count": int(len(node_build.roads)),
            "junction_approach_regularized_count": int(
                node_build.summary.get(
                    "junction_approach_regularized_count",
                    0,
                )
            ),
            "physical_handoff_normalized_count": int(
                node_build.summary.get(
                    "physical_handoff_normalized_count",
                    0,
                )
            ),
        }
    )
    geometry = RoadGeometryResult(
        node_build.roads,
        geometry.geometry_sources,
        geometry_summary,
    )
    continuity_audit = _audit_built_road_continuity(
        node_build.roads,
        node_build.nodes,
        segment_accesses,
        node_build.endpoint_audit,
        run_id=config.run_id,
        maximum_endpoint_shift_m=config.relation_endpoint_max_distance_m,
    )
    candidate = audit_redundant_retained_roads(
        node_build.roads,
        node_build.nodes,
        carriers,
        run_id=config.run_id,
        segment_accesses=segment_accesses,
        overlap_buffer_m=overlap_buffer_m,
        minimum_overlap_ratio=minimum_overlap_ratio,
    )
    audit = candidate.audit.copy()
    if audit.empty or not candidate.suppressed_road_ids:
        if not audit.empty:
            audit["application_state"] = "not_candidate"
        return RedundantRetainedSuppressionResult(
            geometry,
            node_build,
            continuity_audit,
            audit,
            _summary(candidate, applied=False, blocked_segments=set()),
        )

    trial_geometry = _without_roads(
        geometry,
        candidate.suppressed_road_ids,
    )
    trial_nodes = _without_node_roads(
        node_build,
        candidate.suppressed_road_ids,
    )
    trial_continuity = _audit_built_road_continuity(
        trial_nodes.roads,
        trial_nodes.nodes,
        segment_accesses,
        trial_nodes.endpoint_audit,
        run_id=config.run_id,
        maximum_endpoint_shift_m=config.relation_endpoint_max_distance_m,
    )
    trial_swsd = audit_swsd_access_direction_topology(
        segment_units,
        swsd_roads,
        swsd_nodes,
        segment_accesses,
        trial_nodes.roads,
        trial_nodes.nodes,
        run_id=config.run_id,
    )
    candidate_segments = set(candidate.suppressed_segment_ids)
    blocked_segments = (
        set(trial_swsd.fallback_segment_ids)
        | _continuity_failure_segments(trial_continuity)
        | _unrealized_access_segments(
            segment_accesses,
            trial_nodes.roads,
            trial_nodes.nodes,
        )
    ).intersection(candidate_segments)
    audit["application_state"] = "not_candidate"
    if blocked_segments:
        eligible = audit["suppression_eligible"].fillna(False).astype(bool)
        audit.loc[eligible, "application_state"] = "rejected_hard_gate"
        audit.loc[
            eligible,
            "reason_codes",
        ] = audit.loc[eligible, "reason_codes"].astype(str) + "+hard_gate_rejected"
        return RedundantRetainedSuppressionResult(
            geometry,
            node_build,
            continuity_audit,
            audit,
            _summary(
                candidate,
                applied=False,
                blocked_segments=blocked_segments,
            ),
        )

    eligible = audit["suppression_eligible"].fillna(False).astype(bool)
    audit.loc[eligible, "application_state"] = "applied"
    return RedundantRetainedSuppressionResult(
        trial_geometry,
        trial_nodes,
        trial_continuity,
        audit,
        _summary(candidate, applied=True, blocked_segments=set()),
    )


def _node_group_index(nodes: gpd.GeoDataFrame) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for node in nodes.itertuples():
        groups = _split_values(getattr(node, "junction_group_ids", ""))
        mainnode = str(getattr(node, "mainnodeid", "") or "")
        if mainnode and mainnode != "0":
            groups.add(mainnode)
        result[str(node.id)] = groups
    return result


def _through_function_carrier_ids(carriers: gpd.GeoDataFrame) -> set[str]:
    if carriers.empty or "through_function_retained" not in carriers:
        return set()
    protected = carriers[
        carriers["through_function_retained"].fillna(False).astype(bool)
    ]
    return set(protected["carrier_id"].fillna("").astype(str))


def _through_access_counts(
    accesses: gpd.GeoDataFrame | None,
) -> dict[str, int]:
    if accesses is None or accesses.empty:
        return {}
    through = accesses[
        accesses["access_type"].fillna("").astype(str).eq("THROUGH")
    ]
    return {
        str(segment_id): int(len(group))
        for segment_id, group in through.groupby("segment_id", sort=False)
    }


def _component_spans_groups(
    built: gpd.GeoDataFrame,
    node_groups: dict[str, set[str]],
    start_groups: set[str],
    end_groups: set[str],
) -> bool:
    adjacency: dict[str, set[str]] = {}
    for road in built.itertuples():
        start = str(road.snodeid)
        end = str(road.enodeid)
        adjacency.setdefault(start, set()).add(end)
        adjacency.setdefault(end, set()).add(start)
    remaining = set(adjacency)
    while remaining:
        seed = remaining.pop()
        component = {seed}
        pending = [seed]
        while pending:
            current = pending.pop()
            for neighbor in adjacency.get(current, set()):
                if neighbor in component:
                    continue
                component.add(neighbor)
                remaining.discard(neighbor)
                pending.append(neighbor)
        groups = set().union(*(node_groups.get(node_id, set()) for node_id in component))
        if groups.intersection(start_groups) and groups.intersection(end_groups):
            return True
    return False


def _overlap_ratio(
    retained_geometry: object,
    built: gpd.GeoDataFrame | None,
    *,
    buffer_m: float,
) -> float:
    if (
        retained_geometry is None
        or retained_geometry.is_empty
        or retained_geometry.length <= 0.0
        or built is None
        or built.empty
    ):
        return 0.0
    built_geometry = unary_union(
        [
            geometry
            for geometry in built.geometry
            if geometry is not None and not geometry.is_empty
        ]
    )
    if built_geometry.is_empty:
        return 0.0
    covered = retained_geometry.intersection(built_geometry.buffer(buffer_m))
    return min(1.0, float(covered.length / retained_geometry.length))


def _without_roads(
    geometry: RoadGeometryResult,
    road_ids: frozenset[str],
) -> RoadGeometryResult:
    roads = geometry.roads[
        ~geometry.roads["id"].astype(str).isin(road_ids)
    ].copy()
    sources = geometry.geometry_sources[
        ~geometry.geometry_sources["road_id"].astype(str).isin(road_ids)
    ].copy()
    summary = dict(geometry.summary)
    summary.update(
        {
            "road_count": int(len(roads)),
            "built_road_count": int(roads["realization"].eq("built").sum()),
            "retained_road_count": int(roads["realization"].eq("retained").sum()),
            "redundant_retained_suppressed_count": int(len(road_ids)),
        }
    )
    return RoadGeometryResult(roads, sources, summary)


def _without_node_roads(
    node_build: NodeBuildResult,
    road_ids: frozenset[str],
) -> NodeBuildResult:
    roads = node_build.roads[
        ~node_build.roads["id"].astype(str).isin(road_ids)
    ].copy()
    referenced_nodes = set(roads["snodeid"]).union(roads["enodeid"])
    nodes = node_build.nodes[
        node_build.nodes["id"].isin(referenced_nodes)
    ].copy()
    endpoint_audit = _without_relation_rows(
        node_build.endpoint_audit,
        road_ids,
        ("road_id",),
    )
    completion_sources = _without_relation_rows(
        node_build.completion_sources,
        road_ids,
        ("road_id",),
    )
    connection_evidence = _without_relation_rows(
        node_build.connection_evidence,
        road_ids,
        ("source_road_id", "target_road_id"),
    )
    summary = dict(node_build.summary)
    summary.update(
        {
            "node_count": int(len(nodes)),
            "road_endpoint_count": int(len(roads) * 2),
            "redundant_retained_suppressed_count": int(len(road_ids)),
        }
    )
    return NodeBuildResult(
        roads,
        nodes,
        endpoint_audit,
        completion_sources,
        connection_evidence,
        summary,
    )


def _without_relation_rows(
    frame: gpd.GeoDataFrame,
    road_ids: frozenset[str],
    columns: tuple[str, ...],
) -> gpd.GeoDataFrame:
    if frame.empty:
        return frame.copy()
    keep = pd.Series(True, index=frame.index, dtype=bool)
    for column in columns:
        if column in frame:
            keep &= ~frame[column].astype(str).isin(road_ids)
    return frame.loc[keep].copy()


def _continuity_failure_segments(audit: gpd.GeoDataFrame) -> set[str]:
    if audit.empty or "hard_failure" not in audit:
        return set()
    return set(
        audit.loc[
            audit["hard_failure"].fillna(False).astype(bool),
            "segment_id",
        ].astype(str)
    )


def _unrealized_access_segments(
    accesses: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
) -> set[str]:
    node_groups = _node_group_index(nodes)
    segment_node_groups: dict[str, set[str]] = {}
    for road in roads.itertuples():
        groups = segment_node_groups.setdefault(str(road.segment_id), set())
        groups.update(node_groups.get(str(road.snodeid), set()))
        groups.update(node_groups.get(str(road.enodeid), set()))
    return {
        str(access.segment_id)
        for access in accesses.itertuples()
        if str(access.junction_group_id)
        not in segment_node_groups.get(str(access.segment_id), set())
    }


def _split_values(value: object) -> set[str]:
    return {
        item.strip()
        for item in str(value or "").split(",")
        if item.strip()
    }


def _summary(
    candidate: RedundantRetainedAuditResult,
    *,
    applied: bool,
    blocked_segments: set[str],
) -> dict[str, object]:
    return {
        "audited_retained_road_count": int(len(candidate.audit)),
        "suppression_candidate_count": int(len(candidate.suppressed_road_ids)),
        "suppression_candidate_segment_count": int(
            len(candidate.suppressed_segment_ids)
        ),
        "suppression_applied": bool(
            applied and candidate.suppressed_road_ids
        ),
        "suppressed_road_count": (
            int(len(candidate.suppressed_road_ids)) if applied else 0
        ),
        "blocked_segment_ids": sorted(blocked_segments),
    }


def _empty_audit(crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "run_id": pd.Series(dtype="object"),
            "road_id": pd.Series(dtype="object"),
            "segment_id": pd.Series(dtype="object"),
            "carrier_id": pd.Series(dtype="object"),
            "start_junction_group_ids": pd.Series(dtype="object"),
            "end_junction_group_ids": pd.Series(dtype="object"),
            "built_carrier_roles": pd.Series(dtype="object"),
            "through_access_count": pd.Series(dtype="int64"),
            "maximum_through_access_count": pd.Series(dtype="int64"),
            "built_path_spans_retained_accesses": pd.Series(dtype="bool"),
            "overlap_buffer_m": pd.Series(dtype="float64"),
            "overlap_ratio": pd.Series(dtype="float64"),
            "minimum_overlap_ratio": pd.Series(dtype="float64"),
            "suppression_eligible": pd.Series(dtype="bool"),
            "reason_codes": pd.Series(dtype="object"),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


__all__ = [
    "RedundantRetainedAuditResult",
    "RedundantRetainedSuppressionResult",
    "audit_redundant_retained_roads",
    "try_suppress_redundant_retained_roads",
]
