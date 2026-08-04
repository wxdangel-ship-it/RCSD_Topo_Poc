from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from .segment_first_progress import (
    advance_progress,
    begin_progress_stage,
    finish_progress_stage,
)


@dataclass(frozen=True)
class TopologyBuildResult:
    road_next_road: gpd.GeoDataFrame
    summary: dict[str, object]


def compile_road_next_road(
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    explicit_pairs: pd.DataFrame | None,
    *,
    run_id: str,
) -> TopologyBuildResult:
    node_meta = {
        str(row.id): {
            "geometry": row.geometry,
            "junction_kind": str(getattr(row, "junction_kind", "")),
            "junction_groups": _split_keys(
                getattr(row, "junction_group_ids", "")
            ),
            "mainnodeid": getattr(row, "mainnodeid", ""),
        }
        for row in nodes.itertuples()
    }
    rows: list[dict[str, object]] = []
    seen: set[tuple[object, object, str]] = set()
    by_end = _road_roles_by_node(roads)
    allowed = _allowed_pairs(explicit_pairs, roads)
    shared_node_items = sorted(by_end.items(), key=lambda item: str(item[0]))
    begin_progress_stage(
        "topology_shared_nodes",
        len(shared_node_items),
        detail="RoadNextRoad actual shared Node compilation",
    )
    for node_index, (node_id, roles) in enumerate(shared_node_items):
        advance_progress(
            "topology_shared_nodes",
            completed=node_index,
            last_unit=node_id,
            counters={"relation_count": len(rows)},
        )
        meta = node_meta.get(str(node_id))
        if meta is None:
            continue
        incoming = roles["incoming"]
        outgoing = roles["outgoing"]
        for source in incoming:
            for target in outgoing:
                if source["id"] == target["id"]:
                    continue
                if (
                    not _semantic_pair_allowed(source, target)
                    and not _pair_has_explicit_support(
                        source,
                        target,
                        allowed,
                    )
                ):
                    continue
                if (
                    meta["junction_kind"] == "complex_divmerge"
                    and source.get("patch_road_keys")
                    and target.get("patch_road_keys")
                ):
                    candidate_pairs = {
                        (source_key, target_key)
                        for source_key in source["patch_road_keys"]
                        for target_key in target["patch_road_keys"]
                    }
                    if allowed is None or not candidate_pairs.intersection(allowed):
                        continue
                junction_group = _first_group(meta["junction_groups"])
                pair_key = (
                    source["id"],
                    target["id"],
                    junction_group or f"node:{node_id}",
                )
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                rows.append(
                    _relation_row(
                        source,
                        target,
                        source_node_id=node_id,
                        target_node_id=node_id,
                        shared_node_id=node_id,
                        junction_group_id=junction_group,
                        mainnodeid=meta["mainnodeid"],
                        compile_source="actual_shared_node",
                        geometry=meta["geometry"],
                        run_id=run_id,
                    )
                )
    finish_progress_stage(
        "topology_shared_nodes",
        counters={"relation_count": len(rows)},
    )

    semantic_groups = _semantic_ordinary_groups(node_meta)
    semantic_group_items = sorted(semantic_groups.items())
    begin_progress_stage(
        "topology_semantic_junctions",
        len(semantic_group_items),
        detail="ordinary/retained semantic Junction relations",
        counters={"relation_count": len(rows)},
    )
    for group_index, (group_id, group) in enumerate(semantic_group_items):
        advance_progress(
            "topology_semantic_junctions",
            completed=group_index,
            last_unit=group_id,
            counters={"relation_count": len(rows)},
        )
        node_ids = group["node_ids"]
        retained_evidence_only = (
            group["junction_kind"] == "retained"
        )
        incoming: list[dict[str, object]] = []
        outgoing: list[dict[str, object]] = []
        for node_id in node_ids:
            roles = by_end.get(node_id, {"incoming": [], "outgoing": []})
            incoming.extend(roles["incoming"])
            outgoing.extend(roles["outgoing"])
        for source in incoming:
            for target in outgoing:
                explicit_support = _pair_has_explicit_support(
                    source,
                    target,
                    allowed,
                )
                if retained_evidence_only and not explicit_support:
                    continue
                if (
                    not _semantic_pair_allowed(source, target)
                    and not explicit_support
                ):
                    continue
                pair_key = (source["id"], target["id"], group_id)
                if pair_key in seen:
                    continue
                source_node = str(source["node_id"])
                target_node = str(target["node_id"])
                source_meta = node_meta[source_node]
                target_meta = node_meta[target_node]
                if str(source_meta["mainnodeid"]) != str(
                    target_meta["mainnodeid"]
                ):
                    continue
                seen.add(pair_key)
                rows.append(
                    _relation_row(
                        source,
                        target,
                        source_node_id=source["node_id"],
                        target_node_id=target["node_id"],
                        shared_node_id="",
                        junction_group_id=group_id,
                        mainnodeid=source_meta["mainnodeid"],
                        compile_source=(
                            "explicit_lane_topo_retained_semantic"
                            if retained_evidence_only
                            else "ordinary_junction_semantic"
                        ),
                        geometry=_semantic_relation_point(
                            source_meta["geometry"],
                            target_meta["geometry"],
                        ),
                        run_id=run_id,
                    )
                )
    finish_progress_stage(
        "topology_semantic_junctions",
        counters={"relation_count": len(rows)},
    )
    existing_road_pairs = {
        (row["RoadId"], row["NextRoadId"])
        for row in rows
    }
    all_incoming = [
        role
        for roles in by_end.values()
        for role in roles["incoming"]
    ]
    all_outgoing = [
        role
        for roles in by_end.values()
        for role in roles["outgoing"]
    ]
    explicit_outgoing_by_source_key = _explicit_outgoing_index(
        all_outgoing,
        allowed,
    )
    explicit_candidate_pair_count = 0
    begin_progress_stage(
        "topology_advance_right",
        len(all_incoming),
        detail="explicit ADVANCE_RIGHT relations",
        counters={
            "relation_count": len(rows),
            "explicit_candidate_pairs": 0,
        },
    )
    for source_index, source in enumerate(all_incoming):
        advance_progress(
            "topology_advance_right",
            completed=source_index,
            last_unit=source["id"],
            counters={
                "relation_count": len(rows),
                "explicit_candidate_pairs": explicit_candidate_pair_count,
            },
        )
        target_indexes = _explicit_target_indexes(
            source,
            explicit_outgoing_by_source_key,
        )
        explicit_candidate_pair_count += len(target_indexes)
        for target_index in target_indexes:
            target = all_outgoing[target_index]
            road_pair = (source["id"], target["id"])
            if (
                road_pair in existing_road_pairs
                or not _is_advance_right_pair(source, target)
                or not _pair_has_explicit_support(
                    source,
                    target,
                    allowed,
                )
            ):
                continue
            source_meta = node_meta.get(str(source["node_id"]))
            target_meta = node_meta.get(str(target["node_id"]))
            if (
                source_meta is None
                or target_meta is None
                or str(source_meta["junction_kind"])
                not in {"ordinary", "retained"}
                or str(target_meta["junction_kind"])
                not in {"ordinary", "retained"}
            ):
                continue
            mainnodeid = (
                target_meta["mainnodeid"]
                if str(source["segment_id"]).startswith(
                    "advance_right_"
                )
                else source_meta["mainnodeid"]
            )
            group_id = str(mainnodeid)
            rows.append(
                _relation_row(
                    source,
                    target,
                    source_node_id=source["node_id"],
                    target_node_id=target["node_id"],
                    shared_node_id="",
                    junction_group_id=group_id,
                    mainnodeid=mainnodeid,
                    compile_source=(
                        "explicit_lane_topo_advance_right_semantic"
                    ),
                    geometry=_semantic_relation_point(
                        source_meta["geometry"],
                        target_meta["geometry"],
                    ),
                    run_id=run_id,
                )
            )
            existing_road_pairs.add(road_pair)
    finish_progress_stage(
        "topology_advance_right",
        counters={
            "relation_count": len(rows),
            "explicit_candidate_pairs": explicit_candidate_pair_count,
        },
    )
    frame = _records(rows, roads.crs)
    return TopologyBuildResult(
        frame,
        {
            "road_next_road_count": int(len(frame)),
            "actual_shared_node_relation_count": int(
                frame["compile_source"].eq("actual_shared_node").sum()
            )
            if not frame.empty
            else 0,
            "ordinary_semantic_relation_count": int(
                frame["compile_source"].eq(
                    "ordinary_junction_semantic"
                ).sum()
            )
            if not frame.empty
            else 0,
            "explicit_advance_right_semantic_relation_count": int(
                frame["compile_source"].eq(
                    "explicit_lane_topo_advance_right_semantic"
                ).sum()
            )
            if not frame.empty
            else 0,
            "explicit_retained_semantic_relation_count": int(
                frame["compile_source"].eq(
                    "explicit_lane_topo_retained_semantic"
                ).sum()
            )
            if not frame.empty
            else 0,
            "shared_node_count": int(
                frame.loc[
                    frame["compile_source"].eq("actual_shared_node"),
                    "shared_node_id",
                ].nunique()
            )
            if not frame.empty
            else 0,
        },
    )


