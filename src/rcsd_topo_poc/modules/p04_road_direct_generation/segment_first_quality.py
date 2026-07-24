from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import fiona
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from .io import write_gpkg_layers, write_json
from .segment_first_junctions import endpoint_surface_geometry


@dataclass(frozen=True)
class IndependentQualityResult:
    gate_pass: bool
    payload: dict[str, Any]
    json_path: Path
    gpkg_path: Path


def run_independent_quality(
    formal_gpkg: Path,
    audit_gpkg: Path,
    output_dir: Path,
    *,
    expected_crs: str,
    expected_segment_count: int,
    run_id: str,
) -> IndependentQualityResult:
    layers = set(fiona.listlayers(formal_gpkg))
    required_layers = {"Road", "Node", "RoadNextRoad"}
    missing_layers = sorted(required_layers - layers)
    roads = gpd.read_file(formal_gpkg, layer="Road") if "Road" in layers else gpd.GeoDataFrame()
    nodes = gpd.read_file(formal_gpkg, layer="Node") if "Node" in layers else gpd.GeoDataFrame()
    rnr = gpd.read_file(formal_gpkg, layer="RoadNextRoad") if "RoadNextRoad" in layers else gpd.GeoDataFrame()
    audit_layers = set(fiona.listlayers(audit_gpkg))
    plans = gpd.read_file(audit_gpkg, layer="segment_build_units") if "segment_build_units" in audit_layers else gpd.GeoDataFrame()
    spans = gpd.read_file(audit_gpkg, layer="road_geometry_sources") if "road_geometry_sources" in audit_layers else gpd.GeoDataFrame()
    access_realization = gpd.read_file(audit_gpkg, layer="segment_access_realization") if "segment_access_realization" in audit_layers else gpd.GeoDataFrame()
    swsd_topology = gpd.read_file(
        audit_gpkg,
        layer="swsd_topology_contract",
    ) if "swsd_topology_contract" in audit_layers else gpd.GeoDataFrame()
    junction_movements = gpd.read_file(
        audit_gpkg,
        layer="swsd_junction_movement_contract",
    ) if "swsd_junction_movement_contract" in audit_layers else gpd.GeoDataFrame()
    endpoint_coordination = gpd.read_file(
        audit_gpkg,
        layer="endpoint_coordination",
    ) if "endpoint_coordination" in audit_layers else gpd.GeoDataFrame()
    junction_units = gpd.read_file(
        audit_gpkg,
        layer="junction_units",
    ) if "junction_units" in audit_layers else gpd.GeoDataFrame()
    junction_conflicts = gpd.read_file(
        audit_gpkg,
        layer="junction_source_conflicts",
    ) if "junction_source_conflicts" in audit_layers else gpd.GeoDataFrame()
    node_ids = {
        _canonical_id(value)
        for value in nodes.get("id", pd.Series(dtype=object))
    }
    road_ids = {
        _canonical_id(value)
        for value in roads.get("id", pd.Series(dtype=object))
    }
    road_by_id = (
        roads.assign(_canonical_id=roads["id"].map(_canonical_id)).set_index(
            "_canonical_id"
        )
        if not roads.empty and "id" in roads
        else None
    )
    node_by_id = {
        _canonical_id(row.id): row for row in nodes.itertuples()
    }

    violations: list[dict[str, object]] = []
    for road in roads.itertuples():
        if (
            _canonical_id(road.snodeid) not in node_ids
            or _canonical_id(road.enodeid) not in node_ids
        ):
            violations.append(_violation(run_id, "road_node_reference_missing", str(road.id), road.geometry.centroid))
        if road.geometry is None or road.geometry.is_empty or not road.geometry.is_valid or not road.geometry.is_simple:
            violations.append(_violation(run_id, "road_geometry_invalid", str(road.id), road.geometry.centroid if road.geometry else Point()))
        if str(getattr(road, "realization", "")) == "built" and "swsd" in str(getattr(road, "geometry_source", "")).lower():
            violations.append(_violation(run_id, "built_road_contains_swsd_coordinates", str(road.id), road.geometry.centroid))
        if str(getattr(road, "realization", "")) == "built" and _max_sample_turn(road.geometry, 2.0) > 90.0:
            violations.append(_violation(run_id, "built_road_excessive_turn", str(road.id), road.geometry.centroid))
        if str(getattr(road, "carrier_role", "")) == "junction_surface_carrier":
            violations.append(
                _violation(
                    run_id,
                    "ordinary_star_road_present",
                    str(road.id),
                    road.geometry.centroid,
                )
            )
    for relation in rnr.itertuples():
        source_road_id = _canonical_id(relation.RoadId)
        target_road_id = _canonical_id(relation.NextRoadId)
        if source_road_id not in road_ids or target_road_id not in road_ids:
            violations.append(_violation(run_id, "roadnextroad_unknown_road", str(relation.Id), relation.geometry))
            continue
        source = road_by_id.loc[source_road_id]
        target = road_by_id.loc[target_road_id]
        compile_source = str(
            getattr(relation, "compile_source", "actual_shared_node")
        )
        if compile_source == "actual_shared_node":
            shared = _canonical_id(relation.shared_node_id)
            if (
                not shared
                or shared not in _exit_nodes(source)
                or shared not in _entry_nodes(target)
            ):
                violations.append(
                    _violation(
                        run_id,
                        "roadnextroad_not_shared_node",
                        str(relation.Id),
                        relation.geometry,
                    )
                )
        elif compile_source == "ordinary_junction_semantic":
            reason = _ordinary_semantic_relation_violation(
                relation,
                source,
                target,
                node_by_id,
            )
            if reason:
                violations.append(
                    _violation(
                        run_id,
                        reason,
                        str(relation.Id),
                        relation.geometry,
                    )
                )
        elif compile_source in {
            "complex_junction_swsd_explicit",
            "complex_junction_lane_topo_explicit",
        }:
            reason = _complex_explicit_relation_violation(
                relation,
                source,
                target,
                node_by_id,
            )
            if reason:
                violations.append(
                    _violation(
                        run_id,
                        reason,
                        str(relation.Id),
                        relation.geometry,
                    )
                )
        else:
            violations.append(
                _violation(
                    run_id,
                    "roadnextroad_compile_source_unknown",
                    str(relation.Id),
                    relation.geometry,
                )
            )
    duplicate_states = 0
    segment_count = 0
    segment_without_road = 0
    if not plans.empty:
        segment_count = int(plans["segment_id"].nunique())
        duplicate_states = int(plans.duplicated("segment_id", keep=False).sum())
        road_counts = roads.groupby(roads["segment_id"].astype(str)).size()
        segment_without_road = int((~plans["segment_id"].astype(str).isin(road_counts.index)).sum())
        for row in plans[~plans["segment_id"].astype(str).isin(road_counts.index)].itertuples():
            violations.append(_violation(run_id, "segment_without_road", str(row.segment_id), row.geometry.centroid))
    crs_ok = all(
        frame.crs is not None and frame.crs.to_string().upper() == expected_crs.upper()
        for frame in (roads, nodes, rnr)
        if not frame.empty
    )
    if not crs_ok:
        violations.append(_violation(run_id, "crs_invalid", "formal_layers", Point()))
    _append_geometry_span_violations(spans, roads, run_id, violations)
    if access_realization.empty:
        violations.append(_violation(run_id, "segment_access_not_materialized", "all_accesses", Point()))
    else:
        for access in access_realization[~access_realization["access_realized"].astype(bool)].itertuples():
            violations.append(_violation(run_id, "segment_access_not_materialized", str(access.access_id), access.geometry))
    if swsd_topology.empty:
        violations.append(
            _violation(
                run_id,
                "swsd_topology_contract_missing",
                "all_accesses",
                Point(),
            )
        )
    else:
        for access in swsd_topology[
            ~swsd_topology["topology_preserved"].astype(bool)
        ].itertuples():
            violations.append(
                _violation(
                    run_id,
                    "swsd_access_direction_topology_mismatch",
                    f"{access.segment_id}:{access.junction_group_id}",
                    access.geometry,
                )
            )
    if junction_movements.empty:
        violations.append(
            _violation(
                run_id,
                "swsd_junction_movement_contract_missing",
                "all_junctions",
                Point(),
            )
        )
    else:
        for junction in junction_movements[
            ~junction_movements[
                "movement_topology_preserved"
            ].astype(bool)
        ].itertuples():
            violations.append(
                _violation(
                    run_id,
                    "swsd_junction_movement_topology_mismatch",
                    str(junction.junction_group_id),
                    junction.geometry,
                )
            )
    _append_junction_surface_violations(
        endpoint_coordination,
        junction_units,
        junction_conflicts,
        roads,
        nodes,
        run_id,
        violations,
    )
    gates = {
        "formal_layers_present": not missing_layers,
        "formal_layers_nonempty": not roads.empty and not nodes.empty and not rnr.empty,
        "crs_explicit_and_expected": crs_ok,
        "segment_count_conserved": segment_count == expected_segment_count,
        "segment_state_unique": duplicate_states == 0,
        "every_segment_has_road": segment_without_road == 0,
        "road_node_references_valid": not any(row["reason_code"] == "road_node_reference_missing" for row in violations),
        "road_geometry_valid_and_simple": not any(row["reason_code"] == "road_geometry_invalid" for row in violations),
        "built_has_no_swsd_splice": not any(row["reason_code"] == "built_road_contains_swsd_coordinates" for row in violations),
        "roadnextroad_evidence_valid": not any(
            str(row["reason_code"]).startswith("roadnextroad_")
            for row in violations
        ),
        "ordinary_star_geometry_zero": not any(
            row["reason_code"] == "ordinary_star_road_present"
            for row in violations
        ),
        "built_road_absolute_turn_below_90": not any(row["reason_code"] == "built_road_excessive_turn" for row in violations),
        "geometry_source_spans_complete": not any(row["reason_code"] == "geometry_source_span_incomplete" for row in violations),
        "segment_accesses_materialized": not any(row["reason_code"] == "segment_access_not_materialized" for row in violations),
        "swsd_access_direction_topology_preserved": not any(
            row["reason_code"]
            in {
                "swsd_topology_contract_missing",
                "swsd_access_direction_topology_mismatch",
            }
            for row in violations
        ),
        "swsd_junction_movement_topology_preserved": not any(
            row["reason_code"]
            in {
                "swsd_junction_movement_contract_missing",
                "swsd_junction_movement_topology_mismatch",
            }
            for row in violations
        ),
        "built_endpoints_inside_accepted_junction_surface": not any(
            row["reason_code"]
            in {
                "built_road_endpoint_outside_junction_surface",
                "junction_surface_priority_violation",
            }
            for row in violations
        ),
    }
    gate_pass = all(gates.values()) and not violations
    payload = {
        "run_id": run_id,
        "formal_gpkg": str(formal_gpkg),
        "audit_gpkg": str(audit_gpkg),
        "expected_crs": expected_crs,
        "counts": {
            "road": int(len(roads)),
            "node": int(len(nodes)),
            "road_next_road": int(len(rnr)),
            "segment": segment_count,
            "violation": len(violations),
        },
        "gates": gates,
        "gate_pass": gate_pass,
    }
    json_path = output_dir / "p04_segment_first_independent_quality.json"
    gpkg_path = output_dir / "p04_segment_first_independent_quality.gpkg"
    write_json(json_path, payload)
    violation_frame = (
        gpd.GeoDataFrame(violations, geometry="geometry", crs=expected_crs)
        if violations
        else gpd.GeoDataFrame(
            columns=["run_id", "reason_code", "object_id", "geometry"],
            geometry="geometry",
            crs=expected_crs,
        )
    )
    metric_frame = gpd.GeoDataFrame(
        [{"run_id": run_id, "gate_pass": gate_pass, **payload["counts"], "geometry": roads.unary_union.centroid if not roads.empty else Point()}],
        crs=expected_crs,
    )
    layers_to_write = {"quality_metrics": metric_frame}
    if not violation_frame.empty:
        layers_to_write["hard_gate_violations"] = violation_frame
    write_gpkg_layers(gpkg_path, layers_to_write)
    return IndependentQualityResult(gate_pass, payload, json_path, gpkg_path)


