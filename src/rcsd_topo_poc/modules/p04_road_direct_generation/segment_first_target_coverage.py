from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pandas as pd

from .segment_first_skeleton import canonical_id, parse_id_list
from .segment_first_target_disposition import apply_target_disposition_contract


@dataclass(frozen=True)
class TargetCoverageResult:
    segments: gpd.GeoDataFrame
    anchors: gpd.GeoDataFrame
    summary: dict[str, object]


def build_target_coverage_contract(
    segment_units: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    t06_replaceability: pd.DataFrame,
    *,
    patch_ids: Iterable[str],
    target_disposition_path: Path | None = None,
    run_id: str,
) -> TargetCoverageResult:
    patch_set = {canonical_id(value) for value in patch_ids if canonical_id(value)}
    contract_enabled = not t06_replaceability.empty
    replaceability = _replaceability_by_segment(t06_replaceability)
    road_frame = swsd_roads.copy()
    road_frame["canonical_road_id"] = road_frame["id"].map(canonical_id)
    road_by_id = road_frame.drop_duplicates("canonical_road_id").set_index(
        "canonical_road_id"
    )

    rows: list[dict[str, object]] = []
    anchor_rows: list[dict[str, object]] = []
    for segment in segment_units.itertuples():
        segment_id = canonical_id(segment.segment_id)
        segment_type = str(
            getattr(segment, "segment_type", "normal") or "normal"
        ).strip().lower()
        member_ids = parse_id_list(getattr(segment, "swsd_road_ids", ""))
        endpoint_ids = parse_id_list(getattr(segment, "pair_node_ids", ""))
        endpoint_source = "segment_pair_nodes"
        if segment_type == "advance_right" and len(endpoint_ids) < 2:
            endpoint_ids = _single_member_endpoints(member_ids, road_by_id)
            endpoint_source = "single_member_road_endpoints"
        endpoint_memberships = [
            _endpoint_patch_membership(node_id, member_ids, road_by_id)
            for node_id in endpoint_ids[:2]
        ]
        memberships_complete = (
            len(endpoint_memberships) == 2
            and all(bool(values) for values in endpoint_memberships)
        )
        closed_patch = memberships_complete and all(
            values.issubset(patch_set) for values in endpoint_memberships
        )
        touches_patch = memberships_complete and all(
            bool(values.intersection(patch_set)) for values in endpoint_memberships
        )
        boundary_review = touches_patch and not closed_patch
        baseline = replaceability.get(segment_id, {})
        t06_replaceable = bool(baseline.get("t06_replaceable", False))

        target_class, target_required, target_reason = _classify_target(
            contract_enabled=contract_enabled,
            segment_type=segment_type,
            t06_replaceable=t06_replaceable,
            memberships_complete=memberships_complete,
            closed_patch=closed_patch,
            boundary_review=boundary_review,
        )
        rows.append(
            {
                **segment._asdict(),
                "run_id": run_id,
                "segment_id": segment_id,
                "target_class": target_class,
                "target_required": target_required,
                "target_reason": target_reason,
                "target_endpoint_source": endpoint_source,
                "endpoint_patch_membership_complete": memberships_complete,
                "closed_patch": closed_patch,
                "endpoint_0_patch_ids": _membership_text(endpoint_memberships, 0),
                "endpoint_1_patch_ids": _membership_text(endpoint_memberships, 1),
                "t06_replaceable": t06_replaceable,
                "t06_rcsd_road_ids": str(baseline.get("t06_rcsd_road_ids", "")),
                "t06_excluded_advance_right_road_ids": str(
                    baseline.get("t06_excluded_advance_right_road_ids", "")
                ),
                "geometry": segment.geometry,
            }
        )
        anchor_geometry = baseline.get("anchor_geometry")
        if (
            target_required
            and target_class == "core_trunk"
            and anchor_geometry is not None
            and not anchor_geometry.is_empty
        ):
            anchor_rows.append(
                {
                    "run_id": run_id,
                    "segment_id": segment_id,
                    "target_class": target_class,
                    "anchor_source": "t06_replaceability_geometry",
                    "geometry": anchor_geometry,
                }
            )

    result = gpd.GeoDataFrame(rows, geometry="geometry", crs=segment_units.crs)
    anchor_crs = (
        t06_replaceability.crs
        if isinstance(t06_replaceability, gpd.GeoDataFrame)
        else segment_units.crs
    )
    anchors = (
        gpd.GeoDataFrame(anchor_rows, geometry="geometry", crs=anchor_crs)
        if anchor_rows
        else gpd.GeoDataFrame(
            {
                "run_id": pd.Series(dtype=str),
                "segment_id": pd.Series(dtype=str),
                "target_class": pd.Series(dtype=str),
                "anchor_source": pd.Series(dtype=str),
                "geometry": gpd.GeoSeries([], crs=anchor_crs),
            },
            geometry="geometry",
            crs=anchor_crs,
        )
    )
    counts = result["target_class"].value_counts() if not result.empty else pd.Series(dtype=int)
    summary = {
        "contract_enabled": contract_enabled,
        "segment_count": int(len(result)),
        "core_target_count": int(counts.get("core_trunk", 0)),
        "advance_right_target_count": int(counts.get("advance_right", 0)),
        "anchor_segment_count": int(
            anchors["segment_id"].nunique() if not anchors.empty else 0
        ),
        "boundary_review_count": int(counts.get("boundary_review", 0)),
        "not_target_count": int(counts.get("not_target", 0)),
    }
    result, summary = apply_target_disposition_contract(
        result.reset_index(drop=True),
        summary,
        target_disposition_path,
        run_id=run_id,
    )
    return TargetCoverageResult(
        result,
        anchors.reset_index(drop=True),
        summary,
    )


