from __future__ import annotations

import geopandas as gpd
import pandas as pd

from .segment_first_skeleton import canonical_id


LANE_TOPO_PAIR_SOURCES = frozenset({"lane_topo", "lane_topo_lane"})


def project_lane_topo(
    audit: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    road_next_road: gpd.GeoDataFrame,
    *,
    fallback_patch_road_keys: set[str],
    rejected_patch_road_pairs: set[tuple[str, str]],
    connection_evidence: pd.DataFrame | None = None,
    road_lane_relation: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    result = audit.copy()
    roads_by_patch = _roads_by_patch_key(roads)
    roads_by_lane = _roads_by_lane_relation(
        road_lane_relation,
        roads,
    )
    accepted_pairs_by_relation = _accepted_road_pairs_by_relation(
        connection_evidence,
        roads,
    )
    actual_pairs = (
        set(zip(road_next_road["RoadId"], road_next_road["NextRoadId"]))
        if not road_next_road.empty
        else set()
    )
    adjacency: dict[object, set[object]] = {}
    for source_id, target_id in actual_pairs:
        adjacency.setdefault(source_id, set()).add(target_id)
    lineage_by_road = _lineage_by_road(roads)
    retained_semantic_bridge_ids = set(
        roads.loc[
            roads.get(
                "realization",
                pd.Series("", index=roads.index),
            ).eq("retained")
            & roads["carrier_role"].eq("semantic_carrier"),
            "id",
        ]
    )
    junction_carrier_ids = set(
        roads.loc[
            roads["carrier_role"].isin(
                {"junction_surface_carrier", "local_connector"}
            ),
            "id",
        ]
    )
    source_lane_keys = result.get(
        "source_lane_carrier_key", pd.Series("", index=result.index)
    ).astype(str)
    target_lane_keys = result.get(
        "target_lane_carrier_key", pd.Series("", index=result.index)
    ).astype(str)
    source_road_keys = result["source_patch_road_key"].astype(str)
    target_road_keys = result["target_patch_road_key"].astype(str)
    relation_ids = result.get(
        "lane_topo_id", pd.Series("", index=result.index)
    ).astype(str)
    source_ids: list[str] = []
    target_ids: list[str] = []
    carrier_path_ids: list[str] = []
    states: list[str] = []
    for (
        relation_id,
        source_lane_key,
        target_lane_key,
        source_road_key,
        target_road_key,
    ) in zip(
        relation_ids,
        source_lane_keys,
        target_lane_keys,
        source_road_keys,
        target_road_keys,
    ):
        source_lane_candidates = set(
            roads_by_lane.get(source_lane_key, set())
            or roads_by_patch.get(source_lane_key, set())
        )
        target_lane_candidates = set(
            roads_by_lane.get(target_lane_key, set())
            or roads_by_patch.get(target_lane_key, set())
        )
        source_parent_candidates = set(
            roads_by_patch.get(source_road_key, set())
        )
        target_parent_candidates = set(
            roads_by_patch.get(target_road_key, set())
        )
        source_candidates = (
            source_lane_candidates or source_parent_candidates
        )
        target_candidates = (
            target_lane_candidates or target_parent_candidates
        )
        source_id = _joined_ids(source_candidates)
        target_id = _joined_ids(target_candidates)
        carrier_path = ""
        rejected = (
            (source_lane_key, target_lane_key) in rejected_patch_road_pairs
            or (source_road_key, target_road_key) in rejected_patch_road_pairs
        )
        parent_common = source_parent_candidates.intersection(
            target_parent_candidates
        )
        if rejected:
            states.append("excluded_physical_connection_evidence_rejected")
        elif parent_common:
            states.append("mapped_within_road")
            selected = min(parent_common, key=str)
            source_id = target_id = canonical_id(selected)
            carrier_path = canonical_id(selected)
        elif not source_candidates or not target_candidates:
            states.append(
                "excluded_segment_conflict_retained"
                if source_lane_key in fallback_patch_road_keys
                or source_road_key in fallback_patch_road_keys
                or target_lane_key in fallback_patch_road_keys
                or target_road_key in fallback_patch_road_keys
                else "excluded_patch_carrier_not_published"
            )
        elif common := source_candidates.intersection(target_candidates):
            states.append("mapped_within_road")
            selected = min(common, key=str)
            source_id = target_id = canonical_id(selected)
            carrier_path = canonical_id(selected)
        else:
            direct_pairs = sorted(
                (
                    (source, target)
                    for source in source_candidates
                    for target in target_candidates
                    if (source, target) in actual_pairs
                ),
                key=lambda pair: (str(pair[0]), str(pair[1])),
            )
            if direct_pairs:
                states.append("mapped_roadnextroad")
                source_id, target_id = map(canonical_id, direct_pairs[0])
                carrier_path = f"{source_id},{target_id}"
            else:
                lineage_paths = sorted(
                    (
                        path
                        for source in source_candidates
                        for target in target_candidates
                        if (
                            path := _fine_lineage_path(
                                source,
                                target,
                                adjacency,
                                lineage_by_road,
                                retained_semantic_bridge_ids,
                            )
                        )
                    ),
                    key=lambda path: tuple(map(str, path)),
                )
                carrier_pairs = sorted(
                    (
                        (source, target)
                        for source in source_candidates
                        for target in target_candidates
                        if has_junction_carrier_path(
                            source,
                            target,
                            adjacency,
                            junction_carrier_ids,
                        )
                    ),
                    key=lambda pair: (str(pair[0]), str(pair[1])),
                )
                if lineage_paths:
                    states.append("mapped_roadnextroad_chain")
                    path = lineage_paths[0]
                    source_id = canonical_id(path[0])
                    target_id = canonical_id(path[-1])
                    carrier_path = ",".join(map(canonical_id, path))
                elif carrier_pairs:
                    states.append("mapped_junction_carrier_path")
                    source_id, target_id = map(
                        canonical_id, carrier_pairs[0]
                    )
                    carrier_path = f"{source_id},{target_id}"
                else:
                    realized = _accepted_realized_pair(
                        accepted_pairs_by_relation.get(
                            relation_id, ()
                        ),
                        actual_pairs,
                        adjacency,
                        junction_carrier_ids,
                    )
                    if realized is None:
                        states.append(
                            "review_shared_node_relation_missing"
                        )
                    else:
                        state, source, target = realized
                        states.append(state)
                        source_id = canonical_id(source)
                        target_id = canonical_id(target)
                        carrier_path = f"{source_id},{target_id}"
        source_ids.append(source_id)
        target_ids.append(target_id)
        carrier_path_ids.append(carrier_path)
    result["source_road_id"] = source_ids
    result["target_road_id"] = target_ids
    result["carrier_path_road_ids"] = carrier_path_ids
    result["projection_state"] = states
    return result


def _accepted_road_pairs_by_relation(
    connection_evidence: pd.DataFrame | None,
    roads: gpd.GeoDataFrame,
) -> dict[str, tuple[tuple[object, object], ...]]:
    if connection_evidence is None or connection_evidence.empty:
        return {}
    required = {
        "connection_decision",
        "pair_source",
        "source_relation_id",
        "source_road_id",
        "target_road_id",
    }
    if not required.issubset(connection_evidence.columns):
        return {}
    road_ids = {
        canonical_id(road_id): road_id for road_id in roads["id"]
    }
    result: dict[str, set[tuple[object, object]]] = {}
    accepted = connection_evidence[
        connection_evidence["connection_decision"].eq("accepted")
        & connection_evidence["pair_source"].isin(LANE_TOPO_PAIR_SOURCES)
    ]
    for row in accepted.itertuples(index=False):
        source_key = canonical_id(row.source_road_id)
        target_key = canonical_id(row.target_road_id)
        if source_key not in road_ids or target_key not in road_ids:
            continue
        result.setdefault(str(row.source_relation_id), set()).add(
            (road_ids[source_key], road_ids[target_key])
        )
    return {
        relation_id: tuple(
            sorted(pairs, key=lambda pair: (str(pair[0]), str(pair[1])))
        )
        for relation_id, pairs in result.items()
    }


def _accepted_realized_pair(
    accepted_pairs: tuple[tuple[object, object], ...],
    actual_pairs: set[tuple[object, object]],
    adjacency: dict[object, set[object]],
    junction_carrier_ids: set[object],
) -> tuple[str, object, object] | None:
    for source, target in accepted_pairs:
        if source == target:
            return "mapped_within_road", source, target
        if (source, target) in actual_pairs:
            return "mapped_roadnextroad", source, target
        if has_junction_carrier_path(
            source,
            target,
            adjacency,
            junction_carrier_ids,
        ):
            return "mapped_junction_carrier_path", source, target
    return None


def rejected_lane_topo_pairs(
    *connection_evidence: pd.DataFrame,
) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for evidence in connection_evidence:
        required = {
            "connection_decision",
            "pair_source",
            "source_patch_road_key",
            "target_patch_road_key",
        }
        if evidence is None or evidence.empty or not required.issubset(
            evidence.columns
        ):
            continue
        rejected = evidence[
            evidence["connection_decision"].eq("rejected")
            & evidence["pair_source"].isin(LANE_TOPO_PAIR_SOURCES)
        ]
        result.update(
            zip(
                rejected["source_patch_road_key"].astype(str),
                rejected["target_patch_road_key"].astype(str),
            )
        )
    return result


def has_junction_carrier_path(
    source: object,
    target: object,
    adjacency: dict[object, set[object]],
    junction_carrier_ids: set[object],
    *,
    maximum_hops: int = 4,
) -> bool:
    frontier = {source}
    visited = {source}
    for _ in range(maximum_hops):
        next_frontier: set[object] = set()
        for current in frontier:
            for candidate in adjacency.get(current, set()):
                if candidate == target:
                    return True
                if candidate in junction_carrier_ids and candidate not in visited:
                    visited.add(candidate)
                    next_frontier.add(candidate)
        if not next_frontier:
            return False
        frontier = next_frontier
    return False


def _lineage_by_road(
    roads: gpd.GeoDataFrame,
) -> dict[object, tuple[str, str, str]]:
    result: dict[object, tuple[str, str, str]] = {}
    for road in roads.itertuples(index=False):
        movement_parent = canonical_id(
            getattr(road, "movement_parent_carrier_id", "")
        )
        parent = (
            movement_parent
            or canonical_id(
                getattr(road, "lineage_parent_road_id", None)
            )
        )
        if not parent:
            parent = str(
                getattr(road, "carrier_id", "") or ""
            ).split(":part:", 1)[0]
        if parent is None or pd.isna(parent):
            continue
        parent = canonical_id(parent)
        if not parent:
            continue
        result[road.id] = (
            parent,
            str(getattr(road, "segment_id", "")),
            str(getattr(road, "carrier_role", "")),
        )
    return result


def _fine_lineage_path(
    source: object,
    target: object,
    adjacency: dict[object, set[object]],
    lineage_by_road: dict[object, tuple[str, str, str]],
    retained_semantic_bridge_ids: set[object] | None = None,
    *,
    maximum_hops: int = 8,
) -> tuple[object, ...] | None:
    lineage = lineage_by_road.get(source)
    if lineage is None:
        return None
    retained_semantic_bridge_ids = retained_semantic_bridge_ids or set()
    frontier = [(source, (source,))]
    visited = {source}
    for _ in range(maximum_hops):
        next_frontier: list[tuple[object, tuple[object, ...]]] = []
        for current, path in frontier:
            for candidate in sorted(adjacency.get(current, set()), key=str):
                next_path = (*path, candidate)
                if candidate == target:
                    return next_path
                if (
                    candidate not in visited
                    and (
                        lineage_by_road.get(candidate) == lineage
                        or candidate in retained_semantic_bridge_ids
                    )
                ):
                    visited.add(candidate)
                    next_frontier.append((candidate, next_path))
        if not next_frontier:
            return None
        frontier = next_frontier
    return None


def _joined_ids(values: set[object]) -> str:
    return ",".join(canonical_id(value) for value in sorted(values, key=str))


def _roads_by_patch_key(
    roads: gpd.GeoDataFrame,
) -> dict[str, set[object]]:
    result: dict[str, set[object]] = {}
    for road in roads.itertuples():
        raw = str(
            getattr(road, "source_patch_road_keys", "")
            or getattr(road, "patch_road_key", "")
        )
        for key in (item.strip() for item in raw.split(",")):
            if key:
                result.setdefault(key, set()).add(road.id)
    return result


def _roads_by_lane_relation(
    relation: gpd.GeoDataFrame | None,
    roads: gpd.GeoDataFrame,
) -> dict[str, set[object]]:
    if relation is None or relation.empty:
        return {}
    road_ids = {
        canonical_id(road_id): road_id for road_id in roads["id"]
    }
    result: dict[str, set[object]] = {}
    for row in relation.itertuples(index=False):
        road_id = road_ids.get(canonical_id(row.road_id))
        if road_id is None:
            continue
        patch_id = canonical_id(
            getattr(row, "source_patch_id", "")
        )
        lane_id = canonical_id(getattr(row, "lane_id", ""))
        keys = {
            str(getattr(row, "lane_key", "") or ""),
            f"{patch_id}:{lane_id}" if patch_id and lane_id else "",
            (
                f"{patch_id}:lane:{lane_id}"
                if patch_id and lane_id
                else ""
            ),
        }
        for key in keys:
            if key:
                result.setdefault(key, set()).add(road_id)
    return result


_has_junction_carrier_path = has_junction_carrier_path
_project_lane_topo = project_lane_topo


__all__ = [
    "LANE_TOPO_PAIR_SOURCES",
    "_has_junction_carrier_path",
    "_project_lane_topo",
    "has_junction_carrier_path",
    "project_lane_topo",
    "rejected_lane_topo_pairs",
]
