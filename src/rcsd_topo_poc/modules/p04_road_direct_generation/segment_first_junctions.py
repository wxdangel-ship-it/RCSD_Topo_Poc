from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib

import geopandas as gpd
import pandas as pd
from shapely import wkt
from shapely.geometry import Point

from .segment_first_skeleton import canonical_id


@dataclass(frozen=True)
class JunctionBuildResult:
    junction_units: gpd.GeoDataFrame
    access_relations: gpd.GeoDataFrame
    source_conflicts: gpd.GeoDataFrame
    summary: dict[str, object]


def build_junction_units(
    t07_surfaces: gpd.GeoDataFrame,
    t03_surfaces: gpd.GeoDataFrame,
    t04_surfaces: gpd.GeoDataFrame,
    accesses: gpd.GeoDataFrame,
    *,
    t01_nodes: gpd.GeoDataFrame | None = None,
    run_id: str,
) -> JunctionBuildResult:
    crs = accesses.crs or t07_surfaces.crs or t03_surfaces.crs or t04_surfaces.crs
    candidates: dict[str, list[dict[str, object]]] = {}
    for frame, source, kind, priority in (
        (t03_surfaces, "t03_accepted", "ordinary", 1),
        (t07_surfaces, "t07_accepted", "ordinary", 2),
        (t04_surfaces, "t04_accepted", "complex_divmerge", 3),
    ):
        for row in frame.itertuples():
            group_id = _surface_group_id(row, source)
            if not group_id:
                continue
            candidates.setdefault(group_id, []).append(
                {
                    "run_id": run_id,
                    "junction_group_id": group_id,
                    "junction_source": source,
                    "junction_kind": kind,
                    "topology_mode": (
                        "explicit_physical"
                        if kind == "complex_divmerge"
                        else "ordinary_semantic"
                    ),
                    "source_object_id": _source_object_id(row, source),
                    "source_priority": priority,
                    "geometry": row.geometry,
                }
            )
    selected_rows: list[dict[str, object]] = []
    conflict_rows: list[dict[str, object]] = []
    for group_id, rows in sorted(candidates.items()):
        rows = sorted(rows, key=lambda row: (-int(row["source_priority"]), str(row["source_object_id"])))
        selected = dict(rows[0])
        surface_selected = min(
            rows,
            key=lambda row: (
                0
                if row["junction_source"] == "t07_accepted"
                else 1
                if row["junction_source"] == selected["junction_source"]
                else 2,
                str(row["source_object_id"]),
            ),
        )
        selected["surface_source"] = surface_selected["junction_source"]
        selected["surface_source_object_id"] = surface_selected[
            "source_object_id"
        ]
        selected["endpoint_surface_wkt"] = surface_selected["geometry"].wkt
        selected["junction_id"] = _stable_text_id("junction", group_id)
        selected["candidate_source_count"] = len(rows)
        selected["reason_codes"] = (
            "t04_complex_topology_t07_human_surface"
            if (
                selected["junction_source"] == "t04_accepted"
                and selected["surface_source"] == "t07_accepted"
            )
            else "t04_complex_priority"
            if selected["junction_source"] == "t04_accepted"
            else "t07_human_reviewed_priority"
            if selected["junction_source"] == "t07_accepted" and len(rows) > 1
            else "accepted_surface"
        )
        selected_rows.append(selected)
        for rejected in rows[1:]:
            conflict_rows.append(
                {
                    "run_id": run_id,
                    "junction_group_id": group_id,
                    "selected_source": selected["junction_source"],
                    "selected_surface_source": selected["surface_source"],
                    "other_source": rejected["junction_source"],
                    "reason_codes": "lower_priority_accepted_surface_retained_for_audit",
                    "geometry": rejected["geometry"],
                }
            )

    selected_groups = {str(row["junction_group_id"]) for row in selected_rows}
    for group_id, group in accesses.groupby(accesses["junction_group_id"].map(canonical_id)):
        if not group_id or group_id in selected_groups:
            continue
        points = [geometry for geometry in group.geometry if geometry is not None and not geometry.is_empty]
        geometry = points[0] if points else Point()
        junction_kind = _retained_junction_kind(
            group_id,
            t01_nodes,
        )
        selected_rows.append(
            {
                "run_id": run_id,
                "junction_id": _stable_text_id("junction", group_id),
                "junction_group_id": group_id,
                "junction_source": "swsd_retained",
                "junction_kind": junction_kind,
                "topology_mode": (
                    "explicit_physical"
                    if junction_kind == "complex_divmerge"
                    else "ordinary_semantic"
                ),
                "source_object_id": group_id,
                "surface_source": "swsd_retained",
                "surface_source_object_id": group_id,
                "endpoint_surface_wkt": geometry.wkt,
                "source_priority": 0,
                "candidate_source_count": 0,
                "reason_codes": "no_accepted_surface_for_access_group",
                "geometry": geometry,
            }
        )
    junction_units = gpd.GeoDataFrame(selected_rows, geometry="geometry", crs=crs)
    junction_by_group = {
        str(row.junction_group_id): str(row.junction_id)
        for row in junction_units.itertuples()
    }
    access_relations = accesses.copy()
    access_relations["junction_id"] = access_relations["junction_group_id"].map(canonical_id).map(junction_by_group)
    access_relations["relation_state"] = access_relations["junction_id"].notna().map(
        {True: "resolved", False: "missing_junction"}
    )
    conflicts = (
        gpd.GeoDataFrame(conflict_rows, geometry="geometry", crs=crs)
        if conflict_rows
        else gpd.GeoDataFrame(
            {
                "run_id": pd.Series(dtype=str),
                "junction_group_id": pd.Series(dtype=str),
                "selected_source": pd.Series(dtype=str),
                "selected_surface_source": pd.Series(dtype=str),
                "other_source": pd.Series(dtype=str),
                "reason_codes": pd.Series(dtype=str),
                "geometry": gpd.GeoSeries([], crs=crs),
            },
            geometry="geometry",
            crs=crs,
        )
    )
    summary = {
        "junction_count": int(len(junction_units)),
        "source_counts": junction_units["junction_source"].value_counts().to_dict(),
        "surface_source_counts": junction_units[
            "surface_source"
        ].value_counts().to_dict(),
        "topology_mode_counts": junction_units[
            "topology_mode"
        ].value_counts().to_dict(),
        "surface_conflict_count": int(len(conflicts)),
        "unresolved_access_count": int(access_relations["junction_id"].isna().sum()),
    }
    return JunctionBuildResult(junction_units, access_relations, conflicts, summary)


