from __future__ import annotations

from dataclasses import dataclass
import math

import geopandas as gpd
import numpy as np
import pandas as pd

from .segment_first_config import SegmentFirstConfig
from .segment_first_geometry_metrics import max_sample_turn as _max_sample_turn


@dataclass(frozen=True)
class GeometryQualityResult:
    audit: gpd.GeoDataFrame
    fallback_segment_ids: set[str]
    summary: dict[str, object]


def audit_built_road_geometry(
    roads: gpd.GeoDataFrame,
    patch_road_centers: gpd.GeoDataFrame,
    completion_sources: gpd.GeoDataFrame,
    *,
    config: SegmentFirstConfig,
) -> GeometryQualityResult:
    source_by_key = patch_road_centers.drop_duplicates("patch_road_key").set_index(
        "patch_road_key"
    )
    completion_length_by_road = (
        completion_sources.groupby("road_id")["length_m"].sum().to_dict()
        if not completion_sources.empty
        else {}
    )
    rows: list[dict[str, object]] = []
    fallback_segments: set[str] = set()
    carrier_roles = roads.get(
        "carrier_role",
        pd.Series("", index=roads.index, dtype=str),
    )
    segment_built_roads = roads[
        roads["realization"].eq("built")
        & ~carrier_roles.eq("junction_surface_carrier")
    ]
    for road in segment_built_roads.itertuples():
        source_keys = _split_keys(
            getattr(road, "source_patch_road_keys", "")
            or getattr(road, "patch_road_key", "")
        )
        source_geometries = [
            source_by_key.loc[key].geometry for key in source_keys if key in source_by_key.index
        ]
        if not source_geometries:
            source_geometries = [source_by_key.loc[str(road.patch_road_key)].geometry]
        source = gpd.GeoSeries(source_geometries, crs=roads.crs).union_all()
        final_turn = _max_sample_turn(road.geometry, 2.0)
        source_turn = max(_max_sample_turn(value, 2.0) for value in source_geometries)
        base_length = float(
            getattr(road, "base_geometry_length_m", 0.0) or road.geometry.length
        )
        length_ratio = float(road.geometry.length / base_length) if base_length else math.inf
        hausdorff = _directed_sample_distance(road.geometry, source)
        completion_length = float(completion_length_by_road.get(road.id, 0.0)) + (
            float(getattr(road, "internal_completion_fraction", 0.0) or 0.0)
            * base_length
        )
        surface_inferred_fraction = min(
            1.0,
            max(0.0, float(getattr(road, "surface_inferred_fraction", 0.0) or 0.0)),
        )
        observed_fraction = max(
            0.0,
            1.0
            - completion_length / road.geometry.length
            - surface_inferred_fraction,
        ) if road.geometry.length else 0.0
        turn_failure = (
            final_turn > config.completion_hard_max_turn_deg
            and source_turn < config.completion_source_turn_exemption_deg
        )
        observed_missing = observed_fraction + surface_inferred_fraction <= 1e-6
        hard_failure = turn_failure or observed_missing
        review_required = (
            not hard_failure
            and (
                final_turn > config.completion_review_turn_deg
                or length_ratio > config.completion_review_length_ratio
                or hausdorff > config.completion_review_hausdorff_m
            )
        )
        if hard_failure:
            fallback_segments.add(str(road.segment_id))
        reason = (
            "built_road_without_observed_span"
            if observed_missing
            else "completion_turn_conflict"
            if turn_failure
            else "completion_geometry_review"
            if review_required
            else "geometry_gate_pass"
        )
        rows.append(
            {
                "run_id": config.run_id,
                "road_id": road.id,
                "segment_id": str(road.segment_id),
                "patch_road_key": ",".join(source_keys),
                "source_max_turn_deg": source_turn,
                "final_max_turn_deg": final_turn,
                "introduced_turn_deg": final_turn - source_turn,
                "length_ratio": length_ratio,
                "hausdorff_m": hausdorff,
                "observed_fraction": observed_fraction,
                "surface_inferred_fraction": surface_inferred_fraction,
                "completion_fraction": max(
                    0.0,
                    1.0 - observed_fraction - surface_inferred_fraction,
                ),
                "hard_failure": hard_failure,
                "review_required": review_required,
                "reason_codes": reason,
                "geometry": road.geometry,
            }
        )
    audit = gpd.GeoDataFrame(rows, geometry="geometry", crs=roads.crs)
    summary = {
        "built_road_count": int(len(audit)),
        "hard_failure_count": int(audit["hard_failure"].sum()) if not audit.empty else 0,
        "review_required_count": int(audit["review_required"].sum()) if not audit.empty else 0,
        "max_final_turn_deg": float(audit["final_max_turn_deg"].max()) if not audit.empty else 0.0,
        "max_length_ratio": float(audit["length_ratio"].max()) if not audit.empty else 0.0,
        "max_hausdorff_m": float(audit["hausdorff_m"].max()) if not audit.empty else 0.0,
        "fallback_segment_count": int(len(fallback_segments)),
    }
    return GeometryQualityResult(audit, fallback_segments, summary)


def apply_review_flags(
    roads: gpd.GeoDataFrame,
    endpoint_audit: gpd.GeoDataFrame,
    geometry_quality: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Propagate soft endpoint and geometry findings to formal Road output."""

    flagged: set[str] = set()
    for audit in (endpoint_audit, geometry_quality):
        if audit.empty or "road_id" not in audit or "review_required" not in audit:
            continue
        flagged.update(
            audit.loc[
                audit["review_required"].fillna(False).astype(bool),
                "road_id",
            ].astype(str)
        )
    result = roads.copy()
    existing = result.get(
        "review_required",
        pd.Series(False, index=result.index, dtype=bool),
    ).fillna(False).astype(bool)
    result["review_required"] = existing | result["id"].astype(str).isin(flagged)
    return result


def _directed_sample_distance(geometry: object, source: object) -> float:
    if geometry is None or geometry.is_empty or source is None or source.is_empty:
        return math.inf
    count = max(3, int(math.ceil(float(geometry.length) / 2.0)) + 1)
    return max(
        float(geometry.interpolate(distance).distance(source))
        for distance in np.linspace(0.0, float(geometry.length), count)
    )


def _split_keys(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


__all__ = [
    "GeometryQualityResult",
    "apply_review_flags",
    "audit_built_road_geometry",
]
