from __future__ import annotations

from dataclasses import replace
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import substring

from .segment_first_config import SegmentFirstConfig
from .segment_first_nodes import NodeBuildResult


_MAIN_ROLES = {"main_forward", "main_reverse", "main_oneway", "semantic_carrier"}


def normalize_segment_main_handoffs(
    node_build: NodeBuildResult,
    *,
    config: SegmentFirstConfig,
) -> NodeBuildResult:
    """Make non-Junction main-trunk handoffs physically exact.

    A retained SWSD mainnode is only a lineage hint.  It may nominate a
    same-Segment near-straight handoff, but cannot itself publish a semantic
    RoadNextRoad.  The stronger built endpoint is preserved and the weaker
    continuation is locally completed to the same physical Node.
    """
    roads = node_build.roads.copy()
    nodes = node_build.nodes.copy()
    endpoint_audit = node_build.endpoint_audit.copy()
    connection_evidence = node_build.connection_evidence.copy()
    roads, regularized = _regularize_junction_approaches(
        roads,
        nodes,
        config,
    )
    candidates = _handoff_candidates(
        roads,
        nodes,
        maximum_gap_m=float(config.relation_endpoint_max_distance_m),
        maximum_turn_deg=30.0,
    )
    evidence_rows: list[dict[str, object]] = []
    replaced_node_ids: set[str] = set()
    normalized = 0
    used_source: set[tuple[str, str]] = set()
    used_target: set[tuple[str, str]] = set()
    for candidate in candidates:
        source_key = (str(candidate["source_id"]), "end")
        target_key = (str(candidate["target_id"]), "start")
        if source_key in used_source or target_key in used_target:
            continue
        source_index = int(candidate["source_index"])
        target_index = int(candidate["target_index"])
        source = roads.loc[source_index]
        target = roads.loc[target_index]
        source_built = str(source.get("realization", "")) == "built"
        target_built = str(target.get("realization", "")) == "built"
        if not source_built and not target_built:
            continue
        if source_built:
            anchor_point = Point(source.geometry.coords[-1])
            anchor_node_id = source["enodeid"]
            adjusted_index = target_index
            adjusted_endpoint = "start"
            adjusted_node_id = target["snodeid"]
            adjusted_geometry = _correct_start(
                target.geometry,
                anchor_point,
                _end_tangent(source.geometry),
            )
        else:
            anchor_point = Point(target.geometry.coords[0])
            anchor_node_id = target["snodeid"]
            adjusted_index = source_index
            adjusted_endpoint = "end"
            adjusted_node_id = source["enodeid"]
            adjusted_geometry = _correct_end(
                source.geometry,
                anchor_point,
                _start_tangent(target.geometry),
            )
        if adjusted_geometry is None:
            continue
        adjusted_geometry = _regularize_after_handoff(
            adjusted_geometry,
            width=float(
                roads.at[adjusted_index, "width"]
                if "width" in roads
                else 3.5
            ),
            config=config,
        )
        original_geometry = roads.at[adjusted_index, "geometry"]
        roads.at[adjusted_index, "geometry"] = adjusted_geometry
        roads.at[adjusted_index, "length"] = float(adjusted_geometry.length)
        if "base_geometry_length_m" in roads:
            roads.at[adjusted_index, "base_geometry_length_m"] = float(
                adjusted_geometry.length
            )
        if adjusted_endpoint == "start":
            roads.at[adjusted_index, "snodeid"] = anchor_node_id
        else:
            roads.at[adjusted_index, "enodeid"] = anchor_node_id
        roads.at[adjusted_index, "assembly_state"] = _append_state(
            roads.at[adjusted_index, "assembly_state"],
            "physical_handoff_normalized",
        )
        roads.at[adjusted_index, "smoothing_state"] = _append_state(
            roads.at[adjusted_index, "smoothing_state"],
            "local_endpoint_hermite",
        )
        replaced_node_ids.add(str(adjusted_node_id))
        _remap_endpoint_audit(
            endpoint_audit,
            road_id=roads.at[adjusted_index, "id"],
            endpoint=adjusted_endpoint,
            node_id=anchor_node_id,
            point=anchor_point,
            shift_m=float(candidate["gap_m"]),
        )
        evidence_rows.append(
            _connection_evidence_row(
                source,
                target,
                candidate,
                config.run_id,
            )
        )
        used_source.add(source_key)
        used_target.add(target_key)
        normalized += 1

    referenced_node_ids = set(roads["snodeid"].astype(str)) | set(
        roads["enodeid"].astype(str)
    )
    removable = replaced_node_ids - referenced_node_ids
    if removable:
        nodes = nodes[~nodes["id"].astype(str).isin(removable)].copy()
    if evidence_rows:
        added = gpd.GeoDataFrame(
            evidence_rows,
            geometry="geometry",
            crs=connection_evidence.crs or roads.crs,
        )
        connection_evidence = gpd.GeoDataFrame(
            pd.concat(
                [connection_evidence, added],
                ignore_index=True,
                sort=False,
            ),
            geometry="geometry",
            crs=connection_evidence.crs or roads.crs,
        )
    summary = dict(node_build.summary)
    summary.update(
        {
            "node_count": int(len(nodes)),
            "road_endpoint_count": int(len(roads) * 2),
            "physical_handoff_normalized_count": int(normalized),
            "junction_approach_regularized_count": int(regularized),
            "physical_handoff_candidate_count": int(len(candidates)),
            "missing_node_reference_count": int(
                (~roads["snodeid"].isin(nodes["id"])).sum()
                + (~roads["enodeid"].isin(nodes["id"])).sum()
            ),
        }
    )
    return replace(
        node_build,
        roads=roads,
        nodes=nodes,
        endpoint_audit=endpoint_audit,
        connection_evidence=connection_evidence,
        summary=summary,
    )


