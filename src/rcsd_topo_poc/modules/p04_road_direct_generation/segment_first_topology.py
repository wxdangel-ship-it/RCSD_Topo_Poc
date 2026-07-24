from __future__ import annotations

from dataclasses import dataclass
import hashlib

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


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
    for node_id, roles in sorted(by_end.items(), key=lambda item: str(item[0])):
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

    semantic_groups = _semantic_ordinary_groups(node_meta)
    for group_id, node_ids in sorted(semantic_groups.items()):
        incoming: list[dict[str, object]] = []
        outgoing: list[dict[str, object]] = []
        for node_id in node_ids:
            roles = by_end.get(node_id, {"incoming": [], "outgoing": []})
            incoming.extend(roles["incoming"])
            outgoing.extend(roles["outgoing"])
        for source in incoming:
            for target in outgoing:
                if source["id"] == target["id"]:
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
                        compile_source="ordinary_junction_semantic",
                        geometry=_semantic_relation_point(
                            source_meta["geometry"],
                            target_meta["geometry"],
                        ),
                        run_id=run_id,
                    )
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
        start_record = {
            "id": row.id,
            "node_id": getattr(row, "snodeid"),
            "patch_road_keys": _split_keys(
                getattr(row, "start_patch_road_keys", "")
                or getattr(row, "patch_road_key", "")
            ),
        }
        end_record = {
            "id": row.id,
            "node_id": getattr(row, "enodeid"),
            "patch_road_keys": _split_keys(
                getattr(row, "end_patch_road_keys", "")
                or getattr(row, "patch_road_key", "")
            ),
        }
        direction = int(getattr(row, "direction", 2) or 2)
        start = str(getattr(row, "snodeid"))
        end = str(getattr(row, "enodeid"))
        start_record["node_id"] = start
        end_record["node_id"] = end
        result.setdefault(end, {"incoming": [], "outgoing": []})["incoming"].append(end_record)
        result.setdefault(start, {"incoming": [], "outgoing": []})["outgoing"].append(start_record)
        if direction == 1:
            result.setdefault(start, {"incoming": [], "outgoing": []})["incoming"].append(start_record)
            result.setdefault(end, {"incoming": [], "outgoing": []})["outgoing"].append(end_record)
    return result


def _allowed_pairs(explicit_pairs: pd.DataFrame | None, roads: gpd.GeoDataFrame) -> set[tuple[str, str]] | None:
    if explicit_pairs is None or explicit_pairs.empty:
        return None
    return set(
        zip(
            explicit_pairs["source_patch_road_key"].astype(str),
            explicit_pairs["target_patch_road_key"].astype(str),
        )
    )


def _semantic_ordinary_groups(
    node_meta: dict[str, dict[str, object]],
) -> dict[str, tuple[str, ...]]:
    groups: dict[str, set[str]] = {}
    kinds: dict[str, set[str]] = {}
    for node_id, meta in node_meta.items():
        for group_id in meta["junction_groups"]:
            groups.setdefault(group_id, set()).add(node_id)
            kinds.setdefault(group_id, set()).add(
                str(meta["junction_kind"])
            )
    return {
        group_id: tuple(sorted(node_ids))
        for group_id, node_ids in groups.items()
        if kinds.get(group_id, set()).issubset({"ordinary", "retained"})
        and kinds.get(group_id)
    }


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


__all__ = ["TopologyBuildResult", "compile_road_next_road"]
