from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import pandas as pd

from .segment_first_junctions import endpoint_surface_geometry
from .segment_first_skeleton import canonical_id


@dataclass(frozen=True)
class TargetRealizationResult:
    audit: gpd.GeoDataFrame
    summary: dict[str, object]


def audit_target_realization(
    target_segments: gpd.GeoDataFrame,
    published_roads: gpd.GeoDataFrame,
    *,
    segment_plans: gpd.GeoDataFrame | None = None,
    nodes: gpd.GeoDataFrame | None = None,
    segment_accesses: gpd.GeoDataFrame | None = None,
    junction_units: gpd.GeoDataFrame | None = None,
    road_next_road: gpd.GeoDataFrame | None = None,
    terminal_surface_tolerance_m: float = 1.0,
    run_id: str,
) -> TargetRealizationResult:
    baseline_column = (
        "baseline_target"
        if "baseline_target" in target_segments
        else "target_required"
    )
    required = target_segments[
        target_segments[baseline_column].fillna(False).astype(bool)
    ].copy()
    built = published_roads[
        published_roads["realization"].eq("built")
        & published_roads["geometry_source"].astype(str).str.startswith("hp_")
    ].copy()
    built["canonical_segment_id"] = built["segment_id"].map(canonical_id)
    roads_by_segment = {
        segment_id: group.copy()
        for segment_id, group in built.groupby("canonical_segment_id")
    }
    segment_state_by_id = (
        {
            canonical_id(row.segment_id): str(row.segment_state)
            for row in segment_plans.itertuples(index=False)
        }
        if segment_plans is not None and not segment_plans.empty
        else {}
    )
    chain_gate_enabled = (
        nodes is not None
        and not nodes.empty
        and segment_accesses is not None
        and not segment_accesses.empty
    )
    node_groups = (
        {
            str(row.id): set(
                item
                for item in str(
                    getattr(row, "junction_group_ids", "")
                ).split(",")
                if item
            )
            for row in nodes.itertuples()
        }
        if chain_gate_enabled
        else {}
    )
    node_geometries = (
        {
            canonical_id(row.id): row.geometry
            for row in nodes.itertuples()
        }
        if chain_gate_enabled
        else {}
    )
    junction_surfaces = _junction_surface_metadata(
        junction_units,
        nodes.crs if nodes is not None else None,
    )
    topology_edges = _topology_edges(road_next_road)
    terminal_groups_by_segment = (
        {
            canonical_id(segment_id): set(
                group["junction_group_id"].map(canonical_id)
            )
            for segment_id, group in segment_accesses[
                segment_accesses["access_type"].astype(str).eq("ENDPOINT")
            ].groupby(segment_accesses["segment_id"].map(canonical_id))
        }
        if chain_gate_enabled
        else {}
    )
    rows: list[dict[str, object]] = []
    for segment in required.itertuples(index=False):
        segment_id = canonical_id(segment.segment_id)
        target_class = str(segment.target_class)
        direct_build_eligibility = str(
            getattr(
                segment,
                "direct_build_eligibility",
                "direct_build_required",
            )
        )
        direct_build_required = bool(
            getattr(segment, "direct_build_required", True)
        )
        segment_build_state = segment_state_by_id.get(segment_id, "")
        expected_roles, alternative_main = _expected_roles(
            target_class,
            str(getattr(segment, "sgrade", "") or ""),
        )
        segment_roads = roads_by_segment.get(
            segment_id,
            built.iloc[0:0].copy(),
        )
        built_roles = set(segment_roads["carrier_role"].astype(str))
        if alternative_main:
            realized = bool(built_roles.intersection(alternative_main))
            missing = "" if realized else "main_oneway"
            roles_to_check = sorted(
                built_roles.intersection(alternative_main)
            )
        else:
            missing_roles = sorted(expected_roles - built_roles)
            realized = not missing_roles
            missing = ",".join(missing_roles)
            roles_to_check = sorted(expected_roles)
        chain_failures: list[str] = []
        if chain_gate_enabled:
            expected_terminals = terminal_groups_by_segment.get(
                segment_id,
                set(),
            )
            if alternative_main:
                candidate_failures: list[list[str]] = []
                for role in roles_to_check:
                    failures = _directional_chain_failures(
                        segment_roads[
                            segment_roads["carrier_role"].astype(str).eq(
                                role
                            )
                        ],
                        node_groups,
                        expected_terminals,
                        node_geometries=node_geometries,
                        junction_surfaces=junction_surfaces,
                        terminal_surface_tolerance_m=terminal_surface_tolerance_m,
                        topology_edges=topology_edges,
                    )
                    if not failures:
                        candidate_failures = []
                        break
                    candidate_failures.append(
                        [f"{role}:{reason}" for reason in failures]
                    )
                if candidate_failures:
                    chain_failures.extend(
                        min(candidate_failures, key=lambda value: (len(value), value))
                    )
                elif not roles_to_check:
                    chain_failures.append("main_oneway:missing")
            else:
                for role in roles_to_check:
                    failures = _directional_chain_failures(
                        segment_roads[
                            segment_roads["carrier_role"].astype(str).eq(
                                role
                            )
                        ],
                        node_groups,
                        expected_terminals,
                        node_geometries=node_geometries,
                        junction_surfaces=junction_surfaces,
                        terminal_surface_tolerance_m=terminal_surface_tolerance_m,
                        topology_edges=topology_edges,
                    )
                    chain_failures.extend(
                        f"{role}:{reason}" for reason in failures
                    )
            if missing:
                chain_failures.extend(
                    f"{role}:missing"
                    for role in missing.split(",")
                    if role
                )
        chain_complete = not chain_failures
        realized = realized and (
            chain_complete if chain_gate_enabled else True
        )
        direct_build_outcome = (
            "not_applicable"
            if not direct_build_required
            else "realized"
            if realized
            else "hard_conflict"
            if segment_build_state == "conflict_retained"
            else "partial_evidence_unresolved"
        )
        publish_disposition = _publish_disposition(
            direct_build_eligibility,
            realized=realized,
            segment_build_state=segment_build_state,
        )
        rows.append(
            {
                "run_id": run_id,
                "segment_id": segment_id,
                "target_class": target_class,
                "baseline_target": True,
                "direct_build_eligibility": direct_build_eligibility,
                "direct_build_required": direct_build_required,
                "direct_build_outcome": direct_build_outcome,
                "direct_build_realized": direct_build_required and realized,
                "publish_disposition": publish_disposition,
                "segment_build_state": segment_build_state,
                "classification_reason_codes": str(
                    getattr(segment, "classification_reason_codes", "")
                ),
                "classification_evidence_ids": str(
                    getattr(segment, "classification_evidence_ids", "")
                ),
                "classification_source": str(
                    getattr(segment, "classification_source", "")
                ),
                "classification_reviewed_by": str(
                    getattr(segment, "classification_reviewed_by", "")
                ),
                "classification_manifest_hash": str(
                    getattr(segment, "classification_manifest_hash", "")
                ),
                "reality_change_clue_id": str(
                    getattr(segment, "reality_change_clue_id", "")
                ),
                "expected_roles": ",".join(sorted(expected_roles or alternative_main)),
                "built_main_roles": ",".join(
                    sorted(role for role in built_roles if role.startswith("main_"))
                ),
                "built_main_road_count": int(
                    segment_roads["carrier_role"]
                    .astype(str)
                    .str.startswith("main_")
                    .sum()
                ),
                "missing_roles": missing,
                "directional_chain_gate_enabled": chain_gate_enabled,
                "directional_chain_complete": chain_complete,
                "chain_failure_reasons": ",".join(
                    sorted(set(chain_failures))
                ),
                "target_realized": realized,
                "reason_codes": (
                    "target_directional_trunk_chains_complete"
                    if realized
                    else "target_directional_trunk_chain_failed"
                    if chain_failures
                    else "target_high_precision_roles_missing"
                ),
                "geometry": segment.geometry,
            }
        )
    audit = (
        gpd.GeoDataFrame(rows, geometry="geometry", crs=target_segments.crs)
        if rows
        else _empty_audit(target_segments.crs)
    )
    baseline_realized_count = (
        int(audit["target_realized"].sum()) if not audit.empty else 0
    )
    direct = audit[audit["direct_build_required"]].copy()
    direct_realized_count = (
        int(direct["direct_build_realized"].sum()) if not direct.empty else 0
    )
    baseline_class_summary = {
        target_class: {
            "baseline_count": int(len(group)),
            "realized_count": int(group["target_realized"].sum()),
            "missing_count": int((~group["target_realized"]).sum()),
        }
        for target_class, group in audit.groupby("target_class")
    }
    direct_class_summary = {
        target_class: {
            "required_count": int(len(group)),
            "realized_count": int(group["direct_build_realized"].sum()),
            "missing_count": int((~group["direct_build_realized"]).sum()),
        }
        for target_class, group in direct.groupby("target_class")
    }
    summary = {
        "baseline_target_count": int(len(audit)),
        "baseline_realized_count": baseline_realized_count,
        "baseline_unresolved_count": int(len(audit) - baseline_realized_count),
        "direct_build_required_count": int(len(direct)),
        "direct_build_realized_count": direct_realized_count,
        "direct_build_unresolved_count": int(
            len(direct) - direct_realized_count
        ),
        "patch_data_insufficient_count": int(
            audit["direct_build_eligibility"]
            .eq("patch_data_insufficient")
            .sum()
        ),
        "reality_change_count": int(
            audit["direct_build_eligibility"].eq("reality_change").sum()
        ),
        "required_segment_count": int(len(direct)),
        "realized_segment_count": direct_realized_count,
        "missing_segment_count": int(len(direct) - direct_realized_count),
        "target_gate_pass": bool(
            len(direct) > 0 and direct_realized_count == len(direct)
        ),
        "directional_chain_gate_enabled": chain_gate_enabled,
        "directional_chain_complete_count": int(
            direct["directional_chain_complete"].sum()
        )
        if not direct.empty
        else 0,
        "directional_chain_failure_count": int(
            (~direct["directional_chain_complete"]).sum()
        )
        if not direct.empty
        else 0,
        "class_summary": direct_class_summary,
        "baseline_class_summary": baseline_class_summary,
        "direct_build_class_summary": direct_class_summary,
    }
    return TargetRealizationResult(audit, summary)


