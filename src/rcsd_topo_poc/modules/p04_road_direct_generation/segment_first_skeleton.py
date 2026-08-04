from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable

import geopandas as gpd
import pandas as pd

from .segment_first_progress import (
    advance_progress,
    begin_progress_stage,
    finish_progress_stage,
)


@dataclass(frozen=True)
class SegmentSkeletonResult:
    segment_units: gpd.GeoDataFrame
    accesses: gpd.GeoDataFrame
    scoped_roads: gpd.GeoDataFrame
    summary: dict[str, object]


def build_segment_skeleton(
    segments: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    *,
    patch_ids: Iterable[str],
    run_id: str,
) -> SegmentSkeletonResult:
    patch_set = {str(value) for value in patch_ids}
    seed_roads = roads[
        roads["patch_id"].fillna("").astype(str).map(
            lambda value: bool(patch_set.intersection(parse_id_list(value)))
        )
    ].copy()
    segment_ids = set(seed_roads["segmentid"].dropna().map(canonical_id))
    scoped_roads = roads[
        roads["segmentid"].map(canonical_id).isin(segment_ids)
    ].copy()
    segment_units = segments[segments["id"].map(canonical_id).isin(segment_ids)].copy()
    segment_units["segment_id"] = segment_units["id"].map(canonical_id)
    segment_units["segment_type"] = segment_units.get("segment_type", "normal").fillna("normal").astype(str)
    segment_units["pair_node_ids"] = segment_units["pair_nodes"].map(lambda value: ",".join(parse_id_list(value)))
    segment_units["junc_node_ids"] = segment_units["junc_nodes"].map(lambda value: ",".join(parse_id_list(value)))
    segment_units["swsd_road_ids"] = segment_units["roads"].map(lambda value: ",".join(parse_id_list(value)))
    segment_units["source_patch_ids"] = segment_units["segment_id"].map(
        _segment_patch_ids(scoped_roads)
    )
    segment_units["run_id"] = run_id
    segment_units["business_owner"] = "T01_SEGMENT"
    segment_units["segment_publishable"] = False
    segment_units["reason_codes"] = "skeleton_only"
    segment_units = segment_units.sort_values("segment_id").reset_index(drop=True)

    node_by_id = nodes.copy()
    node_by_id["canonical_node_id"] = node_by_id["id"].map(canonical_id)
    node_by_id = node_by_id.drop_duplicates("canonical_node_id").set_index("canonical_node_id")
    road_endpoint_index, road_endpoint_columns = _build_road_endpoint_index(
        scoped_roads
    )
    access_rows: list[dict[str, object]] = []
    begin_progress_stage(
        "segment_skeleton_access",
        len(segment_units),
        detail="Segment endpoint/THROUGH access materialization",
    )
    endpoint_count = 0
    through_count = 0
    for segment_ordinal, segment in enumerate(
        segment_units.itertuples(),
        start=1,
    ):
        pair_nodes = parse_id_list(segment.pair_node_ids)
        junc_nodes = parse_id_list(segment.junc_node_ids)
        if not pair_nodes and segment.segment_type == "advance_right":
            pair_nodes = _road_endpoints_from_index(
                parse_id_list(segment.swsd_road_ids),
                road_endpoint_index,
                road_endpoint_columns,
            )
        for ordinal, node_id in enumerate(pair_nodes):
            access_rows.append(
                _access_row(segment.segment_id, node_id, "ENDPOINT", ordinal, node_by_id, run_id)
            )
            endpoint_count += 1
        for ordinal, node_id in enumerate(junc_nodes):
            access_rows.append(
                _access_row(segment.segment_id, node_id, "THROUGH", ordinal, node_by_id, run_id)
            )
            through_count += 1
        if segment_ordinal % 256 == 0 or segment_ordinal == len(segment_units):
            advance_progress(
                "segment_skeleton_access",
                completed=segment_ordinal,
                last_unit=segment.segment_id,
                counters={
                    "endpoint_accesses": endpoint_count,
                    "through_accesses": through_count,
                    "indexed_roads": len(scoped_roads),
                },
            )
    finish_progress_stage(
        "segment_skeleton_access",
        counters={
            "endpoint_accesses": endpoint_count,
            "through_accesses": through_count,
            "indexed_roads": len(scoped_roads),
        },
    )
    accesses = gpd.GeoDataFrame(access_rows, geometry="geometry", crs=segments.crs)
    summary = {
        "segment_count": int(len(segment_units)),
        "scoped_swsd_road_count": int(len(scoped_roads)),
        "advance_right_segment_count": int((segment_units["segment_type"] == "advance_right").sum()),
        "endpoint_access_count": int((accesses["access_type"] == "ENDPOINT").sum()) if not accesses.empty else 0,
        "through_access_count": int((accesses["access_type"] == "THROUGH").sum()) if not accesses.empty else 0,
        "segment_without_access_count": int(
            len(set(segment_units["segment_id"]) - set(accesses["segment_id"]))
        ),
    }
    return SegmentSkeletonResult(segment_units, accesses, scoped_roads, summary)