def _road_roles_by_node(roads: gpd.GeoDataFrame) -> dict[object, dict[str, list[dict[str, object]]]]:
    result: dict[object, dict[str, list[dict[str, object]]]] = {}
    for row in roads.itertuples():
        base = {
            "id": row.id,
            "segment_id": str(getattr(row, "segment_id", "") or ""),
            "carrier_role": str(getattr(row, "carrier_role", "") or ""),
            "realization": str(getattr(row, "realization", "") or ""),
            "geometry": row.geometry,
            "evidence_keys": _road_evidence_keys(row),
        }
        direction = int(getattr(row, "direction", 2) or 2)
        start = str(getattr(row, "snodeid"))
        end = str(getattr(row, "enodeid"))
        start_keys = _split_keys(
            getattr(row, "start_patch_road_keys", "")
            or getattr(row, "patch_road_key", "")
        )
        end_keys = _split_keys(
            getattr(row, "end_patch_road_keys", "")
            or getattr(row, "patch_road_key", "")
        )
        if direction in {0, 1}:
            _append_role(
                result, start, base, start_keys, "incoming",
                _endpoint_vector(row.geometry, "start", "incoming"),
            )
            _append_role(
                result, start, base, start_keys, "outgoing",
                _endpoint_vector(row.geometry, "start", "outgoing"),
            )
            _append_role(
                result, end, base, end_keys, "incoming",
                _endpoint_vector(row.geometry, "end", "incoming"),
            )
            _append_role(
                result, end, base, end_keys, "outgoing",
                _endpoint_vector(row.geometry, "end", "outgoing"),
            )
        elif direction == 3:
            _append_role(
                result, start, base, start_keys, "incoming",
                _endpoint_vector(row.geometry, "start", "incoming"),
            )
            _append_role(
                result, end, base, end_keys, "outgoing",
                _endpoint_vector(row.geometry, "end", "outgoing"),
            )
        else:
            _append_role(
                result, start, base, start_keys, "outgoing",
                _endpoint_vector(row.geometry, "start", "outgoing"),
            )
            _append_role(
                result, end, base, end_keys, "incoming",
                _endpoint_vector(row.geometry, "end", "incoming"),
            )
    return result