def _expected_roles(
    target_class: str,
    sgrade: str,
) -> tuple[set[str], set[str]]:
    if target_class == "advance_right":
        return {"main_oneway"}, set()
    if sgrade.endswith("双"):
        return {"main_forward", "main_reverse"}, set()
    return set(), {"main_oneway", "main_forward", "main_reverse"}


def _publish_disposition(
    eligibility: str,
    *,
    realized: bool,
    segment_build_state: str,
) -> str:
    if eligibility == "patch_data_insufficient":
        return "swsd_retained_data_insufficient"
    if eligibility == "reality_change":
        return "swsd_retained_reality_change_pending"
    if realized:
        return "hp_published"
    if segment_build_state == "conflict_retained":
        return "conflict_retained"
    return "swsd_retained_partial_evidence"


def _directional_chain_failures(
    roads: gpd.GeoDataFrame,
    node_groups: dict[str, set[str]],
    expected_terminals: set[str],
    *,
    node_geometries: dict[str, object],
    junction_surfaces: dict[str, dict[str, object]],
    terminal_surface_tolerance_m: float,
    topology_edges: set[tuple[str, str]],
) -> list[str]:
    if roads.empty:
        return ["missing"]
    road_ids = list(roads["id"])
    if len(set(road_ids)) != len(road_ids):
        return ["duplicated"]
    by_start: dict[str, list[object]] = {}
    by_end: dict[str, list[object]] = {}
    for road in roads.itertuples():
        by_start.setdefault(str(road.snodeid), []).append(road.id)
        by_end.setdefault(str(road.enodeid), []).append(road.id)
    adjacency: dict[object, set[object]] = {
        road_id: set() for road_id in road_ids
    }
    indegree = {road_id: 0 for road_id in road_ids}
    for node_id in set(by_start).intersection(by_end):
        for source in by_end[node_id]:
            for target in by_start[node_id]:
                if source == target or target in adjacency[source]:
                    continue
                adjacency[source].add(target)
                indegree[target] += 1
    road_id_by_canonical = {
        canonical_id(road_id): road_id for road_id in road_ids
    }
    member_id_by_road = {
        canonical_id(row.id): canonical_id(
            getattr(row, "member_swsd_road_id", "")
        )
        for row in roads.itertuples()
    }
    for source_id, target_id in topology_edges:
        source = road_id_by_canonical.get(source_id)
        target = road_id_by_canonical.get(target_id)
        source_member_id = member_id_by_road.get(source_id, "")
        target_member_id = member_id_by_road.get(target_id, "")
        if (
            source is None
            or target is None
            or source == target
            or target in adjacency[source]
            or (
                source_member_id
                and source_member_id == target_member_id
            )
        ):
            continue
        adjacency[source].add(target)
        indegree[target] += 1
    sources = [road_id for road_id in road_ids if indegree[road_id] == 0]
    sinks = [road_id for road_id in road_ids if not adjacency[road_id]]
    failures: list[str] = []
    if any(value > 1 for value in indegree.values()) or any(
        len(value) > 1 for value in adjacency.values()
    ):
        failures.append("branched")
    visited: set[object] = set()
    frontier = list(sources)
    while frontier:
        road_id = frontier.pop()
        if road_id in visited:
            continue
        visited.add(road_id)
        frontier.extend(adjacency[road_id] - visited)
    if (
        len(sources) != 1
        or len(sinks) != 1
        or len(visited) != len(road_ids)
        or sum(len(value) for value in adjacency.values())
        != len(road_ids) - 1
    ):
        failures.append("disconnected")
    if len(sources) == 1 and len(sinks) == 1:
        indexed = roads.set_index("id")
        start_node = canonical_id(indexed.loc[sources[0], "snodeid"])
        end_node = canonical_id(indexed.loc[sinks[0], "enodeid"])
        terminal_pairings = _terminal_pairings(
            node_groups.get(start_node, set()),
            node_groups.get(end_node, set()),
            expected_terminals,
        )
        if not terminal_pairings:
            failures.append("terminal_mismatch")
        elif junction_surfaces and not any(
            _pairing_reaches_terminal_surfaces(
                pairing,
                start_node=start_node,
                end_node=end_node,
                node_geometries=node_geometries,
                junction_surfaces=junction_surfaces,
                tolerance_m=terminal_surface_tolerance_m,
            )
            for pairing in terminal_pairings
        ):
            failures.append("terminal_surface_mismatch")
    else:
        failures.append("terminal_mismatch")
    lineage_missing = roads[
        roads.get(
            "source_patch_road_keys",
            pd.Series("", index=roads.index),
        )
        .fillna("")
        .astype(str)
        .eq("")
        & roads.get(
            "source_lane_ids",
            pd.Series("", index=roads.index),
        )
        .fillna("")
        .astype(str)
        .eq("")
    ]
    if not lineage_missing.empty:
        failures.append("lineage_missing")
    return sorted(set(failures))


