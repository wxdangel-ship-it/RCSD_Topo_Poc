from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from threading import RLock
import time
from typing import Mapping
import weakref

import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry

from .segment_first_carrier_context import (
    carrier_context_cache_stats,
    reset_carrier_context_cache,
)
from .segment_first_carriers import (
    CarrierPlanResult,
    plan_segment_carriers as _plan_all_segment_carriers,
)
from .segment_first_progress import (
    begin_progress_stage,
    finish_progress_stage,
)


_COUNTER_KEYS = (
    "forced_retained_segment_count",
    "insufficient_member_count",
    "assembled_patch_source_count",
    "published_local_connector_count",
    "suppressed_local_connector_count",
    "forced_suppressed_local_connector_count",
    "target_fragment_takeover_count",
    "member_surface_inference_takeover_count",
    "baseline_recovery_takeover_count",
    "access_surface_recovery_takeover_count",
    "endpoint_surface_scoped_segment_count",
    "access_support_carrier_count",
    "partial_member_takeover_count",
)


@dataclass
class _PlannerState:
    static_token: tuple[object, ...]
    fingerprints: dict[str, tuple[object, ...]]
    result: CarrierPlanResult


_LOCK = RLock()
_STATE: _PlannerState | None = None
_GROUP_TOKEN_CACHE: dict[
    tuple[int, str],
    tuple[
        weakref.ReferenceType[pd.DataFrame],
        int,
        dict[str, bytes],
    ],
] = {}
_RECOVERY_TOKEN_CACHE: dict[
    int,
    tuple[weakref.ReferenceType[pd.DataFrame], int, bytes],
] = {}
_STATS = {
    "invocation_count": 0,
    "full_recompute_invocation_count": 0,
    "incremental_recompute_invocation_count": 0,
    "no_change_invocation_count": 0,
    "segment_units_seen": 0,
    "segment_units_recomputed": 0,
    "segment_units_reused": 0,
    "fingerprint_seconds": 0.0,
    "merge_seconds": 0.0,
    "fingerprint_cache_hit_count": 0,
    "fingerprint_cache_miss_count": 0,
}