def _allowed_pairs(explicit_pairs: pd.DataFrame | None, roads: gpd.GeoDataFrame) -> set[tuple[str, str]] | None:
    if explicit_pairs is None or explicit_pairs.empty:
        return None
    if "source_relation_id" in explicit_pairs.columns:
        allowed: set[tuple[str, str]] = set()
        for _, group in explicit_pairs.groupby(
            "source_relation_id",
            dropna=False,
        ):
            source_keys = set(
                group["source_patch_road_key"].astype(str)
            )
            target_keys = set(
                group["target_patch_road_key"].astype(str)
            )
            allowed.update(
                (source_key, target_key)
                for source_key in source_keys
                for target_key in target_keys
            )
        return allowed
    return set(
        zip(
            explicit_pairs["source_patch_road_key"].astype(str),
            explicit_pairs["target_patch_road_key"].astype(str),
        )
    )


def _pair_has_explicit_support(
    source: dict[str, object],
    target: dict[str, object],
    allowed: set[tuple[str, str]] | None,
) -> bool:
    if not allowed:
        return False
    candidate_pairs = {
        (source_key, target_key)
        for source_key in source.get(
            "evidence_keys",
            source.get("patch_road_keys", ()),
        )
        for target_key in target.get(
            "evidence_keys",
            target.get("patch_road_keys", ()),
        )
    }
    return bool(candidate_pairs.intersection(allowed))