def _terminal_pairings(
    start_groups: set[str],
    end_groups: set[str],
    expected_terminals: set[str],
) -> list[tuple[str, str]]:
    if len(expected_terminals) != 2:
        return []
    pairings: list[tuple[str, str]] = []
    for start_group in sorted(expected_terminals.intersection(start_groups)):
        for end_group in sorted(expected_terminals.intersection(end_groups)):
            if start_group != end_group:
                pairings.append((start_group, end_group))
    return pairings


def _pairing_reaches_terminal_surfaces(
    pairing: tuple[str, str],
    *,
    start_node: str,
    end_node: str,
    node_geometries: dict[str, object],
    junction_surfaces: dict[str, dict[str, object]],
    tolerance_m: float,
) -> bool:
    for node_id, junction_group_id in zip(
        (start_node, end_node),
        pairing,
        strict=True,
    ):
        surface = junction_surfaces.get(junction_group_id)
        if surface is None:
            return False
        if surface["junction_source"] == "swsd_retained":
            continue
        node_geometry = node_geometries.get(node_id)
        surface_geometry = surface["geometry"]
        if (
            node_geometry is None
            or node_geometry.is_empty
            or surface_geometry is None
            or surface_geometry.is_empty
            or not surface_geometry.contains(node_geometry)
        ):
            return False
    return True


