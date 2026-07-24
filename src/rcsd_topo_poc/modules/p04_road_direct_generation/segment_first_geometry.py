from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import substring

from .segment_first_config import SegmentFirstConfig
from .segment_first_skeleton import canonical_id


@dataclass(frozen=True)
class RoadGeometryResult:
    roads: gpd.GeoDataFrame
    geometry_sources: gpd.GeoDataFrame
    summary: dict[str, object]


def materialize_road_geometry(
    carriers: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    *,
    config: SegmentFirstConfig,
) -> RoadGeometryResult:
    member_frame = swsd_roads.copy()
    member_frame["canonical_road_id"] = member_frame["id"].map(canonical_id)
    member_by_id = member_frame.drop_duplicates("canonical_road_id").set_index("canonical_road_id")
    used_ids: set[int] = set()
    rows: list[dict[str, object]] = []
    source_rows: list[dict[str, object]] = []
    for carrier in carriers.itertuples():
        member_id = canonical_id(carrier.member_swsd_road_id)
        member = member_by_id.loc[member_id] if member_id in member_by_id.index else None
        realization = str(carrier.realization)
        if realization == "built":
            road_id = _unique_road_id(carrier, used_ids)
            geometry, smoothing = _smooth_centerline(
                carrier.geometry,
                spacing=config.smoothing_sample_spacing_m,
                max_deviation=config.smoothing_max_deviation_m,
            )
            source = config.output_source_built
            direction = 2
            geometry_source = str(getattr(carrier, "geometry_source", "hp_observed"))
            source_patch_ids = str(
                getattr(carrier, "source_patch_ids", "")
                or getattr(carrier, "source_patch_id", "")
            )
            patch_road_key = str(carrier.patch_road_key)
            source_patch_road_keys = str(
                getattr(carrier, "source_patch_road_keys", "") or patch_road_key
            )
            start_patch_road_keys = str(
                getattr(carrier, "start_patch_road_keys", "") or patch_road_key
            )
            end_patch_road_keys = str(
                getattr(carrier, "end_patch_road_keys", "") or patch_road_key
            )
            lane_ids = str(
                getattr(carrier, "source_lane_ids", "")
                or canonical_id(getattr(carrier, "center_lane_id", ""))
            )
        else:
            retained_geometry_source = str(
                getattr(carrier, "geometry_source", "swsd_retained_whole")
            )
            road_id = (
                _stable_int(
                    "retained-road-part",
                    getattr(carrier, "carrier_id", member_id),
                )
                if retained_geometry_source == "swsd_retained_partial"
                else _safe_int(member_id, "retained-road", member_id)
            )
            if road_id in used_ids:
                road_id = _stable_int("retained-road", member_id)
            geometry = carrier.geometry
            smoothing = "not_applicable_retained"
            source = int(_member_value(member, "source", config.output_source_retained) or config.output_source_retained)
            direction = int(_member_value(member, "direction", 1) or 1)
            geometry_source = retained_geometry_source
            source_patch_ids = str(_member_value(member, "patch_id", ""))
            patch_road_key = ""
            source_patch_road_keys = ""
            start_patch_road_keys = ""
            end_patch_road_keys = ""
            lane_ids = ""
        member_snodeid = canonical_id(_member_value(member, "snodeid", ""))
        member_enodeid = canonical_id(_member_value(member, "enodeid", ""))
        if realization == "built" and str(getattr(carrier, "carrier_role", "")) == "local_connector":
            source_snodeid = ""
            source_enodeid = ""
        elif realization == "built" and str(getattr(carrier, "direction_role", "")) == "reverse":
            source_snodeid = member_enodeid
            source_enodeid = member_snodeid
        else:
            source_snodeid = member_snodeid
            source_enodeid = member_enodeid
        if not bool(
            getattr(carrier, "inherit_source_snodeid", True)
        ):
            source_snodeid = ""
        if not bool(
            getattr(carrier, "inherit_source_enodeid", True)
        ):
            source_enodeid = ""
        used_ids.add(road_id)
        road = {
            "mapid": 0,
            "id": road_id,
            "width": float(_number(getattr(carrier, "median_lane_width_m", 0.0))),
            "direction": direction,
            "const_st": int(_member_value(member, "const_st", 0) or 0),
            "snodeid": 0,
            "enodeid": 0,
            "source_snodeid": source_snodeid,
            "source_enodeid": source_enodeid,
            "funcclass": int(_member_value(member, "roadtype", 0) or 0),
            "length": float(geometry.length),
            "lanenumsum": int(_number(getattr(carrier, "lane_count", 0))),
            "lanenums2e": int(_number(getattr(carrier, "lane_count", 0))) if direction == 2 else 0,
            "lanenume2s": 0,
            "roadtype": int(_member_value(member, "roadtype", 0) or 0),
            "roadclass": int(_member_value(member, "road_kind", 0) or 0),
            "ownership": 0,
            "patchid": source_patch_ids,
            "source": source,
            "city_code": "",
            "formway": int(_member_value(member, "formway", 0) or 0),
            "layer": 0,
            "source_road_id": source_patch_road_keys or member_id,
            "segment_id": str(carrier.segment_id),
            "segment_type": str(getattr(carrier, "segment_type", "normal")),
            "target_class": str(getattr(carrier, "target_class", "not_target")),
            "owner_type": "SEGMENT",
            "junction_group_id": "",
            "member_swsd_road_id": member_id,
            "carrier_id": _text(getattr(carrier, "carrier_id", "")),
            "carrier_role": str(getattr(carrier, "carrier_role", "semantic_carrier")),
            "direction_role": _text(
                getattr(carrier, "direction_role", "")
            ),
            "movement_parent_carrier_id": _text(
                getattr(carrier, "movement_parent_carrier_id", "")
            ),
            "realization": realization,
            "geometry_source": geometry_source,
            "source_patch_ids": source_patch_ids,
            "patch_road_key": patch_road_key,
            "source_patch_road_keys": source_patch_road_keys,
            "start_patch_road_keys": start_patch_road_keys,
            "end_patch_road_keys": end_patch_road_keys,
            "access_support_access_ids": _text(
                getattr(carrier, "access_support_access_ids", "")
            ),
            "constrained_completion_access_ids": _text(
                getattr(carrier, "constrained_completion_access_ids", "")
            ),
            "start_access_ids": _text(
                getattr(carrier, "start_access_ids", "")
            ),
            "end_access_ids": _text(
                getattr(carrier, "end_access_ids", "")
            ),
            "start_junction_group_ids": _text(
                getattr(carrier, "start_junction_group_ids", "")
            ),
            "end_junction_group_ids": _text(
                getattr(carrier, "end_junction_group_ids", "")
            ),
            "source_lane_ids": lane_ids,
            "observed_coverage_ratio": float(
                _number(getattr(carrier, "observed_coverage_ratio", 0.0))
            ),
            "internal_completion_fraction": float(
                _number(getattr(carrier, "internal_completion_fraction", 0.0))
            ),
            "surface_inferred_fraction": float(
                _number(getattr(carrier, "surface_inferred_fraction", 0.0))
            ),
            "assembly_state": str(getattr(carrier, "assembly_state", "")),
            "base_geometry_length_m": float(geometry.length),
            "review_required": str(getattr(carrier, "evidence_quality_state", "")) != "usable"
            if realization == "built"
            else False,
            "smoothing_state": smoothing,
            "run_id": config.run_id,
            "geometry": geometry,
        }
        rows.append(road)
        spans = _carrier_spans(carrier, geometry_source, patch_road_key or member_id)
        for span_index, span in enumerate(spans):
            start_fraction = float(span["start_fraction"])
            end_fraction = float(span["end_fraction"])
            span_geometry = substring(
                geometry,
                start_fraction * geometry.length,
                end_fraction * geometry.length,
            )
            source_rows.append(
                {
                    "run_id": config.run_id,
                    "road_id": road_id,
                    "segment_id": str(carrier.segment_id),
                    "source_span_id": f"{road_id}:{span_index}",
                    "geometry_source": str(span["geometry_source"]),
                    "source_object_ids": str(span["source_object_ids"]),
                    "start_fraction": start_fraction,
                    "end_fraction": end_fraction,
                    "length_m": float(span_geometry.length),
                    "geometry": span_geometry,
                }
            )
    roads = gpd.GeoDataFrame(rows, geometry="geometry", crs=carriers.crs)
    sources = gpd.GeoDataFrame(source_rows, geometry="geometry", crs=carriers.crs)
    summary = {
        "road_count": int(len(roads)),
        "built_road_count": int((roads["realization"] == "built").sum()),
        "retained_road_count": int((roads["realization"] == "retained").sum()),
        "center_lane_smoothed_count": int(roads["smoothing_state"].eq("smoothed_within_deviation_gate").sum()),
        "invalid_geometry_count": int((~roads.geometry.is_valid).sum()),
        "non_simple_geometry_count": int((~roads.geometry.is_simple).sum()),
        "built_swsd_splice_count": int(
            roads.loc[roads["realization"] == "built", "geometry_source"].str.contains("swsd", case=False).sum()
        ),
    }
    return RoadGeometryResult(roads, sources, summary)