def _append_junction_surface_violations(
    endpoint_coordination: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    junction_conflicts: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    run_id: str,
    violations: list[dict[str, object]],
) -> None:
    if endpoint_coordination.empty or junction_units.empty:
        return
    units = {
        _canonical_id(row.junction_group_id): row
        for row in junction_units.itertuples(index=False)
    }
    manual_groups = {
        group_id
        for group_id, row in units.items()
        if str(getattr(row, "junction_source", "")) == "t07_accepted"
    }
    if not junction_conflicts.empty:
        for row in junction_conflicts.itertuples(index=False):
            if "t07_accepted" in {
                str(getattr(row, "selected_source", "")),
                str(getattr(row, "other_source", "")),
            }:
                manual_groups.add(
                    _canonical_id(row.junction_group_id)
                )
    for group_id in sorted(manual_groups):
        unit = units.get(group_id)
        if unit is None:
            continue
        surface_source = str(
            getattr(
                unit,
                "surface_source",
                getattr(unit, "junction_source", ""),
            )
        )
        if surface_source != "t07_accepted":
            violations.append(
                _violation(
                    run_id,
                    "junction_surface_priority_violation",
                    group_id,
                    unit.geometry.representative_point(),
                )
            )

    road_by_id = {
        _canonical_id(row.id): row for row in roads.itertuples(index=False)
    }
    node_by_id = {
        _canonical_id(row.id): row for row in nodes.itertuples(index=False)
    }
    accepted_sources = {
        "t07_accepted",
        "t03_accepted",
        "t04_accepted",
    }
    for endpoint in endpoint_coordination.itertuples(index=False):
        road_id = _canonical_id(endpoint.road_id)
        road = road_by_id.get(road_id)
        group_id = _canonical_id(
            getattr(endpoint, "junction_group_id", "")
        )
        unit = units.get(group_id)
        if (
            road is None
            or str(getattr(road, "realization", "")) != "built"
            or unit is None
            or str(getattr(unit, "junction_source", ""))
            not in accepted_sources
        ):
            continue
        endpoint_name = str(getattr(endpoint, "endpoint", ""))
        node_id = _canonical_id(
            getattr(
                road,
                "snodeid" if endpoint_name == "start" else "enodeid",
                "",
            )
        )
        node = node_by_id.get(node_id)
        surface = endpoint_surface_geometry(unit)
        if (
            node is None
            or surface is None
            or surface.is_empty
            or not surface.contains(node.geometry)
        ):
            violations.append(
                _violation(
                    run_id,
                    "built_road_endpoint_outside_junction_surface",
                    f"{road_id}:{endpoint_name}:{group_id}",
                    node.geometry
                    if node is not None
                    else endpoint.geometry,
                )
            )