def _explicit_outgoing_index(
    outgoing: list[dict[str, object]],
    allowed: set[tuple[str, str]] | None,
) -> dict[str, tuple[int, ...]]:
    if not allowed:
        return {}
    outgoing_by_evidence_key: dict[str, list[int]] = {}
    for index, target in enumerate(outgoing):
        for key in target.get(
            "evidence_keys",
            target.get("patch_road_keys", ()),
        ):
            outgoing_by_evidence_key.setdefault(str(key), []).append(index)
    candidate_indexes: dict[str, set[int]] = {}
    for source_key, target_key in allowed:
        indexes = outgoing_by_evidence_key.get(str(target_key), ())
        if indexes:
            candidate_indexes.setdefault(str(source_key), set()).update(
                indexes
            )
    return {
        key: tuple(sorted(indexes))
        for key, indexes in candidate_indexes.items()
    }


def _explicit_target_indexes(
    source: dict[str, object],
    outgoing_by_source_key: dict[str, tuple[int, ...]],
) -> tuple[int, ...]:
    indexes = {
        index
        for source_key in source.get(
            "evidence_keys",
            source.get("patch_road_keys", ()),
        )
        for index in outgoing_by_source_key.get(str(source_key), ())
    }
    return tuple(sorted(indexes))


def _road_evidence_keys(row: object) -> tuple[str, ...]:
    keys = set(
        _split_keys(
            getattr(row, "source_patch_road_keys", "")
            or getattr(row, "patch_road_key", "")
        )
    )
    keys.update(
        _split_keys(getattr(row, "start_patch_road_keys", ""))
    )
    keys.update(
        _split_keys(getattr(row, "end_patch_road_keys", ""))
    )
    patch_ids = _split_keys(getattr(row, "source_patch_ids", ""))
    lane_ids = _split_keys(getattr(row, "source_lane_ids", ""))
    for lane_id in lane_ids:
        if ":lane:" in lane_id:
            keys.add(lane_id)
            continue
        for patch_id in patch_ids:
            keys.add(f"{patch_id}:lane:{lane_id}")
    return tuple(sorted(keys))