def _smooth_centerline(
    geometry: LineString,
    *,
    spacing: float,
    max_deviation: float,
) -> tuple[LineString, str]:
    if geometry is None or geometry.is_empty or geometry.length < spacing * 5:
        return geometry, "too_short_for_smoothing"
    count = max(6, int(math.ceil(geometry.length / spacing)) + 1)
    distances = np.linspace(0.0, geometry.length, count)
    coords = np.array([[geometry.interpolate(value).x, geometry.interpolate(value).y] for value in distances])
    smoothed = coords.copy()
    for index in range(2, count - 2):
        smoothed[index] = np.average(coords[index - 2 : index + 3], axis=0, weights=[1, 2, 3, 2, 1])
    candidate = LineString(smoothed).simplify(0.10, preserve_topology=True)
    if not candidate.is_valid or not candidate.is_simple:
        return geometry.simplify(0.10, preserve_topology=True), "smoothing_rejected_invalid"
    sample_points = [candidate.interpolate(value, normalized=True) for value in np.linspace(0, 1, 21)]
    deviation = max(point.distance(geometry) for point in sample_points)
    if deviation > max_deviation:
        return geometry.simplify(0.10, preserve_topology=True), "smoothing_rejected_deviation"
    return candidate, "smoothed_within_deviation_gate"