def _exit_nodes(road: pd.Series) -> set[str]:
    direction = int(road.get("direction", 2) or 2)
    if direction == 1:
        return {
            _canonical_id(road.get("snodeid")),
            _canonical_id(road.get("enodeid")),
        }
    return {_canonical_id(road.get("enodeid"))}


def _entry_nodes(road: pd.Series) -> set[str]:
    direction = int(road.get("direction", 2) or 2)
    if direction == 1:
        return {
            _canonical_id(road.get("snodeid")),
            _canonical_id(road.get("enodeid")),
        }
    return {_canonical_id(road.get("snodeid"))}


def _ordinary_semantic_relation_violation(
    relation: object,
    source: pd.Series,
    target: pd.Series,
    node_by_id: dict[str, object],
) -> str:
    source_node_id = _canonical_id(
        getattr(relation, "source_node_id", "")
    )
    target_node_id = _canonical_id(
        getattr(relation, "target_node_id", "")
    )
    if (
        source_node_id not in _exit_nodes(source)
        or target_node_id not in _entry_nodes(target)
    ):
        return "roadnextroad_semantic_endpoint_mismatch"
    source_node = node_by_id.get(source_node_id)
    target_node = node_by_id.get(target_node_id)
    if source_node is None or target_node is None:
        return "roadnextroad_semantic_node_missing"
    group_id = _canonical_id(
        getattr(relation, "junction_group_id", "")
    )
    source_groups = set(
        _split_values(getattr(source_node, "junction_group_ids", ""))
    )
    target_groups = set(
        _split_values(getattr(target_node, "junction_group_ids", ""))
    )
    if (
        not group_id
        or group_id not in source_groups
        or group_id not in target_groups
    ):
        return "roadnextroad_semantic_junction_mismatch"
    kinds = {
        str(getattr(source_node, "junction_kind", "")),
        str(getattr(target_node, "junction_kind", "")),
    }
    if not kinds.issubset({"ordinary", "retained"}):
        return "roadnextroad_semantic_junction_not_ordinary"
    source_main = _canonical_id(
        getattr(source_node, "mainnodeid", "")
    )
    target_main = _canonical_id(
        getattr(target_node, "mainnodeid", "")
    )
    relation_main = _canonical_id(
        getattr(relation, "mainnodeid", "")
    )
    if (
        not source_main
        or source_main != target_main
        or relation_main != source_main
    ):
        return "roadnextroad_semantic_mainnode_mismatch"
    return ""


