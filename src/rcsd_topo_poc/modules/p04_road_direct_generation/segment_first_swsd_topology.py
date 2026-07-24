from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import pandas as pd

from .segment_first_skeleton import canonical_id, parse_id_list


@dataclass(frozen=True)
class SwsdTopologyContractResult:
    audit: gpd.GeoDataFrame
    fallback_segment_ids: frozenset[str]
    summary: dict[str, object]


def audit_swsd_access_direction_topology(
    segment_units: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    swsd_nodes: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
    published_roads: gpd.GeoDataFrame,
    published_nodes: gpd.GeoDataFrame,
    *,
    run_id: str,
) -> SwsdTopologyContractResult:
    """Compare every T01 Segment access with its original SWSD direction roles.

    Road may be split into any number of fine parts. The contract only requires
    the resulting directed chains to expose the same inbound/outbound roles at
    every SWSD/T01 Junction access.
    """
    segment_members = {
        canonical_id(row.segment_id): set(
            parse_id_list(row.swsd_road_ids)
        )
        for row in segment_units.itertuples()
    }
    road_to_segment = {
        road_id: segment_id
        for segment_id, road_ids in segment_members.items()
        for road_id in road_ids
    }
    expected_node_groups = _node_groups(swsd_nodes)
    actual_node_groups = _published_node_groups(published_nodes)
    expected = _access_roles(
        swsd_roads,
        expected_node_groups,
        road_to_segment=road_to_segment,
        segment_field="segmentid",
        road_id_field="id",
    )
    actual = _access_roles(
        published_roads,
        actual_node_groups,
        segment_field="segment_id",
        road_id_field="id",
    )

    rows: list[dict[str, object]] = []
    grouped_accesses = segment_accesses.groupby(
        [
            segment_accesses["segment_id"].map(canonical_id),
            segment_accesses["junction_group_id"].map(canonical_id),
        ],
        sort=True,
    )
    for (segment_id, junction_group_id), accesses in grouped_accesses:
        key = (segment_id, junction_group_id)
        expected_role = expected.get(key, _empty_role())
        actual_role = actual.get(key, _empty_role())
        expected_inbound = bool(expected_role["inbound"])
        expected_outbound = bool(expected_role["outbound"])
        actual_inbound = bool(actual_role["inbound"])
        actual_outbound = bool(actual_role["outbound"])
        reasons: list[str] = []
        if not expected_inbound and not expected_outbound:
            reasons.append("swsd_access_direction_unresolved")
        if expected_inbound and not actual_inbound:
            reasons.append("swsd_inbound_role_missing")
        if expected_outbound and not actual_outbound:
            reasons.append("swsd_outbound_role_missing")
        if actual_inbound and not expected_inbound:
            reasons.append("unexpected_inbound_role")
        if actual_outbound and not expected_outbound:
            reasons.append("unexpected_outbound_role")
        rows.append(
            {
                "run_id": run_id,
                "segment_id": segment_id,
                "junction_group_id": junction_group_id,
                "access_ids": ",".join(
                    sorted(set(accesses["access_id"].astype(str)))
                ),
                "access_types": ",".join(
                    sorted(set(accesses["access_type"].astype(str)))
                ),
                "expected_inbound": expected_inbound,
                "expected_outbound": expected_outbound,
                "actual_inbound": actual_inbound,
                "actual_outbound": actual_outbound,
                "expected_swsd_road_ids": ",".join(
                    sorted(expected_role["road_ids"])
                ),
                "actual_road_ids": ",".join(
                    sorted(actual_role["road_ids"])
                ),
                "topology_preserved": not reasons,
                "reason_codes": (
                    "swsd_access_direction_topology_preserved"
                    if not reasons
                    else ",".join(reasons)
                ),
                "geometry": accesses.iloc[0].geometry,
            }
        )
    audit = (
        gpd.GeoDataFrame(
            rows,
            geometry="geometry",
            crs=segment_accesses.crs,
        )
        if rows
        else _empty_audit(segment_accesses.crs)
    )
    failures = audit[~audit["topology_preserved"]]
    fallback_segment_ids = frozenset(
        failures["segment_id"].astype(str)
    )
    reason_counts = (
        failures["reason_codes"]
        .str.split(",")
        .explode()
        .value_counts()
        .to_dict()
        if not failures.empty
        else {}
    )
    summary = {
        "access_contract_count": int(len(audit)),
        "preserved_access_count": int(audit["topology_preserved"].sum()),
        "failed_access_count": int((~audit["topology_preserved"]).sum()),
        "failed_segment_count": int(len(fallback_segment_ids)),
        "reason_counts": reason_counts,
        "gate_pass": bool(not audit.empty and failures.empty),
    }
    return SwsdTopologyContractResult(
        audit,
        fallback_segment_ids,
        summary,
    )


