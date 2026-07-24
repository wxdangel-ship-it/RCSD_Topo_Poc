from __future__ import annotations

import geopandas as gpd
import pandas as pd

from .segment_first_skeleton import canonical_id


def build_swsd_junction_structure_audit(
    junction_units: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
    access_contract: gpd.GeoDataFrame,
    movement_contract: gpd.GeoDataFrame,
    *,
    run_id: str,
) -> gpd.GeoDataFrame:
    """Summarize the complete SWSD Junction topology for QGIS review."""
    if junction_units.empty or segment_accesses.empty:
        return _empty(junction_units.crs or segment_accesses.crs)

    accesses = segment_accesses.copy()
    accesses["junction_group_id"] = accesses[
        "junction_group_id"
    ].map(canonical_id)
    access_rows: list[dict[str, object]] = []
    for group_id, group in accesses.groupby(
        "junction_group_id",
        sort=True,
    ):
        access_rows.append(
            {
                "junction_group_id": group_id,
                "access_count": int(len(group)),
                "segment_count": int(group["segment_id"].nunique()),
                "endpoint_access_count": int(
                    group["access_type"].astype(str).eq("ENDPOINT").sum()
                ),
                "through_access_count": int(
                    group["access_type"].astype(str).eq("THROUGH").sum()
                ),
                "segment_ids": ",".join(
                    sorted(set(group["segment_id"].astype(str)))
                ),
            }
        )
    access_summary = pd.DataFrame(access_rows)

    direction_rows: list[dict[str, object]] = []
    if not access_contract.empty:
        contracts = access_contract.copy()
        contracts["junction_group_id"] = contracts[
            "junction_group_id"
        ].map(canonical_id)
        for group_id, group in contracts.groupby(
            "junction_group_id",
            sort=True,
        ):
            direction_rows.append(
                {
                    "junction_group_id": group_id,
                    "expected_inbound_count": int(
                        group["expected_inbound"].fillna(False).sum()
                    ),
                    "expected_outbound_count": int(
                        group["expected_outbound"].fillna(False).sum()
                    ),
                    "access_direction_contract_pass": bool(
                        group["topology_preserved"].fillna(False).all()
                    ),
                }
            )
    direction_summary = pd.DataFrame(direction_rows)

    movement = movement_contract.copy()
    if not movement.empty:
        movement["junction_group_id"] = movement[
            "junction_group_id"
        ].map(canonical_id)
        movement = movement[
            [
                "junction_group_id",
                "expected_movement_count",
                "actual_movement_count",
                "movement_topology_preserved",
            ]
        ].drop_duplicates("junction_group_id")

    units = junction_units.drop_duplicates(
        "junction_group_id",
        keep="first",
    ).copy()
    units["junction_group_id"] = units[
        "junction_group_id"
    ].map(canonical_id)
    result = units.merge(
        access_summary,
        on="junction_group_id",
        how="inner",
    )
    if not direction_summary.empty:
        result = result.merge(
            direction_summary,
            on="junction_group_id",
            how="left",
        )
    if not movement.empty:
        result = result.merge(
            movement,
            on="junction_group_id",
            how="left",
        )
    result["run_id"] = run_id
    result["junction_structure_class"] = result.apply(
        lambda row: (
            "complex_explicit"
            if str(row["topology_mode"]) == "explicit_physical"
            else "ordinary_with_through"
            if int(row["through_access_count"]) > 0
            else "ordinary_endpoint"
        ),
        axis=1,
    )
    result["complete_topology_contract"] = (
        result.get(
            "access_direction_contract_pass",
            pd.Series(False, index=result.index),
        )
        .fillna(False)
        .astype(bool)
        & result.get(
            "movement_topology_preserved",
            pd.Series(False, index=result.index),
        )
        .fillna(False)
        .astype(bool)
    )
    return gpd.GeoDataFrame(
        result,
        geometry="geometry",
        crs=junction_units.crs,
    )


def _empty(crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "run_id": pd.Series(dtype=str),
            "junction_group_id": pd.Series(dtype=str),
            "junction_structure_class": pd.Series(dtype=str),
            "complete_topology_contract": pd.Series(dtype=bool),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


__all__ = ["build_swsd_junction_structure_audit"]