def _complex_explicit_relation_violation(
    relation: object,
    source: pd.Series,
    target: pd.Series,
    node_by_id: dict[str, object],
) -> str:
    source_node_id = _canonical_id(
        getattr(relation, "source_node_id", "")
    )
    target_node_id = _canonical_id(
        getattr(relation, "target_node_id", "")
    )
    if (
        source_node_id not in _exit_nodes(source)
        or target_node_id not in _entry_nodes(target)
    ):
        return "roadnextroad_complex_endpoint_mismatch"
    source_node = node_by_id.get(source_node_id)
    target_node = node_by_id.get(target_node_id)
    if source_node is None or target_node is None:
        return "roadnextroad_complex_node_missing"
    group_id = _canonical_id(
        getattr(relation, "junction_group_id", "")
    )
    source_groups = set(
        _split_values(getattr(source_node, "junction_group_ids", ""))
    )
    target_groups = set(
        _split_values(getattr(target_node, "junction_group_ids", ""))
    )
    if (
        not group_id
        or group_id not in source_groups
        or group_id not in target_groups
    ):
        return "roadnextroad_complex_junction_mismatch"
    kinds = {
        str(getattr(source_node, "junction_kind", "")),
        str(getattr(target_node, "junction_kind", "")),
    }
    if kinds != {"complex_divmerge"}:
        return "roadnextroad_complex_junction_not_complex"
    source_main = _canonical_id(
        getattr(source_node, "mainnodeid", "")
    )
    target_main = _canonical_id(
        getattr(target_node, "mainnodeid", "")
    )
    relation_main = _canonical_id(
        getattr(relation, "mainnodeid", "")
    )
    if (
        not source_main
        or source_main != target_main
        or relation_main != source_main
    ):
        return "roadnextroad_complex_mainnode_mismatch"
    return ""