def _semantic_ordinary_groups(
    node_meta: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    groups: dict[str, set[str]] = {}
    kinds: dict[str, set[str]] = {}
    for node_id, meta in node_meta.items():
        for group_id in meta["junction_groups"]:
            groups.setdefault(group_id, set()).add(node_id)
            kinds.setdefault(group_id, set()).add(
                str(meta["junction_kind"])
            )
    return {
        group_id: {
            "node_ids": tuple(sorted(node_ids)),
            "junction_kind": next(iter(kinds[group_id])),
        }
        for group_id, node_ids in groups.items()
        if kinds.get(group_id, set()) in (
            {"ordinary"},
            {"retained"},
        )
        and kinds.get(group_id)
    }


def _append_role(
    result: dict[object, dict[str, list[dict[str, object]]]],
    node_id: str,
    base: dict[str, object],
    patch_road_keys: tuple[str, ...],
    role: str,
    travel_vector: tuple[float, float],
) -> None:
    record = dict(base)
    record.update(
        {
            "node_id": node_id,
            "patch_road_keys": patch_road_keys,
            "travel_vector": travel_vector,
        }
    )
    result.setdefault(
        node_id,
        {"incoming": [], "outgoing": []},
    )[role].append(record)


def _endpoint_vector(
    geometry: object,
    endpoint: str,
    role: str,
) -> tuple[float, float]:
    coordinates = list(geometry.coords)
    if len(coordinates) < 2:
        return (0.0, 0.0)
    if endpoint == "start":
        vector = np.asarray(coordinates[1], dtype=float) - np.asarray(
            coordinates[0],
            dtype=float,
        )
        if role == "incoming":
            vector = -vector
    else:
        vector = np.asarray(coordinates[-1], dtype=float) - np.asarray(
            coordinates[-2],
            dtype=float,
        )
        if role == "outgoing":
            vector = -vector
    return (float(vector[0]), float(vector[1]))


def _semantic_pair_allowed(
    source: dict[str, object],
    target: dict[str, object],
) -> bool:
    source_id = source.get("id", source.get("road_id"))
    target_id = target.get("id", target.get("road_id"))
    if source_id == target_id:
        return False
    source_vector = np.asarray(source.get("travel_vector", (0.0, 0.0)))
    target_vector = np.asarray(target.get("travel_vector", (0.0, 0.0)))
    denominator = float(
        np.linalg.norm(source_vector) * np.linalg.norm(target_vector)
    )
    if denominator <= 1e-9:
        return False
    cosine = float(
        np.clip(
            np.dot(source_vector, target_vector) / denominator,
            -1.0,
            1.0,
        )
    )
    turn = math.degrees(math.acos(cosine))
    return turn < 135.0


def _is_advance_right_pair(
    source: dict[str, object],
    target: dict[str, object],
) -> bool:
    source_segment = str(source.get("segment_id", ""))
    target_segment = str(target.get("segment_id", ""))
    return (
        source.get("id") != target.get("id")
        and (
            source_segment.startswith("advance_right_")
            or target_segment.startswith("advance_right_")
        )
    )


def _relation_row(
    source: dict[str, object],
    target: dict[str, object],
    *,
    source_node_id: object,
    target_node_id: object,
    shared_node_id: object,
    junction_group_id: str,
    mainnodeid: object,
    compile_source: str,
    geometry: Point,
    run_id: str,
) -> dict[str, object]:
    key = (
        source["id"],
        target["id"],
        compile_source,
        junction_group_id,
        source_node_id,
        target_node_id,
    )
    return {
        "run_id": run_id,
        "Id": _stable_int("rnr", *key),
        "RoadId": source["id"],
        "NextRoadId": target["id"],
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "shared_node_id": shared_node_id,
        "junction_group_id": junction_group_id,
        "mainnodeid": mainnodeid,
        "TurnType": 0,
        "Length": 0,
        "TrafficLightControl": 0,
        "MultiTurnType": 0,
        "compile_source": compile_source,
        "geometry": geometry,
    }


def _semantic_relation_point(source: Point, target: Point) -> Point:
    return Point(
        (float(source.x) + float(target.x)) / 2.0,
        (float(source.y) + float(target.y)) / 2.0,
    )


def _first_group(groups: tuple[str, ...]) -> str:
    return groups[0] if groups else ""


def _records(
    rows: list[dict[str, object]],
    crs: object,
) -> gpd.GeoDataFrame:
    if rows:
        return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    return gpd.GeoDataFrame(
        {
            "run_id": pd.Series(dtype=str),
            "Id": pd.Series(dtype=object),
            "RoadId": pd.Series(dtype=object),
            "NextRoadId": pd.Series(dtype=object),
            "source_node_id": pd.Series(dtype=object),
            "target_node_id": pd.Series(dtype=object),
            "shared_node_id": pd.Series(dtype=object),
            "junction_group_id": pd.Series(dtype=str),
            "mainnodeid": pd.Series(dtype=object),
            "TurnType": pd.Series(dtype=int),
            "Length": pd.Series(dtype=float),
            "TrafficLightControl": pd.Series(dtype=int),
            "MultiTurnType": pd.Series(dtype=int),
            "compile_source": pd.Series(dtype=str),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


def _stable_int(prefix: str, *values: object) -> int:
    digest = hashlib.sha1("|".join([prefix, *(str(value) for value in values)]).encode("utf-8")).hexdigest()
    return 7_000_000_000_000_000 + int(digest[:13], 16) % 999_999_999_999_999


def _split_keys(value: object) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


__all__ = [
    "TopologyBuildResult",
    "compile_road_next_road",
]
