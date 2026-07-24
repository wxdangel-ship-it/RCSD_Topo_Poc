from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import geopandas as gpd


def recover_dual_target_member_carriers(
    segment_id: str,
    member_ids: Sequence[str],
    road_by_id: gpd.GeoDataFrame,
    evidence_by_member: Mapping[tuple[str, str], gpd.GeoDataFrame],
    directional_member_roles: Mapping[tuple[str, str, str], str],
    *,
    run_id: str,
    drivezone_surface: object,
    minimum_member_coverage: float,
    sample_spacing_m: float,
    completion_min_coverage: float,
    required_surfaces: Sequence[object] = (),
    surface_max_distance_m: float = 20.0,
    member_carrier_builder: Callable[..., list[dict[str, object]]],
) -> list[dict[str, object]]:
    """Recover a dual target only when every SWSD member can be realized."""
    rows: list[dict[str, object]] = []
    for member_id in member_ids:
        if member_id not in road_by_id.index:
            return []
        evidence = evidence_by_member.get((segment_id, member_id))
        if evidence is None or evidence.empty:
            return []
        directional = evidence[
            evidence["carrier_role"].eq("directional_corridor")
        ].copy()
        member_rows = member_carrier_builder(
            segment_id,
            member_id,
            road_by_id.loc[member_id],
            directional,
            run_id=run_id,
            drivezone_surface=drivezone_surface,
            minimum_member_coverage=minimum_member_coverage,
            sample_spacing_m=sample_spacing_m,
            completion_min_coverage=completion_min_coverage,
            carrier_roles_by_direction={
                direction_role: carrier_role
                for (
                    role_segment_id,
                    role_member_id,
                    direction_role,
                ), carrier_role in directional_member_roles.items()
                if role_segment_id == segment_id and role_member_id == member_id
            },
            allow_surface_inferred_counterpart=True,
            required_surfaces=(
                tuple(required_surfaces) if len(member_ids) == 1 else ()
            ),
            surface_max_distance_m=surface_max_distance_m,
        )
        if not member_rows:
            return []
        rows.extend(member_rows)

    if not any(
        float(row.get("surface_inferred_fraction", 0.0) or 0.0) > 0.0
        for row in rows
    ):
        return []
    built_roles = {
        str(row.get("carrier_role", ""))
        for row in rows
        if str(row.get("realization", "")) == "built"
    }
    if not {"main_forward", "main_reverse"}.issubset(built_roles):
        return []
    required_member_roles = {
        (role_member_id, carrier_role)
        for (
            role_segment_id,
            role_member_id,
            _,
        ), carrier_role in directional_member_roles.items()
        if role_segment_id == segment_id
    }
    built_member_roles = {
        (
            str(row.get("member_swsd_road_id", "")),
            str(row.get("carrier_role", "")),
        )
        for row in rows
        if str(row.get("realization", "")) == "built"
    }
    if not required_member_roles.issubset(built_member_roles):
        return []
    return rows


__all__ = ["recover_dual_target_member_carriers"]