def _handoff_candidates(
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    *,
    maximum_gap_m: float,
    maximum_turn_deg: float,
) -> list[dict[str, object]]:
    node_meta = {
        str(row.id): {
            "kind": str(getattr(row, "junction_kind", "")),
            "mainnodeid": str(getattr(row, "mainnodeid", "") or ""),
            "groups": _split_values(
                getattr(row, "junction_group_ids", "")
            ),
        }
        for row in nodes.itertuples()
    }
    incoming: dict[str, list[dict[str, object]]] = {}
    outgoing: dict[str, list[dict[str, object]]] = {}
    for index, road in roads.iterrows():
        if (
            int(road.get("direction", 2) or 2) != 2
            or str(road.get("owner_type", "")) != "SEGMENT"
            or str(road.get("carrier_role", "")) not in _MAIN_ROLES
        ):
            continue
        start_group = _retained_group(node_meta.get(str(road["snodeid"])))
        end_group = _retained_group(node_meta.get(str(road["enodeid"])))
        base = {
            "index": int(index),
            "id": road["id"],
            "segment_id": str(road.get("segment_id", "")),
            "realization": str(road.get("realization", "")),
            "geometry": road.geometry,
        }
        if start_group:
            outgoing.setdefault(start_group, []).append(base)
        if end_group:
            incoming.setdefault(end_group, []).append(base)
    candidates: list[dict[str, object]] = []
    for group_id in sorted(set(incoming).intersection(outgoing)):
        for source in incoming[group_id]:
            for target in outgoing[group_id]:
                if (
                    str(source["id"]) == str(target["id"])
                    or source["segment_id"] != target["segment_id"]
                    or not source["segment_id"]
                ):
                    continue
                source_point = Point(source["geometry"].coords[-1])
                target_point = Point(target["geometry"].coords[0])
                gap = float(source_point.distance(target_point))
                if gap <= 1e-7 or gap > maximum_gap_m + 1e-9:
                    continue
                turn = _vector_angle(
                    _end_tangent(source["geometry"]),
                    _start_tangent(target["geometry"]),
                )
                if turn > maximum_turn_deg + 1e-9:
                    continue
                candidates.append(
                    {
                        "junction_group_id": group_id,
                        "source_index": source["index"],
                        "target_index": target["index"],
                        "source_id": source["id"],
                        "target_id": target["id"],
                        "gap_m": gap,
                        "turn_deg": turn,
                        "geometry": LineString(
                            [source_point, target_point]
                        ),
                    }
                )
    return sorted(
        candidates,
        key=lambda item: (
            float(item["turn_deg"]),
            float(item["gap_m"]),
            str(item["source_id"]),
            str(item["target_id"]),
        ),
    )