def plan_segment_carriers_incremental(
    segment_units: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    assignments: gpd.GeoDataFrame,
    *,
    run_id: str,
    explicit_pairs: pd.DataFrame | None = None,
    drivezones: gpd.GeoDataFrame | None = None,
    target_reference_axes: gpd.GeoDataFrame | None = None,
    required_endpoint_surfaces: gpd.GeoDataFrame | None = None,
    endpoint_surface_segment_ids: set[str] | None = None,
    required_through_surfaces: gpd.GeoDataFrame | None = None,
    forced_through_access_ids: set[str] | None = None,
    through_surface_max_distance_m: float = 20.0,
    minimum_member_coverage: float = 0.60,
    sample_spacing_m: float = 2.0,
    completion_min_coverage: float = 0.90,
    maximum_target_main_angle_deg: float = 35.0,
    forced_retained_segment_ids: set[str] | None = None,
    forced_suppressed_local_connector_keys: set[str] | None = None,
    directional_member_roles: dict[tuple[str, str, str], str] | None = None,
) -> CarrierPlanResult:
    """Recompute only Segment plans whose complete planning inputs changed."""

    global _STATE
    started = time.perf_counter()
    segment_ids = tuple(segment_units["segment_id"].astype(str))
    static_token = _static_token(
        segment_units,
        swsd_roads,
        explicit_pairs,
        drivezones,
        required_endpoint_surfaces,
        directional_member_roles,
        run_id=run_id,
        through_surface_max_distance_m=through_surface_max_distance_m,
        minimum_member_coverage=minimum_member_coverage,
        sample_spacing_m=sample_spacing_m,
        completion_min_coverage=completion_min_coverage,
        maximum_target_main_angle_deg=maximum_target_main_angle_deg,
    )
    fingerprints = _segment_fingerprints(
        segment_units,
        assignments,
        target_reference_axes,
        required_through_surfaces,
        endpoint_surface_segment_ids or set(),
        forced_through_access_ids or set(),
        forced_retained_segment_ids or set(),
        forced_suppressed_local_connector_keys or set(),
    )
    with _LOCK:
        previous = _STATE
    full_recompute = previous is None or previous.static_token != static_token
    dirty_ids = (
        set(segment_ids)
        if full_recompute
        else {
            segment_id
            for segment_id in segment_ids
            if previous.fingerprints.get(segment_id)
            != fingerprints.get(segment_id)
        }
    )
    fingerprint_seconds = time.perf_counter() - started
    begin_progress_stage(
        "segment_carrier_change_detection",
        len(segment_ids),
        detail="exact per-Segment planning input fingerprint",
    )
    finish_progress_stage(
        "segment_carrier_change_detection",
        counters={
            "dirty_segments": len(dirty_ids),
            "reused_segments": len(segment_ids) - len(dirty_ids),
            "full_recompute": str(full_recompute).lower(),
        },
    )

    common = {
        "run_id": run_id,
        "explicit_pairs": explicit_pairs,
        "drivezones": drivezones,
        "target_reference_axes": target_reference_axes,
        "required_endpoint_surfaces": required_endpoint_surfaces,
        "endpoint_surface_segment_ids": endpoint_surface_segment_ids,
        "required_through_surfaces": required_through_surfaces,
        "forced_through_access_ids": forced_through_access_ids,
        "through_surface_max_distance_m": through_surface_max_distance_m,
        "minimum_member_coverage": minimum_member_coverage,
        "sample_spacing_m": sample_spacing_m,
        "completion_min_coverage": completion_min_coverage,
        "maximum_target_main_angle_deg": maximum_target_main_angle_deg,
        "forced_retained_segment_ids": forced_retained_segment_ids,
        "forced_suppressed_local_connector_keys": (
            forced_suppressed_local_connector_keys
        ),
        "directional_member_roles": directional_member_roles,
    }
    merge_seconds = 0.0
    if full_recompute:
        result = _plan_all_segment_carriers(
            segment_units,
            swsd_roads,
            assignments,
            **common,
        )
    elif not dirty_ids:
        result = previous.result
    else:
        dirty_units = segment_units[
            segment_units["segment_id"].astype(str).isin(dirty_ids)
        ].copy()
        replacement = _plan_all_segment_carriers(
            dirty_units,
            swsd_roads,
            assignments,
            **common,
        )
        merge_started = time.perf_counter()
        result = _merge_results(
            previous.result,
            replacement,
            segment_ids,
            dirty_ids,
        )
        merge_seconds = time.perf_counter() - merge_started

    with _LOCK:
        _STATE = _PlannerState(static_token, fingerprints, result)
        _STATS["invocation_count"] += 1
        _STATS["segment_units_seen"] += len(segment_ids)
        _STATS["segment_units_recomputed"] += len(dirty_ids)
        _STATS["segment_units_reused"] += len(segment_ids) - len(dirty_ids)
        _STATS["fingerprint_seconds"] += fingerprint_seconds
        _STATS["merge_seconds"] += merge_seconds
        if full_recompute:
            _STATS["full_recompute_invocation_count"] += 1
        elif dirty_ids:
            _STATS["incremental_recompute_invocation_count"] += 1
        else:
            _STATS["no_change_invocation_count"] += 1
    return result


def incremental_carrier_planner_stats() -> dict[str, int | float]:
    with _LOCK:
        stats = dict(_STATS)
    seen = int(stats["segment_units_seen"])
    reused = int(stats["segment_units_reused"])
    stats["segment_reuse_ratio"] = reused / seen if seen else 0.0
    stats.update(carrier_context_cache_stats())
    return stats