def _retained_junction_kind(
    group_id: str,
    t01_nodes: gpd.GeoDataFrame | None,
) -> str:
    if (
        t01_nodes is None
        or t01_nodes.empty
        or "kind_2" not in t01_nodes.columns
    ):
        return "retained"
    ids = t01_nodes["id"].map(canonical_id)
    mainnodes = (
        t01_nodes["mainnodeid"].map(canonical_id)
        if "mainnodeid" in t01_nodes.columns
        else pd.Series("", index=t01_nodes.index)
    )
    group = t01_nodes[(ids == group_id) | (mainnodes == group_id)]
    kind_values = {
        canonical_id(value) for value in group["kind_2"]
    }
    return (
        "complex_divmerge"
        if "128" in kind_values
        else "retained"
    )


def _surface_group_id(row: object, source: str) -> str:
    for field in ("mainnodeid", "target_id", "base_id_candidate", "representative_node_id"):
        value = canonical_id(getattr(row, field, None))
        if value and value != "0":
            return value
    return _source_object_id(row, source)


def _source_object_id(row: object, source: str) -> str:
    fields = {
        "t04_accepted": ("anchor_id", "case_id", "mainnodeid"),
        "t07_accepted": ("surface_candidate_id", "id", "mainnodeid"),
        "t03_accepted": ("mainnodeid", "representative_node_id"),
    }[source]
    for field in fields:
        value = canonical_id(getattr(row, field, None))
        if value:
            return value
    return _stable_text_id(source, row.geometry.wkb_hex)


def _stable_text_id(prefix: str, value: object) -> str:
    digest = hashlib.sha1(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def endpoint_surface_geometry(row: object) -> object:
    value = getattr(row, "endpoint_surface_wkt", None)
    if value is None and hasattr(row, "get"):
        value = row.get("endpoint_surface_wkt")
    if value is not None and pd.notna(value) and str(value):
        return _load_endpoint_surface_wkt(str(value))
    return getattr(row, "geometry")


@lru_cache(maxsize=16384)
def _load_endpoint_surface_wkt(value: str) -> object:
    return wkt.loads(value)


def build_endpoint_surface_audit(
    junction_units: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    result = junction_units.copy()
    result.geometry = gpd.GeoSeries(
        [
            endpoint_surface_geometry(row)
            for row in result.itertuples(index=False)
        ],
        index=result.index,
        crs=result.crs,
    )
    return result


__all__ = [
    "JunctionBuildResult",
    "build_endpoint_surface_audit",
    "build_junction_units",
    "endpoint_surface_geometry",
]