def _regularize_junction_approaches(
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    config: SegmentFirstConfig,
) -> tuple[gpd.GeoDataFrame, int]:
    output = roads.copy()
    accepted = 0
    accepted_node_ids = {
        str(row.id)
        for row in nodes.itertuples()
        if str(getattr(row, "junction_kind", ""))
        in {"ordinary", "complex_divmerge", "retained"}
    }
    for index, road in output.iterrows():
        geometry = road.geometry
        if (
            str(road.get("realization", "")) != "built"
            or str(road.get("owner_type", "")) != "SEGMENT"
            or str(road.get("carrier_role", "")) not in _MAIN_ROLES
            or geometry is None
            or geometry.is_empty
            or float(geometry.length) < 15.0
            or not (
                str(road.get("start_junction_group_ids", ""))
                or str(road.get("end_junction_group_ids", ""))
                or str(road.get("snodeid", "")) in accepted_node_ids
                or str(road.get("enodeid", "")) in accepted_node_ids
            )
        ):
            continue
        chord = Point(geometry.coords[0]).distance(
            Point(geometry.coords[-1])
        )
        if chord / float(geometry.length) < 0.94:
            continue
        candidate = _hermite_curve(geometry)
        if candidate is None:
            continue
        width = float(road.get("width", 3.5) or 3.5)
        deviation_limit = max(
            float(config.smoothing_max_deviation_m),
            min(5.0, max(2.0, width * 1.5)),
        )
        deviation = float(geometry.hausdorff_distance(candidate))
        if (
            deviation > deviation_limit + 1e-9
            or candidate.length / geometry.length < 0.94
            or _max_sample_turn(candidate) + 0.5
            >= _max_sample_turn(geometry)
        ):
            continue
        output.at[index, "geometry"] = candidate
        output.at[index, "length"] = float(candidate.length)
        if "base_geometry_length_m" in output:
            output.at[index, "base_geometry_length_m"] = float(
                candidate.length
            )
        output.at[index, "assembly_state"] = _append_state(
            road.get("assembly_state", ""),
            "junction_approach_regularized",
        )
        output.at[index, "smoothing_state"] = _append_state(
            road.get("smoothing_state", ""),
            "endpoint_tangent_hermite",
        )
        accepted += 1
    return output, accepted


def _regularize_after_handoff(
    geometry: LineString,
    *,
    width: float,
    config: SegmentFirstConfig,
) -> LineString:
    candidate = _hermite_curve(geometry)
    if candidate is None:
        return geometry
    deviation_limit = max(
        float(config.smoothing_max_deviation_m),
        min(5.0, max(2.0, width * 1.5)),
    )
    if (
        geometry.hausdorff_distance(candidate) > deviation_limit + 1e-9
        or candidate.length / geometry.length < 0.94
        or _max_sample_turn(candidate) + 0.5
        >= _max_sample_turn(geometry)
    ):
        return geometry
    return candidate


