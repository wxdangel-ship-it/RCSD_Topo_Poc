from __future__ import annotations

import hashlib
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import fiona
import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from .directional_quality import (
    _movement_join_audit,
    _physical_node_audit,
    _road_smoothness_audit,
)
from .geometry import canonical_id
from .io import write_gpkg_layers, write_json


@dataclass(frozen=True)
class HighPrecisionQualityThresholds:
    analysis_crs: str = "EPSG:32650"
    physical_node_gap_tolerance_m: float = 0.05
    turn_sample_spacing_m: float = 5.0
    supported_turn_excess_tolerance_deg: float = 26.0
    movement_portal_tolerance_m: float = 0.05
    movement_join_angle_tolerance_deg: float = 10.0
    source_fraction_tolerance: float = 1e-6
    source_length_tolerance_m: float = 0.05
    minimum_evidence_road_control_ratio: float = 0.80
    maximum_network_swsd_fallback_ratio: float = 0.40


def run_high_precision_independent_quality(
    run_root: str | Path,
    *,
    thresholds: HighPrecisionQualityThresholds | None = None,
) -> dict[str, Any]:
    """Read only the published V3 package and independently audit its claims."""

    started = time.perf_counter()
    root = Path(run_root).expanduser().resolve()
    limits = thresholds or HighPrecisionQualityThresholds()
    road_path = root / "p04_hp_v3_roads.gpkg"
    corridor_path = root / "p04_hp_v3_corridors.gpkg"
    source_path = root / "p04_hp_v3_geometry_sources.gpkg"
    graph_path = root / "p04_hp_v3_road_graph.gpkg"
    roads = gpd.read_file(road_path, layer="high_precision_roads")
    decisions = gpd.read_file(
        corridor_path, layer="physical_corridor_decisions"
    )
    observations = gpd.read_file(corridor_path, layer="center_observations")
    segments = gpd.read_file(source_path, layer="geometry_segments")
    stations = gpd.read_file(source_path, layer="fit_stations")
    parents = gpd.read_file(graph_path, layer="parent_swsd_roads")
    portals = gpd.read_file(graph_path, layer="high_precision_portals")
    arms = gpd.read_file(graph_path, layer="high_precision_arms")
    movements = gpd.read_file(graph_path, layer="high_precision_movements")
    evidence = _read_optional(graph_path, "movement_evidence_links", limits.analysis_crs)

    roads["v3_road_id"] = roads["v3_road_id"].astype(str)
    parents["swsd_unit_id"] = parents["swsd_unit_id"].map(canonical_id)
    adapted_roads = roads.copy()
    adapted_roads["directional_road_id"] = adapted_roads["v3_road_id"]
    parent_by_id = parents.set_index("swsd_unit_id", drop=False)
    road_by_id = adapted_roads.set_index("directional_road_id", drop=False)
    adapted_movements = _adapt_movements(movements)

    smoothness = _road_smoothness_audit(
        adapted_roads,
        parent_by_id,
        sample_spacing_m=limits.turn_sample_spacing_m,
        excess_tolerance_deg=limits.supported_turn_excess_tolerance_deg,
    ).rename(columns={"directional_road_id": "v3_road_id"})
    physical_nodes = _physical_node_audit(
        adapted_roads,
        tolerance_m=limits.physical_node_gap_tolerance_m,
    )
    movement_audit = _movement_join_audit(
        adapted_movements,
        road_by_id,
        portal_tolerance_m=limits.movement_portal_tolerance_m,
        angle_tolerance_deg=limits.movement_join_angle_tolerance_deg,
    ).rename(
        columns={
            "directional_movement_id": "v3_movement_id",
            "source_directional_road_id": "source_v3_road_id",
            "target_directional_road_id": "target_v3_road_id",
        }
    )
    source_audit, source_metrics = _geometry_source_audit(
        roads,
        segments,
        stations,
        observations,
        limits=limits,
    )
    corridor_audit, corridor_metrics = _corridor_audit(
        roads,
        parents,
        decisions,
    )
    portal_audit, portal_metrics = _portal_arm_audit(roads, portals, arms)
    lane_topo_metrics = _lane_topo_audit(evidence, movements, set(roads["v3_road_id"]))

    turn_violations = smoothness[
        smoothness["quality_gate_applicable"] & ~smoothness["turn_gate_pass"]
    ]
    node_violations = physical_nodes[~physical_nodes["gap_gate_pass"]]
    movement_violations = movement_audit[~movement_audit["join_gate_pass"]]
    gates = {
        "all_required_layers_present": _required_layers_present(
            road_path, corridor_path, source_path, graph_path
        ),
        "all_crs_explicit": all(
            _crs_matches(frame, limits.analysis_crs)
            for frame in (
                roads,
                decisions,
                observations,
                segments,
                stations,
                parents,
                portals,
                arms,
                movements,
                evidence,
            )
        ),
        "road_geometry_valid_simple": bool(
            roads.geometry.notna().all()
            and (~roads.geometry.is_empty).all()
            and roads.geometry.is_valid.all()
            and roads.geometry.is_simple.all()
        ),
        "parent_semantic_conservation": corridor_metrics["parent_conservation_pass"],
        "physical_directional_split_evidence": corridor_metrics[
            "split_violation_count"
        ]
        == 0,
        "geometry_source_partition": source_metrics["partition_violation_count"] == 0,
        "geometry_source_matches_final_roads": source_metrics[
            "final_geometry_coverage_violation_count"
        ]
        == 0,
        "geometry_source_declarations": source_metrics[
            "declaration_mismatch_count"
        ]
        == 0,
        "direct_observation_not_inflated": source_metrics[
            "unbacked_observed_segment_count"
        ]
        == 0,
        "constrained_interpolation_backed": source_metrics[
            "unbacked_constrained_road_count"
        ]
        == 0,
        "evidence_road_control_ratio": source_metrics[
            "evidence_road_control_ratio"
        ]
        >= limits.minimum_evidence_road_control_ratio,
        "network_swsd_fallback_ratio": source_metrics["network_swsd_fallback_ratio"]
        < limits.maximum_network_swsd_fallback_ratio,
        "portal_arm_completeness": portal_metrics["violation_count"] == 0,
        "all_physical_nodes_closed": node_violations.empty,
        "supported_road_smoothness": turn_violations.empty,
        "movement_portal_and_tangent": movement_violations.empty,
        "lane_topo_projection_conserved": lane_topo_metrics["gate_pass"],
    }
    gate_pass = all(gates.values())
    paths = (road_path, corridor_path, source_path, graph_path)
    payload = {
        "audit_version": "p04_high_precision_independent_quality_v3",
        "audit_scope": "published_gpkg_only; generation summary not consumed",
        "run_root": str(root),
        "thresholds": asdict(limits),
        "source_files": {
            path.name: {"sha256": _sha256(path), "size_bytes": path.stat().st_size}
            for path in paths
        },
        "road": {
            "count": int(len(roads)),
            "valid_count": int(roads.geometry.is_valid.sum()),
            "simple_count": int(roads.geometry.is_simple.sum()),
            "turn_violation_count": int(len(turn_violations)),
            "max_supported_turn_excess_deg": _safe_max(
                smoothness.loc[
                    smoothness["quality_gate_applicable"], "max_turn_excess_deg"
                ]
            ),
        },
        "corridor": corridor_metrics,
        "geometry_source": source_metrics,
        "physical_node": {
            "audited_count": int(len(physical_nodes)),
            "violation_count": int(len(node_violations)),
            "max_gap_m": _safe_max(physical_nodes["max_endpoint_gap_m"]),
        },
        "portal_arm": portal_metrics,
        "movement": {
            "count": int(len(movements)),
            "violation_count": int(len(movement_violations)),
            "max_portal_gap_m": _safe_max(movement_audit["max_portal_gap_m"]),
            "max_join_angle_deg": _safe_max(movement_audit["max_join_angle_deg"]),
        },
        "lane_topo": lane_topo_metrics,
        "gates": gates,
        "gate_pass": gate_pass,
        "fail_reasons": [name for name, passed in gates.items() if not passed],
        "performance": {"audit_seconds": time.perf_counter() - started},
        "outputs": {
            "audit_json": "p04_hp_v3_independent_quality.json",
            "audit_gpkg": "p04_hp_v3_independent_quality.gpkg",
        },
    }
    write_gpkg_layers(
        root / "p04_hp_v3_independent_quality.gpkg",
        {
            "road_smoothness_audit": smoothness,
            "physical_node_audit": physical_nodes,
            "movement_join_audit": movement_audit,
            "geometry_source_audit": source_audit,
            "corridor_split_audit": corridor_audit,
            "portal_arm_audit": portal_audit,
        },
    )
    write_json(root / "p04_hp_v3_independent_quality.json", payload)
    return payload