def _split_values(value: object) -> tuple[str, ...]:
    return tuple(
        _canonical_id(item)
        for item in str(value or "").split(",")
        if _canonical_id(item)
    )


def _canonical_id(value: object) -> str:
    if value is None or bool(pd.isna(value)):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
        return text[:-2]
    return text


def _violation(run_id: str, reason: str, object_id: str, geometry: object) -> dict[str, object]:
    return {
        "run_id": run_id,
        "reason_code": reason,
        "object_id": object_id,
        "geometry": geometry if geometry is not None else Point(),
    }


def _max_sample_turn(geometry: object, spacing: float) -> float:
    if geometry is None or geometry.is_empty or geometry.length <= spacing * 2:
        return 0.0
    count = max(3, int(math.ceil(geometry.length / spacing)) + 1)
    points = [geometry.interpolate(value) for value in np.linspace(0.0, geometry.length, count)]
    maximum = 0.0
    for index in range(1, len(points) - 1):
        first = np.array([points[index].x - points[index - 1].x, points[index].y - points[index - 1].y])
        second = np.array([points[index + 1].x - points[index].x, points[index + 1].y - points[index].y])
        denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
        if denominator <= 1e-9:
            continue
        cosine = float(np.clip(np.dot(first, second) / denominator, -1.0, 1.0))
        maximum = max(maximum, math.degrees(math.acos(cosine)))
    return maximum


def _append_geometry_span_violations(
    spans: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    run_id: str,
    violations: list[dict[str, object]],
) -> None:
    road_by_id = roads.set_index("id") if not roads.empty else None
    if spans.empty or road_by_id is None:
        violations.append(_violation(run_id, "geometry_source_span_incomplete", "all_roads", Point()))
        return
    normalized_spans = spans.assign(
        _canonical_road_id=spans["road_id"].map(_canonical_id)
    )
    groups = {
        road_id: group
        for road_id, group in normalized_spans.groupby(
            "_canonical_road_id"
        )
    }
    for road in roads.itertuples():
        group = groups.get(_canonical_id(road.id))
        if group is None or group.empty:
            violations.append(_violation(run_id, "geometry_source_span_incomplete", str(road.id), road.geometry.centroid))
            continue
        ordered = group.sort_values(["start_fraction", "end_fraction"])
        cursor = 0.0
        valid = True
        for span in ordered.itertuples():
            start = float(span.start_fraction)
            end = float(span.end_fraction)
            if abs(start - cursor) > 1e-6 or end <= start or end > 1.0 + 1e-6:
                valid = False
                break
            cursor = end
        if not valid or abs(cursor - 1.0) > 1e-6:
            violations.append(_violation(run_id, "geometry_source_span_incomplete", str(road.id), road.geometry.centroid))


__all__ = ["IndependentQualityResult", "run_independent_quality"]