def _member_value(member: pd.Series | None, field: str, default: object) -> object:
    if member is None or field not in member or pd.isna(member[field]):
        return default
    return member[field]


def _number(value: object, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    return float(value)


def _text(value: object) -> str:
    if value is None or bool(pd.isna(value)):
        return ""
    return str(value)


def _unique_road_id(carrier: object, used_ids: set[int]) -> int:
    realization = str(getattr(carrier, "realization", ""))
    if realization == "built":
        candidate = _stable_int(
            "segment-road",
            "|".join(
                [
                    str(getattr(carrier, "segment_id", "")),
                    str(getattr(carrier, "member_swsd_road_id", "")),
                    str(getattr(carrier, "carrier_role", "")),
                    str(getattr(carrier, "patch_road_key", ""))
                    if str(getattr(carrier, "carrier_role", "")) == "local_connector"
                    else "",
                ]
            ),
        )
    else:
        raw = canonical_id(getattr(carrier, "road_id", ""))
        candidate = _safe_int(raw, "retained-road", getattr(carrier, "member_swsd_road_id", raw))
    if candidate in used_ids:
        return _stable_int("segment-road-collision", getattr(carrier, "carrier_id", candidate))
    return candidate


def _carrier_spans(
    carrier: object,
    geometry_source: str,
    source_object_ids: str,
) -> list[dict[str, object]]:
    raw = str(getattr(carrier, "evidence_spans_json", "") or "")
    if raw:
        try:
            spans = json.loads(raw)
            if spans:
                return spans
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return [
        {
            "geometry_source": geometry_source,
            "source_object_ids": source_object_ids,
            "start_fraction": 0.0,
            "end_fraction": 1.0,
        }
    ]


def _safe_int(value: str, prefix: str, fallback: object) -> int:
    try:
        number = int(value)
        if 0 < number < 9_000_000_000_000_000_000:
            return number
    except ValueError:
        pass
    return _stable_int(prefix, fallback)


def _stable_int(prefix: str, value: object) -> int:
    digest = hashlib.sha1(f"{prefix}|{value}".encode("utf-8")).hexdigest()
    return 7_000_000_000_000_000 + int(digest[:13], 16) % 999_999_999_999_999


__all__ = ["RoadGeometryResult", "materialize_road_geometry"]