def _junction_surface_metadata(
    junction_units: gpd.GeoDataFrame | None,
    target_crs: object,
) -> dict[str, dict[str, object]]:
    if junction_units is None or junction_units.empty:
        return {}
    surfaces = junction_units.copy()
    surfaces.geometry = gpd.GeoSeries(
        [
            endpoint_surface_geometry(row)
            for row in surfaces.itertuples(index=False)
        ],
        index=surfaces.index,
        crs=surfaces.crs,
    )
    if (
        target_crs is not None
        and surfaces.crs is not None
        and surfaces.crs != target_crs
    ):
        surfaces = surfaces.to_crs(target_crs)
    return {
        canonical_id(row.junction_group_id): {
            "junction_source": str(row.junction_source),
            "geometry": row.geometry,
        }
        for row in surfaces.itertuples()
    }


def _topology_edges(
    road_next_road: gpd.GeoDataFrame | None,
) -> set[tuple[str, str]]:
    if road_next_road is None or road_next_road.empty:
        return set()
    source_column = (
        "RoadId"
        if "RoadId" in road_next_road
        else "source_road_id"
        if "source_road_id" in road_next_road
        else ""
    )
    target_column = (
        "NextRoadId"
        if "NextRoadId" in road_next_road
        else "target_road_id"
        if "target_road_id" in road_next_road
        else ""
    )
    if not source_column or not target_column:
        return set()
    return {
        (
            canonical_id(source_id),
            canonical_id(target_id),
        )
        for source_id, target_id in zip(
            road_next_road[source_column],
            road_next_road[target_column],
            strict=True,
        )
    }