def _hermite_curve(line: LineString) -> LineString | None:
    length = float(line.length)
    chord = Point(line.coords[0]).distance(Point(line.coords[-1]))
    if length <= 1e-9 or chord <= 1e-9:
        return None
    sample = min(30.0, length * 0.25)
    start = np.asarray(line.coords[0], dtype=float)
    end = np.asarray(line.coords[-1], dtype=float)
    start_vector = (
        np.asarray(line.interpolate(sample).coords[0], dtype=float) - start
    )
    end_vector = (
        end
        - np.asarray(
            line.interpolate(length - sample).coords[0],
            dtype=float,
        )
    )
    start_vector = _unit(start_vector)
    end_vector = _unit(end_vector)
    if start_vector is None or end_vector is None:
        return None
    coordinates = _hermite_coordinates(
        start,
        end,
        start_vector,
        end_vector,
        max(8, int(math.ceil(length / 2.0)) + 1),
    )
    candidate = LineString(coordinates)
    return (
        candidate
        if candidate.is_valid and candidate.is_simple and not candidate.is_empty
        else None
    )


def _correct_start(
    line: LineString,
    anchor: Point,
    anchor_tangent: np.ndarray,
) -> LineString | None:
    gap = float(anchor.distance(Point(line.coords[0])))
    if gap <= 1e-9:
        return line
    length = float(line.length)
    window = min(max(12.0, gap * 3.0), length * 0.5)
    if window <= 1e-6:
        return None
    join = line.interpolate(window)
    after = line.interpolate(min(length, window + min(5.0, length - window)))
    join_tangent = _unit(
        np.asarray(after.coords[0], dtype=float)
        - np.asarray(join.coords[0], dtype=float)
    )
    anchor_vector = _unit(np.asarray(anchor_tangent, dtype=float))
    if join_tangent is None or anchor_vector is None:
        return None
    curve = _hermite_coordinates(
        np.asarray(anchor.coords[0], dtype=float),
        np.asarray(join.coords[0], dtype=float),
        anchor_vector,
        join_tangent,
        max(6, int(math.ceil(window / 2.0)) + 1),
    )
    rest = substring(line, window, length)
    coordinates = list(curve)
    rest_coordinates = list(rest.coords)
    if rest_coordinates:
        coordinates.extend(rest_coordinates[1:])
    candidate = LineString(coordinates)
    if (
        candidate.is_empty
        or not candidate.is_valid
        or not candidate.is_simple
        or candidate.length > line.length + gap * 2.0 + 1e-9
    ):
        return None
    return candidate


def _correct_end(
    line: LineString,
    anchor: Point,
    target_tangent: np.ndarray,
) -> LineString | None:
    reversed_line = LineString(list(line.coords)[::-1])
    corrected = _correct_start(
        reversed_line,
        anchor,
        -np.asarray(target_tangent, dtype=float),
    )
    return (
        LineString(list(corrected.coords)[::-1])
        if corrected is not None
        else None
    )


def _hermite_coordinates(
    start: np.ndarray,
    end: np.ndarray,
    start_tangent: np.ndarray,
    end_tangent: np.ndarray,
    count: int,
) -> list[tuple[float, float]]:
    scale = float(np.linalg.norm(end - start))
    coordinates: list[tuple[float, float]] = []
    for value in np.linspace(0.0, 1.0, count):
        h00 = 2.0 * value**3 - 3.0 * value**2 + 1.0
        h10 = value**3 - 2.0 * value**2 + value
        h01 = -2.0 * value**3 + 3.0 * value**2
        h11 = value**3 - value**2
        point = (
            h00 * start
            + h10 * start_tangent * scale / 3.0
            + h01 * end
            + h11 * end_tangent * scale / 3.0
        )
        coordinates.append((float(point[0]), float(point[1])))
    return coordinates


def _max_sample_turn(line: LineString, spacing_m: float = 2.0) -> float:
    count = max(3, int(math.ceil(float(line.length) / spacing_m)) + 1)
    points = [
        line.interpolate(distance)
        for distance in np.linspace(0.0, float(line.length), count)
    ]
    maximum = 0.0
    for left, middle, right in zip(points, points[1:], points[2:]):
        first = np.asarray(
            [middle.x - left.x, middle.y - left.y],
            dtype=float,
        )
        second = np.asarray(
            [right.x - middle.x, right.y - middle.y],
            dtype=float,
        )
        maximum = max(maximum, _vector_angle(first, second))
    return maximum