def _replaceability_by_segment(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    if frame.empty:
        return {}
    required = {"swsd_segment_id", "replacement_ready", "hard_filter_passed"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            "t06_replaceability missing required columns: " + ", ".join(missing)
        )
    result: dict[str, dict[str, object]] = {}
    for row in frame.itertuples(index=False):
        segment_id = canonical_id(getattr(row, "swsd_segment_id"))
        if not segment_id:
            continue
        ready = _truthy(getattr(row, "replacement_ready")) and _truthy(
            getattr(row, "hard_filter_passed")
        )
        result[segment_id] = {
            "t06_replaceable": ready,
            "t06_rcsd_road_ids": ",".join(
                parse_id_list(getattr(row, "rcsd_road_ids", ""))
            ),
            "t06_excluded_advance_right_road_ids": ",".join(
                parse_id_list(
                    getattr(row, "excluded_advance_right_turn_road_ids", "")
                )
            ),
            "anchor_geometry": getattr(row, "geometry", None),
        }
    return result


def _endpoint_patch_membership(
    node_id: str,
    member_ids: tuple[str, ...],
    road_by_id: gpd.GeoDataFrame,
) -> set[str]:
    membership: set[str] = set()
    for member_id in member_ids:
        if member_id not in road_by_id.index:
            continue
        road = road_by_id.loc[member_id]
        if node_id not in {
            canonical_id(road.get("snodeid")),
            canonical_id(road.get("enodeid")),
        }:
            continue
        membership.update(parse_id_list(road.get("patch_id")))
    return membership


def _single_member_endpoints(
    member_ids: tuple[str, ...],
    road_by_id: gpd.GeoDataFrame,
) -> tuple[str, ...]:
    if len(member_ids) != 1 or member_ids[0] not in road_by_id.index:
        return ()
    road = road_by_id.loc[member_ids[0]]
    endpoints = (
        canonical_id(road.get("snodeid")),
        canonical_id(road.get("enodeid")),
    )
    return endpoints if all(endpoints) else ()


def _classify_target(
    *,
    contract_enabled: bool,
    segment_type: str,
    t06_replaceable: bool,
    memberships_complete: bool,
    closed_patch: bool,
    boundary_review: bool,
) -> tuple[str, bool, str]:
    if not contract_enabled:
        return "not_target", False, "target_contract_disabled"
    if not memberships_complete:
        return "not_target", False, "endpoint_patch_membership_missing"
    if boundary_review and (t06_replaceable or segment_type == "advance_right"):
        return "boundary_review", False, "endpoint_patch_membership_open_boundary"
    if segment_type == "advance_right" and closed_patch:
        return "advance_right", True, "advance_right_closed_patch_target"
    if t06_replaceable and closed_patch:
        return "core_trunk", True, "t06_replaceable_closed_patch_target"
    return "not_target", False, "t06_not_replaceable"


def _membership_text(memberships: list[set[str]], index: int) -> str:
    if index >= len(memberships):
        return ""
    return ",".join(sorted(memberships[index]))


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


__all__ = ["TargetCoverageResult", "build_target_coverage_contract"]
