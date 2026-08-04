from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import fiona
import geopandas as gpd
from shapely.ops import substring

from .segment_first_geometry import RoadGeometryResult
from .segment_first_junction_carriers import JunctionCarrierResult
from .segment_first_skeleton import canonical_id


def orphan_junction_carrier_ids(
    continuity_failures: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
) -> set[str]:
    if continuity_failures.empty or roads.empty:
        return set()
    road_by_id = {
        str(row.id): row
        for row in roads.itertuples()
    }
    return {
        str(row.road_id)
        for row in continuity_failures.itertuples()
        if str(getattr(road_by_id.get(str(row.road_id)), "owner_type", ""))
        == "JUNCTION_UNIT"
        and str(
            getattr(road_by_id.get(str(row.road_id)), "carrier_role", "")
        )
        == "junction_surface_carrier"
    }


def suppress_junction_carrier_roads(
    geometry: RoadGeometryResult,
    junction_carriers: JunctionCarrierResult,
    suppressed_ids: set[str],
) -> tuple[RoadGeometryResult, JunctionCarrierResult]:
    if not suppressed_ids:
        return geometry, junction_carriers
    roads = geometry.roads[
        ~geometry.roads["id"].astype(str).isin(suppressed_ids)
    ].copy()
    sources = geometry.geometry_sources[
        ~geometry.geometry_sources["road_id"].astype(str).isin(suppressed_ids)
    ].copy()
    geometry_summary = dict(geometry.summary)
    geometry_summary.update(
        {
            "road_count": int(len(roads)),
            "built_road_count": int(roads["realization"].eq("built").sum()),
            "retained_road_count": int(roads["realization"].eq("retained").sum()),
            "junction_carrier_road_count": int(
                roads["owner_type"].fillna("").eq("JUNCTION_UNIT").sum()
            ),
        }
    )
    carrier_roads = junction_carriers.roads[
        ~junction_carriers.roads["id"].astype(str).isin(suppressed_ids)
    ].copy()
    carrier_sources = junction_carriers.geometry_sources[
        ~junction_carriers.geometry_sources["road_id"]
        .astype(str)
        .isin(suppressed_ids)
    ].copy()
    carrier_summary = dict(junction_carriers.summary)
    carrier_summary["junction_carrier_road_count"] = int(len(carrier_roads))
    carrier_summary["orphan_suppressed_count"] = int(
        len(set(junction_carriers.roads["id"].astype(str)) & suppressed_ids)
    )
    return (
        RoadGeometryResult(roads, sources, geometry_summary),
        replace(
            junction_carriers,
            roads=carrier_roads,
            geometry_sources=carrier_sources,
            summary=carrier_summary,
        ),
    )