def _geometry_source_audit(
    roads: gpd.GeoDataFrame,
    segments: gpd.GeoDataFrame,
    stations: gpd.GeoDataFrame,
    observations: gpd.GeoDataFrame,
    *,
    limits: HighPrecisionQualityThresholds,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    valid_sources = {
        "hp_observed",
        "hp_constrained_interpolation",
        "swsd_fallback",
    }
    rows: list[dict[str, Any]] = []
    totals = {source: 0.0 for source in valid_sources}
    evidence_length = 0.0
    evidence_controlled = 0.0
    for road in roads.itertuples(index=False):
        road_id = str(road.v3_road_id)
        frame = segments[segments["v3_road_id"].astype(str) == road_id].copy()
        frame = frame.sort_values(["start_fraction", "end_fraction"])
        fractions = list(
            zip(frame["start_fraction"].astype(float), frame["end_fraction"].astype(float))
        )
        partition_pass = bool(
            fractions
            and abs(fractions[0][0]) <= limits.source_fraction_tolerance
            and abs(fractions[-1][1] - 1.0) <= limits.source_fraction_tolerance
            and all(end > start for start, end in fractions)
            and all(
                abs(first[1] - second[0]) <= limits.source_fraction_tolerance
                for first, second in zip(fractions, fractions[1:])
            )
            and set(frame["geometry_source"].astype(str)).issubset(valid_sources)
        )
        actual = {
            source: float(
                frame.loc[frame["geometry_source"] == source].geometry.length.sum()
            )
            for source in valid_sources
        }
        for source, length in actual.items():
            totals[source] += length
        declared = {
            "hp_observed": float(road.observed_length_m),
            "hp_constrained_interpolation": float(road.constrained_length_m),
            "swsd_fallback": float(road.swsd_fallback_length_m),
        }
        length_fields_pass = all(
            abs(float(row.length_m) - float(row.geometry.length))
            <= limits.source_length_tolerance_m
            for row in frame.itertuples(index=False)
        )
        declaration_pass = length_fields_pass and all(
            abs(declared[source] - actual[source]) <= limits.source_length_tolerance_m
            for source in valid_sources
        )
        segment_union = unary_union(list(frame.geometry)) if not frame.empty else None
        final_geometry_coverage_pass = bool(
            segment_union is not None
            and abs(float(frame.geometry.length.sum()) - float(road.geometry.length))
            <= limits.source_length_tolerance_m
            and float(segment_union.hausdorff_distance(road.geometry))
            <= limits.source_length_tolerance_m
        )
        observed_frames = frame[frame["geometry_source"] == "hp_observed"]
        road_stations = stations[
            (stations["v3_road_id"].astype(str) == road_id)
            & stations["direct_observation"].map(_truthy)
        ]
        road_observations = observations[
            observations["v3_road_id"].astype(str) == road_id
        ]
        unbacked = 0
        for segment in observed_frames.itertuples(index=False):
            station_backed = road_stations["station_fraction"].astype(float).between(
                float(segment.start_fraction) - limits.source_fraction_tolerance,
                float(segment.end_fraction) + limits.source_fraction_tolerance,
            ).any()
            observation_backed = (
                not road_observations.empty
                and road_observations["station_fraction"]
                .astype(float)
                .between(
                    float(segment.start_fraction)
                    - limits.source_fraction_tolerance,
                    float(segment.end_fraction)
                    + limits.source_fraction_tolerance,
                )
                .any()
            )
            if not station_backed and not observation_backed:
                unbacked += 1
        observed = actual["hp_observed"]
        controlled = observed + actual["hp_constrained_interpolation"]
        unbacked_constrained = int(
            actual["hp_constrained_interpolation"]
            > limits.source_length_tolerance_m
            and road_observations.empty
        )
        if not road_observations.empty:
            evidence_length += float(road.geometry.length)
            evidence_controlled += controlled
        rows.append(
            {
                "v3_road_id": road_id,
                "parent_swsd_unit_id": str(road.parent_swsd_unit_id),
                "segment_count": int(len(frame)),
                "partition_pass": partition_pass,
                "declaration_pass": declaration_pass,
                "final_geometry_coverage_pass": final_geometry_coverage_pass,
                "unbacked_observed_segment_count": unbacked,
                "unbacked_constrained_road_count": unbacked_constrained,
                "actual_observed_length_m": observed,
                "actual_constrained_length_m": actual[
                    "hp_constrained_interpolation"
                ],
                "actual_swsd_fallback_length_m": actual["swsd_fallback"],
                "geometry": road.geometry,
            }
        )
    audit = gpd.GeoDataFrame(rows, geometry="geometry", crs=roads.crs)
    network_length = float(roads.geometry.length.sum())
    metrics = {
        "partition_violation_count": int((~audit["partition_pass"]).sum()),
        "final_geometry_coverage_violation_count": int(
            (~audit["final_geometry_coverage_pass"]).sum()
        ),
        "declaration_mismatch_count": int((~audit["declaration_pass"]).sum()),
        "unbacked_observed_segment_count": int(
            audit["unbacked_observed_segment_count"].sum()
        ),
        "unbacked_constrained_road_count": int(
            audit["unbacked_constrained_road_count"].sum()
        ),
        "observed_length_m": totals["hp_observed"],
        "constrained_length_m": totals["hp_constrained_interpolation"],
        "swsd_fallback_length_m": totals["swsd_fallback"],
        "observed_ratio": totals["hp_observed"] / network_length
        if network_length
        else 0.0,
        "evidence_road_control_ratio": evidence_controlled / evidence_length
        if evidence_length
        else 0.0,
        "network_swsd_fallback_ratio": totals["swsd_fallback"] / network_length
        if network_length
        else 0.0,
    }
    return audit, metrics


def _corridor_audit(
    roads: gpd.GeoDataFrame,
    parents: gpd.GeoDataFrame,
    decisions: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    road_parent_ids = set(roads["parent_swsd_unit_id"].map(canonical_id))
    parent_ids = set(parents["swsd_unit_id"].map(canonical_id))
    decision_ids = set(decisions["parent_swsd_unit_id"].map(canonical_id))
    rows: list[dict[str, Any]] = []
    for decision in decisions.itertuples(index=False):
        parent_id = canonical_id(decision.parent_swsd_unit_id)
        children = roads[
            roads["parent_swsd_unit_id"].map(canonical_id) == parent_id
        ]
        split = str(decision.decision) == "split"
        sides = set(children["travel_side"].astype(str))
        pair_distance = math.nan
        if len(children) == 2:
            first, second = children.geometry.iloc[0], children.geometry.iloc[1]
            samples = [
                first.interpolate(value, normalized=True) for value in np.linspace(0, 1, 11)
            ] + [
                second.interpolate(value, normalized=True) for value in np.linspace(0, 1, 11)
            ]
            pair_distance = float(
                np.median(
                    [second.distance(point) for point in samples[:11]]
                    + [first.distance(point) for point in samples[11:]]
                )
            )
        required = float(decision.required_min_separation_m)
        gate_pass = bool(
            (not split and len(children) == 1)
            or (
                split
                and len(children) == 2
                and sides == {"forward", "reverse"}
                and _truthy(decision.separation_gate_pass)
                and _truthy(decision.continuity_gate_pass)
                and float(decision.anchor_median_separation_m) >= required
                and pair_distance >= required
            )
        )
        rows.append(
            {
                "parent_swsd_unit_id": parent_id,
                "decision": str(decision.decision),
                "published_child_count": int(len(children)),
                "published_travel_sides": ";".join(sorted(sides)),
                "required_min_separation_m": required,
                "published_median_separation_m": pair_distance,
                "split_gate_pass": gate_pass,
                "geometry": decision.geometry,
            }
        )
    audit = gpd.GeoDataFrame(rows, geometry="geometry", crs=decisions.crs)
    conservation = bool(
        road_parent_ids == parent_ids == decision_ids
        and decisions["parent_swsd_unit_id"].map(canonical_id).is_unique
    )
    return audit, {
        "parent_count": int(len(parent_ids)),
        "published_road_count": int(len(roads)),
        "decision_count": int(len(decisions)),
        "parent_conservation_pass": conservation,
        "split_violation_count": int((~audit["split_gate_pass"]).sum()),
    }


def _portal_arm_audit(
    roads: gpd.GeoDataFrame,
    portals: gpd.GeoDataFrame,
    arms: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for road in roads.itertuples(index=False):
        road_id = str(road.v3_road_id)
        for endpoint, index in (("s", 0), ("e", -1)):
            expected = Point(road.geometry.coords[index])
            portal = portals[
                (portals["v3_road_id"].astype(str) == road_id)
                & (portals["endpoint"].astype(str) == endpoint)
            ]
            arm = arms[
                (arms["v3_road_id"].astype(str) == road_id)
                & (arms["endpoint"].astype(str) == endpoint)
            ]
            portal_gap = (
                float(expected.distance(portal.geometry.iloc[0]))
                if len(portal) == 1
                else math.inf
            )
            arm_gap = (
                min(
                    expected.distance(Point(arm.geometry.iloc[0].coords[0])),
                    expected.distance(Point(arm.geometry.iloc[0].coords[-1])),
                )
                if len(arm) == 1
                else math.inf
            )
            passed = len(portal) == 1 and len(arm) == 1 and max(portal_gap, arm_gap) <= 1e-8
            rows.append(
                {
                    "v3_road_id": road_id,
                    "endpoint": endpoint,
                    "portal_count": int(len(portal)),
                    "arm_count": int(len(arm)),
                    "portal_gap_m": portal_gap,
                    "arm_gap_m": arm_gap,
                    "portal_arm_gate_pass": passed,
                    "geometry": expected,
                }
            )
    audit = gpd.GeoDataFrame(rows, geometry="geometry", crs=roads.crs)
    return audit, {
        "expected_endpoint_count": int(len(roads) * 2),
        "portal_count": int(len(portals)),
        "arm_count": int(len(arms)),
        "violation_count": int((~audit["portal_arm_gate_pass"]).sum()),
    }


def _lane_topo_audit(
    evidence: gpd.GeoDataFrame,
    movements: gpd.GeoDataFrame,
    road_ids: set[str],
) -> dict[str, Any]:
    if evidence.empty:
        return {
            "evidence_link_count": 0,
            "confirmed_link_count": 0,
            "movement_link_count": 0,
            "orphan_road_reference_count": 0,
            "missing_confirmed_link_count": 0,
            "gate_pass": False,
        }
    source_column = _first_column(evidence, "source_v3_road_id", "source_directional_road_id")
    target_column = _first_column(evidence, "target_v3_road_id", "target_directional_road_id")
    confirmed = evidence[evidence["projection_state"].astype(str) == "confirmed"]
    references = set(confirmed[source_column].astype(str)) | set(
        confirmed[target_column].astype(str)
    )
    confirmed_ids = set(confirmed["link_id"].astype(str))
    movement_ids: set[str] = set()
    if "lane_topo_link_ids" in movements.columns:
        for value in movements["lane_topo_link_ids"].dropna().astype(str):
            movement_ids.update(item for item in value.split(";") if item)
    else:
        movement_ids = confirmed_ids
    missing = confirmed_ids - movement_ids
    orphans = references - road_ids - {""}
    return {
        "evidence_link_count": int(len(evidence)),
        "confirmed_link_count": int(len(confirmed)),
        "movement_link_count": int(len(movement_ids)),
        "orphan_road_reference_count": int(len(orphans)),
        "missing_confirmed_link_count": int(len(missing)),
        "gate_pass": not orphans and not missing,
    }


def _adapt_movements(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = frame.copy()
    result["directional_movement_id"] = result[
        _first_column(result, "directional_movement_id", "v3_movement_id")
    ].astype(str)
    result["source_directional_road_id"] = result[
        _first_column(result, "source_v3_road_id", "source_directional_road_id")
    ].astype(str)
    result["target_directional_road_id"] = result[
        _first_column(result, "target_v3_road_id", "target_directional_road_id")
    ].astype(str)
    return result


def _required_layers_present(*paths: Path) -> bool:
    expected = {
        paths[0]: {"high_precision_roads"},
        paths[1]: {"physical_corridor_decisions", "center_observations"},
        paths[2]: {"geometry_segments", "fit_stations"},
        paths[3]: {
            "parent_swsd_roads",
            "high_precision_portals",
            "high_precision_arms",
            "high_precision_movements",
            "movement_evidence_links",
        },
    }
    return all(path.is_file() and layers.issubset(set(fiona.listlayers(path))) for path, layers in expected.items())


def _read_optional(path: Path, layer: str, crs: str) -> gpd.GeoDataFrame:
    if path.is_file() and layer in fiona.listlayers(path):
        return gpd.read_file(path, layer=layer)
    return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=crs)


def _first_column(frame: gpd.GeoDataFrame, *names: str) -> str:
    for name in names:
        if name in frame.columns:
            return name
    raise KeyError(f"none of the required columns exists: {names}")


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _crs_matches(frame: gpd.GeoDataFrame, expected: str) -> bool:
    return bool(frame.crs and frame.crs.to_string().upper() == expected.upper())


def _safe_max(values: Any) -> float:
    return float(values.max()) if len(values) else 0.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "HighPrecisionQualityThresholds",
    "run_high_precision_independent_quality",
]