def reset_incremental_carrier_planner() -> None:
    with _LOCK:
        global _STATE
        _STATE = None
        _GROUP_TOKEN_CACHE.clear()
        _RECOVERY_TOKEN_CACHE.clear()
        reset_carrier_context_cache()
        for key in _STATS:
            _STATS[key] = 0.0 if key.endswith("_seconds") else 0


def _static_token(
    segment_units: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    explicit_pairs: pd.DataFrame | None,
    drivezones: gpd.GeoDataFrame | None,
    required_endpoint_surfaces: gpd.GeoDataFrame | None,
    directional_member_roles: Mapping[tuple[str, str, str], str] | None,
    **scalars: object,
) -> tuple[object, ...]:
    roles = tuple(sorted((key, str(value)) for key, value in (directional_member_roles or {}).items()))
    return (
        _object_identity(segment_units),
        _object_identity(swsd_roads),
        _object_identity(explicit_pairs),
        _object_identity(drivezones),
        _object_identity(required_endpoint_surfaces),
        roles,
        tuple(sorted(scalars.items())),
    )


def _object_identity(value: object | None) -> tuple[int, int]:
    return id(value), len(value) if value is not None else 0


def _segment_fingerprints(
    segment_units: gpd.GeoDataFrame,
    assignments: gpd.GeoDataFrame,
    target_reference_axes: gpd.GeoDataFrame | None,
    required_through_surfaces: gpd.GeoDataFrame | None,
    endpoint_surface_segment_ids: set[str],
    forced_through_access_ids: set[str],
    forced_retained_segment_ids: set[str],
    forced_suppressed_local_connector_keys: set[str],
) -> dict[str, tuple[object, ...]]:
    assignment_tokens = _group_tokens(assignments, "assigned_segment_id")
    reference_tokens = _group_tokens(target_reference_axes, "segment_id")
    through_surface_tokens = _group_tokens(
        required_through_surfaces,
        "segment_id",
    )
    target_core_ids = set(
        segment_units.loc[
            segment_units.get(
                "target_required",
                pd.Series(False, index=segment_units.index),
            )
            .fillna(False)
            .astype(bool)
            & segment_units.get(
                "target_class",
                pd.Series("", index=segment_units.index),
            )
            .fillna("")
            .astype(str)
            .eq("core_trunk"),
            "segment_id",
        ].astype(str)
    )
    recovery_token = _recovery_token(assignments)
    through_by_segment, unknown_through = _through_accesses_by_segment(
        required_through_surfaces,
        forced_through_access_ids,
    )
    suppressed_by_segment, unknown_suppressed = _suppressed_keys_by_segment(
        assignments,
        forced_suppressed_local_connector_keys,
    )
    result: dict[str, tuple[object, ...]] = {}
    for row in segment_units.itertuples(index=False):
        segment_id = str(row.segment_id)
        result[segment_id] = (
            assignment_tokens.get(segment_id, b""),
            reference_tokens.get(segment_id, b""),
            recovery_token if segment_id in target_core_ids else b"",
            segment_id in endpoint_surface_segment_ids,
            segment_id in forced_retained_segment_ids,
            through_surface_tokens.get(segment_id, b""),
            through_by_segment.get(segment_id, ()),
            unknown_through if segment_id in target_core_ids else (),
            suppressed_by_segment.get(segment_id, ()),
            unknown_suppressed,
        )
    return result