def segment_road_relation(roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    columns = [
        "run_id",
        "segment_id",
        "owner_type",
        "junction_group_id",
        "id",
        "realization",
        "geometry_source",
        "patch_road_key",
        "source_patch_road_keys",
        "member_swsd_road_id",
        "geometry",
    ]
    result = roads[columns].copy().rename(columns={"id": "road_id"})
    result["relation_state"] = "published"
    return result


def junction_node_relation(nodes: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = nodes[nodes["junction_group_ids"].fillna("").astype(str) != ""].copy()
    result = result[["run_id", "id", "mainnodeid", "junction_group_ids", "geometry"]]
    return result.rename(columns={"id": "node_id"})


def audit_segment_access_realization(
    accesses: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    run_id: str,
) -> gpd.GeoDataFrame:
    node_groups: dict[object, set[str]] = {}
    for node in nodes.itertuples():
        groups = {
            value
            for value in str(getattr(node, "junction_group_ids", "") or "").split(",")
            if value
        }
        mainnode = str(getattr(node, "mainnodeid", "") or "")
        if mainnode and mainnode != "0":
            groups.add(mainnode)
        node_groups[node.id] = groups
    segment_nodes: dict[str, set[object]] = {}
    for road in roads.itertuples():
        segment_nodes.setdefault(str(road.segment_id), set()).update(
            {road.snodeid, road.enodeid}
        )
    rows: list[dict[str, object]] = []
    for access in accesses.itertuples():
        candidate_nodes = segment_nodes.get(str(access.segment_id), set())
        matched = sorted(
            node_id
            for node_id in candidate_nodes
            if str(access.junction_group_id) in node_groups.get(node_id, set())
        )
        realized = bool(matched)
        rows.append(
            {
                "run_id": run_id,
                "access_id": str(access.access_id),
                "segment_id": str(access.segment_id),
                "access_type": str(access.access_type),
                "access_ordinal": int(access.access_ordinal),
                "source_node_id": str(access.source_node_id),
                "junction_group_id": str(access.junction_group_id),
                "access_realized": realized,
                "matched_node_ids": ",".join(str(value) for value in matched),
                "reason_codes": (
                    "segment_road_endpoint_in_junction_group"
                    if realized
                    else "segment_access_not_materialized"
                ),
                "geometry": access.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=accesses.crs)


def final_geometry_sources(
    roads: gpd.GeoDataFrame,
    base_sources: gpd.GeoDataFrame,
    completions: gpd.GeoDataFrame,
    run_id: str,
) -> gpd.GeoDataFrame:
    completion_by_road = {
        road_id: group
        for road_id, group in completions.groupby("road_id")
    } if not completions.empty else {}
    base_by_road = {
        road_id: group.sort_values("start_fraction", kind="stable")
        for road_id, group in base_sources.groupby("road_id")
    } if not base_sources.empty else {}
    rows: list[dict[str, object]] = []
    for road in roads.itertuples():
        group = completion_by_road.get(road.id)
        start_length = 0.0
        end_length = 0.0
        source_ids: dict[str, str] = {"start": "", "end": ""}
        source_kinds: dict[str, str] = {}
        if group is not None:
            for endpoint, endpoint_group in group.groupby("endpoint"):
                length = float(endpoint_group["length_m"].sum())
                if endpoint == "start":
                    start_length = length
                elif endpoint == "end":
                    end_length = length
                source_ids[str(endpoint)] = ",".join(
                    sorted(set(endpoint_group["source_object_ids"].astype(str)))
                )
                source_kinds[str(endpoint)] = str(
                    endpoint_group.iloc[0]["geometry_source"]
                )
        total_length = float(road.geometry.length)
        completion_total = start_length + end_length
        if completion_total > total_length and completion_total > 0.0:
            scale = total_length / completion_total
            start_length *= scale
            end_length *= scale
        base_start = start_length
        base_end = max(start_length, total_length - end_length)

        def append_span(
            label: str,
            start_m: float,
            end_m: float,
            source_ids_value: str,
        ) -> None:
            if end_m - start_m <= 1e-9:
                return
            geometry = substring(road.geometry, start_m, end_m)
            rows.append(
                {
                    "run_id": run_id,
                    "road_id": road.id,
                    "segment_id": str(road.segment_id),
                    "source_span_id": f"{road.id}:{len(rows)}",
                    "geometry_source": label,
                    "source_object_ids": source_ids_value,
                    "start_fraction": start_m / total_length,
                    "end_fraction": end_m / total_length,
                    "length_m": float(geometry.length),
                    "geometry": geometry,
                }
            )

        append_span(
            source_kinds.get("start", "hp_constrained_completion"),
            0.0,
            start_length,
            source_ids["start"],
        )
        base_group = base_by_road.get(road.id)
        if base_group is None or base_group.empty:
            append_span(
                "hp_observed" if road.realization == "built" else "swsd_retained_whole",
                base_start,
                base_end,
                str(road.patch_road_key or road.member_swsd_road_id),
            )
        else:
            base_length = max(0.0, base_end - base_start)
            for base in base_group.itertuples():
                append_span(
                    str(base.geometry_source),
                    base_start + float(base.start_fraction) * base_length,
                    base_start + float(base.end_fraction) * base_length,
                    str(base.source_object_ids),
                )
        append_span(
            source_kinds.get("end", "hp_constrained_completion"),
            base_end,
            total_length,
            source_ids["end"],
        )
    return gpd.GeoDataFrame(
        rows,
        geometry="geometry",
        crs=roads.crs,
    )


def soft_review_features(
    roads: gpd.GeoDataFrame,
    endpoint_audit: gpd.GeoDataFrame,
    geometry_quality: gpd.GeoDataFrame,
    run_id: str,
) -> gpd.GeoDataFrame:
    rows = []
    for road in roads[roads["review_required"].fillna(False)].itertuples():
        rows.append(
            {
                "run_id": run_id,
                "object_type": "Road",
                "object_id": str(road.id),
                "reason_codes": "input_quality_isolated",
                "geometry": road.geometry.centroid,
            }
        )
    for quality in geometry_quality[
        geometry_quality["review_required"].fillna(False)
    ].itertuples():
        rows.append(
            {
                "run_id": run_id,
                "object_type": "RoadGeometry",
                "object_id": str(quality.road_id),
                "reason_codes": str(quality.reason_codes),
                "geometry": quality.geometry.centroid,
            }
        )
    for endpoint in endpoint_audit[
        endpoint_audit["review_required"].fillna(False)
    ].itertuples():
        reason = (
            "segment_access_surface_handoff"
            if endpoint.junction_membership_source
            == "segment_access_surface_handoff"
            else "long_constrained_completion"
        )
        rows.append(
            {
                "run_id": run_id,
                "object_type": "RoadEndpoint",
                "object_id": f"{endpoint.road_id}:{endpoint.endpoint}",
                "reason_codes": reason,
                "geometry": endpoint.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=roads.crs)


def scope_to_drivezones(
    roads: gpd.GeoDataFrame,
    drivezones: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    if roads.empty or drivezones.empty:
        return roads
    scope = drivezones.geometry.union_all()
    indexes = list(roads.sindex.query(scope))
    return roads.iloc[indexes].copy().reset_index(drop=True)


def nodes_for_road_endpoints(
    nodes: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    if nodes.empty or roads.empty:
        return nodes.iloc[0:0].copy()
    endpoint_ids = {
        canonical_id(value)
        for column in ("snodeid", "enodeid")
        if column in roads.columns
        for value in roads[column]
        if canonical_id(value)
    }
    if not endpoint_ids or "id" not in nodes.columns:
        return nodes.iloc[0:0].copy()
    return nodes[
        nodes["id"].map(canonical_id).isin(endpoint_ids)
    ].copy().reset_index(drop=True)


def read_frozen_v3(root: Path | None, crs: str) -> gpd.GeoDataFrame | None:
    if root is None:
        return None
    path = root / "p04_hp_v3_road_graph.gpkg"
    if not path.is_file():
        return None
    layers = fiona.listlayers(path)
    layer = next(
        (
            name
            for name in layers
            if "road" in name.lower() and "parent" not in name.lower()
        ),
        None,
    )
    if layer is None:
        return None
    frame = gpd.read_file(path, layer=layer)
    return frame.to_crs(crs)


__all__ = [
    "audit_segment_access_realization",
    "final_geometry_sources",
    "junction_node_relation",
    "nodes_for_road_endpoints",
    "orphan_junction_carrier_ids",
    "read_frozen_v3",
    "scope_to_drivezones",
    "segment_road_relation",
    "soft_review_features",
    "suppress_junction_carrier_roads",
]