def _remap_endpoint_audit(
    audit: gpd.GeoDataFrame,
    *,
    road_id: object,
    endpoint: str,
    node_id: object,
    point: Point,
    shift_m: float,
) -> None:
    if audit.empty:
        return
    mask = audit["road_id"].astype(str).eq(str(road_id)) & audit[
        "endpoint"
    ].astype(str).eq(endpoint)
    if not mask.any():
        return
    audit.loc[mask, "node_id"] = node_id
    audit.loc[mask, "endpoint_shift_m"] = (
        audit.loc[mask, "endpoint_shift_m"].fillna(0.0).astype(float)
        + shift_m
    )
    audit.loc[mask, "connection_state"] = "physical_handoff_normalized"
    audit.loc[mask, "reason_codes"] = audit.loc[
        mask, "reason_codes"
    ].map(lambda value: _append_state(value, "exact_shared_node_handoff"))
    audit.loc[mask, "geometry"] = point


def _connection_evidence_row(
    source: pd.Series,
    target: pd.Series,
    candidate: dict[str, object],
    run_id: str,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "source_patch_road_key": str(
            source.get("end_patch_road_keys", "")
            or source.get("patch_road_key", "")
        ),
        "target_patch_road_key": str(
            target.get("start_patch_road_keys", "")
            or target.get("patch_road_key", "")
        ),
        "source_relation_id": "",
        "pair_source": "segment_main_trunk_physical_handoff",
        "source_road_id": source["id"],
        "target_road_id": target["id"],
        "source_segment_id": str(source.get("segment_id", "")),
        "target_segment_id": str(target.get("segment_id", "")),
        "endpoint_distance_m": float(candidate["gap_m"]),
        "same_accepted_surface": False,
        "drivezone_coverage": float("nan"),
        "connection_decision": "accepted",
        "reason_codes": "retained_group_near_straight_exact_shared_node",
        "pipeline_stage": "post_lineage_physical_handoff",
        "geometry": candidate["geometry"],
    }


def _retained_group(meta: dict[str, object] | None) -> str:
    if meta is None or str(meta.get("kind", "")) != "retained":
        return ""
    groups = tuple(meta.get("groups", ()))
    if groups:
        return str(groups[0])
    mainnode = str(meta.get("mainnodeid", ""))
    return mainnode if mainnode and mainnode != "0" else ""


def _start_tangent(line: LineString) -> np.ndarray:
    distance = min(8.0, max(0.1, float(line.length) * 0.2))
    return np.asarray(line.interpolate(distance).coords[0], dtype=float) - np.asarray(
        line.coords[0],
        dtype=float,
    )


def _end_tangent(line: LineString) -> np.ndarray:
    distance = min(8.0, max(0.1, float(line.length) * 0.2))
    return np.asarray(line.coords[-1], dtype=float) - np.asarray(
        line.interpolate(max(0.0, float(line.length) - distance)).coords[0],
        dtype=float,
    )


def _vector_angle(first: np.ndarray, second: np.ndarray) -> float:
    left = _unit(np.asarray(first, dtype=float))
    right = _unit(np.asarray(second, dtype=float))
    if left is None or right is None:
        return 180.0
    return math.degrees(
        math.acos(float(np.clip(np.dot(left, right), -1.0, 1.0)))
    )


def _unit(vector: np.ndarray) -> np.ndarray | None:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-9 else None


def _split_values(value: object) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in str(value or "").split(",")
        if item.strip()
    )


def _append_state(value: object, state: str) -> str:
    current = str(value or "")
    if not current:
        return state
    values = current.split("+")
    return current if state in values else f"{current}+{state}"


__all__ = ["normalize_segment_main_handoffs"]