def _node_groups(nodes: gpd.GeoDataFrame) -> dict[str, set[str]]:
    return {
        canonical_id(row.id): {
            _mainnode_group(row),
        }
        for row in nodes.itertuples()
        if canonical_id(row.id)
    }


def _published_node_groups(
    nodes: gpd.GeoDataFrame,
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for row in nodes.itertuples():
        node_id = canonical_id(row.id)
        if not node_id:
            continue
        result[node_id] = set(
            parse_id_list(getattr(row, "junction_group_ids", ""))
        )
    return result


def _mainnode_group(node: object) -> str:
    node_id = canonical_id(getattr(node, "id", ""))
    mainnode = canonical_id(getattr(node, "mainnodeid", ""))
    return mainnode if mainnode and mainnode != "0" else node_id


def _access_roles(
    roads: gpd.GeoDataFrame,
    node_groups: dict[str, set[str]],
    *,
    segment_field: str,
    road_id_field: str,
    road_to_segment: dict[str, str] | None = None,
) -> dict[tuple[str, str], dict[str, object]]:
    roles: dict[tuple[str, str], dict[str, object]] = {}
    for row in roads.itertuples():
        road_id = canonical_id(getattr(row, road_id_field, ""))
        segment_id = (
            road_to_segment.get(road_id, "")
            if road_to_segment is not None
            else canonical_id(getattr(row, segment_field, ""))
        )
        if not segment_id:
            continue
        start_groups = node_groups.get(
            canonical_id(getattr(row, "snodeid", "")),
            set(),
        )
        end_groups = node_groups.get(
            canonical_id(getattr(row, "enodeid", "")),
            set(),
        )
        direction = _direction(getattr(row, "direction", 2))
        if direction in {0, 1}:
            _record_roles(
                roles,
                segment_id,
                start_groups,
                road_id,
                inbound=True,
                outbound=True,
            )
            _record_roles(
                roles,
                segment_id,
                end_groups,
                road_id,
                inbound=True,
                outbound=True,
            )
        elif direction == 2:
            _record_roles(
                roles,
                segment_id,
                start_groups,
                road_id,
                outbound=True,
            )
            _record_roles(
                roles,
                segment_id,
                end_groups,
                road_id,
                inbound=True,
            )
        elif direction == 3:
            _record_roles(
                roles,
                segment_id,
                start_groups,
                road_id,
                inbound=True,
            )
            _record_roles(
                roles,
                segment_id,
                end_groups,
                road_id,
                outbound=True,
            )
    return roles


def _record_roles(
    roles: dict[tuple[str, str], dict[str, object]],
    segment_id: str,
    groups: set[str],
    road_id: str,
    *,
    inbound: bool = False,
    outbound: bool = False,
) -> None:
    for group_id in groups:
        if not group_id:
            continue
        role = roles.setdefault(
            (segment_id, group_id),
            _empty_role(),
        )
        role["inbound"] = bool(role["inbound"] or inbound)
        role["outbound"] = bool(role["outbound"] or outbound)
        role["road_ids"].add(road_id)


def _empty_role() -> dict[str, object]:
    return {
        "inbound": False,
        "outbound": False,
        "road_ids": set(),
    }


def _direction(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 2


def _empty_audit(crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "run_id": pd.Series(dtype=str),
            "segment_id": pd.Series(dtype=str),
            "junction_group_id": pd.Series(dtype=str),
            "access_ids": pd.Series(dtype=str),
            "access_types": pd.Series(dtype=str),
            "expected_inbound": pd.Series(dtype=bool),
            "expected_outbound": pd.Series(dtype=bool),
            "actual_inbound": pd.Series(dtype=bool),
            "actual_outbound": pd.Series(dtype=bool),
            "expected_swsd_road_ids": pd.Series(dtype=str),
            "actual_road_ids": pd.Series(dtype=str),
            "topology_preserved": pd.Series(dtype=bool),
            "reason_codes": pd.Series(dtype=str),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


__all__ = [
    "SwsdTopologyContractResult",
    "audit_swsd_access_direction_topology",
]