def parse_id_list(value: object) -> tuple[str, ...]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        values = value
    else:
        text = str(value).strip()
        if not text:
            return ()
        if text.startswith("["):
            try:
                decoded = json.loads(text)
                values = decoded if isinstance(decoded, list) else [decoded]
            except json.JSONDecodeError:
                values = text.strip("[]").split(",")
        else:
            values = text.split(",")
    ordered: list[str] = []
    seen: set[str] = set()
    for item in values:
        normalized = canonical_id(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return tuple(ordered)


def canonical_id(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().strip("\"'")
    if not text:
        return ""
    unsigned = text[1:] if text[:1] in {"+", "-"} else text
    if unsigned.isdecimal():
        return str(int(text))
    whole, separator, fraction = unsigned.partition(".")
    if (
        separator
        and "." not in fraction
        and whole.isdecimal()
        and bool(fraction)
        and not fraction.strip("0")
    ):
        signed_whole = text[:1] + whole if text[:1] in {"+", "-"} else whole
        return str(int(signed_whole))
    return text


def _segment_patch_ids(roads: gpd.GeoDataFrame):
    mapping: dict[str, set[str]] = {}
    for row in roads.itertuples():
        segment_id = canonical_id(row.segmentid)
        mapping.setdefault(segment_id, set()).update(parse_id_list(row.patch_id))
    return lambda segment_id: ",".join(sorted(mapping.get(str(segment_id), set())))


def _access_row(
    segment_id: str,
    node_id: str,
    access_type: str,
    ordinal: int,
    node_by_id: gpd.GeoDataFrame,
    run_id: str,
) -> dict[str, object]:
    node = node_by_id.loc[node_id] if node_id in node_by_id.index else None
    geometry = node.geometry if node is not None else None
    mainnode = canonical_id(node.get("mainnodeid")) if node is not None else ""
    if not mainnode or mainnode == "0":
        mainnode = node_id
    return {
        "run_id": run_id,
        "access_id": f"{segment_id}:{access_type.lower()}:{ordinal}:{node_id}",
        "segment_id": segment_id,
        "access_type": access_type,
        "access_ordinal": ordinal,
        "source_node_id": node_id,
        "junction_group_id": mainnode,
        "source_exists": node is not None,
        "geometry": geometry,
    }


def _road_endpoints(road_ids: tuple[str, ...], roads: gpd.GeoDataFrame) -> tuple[str, ...]:
    index, columns = _build_road_endpoint_index(roads)
    return _road_endpoints_from_index(road_ids, index, columns)


def _build_road_endpoint_index(
    roads: gpd.GeoDataFrame,
) -> tuple[
    dict[str, list[tuple[int, tuple[str, ...]]]],
    tuple[str, ...],
]:
    endpoint_columns = tuple(
        column for column in ("snodeid", "enodeid") if column in roads
    )
    columns = tuple(roads.columns)
    id_index = columns.index("id")
    endpoint_indexes = tuple(columns.index(column) for column in endpoint_columns)
    result: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
    for ordinal, row in enumerate(roads.itertuples(index=False, name=None)):
        road_id = canonical_id(row[id_index])
        result.setdefault(road_id, []).append(
            (
                ordinal,
                tuple(canonical_id(row[index]) for index in endpoint_indexes),
            )
        )
    return result, endpoint_columns


def _road_endpoints_from_index(
    road_ids: tuple[str, ...],
    index: dict[str, list[tuple[int, tuple[str, ...]]]],
    endpoint_columns: tuple[str, ...],
) -> tuple[str, ...]:
    selected = sorted(
        (
            record
            for road_id in set(road_ids)
            for record in index.get(canonical_id(road_id), ())
        ),
        key=lambda record: record[0],
    )
    values: list[str] = []
    for column_index in range(len(endpoint_columns)):
        values.extend(record[1][column_index] for record in selected)
    counts = pd.Series(values).value_counts()
    endpoints = tuple(sorted(counts[counts == 1].index))
    return endpoints[:2] if endpoints else tuple(dict.fromkeys(values))[:2]


__all__ = [
    "SegmentSkeletonResult",
    "build_segment_skeleton",
    "canonical_id",
    "parse_id_list",
]