def _empty_audit(crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "run_id": pd.Series(dtype=str),
            "segment_id": pd.Series(dtype=str),
            "target_class": pd.Series(dtype=str),
            "baseline_target": pd.Series(dtype=bool),
            "direct_build_eligibility": pd.Series(dtype=str),
            "direct_build_required": pd.Series(dtype=bool),
            "direct_build_outcome": pd.Series(dtype=str),
            "direct_build_realized": pd.Series(dtype=bool),
            "publish_disposition": pd.Series(dtype=str),
            "segment_build_state": pd.Series(dtype=str),
            "classification_reason_codes": pd.Series(dtype=str),
            "classification_evidence_ids": pd.Series(dtype=str),
            "classification_source": pd.Series(dtype=str),
            "classification_reviewed_by": pd.Series(dtype=str),
            "classification_manifest_hash": pd.Series(dtype=str),
            "reality_change_clue_id": pd.Series(dtype=str),
            "expected_roles": pd.Series(dtype=str),
            "built_main_roles": pd.Series(dtype=str),
            "built_main_road_count": pd.Series(dtype=int),
            "missing_roles": pd.Series(dtype=str),
            "directional_chain_gate_enabled": pd.Series(dtype=bool),
            "directional_chain_complete": pd.Series(dtype=bool),
            "chain_failure_reasons": pd.Series(dtype=str),
            "target_realized": pd.Series(dtype=bool),
            "reason_codes": pd.Series(dtype=str),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


__all__ = ["TargetRealizationResult", "audit_target_realization"]