def _through_accesses_by_segment(
    surfaces: gpd.GeoDataFrame | None,
    forced_access_ids: set[str],
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    if not forced_access_ids:
        return {}, ()
    access_to_segment = {}
    if surfaces is not None and not surfaces.empty:
        access_to_segment = {
            str(access_id): str(segment_id)
            for access_id, segment_id in zip(
                surfaces.get("access_id", pd.Series("", index=surfaces.index)),
                surfaces.get("segment_id", pd.Series("", index=surfaces.index)),
            )
        }
    grouped: dict[str, list[str]] = {}
    unknown: list[str] = []
    for access_id in sorted(map(str, forced_access_ids)):
        segment_id = access_to_segment.get(access_id, "")
        if segment_id:
            grouped.setdefault(segment_id, []).append(access_id)
        else:
            unknown.append(access_id)
    return {key: tuple(values) for key, values in grouped.items()}, tuple(unknown)


def _suppressed_keys_by_segment(
    assignments: gpd.GeoDataFrame,
    suppressed_keys: set[str],
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    if not suppressed_keys or assignments.empty:
        return {}, tuple(sorted(map(str, suppressed_keys)))
    key_to_segments: dict[str, set[str]] = {}
    for patch_key, segment_id in zip(
        assignments.get("patch_road_key", pd.Series("", index=assignments.index)),
        assignments.get(
            "assigned_segment_id",
            pd.Series("", index=assignments.index),
        ),
    ):
        key_to_segments.setdefault(str(patch_key), set()).add(str(segment_id))
    grouped: dict[str, list[str]] = {}
    unknown: list[str] = []
    for patch_key in sorted(map(str, suppressed_keys)):
        segment_ids = {value for value in key_to_segments.get(patch_key, set()) if value}
        if not segment_ids:
            unknown.append(patch_key)
            continue
        for segment_id in segment_ids:
            grouped.setdefault(segment_id, []).append(patch_key)
    return {key: tuple(values) for key, values in grouped.items()}, tuple(unknown)


def _group_tokens(
    frame: pd.DataFrame | None,
    group_column: str,
) -> dict[str, bytes]:
    if frame is None or frame.empty or group_column not in frame:
        return {}
    key = (id(frame), group_column)
    cached = _GROUP_TOKEN_CACHE.get(key)
    if (
        cached is not None
        and cached[0]() is frame
        and cached[1] == id(frame._mgr)
    ):
        _record_fingerprint_cache(True)
        return cached[2]
    columns = tuple(frame.columns)
    group_index = columns.index(group_column)
    digests: dict[str, object] = {}
    for row in frame.itertuples(index=False, name=None):
        group = str(row[group_index])
        digest = digests.setdefault(group, hashlib.blake2b(digest_size=16))
        for value in row:
            payload = _value_bytes(value)
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
    result = {group: digest.digest() for group, digest in digests.items()}

    def remove(_: weakref.ReferenceType[pd.DataFrame]) -> None:
        current = _GROUP_TOKEN_CACHE.get(key)
        if current is not None and current[0]() is None:
            _GROUP_TOKEN_CACHE.pop(key, None)

    _GROUP_TOKEN_CACHE[key] = (
        weakref.ref(frame, remove),
        id(frame._mgr),
        result,
    )
    _record_fingerprint_cache(False)
    return result


def _recovery_token(assignments: gpd.GeoDataFrame) -> bytes:
    key = id(assignments)
    cached = _RECOVERY_TOKEN_CACHE.get(key)
    if (
        cached is not None
        and cached[0]() is assignments
        and cached[1] == id(assignments._mgr)
    ):
        _record_fingerprint_cache(True)
        return cached[2]
    recovery = assignments[
        assignments.get(
            "assignment_source",
            pd.Series("", index=assignments.index),
        )
        .fillna("")
        .astype(str)
        .isin(
            {
                "target_baseline_recovery_candidate",
                "target_access_surface_candidate",
            }
        )
    ] if not assignments.empty else assignments
    result = _frame_token(recovery)

    def remove(_: weakref.ReferenceType[pd.DataFrame]) -> None:
        current = _RECOVERY_TOKEN_CACHE.get(key)
        if current is not None and current[0]() is None:
            _RECOVERY_TOKEN_CACHE.pop(key, None)

    _RECOVERY_TOKEN_CACHE[key] = (
        weakref.ref(assignments, remove),
        id(assignments._mgr),
        result,
    )
    _record_fingerprint_cache(False)
    return result


def _record_fingerprint_cache(hit: bool) -> None:
    key = (
        "fingerprint_cache_hit_count"
        if hit
        else "fingerprint_cache_miss_count"
    )
    with _LOCK:
        _STATS[key] += 1


def _frame_token(frame: pd.DataFrame | None) -> bytes:
    if frame is None or frame.empty:
        return b""
    digest = hashlib.blake2b(digest_size=16)
    for row in frame.itertuples(index=False, name=None):
        for value in row:
            payload = _value_bytes(value)
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
    return digest.digest()


def _value_bytes(value: object) -> bytes:
    if value is None:
        return b"<none>"
    if isinstance(value, BaseGeometry):
        return b"<geometry>" + bytes(value.wkb)
    if isinstance(value, float):
        if math.isnan(value):
            return b"<nan>"
        return f"float:{value!r}".encode("utf-8")
    if isinstance(value, (str, int, bool, bytes)):
        return f"{type(value).__name__}:{value!r}".encode("utf-8")
    if value is pd.NA or value is pd.NaT:
        return b"<missing>"
    try:
        wkb = value.wkb
    except (AttributeError, TypeError, ValueError):
        wkb = None
    if wkb is not None:
        return b"<geometry>" + bytes(wkb)
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, bool) and missing:
        return b"<missing>"
    return f"{type(value).__name__}:{value!r}".encode("utf-8")


def _merge_results(
    previous: CarrierPlanResult,
    replacement: CarrierPlanResult,
    segment_ids: tuple[str, ...],
    dirty_ids: set[str],
) -> CarrierPlanResult:
    plans = _merge_frame(
        previous.segment_plans,
        replacement.segment_plans,
        segment_ids,
        dirty_ids,
    )
    column_orders = dict(previous.segment_carrier_column_orders)
    column_orders.update(replacement.segment_carrier_column_orders)
    carriers = _merge_frame(
        previous.carriers,
        replacement.carriers,
        segment_ids,
        dirty_ids,
        column_orders=column_orders,
    )
    contributions = dict(previous.segment_summary_contributions)
    contributions.update(replacement.segment_summary_contributions)
    summary = {
        "segment_count": int(len(plans)),
        "state_counts": plans["segment_state"].value_counts().to_dict(),
        "built_carrier_count": int(carriers["realization"].eq("built").sum()),
        "retained_carrier_count": int(carriers["realization"].eq("retained").sum()),
    }
    summary.update(
        {
            key: int(
                sum(values.get(key, 0) for values in contributions.values())
            )
            for key in _COUNTER_KEYS
        }
    )
    return CarrierPlanResult(
        plans,
        carriers,
        summary,
        contributions,
        column_orders,
    )


def _merge_frame(
    previous: gpd.GeoDataFrame,
    replacement: gpd.GeoDataFrame,
    segment_ids: tuple[str, ...],
    dirty_ids: set[str],
    *,
    column_orders: Mapping[str, tuple[str, ...]] | None = None,
) -> gpd.GeoDataFrame:
    kept = previous[~previous["segment_id"].astype(str).isin(dirty_ids)].copy()
    frames = [frame for frame in (kept, replacement) if not frame.empty]
    if not frames:
        return previous.iloc[0:0].copy()
    merged = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True, sort=False),
        geometry="geometry",
        crs=previous.crs,
    )
    if column_orders is not None:
        ordered_columns = tuple(
            dict.fromkeys(
                column
                for segment_id in segment_ids
                for column in column_orders.get(segment_id, ())
            )
        )
        merged = merged[
            [column for column in ordered_columns if column in merged]
        ]
    order = {segment_id: index for index, segment_id in enumerate(segment_ids)}
    merged["_segment_order"] = merged["segment_id"].astype(str).map(order)
    merged["_row_order"] = range(len(merged))
    merged = merged.sort_values(
        ["_segment_order", "_row_order"],
        kind="stable",
    ).drop(columns=["_segment_order", "_row_order"])
    return merged.reset_index(drop=True)


__all__ = [
    "incremental_carrier_planner_stats",
    "plan_segment_carriers_incremental",
    "reset_incremental_carrier_planner",
]
