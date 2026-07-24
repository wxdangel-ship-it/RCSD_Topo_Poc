from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import pandas as pd

from .geometry import canonical_id


@dataclass(frozen=True)
class ComparisonResult:
    old_roads: gpd.GeoDataFrame
    fragmentation: pd.DataFrame
    summary: dict[str, Any]


def compare_old_road_groups(
    decisions: gpd.GeoDataFrame,
    old_roads: gpd.GeoDataFrame,
    *,
    run_id: str,
) -> ComparisonResult:
    roads = old_roads.copy()
    roads["old_road_id"] = roads["Id"].map(canonical_id)
    grouped_records: list[dict[str, Any]] = []
    for old_road_id, group in decisions.groupby("old_road_id", dropna=False):
        supported = group[
            group["owner_state"].isin(["accepted", "review_required"])
            & group["swsd_unit_id"].notna()
        ]
        accepted = group[group["decision"] == "accepted"]
        owner_ids = sorted(supported["swsd_unit_id"].dropna().astype(str).unique())
        if not owner_ids:
            state = "no_supported_owner"
        elif len(owner_ids) == 1:
            state = "single_swsd_owner"
        else:
            state = "mixed_swsd_owner"
        grouped_records.append(
            {
                "old_road_id": old_road_id,
                "lane_count": len(group),
                "accepted_lane_count": len(accepted),
                "review_lane_count": int((group["decision"] == "review_required").sum()),
                "insufficient_lane_count": int((group["decision"] == "insufficient_evidence").sum()),
                "swsd_owner_ids": ",".join(owner_ids),
                "swsd_owner_count": len(owner_ids),
                "comparison_state": state,
            }
        )
    grouped = pd.DataFrame(grouped_records)
    roads = roads.merge(grouped, on="old_road_id", how="left")
    roads["run_id"] = run_id
    roads["source_patch_ids"] = roads["patch_id"]
    roads["source_object_type"] = "OldPatchRoad"
    roads["source_object_ids"] = roads["old_road_id"]
    roads["swsd_unit_id"] = roads["swsd_owner_ids"]
    roads["decision"] = roads["comparison_state"].fillna("no_lane_member")
    roads["reason_codes"] = "old_lane_group_comparison"
    roads["evidence_state"] = "comparison_only"
    roads["input_manifest_ref"] = "p04_input_manifest.json"
    roads["comparison_channel"] = "old_road_read_only"

    accepted = decisions[(decisions["decision"] == "accepted") & decisions["swsd_unit_id"].notna()]
    fragmentation_records: list[dict[str, Any]] = []
    for swsd_unit_id, group in accepted.groupby("swsd_unit_id"):
        old_ids = sorted(group["old_road_id"].dropna().astype(str).unique())
        fragmentation_records.append(
            {
                "run_id": run_id,
                "swsd_unit_id": swsd_unit_id,
                "accepted_lane_count": len(group),
                "old_road_ids": ",".join(old_ids),
                "old_road_count": len(old_ids),
                "fragmentation_state": "fragmented_old_groups" if len(old_ids) > 1 else "single_old_group",
            }
        )
    fragmentation = pd.DataFrame(fragmentation_records)
    summary = {
        "old_road_count": len(roads),
        "old_road_with_lane_decision_count": int(roads["comparison_state"].notna().sum()),
        "old_road_comparison_state_counts": roads["comparison_state"].fillna("no_lane_member").value_counts().to_dict(),
        "mixed_owner_old_road_count": int((roads["comparison_state"] == "mixed_swsd_owner").sum()),
        "swsd_owner_with_accepted_lane_count": len(fragmentation),
        "swsd_owner_fragmented_across_old_roads_count": int(
            (fragmentation.get("old_road_count", pd.Series(dtype=int)) > 1).sum()
        ),
    }
    return ComparisonResult(old_roads=roads, fragmentation=fragmentation, summary=summary)


__all__ = ["ComparisonResult", "compare_old_road_groups"]
