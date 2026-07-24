from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import substring


COHORTS = {
    "strict_accepted": lambda frame: frame["decision"].eq("accepted"),
    "owner_surface_usable": lambda frame: frame["owner_state"].eq("accepted")
    & frame["drivezone_coverage"].fillna(0.0).ge(0.80),
    "owner_accepted": lambda frame: frame["owner_state"].eq("accepted"),
}

POLICY_GRID = (
    (0.0, 0.90, 10.0),
    (0.0, 0.95, 10.0),
    (5.0, 0.95, 10.0),
    (8.0, 0.95, 15.0),
    (10.0, 0.95, 15.0),
    (8.0, 0.98, 10.0),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze P04 M2 Road support on an M1 run.")
    parser.add_argument("--m1-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--analysis-crs", default="EPSG:32650")
    parser.add_argument("--projection-spacing-m", type=float, default=5.0)
    parser.add_argument("--selected-cohort", choices=tuple(COHORTS), default="owner_surface_usable")
    parser.add_argument("--selected-padding-m", type=float, default=8.0)
    parser.add_argument("--selected-full-coverage", type=float, default=0.95)
    parser.add_argument("--selected-max-gap-m", type=float, default=15.0)
    return parser.parse_args()


def sample_offsets(length: float, spacing: float) -> np.ndarray:
    if length <= 0.0:
        return np.asarray([0.0])
    count = max(2, int(math.ceil(length / spacing)) + 1)
    return np.linspace(0.0, length, count)


def merge_intervals(intervals: Iterable[tuple[float, float]], length: float) -> list[tuple[float, float]]:
    normalized = sorted(
        (max(0.0, min(length, float(start))), max(0.0, min(length, float(end))))
        for start, end in intervals
        if float(end) >= float(start)
    )
    merged: list[list[float]] = []
    for start, end in normalized:
        if not merged or start > merged[-1][1] + 1e-8:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def complement_intervals(support: list[tuple[float, float]], length: float) -> list[tuple[float, float]]:
    gaps: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in support:
        if start > cursor + 1e-8:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < length - 1e-8:
        gaps.append((cursor, length))
    return gaps


def line_part(line: Any, start: float, end: float) -> Any:
    if end - start <= 1e-8:
        point = line.interpolate(start)
        return LineString([point, point])
    return substring(line, start, end)


def lane_projection_rows(
    lanes: gpd.GeoDataFrame,
    roads_by_id: dict[str, Any],
    spacing_m: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for lane in lanes.itertuples():
        road_id = str(lane.swsd_unit_id) if lane.swsd_unit_id is not None else ""
        road = roads_by_id.get(road_id)
        if road is None or road.is_empty or lane.geometry is None or lane.geometry.is_empty:
            continue
        offsets = sample_offsets(float(lane.geometry.length), spacing_m)
        projections = np.asarray(
            [float(road.project(lane.geometry.interpolate(float(offset)))) for offset in offsets]
        )
        differences = np.diff(projections)
        path_progress = float(np.abs(differences).sum())
        net_progress = abs(float(projections[-1] - projections[0]))
        monotonicity = net_progress / path_progress if path_progress > 1e-8 else 1.0
        span = float(projections.max() - projections.min())
        lane_length = float(lane.geometry.length)
        rows.append(
            {
                "lane_id": str(lane.lane_id),
                "source_patch_ids": str(lane.source_patch_ids),
                "swsd_unit_id": road_id,
                "decision": str(lane.decision),
                "owner_state": str(lane.owner_state),
                "width_state": str(lane.width_state),
                "drivezone_coverage": float(lane.drivezone_coverage),
                "road_length_m": float(road.length),
                "lane_length_m": lane_length,
                "projected_start_m": float(projections.min()),
                "projected_end_m": float(projections.max()),
                "projected_span_m": span,
                "projected_span_to_lane_ratio": span / lane_length if lane_length > 1e-8 else 0.0,
                "projection_monotonicity": monotonicity,
                "projection_sample_count": int(len(offsets)),
                "owner_distance_p90_m": float(lane.owner_distance_p90_m),
                "owner_direction_delta_deg": float(lane.owner_direction_delta_deg),
                "reason_codes": str(lane.reason_codes),
            }
        )
    return pd.DataFrame(rows)


def road_metrics(
    roads: gpd.GeoDataFrame,
    lane_metrics: pd.DataFrame,
    eligible_lane_ids: set[str],
    *,
    padding_m: float,
    full_coverage: float,
    max_gap_m: float,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    eligible = lane_metrics[lane_metrics["lane_id"].isin(eligible_lane_ids)]
    lanes_by_road = {road_id: frame for road_id, frame in eligible.groupby("swsd_unit_id")}
    rows: list[dict[str, Any]] = []
    interval_rows: list[dict[str, Any]] = []
    for road in roads.itertuples():
        road_id = str(road.swsd_unit_id)
        length = float(road.geometry.length)
        lane_rows = lanes_by_road.get(road_id)
        raw_intervals: list[tuple[float, float]] = []
        lane_ids: list[str] = []
        patch_ids: set[str] = set()
        if lane_rows is not None:
            for lane in lane_rows.itertuples():
                raw_intervals.append(
                    (
                        float(lane.projected_start_m) - padding_m,
                        float(lane.projected_end_m) + padding_m,
                    )
                )
                lane_ids.append(str(lane.lane_id))
                patch_ids.add(str(lane.source_patch_ids))
        support = merge_intervals(raw_intervals, length)
        gaps = complement_intervals(support, length)
        support_length = sum(end - start for start, end in support)
        gap_lengths = [end - start for start, end in gaps]
        coverage = support_length / length if length > 1e-8 else 0.0
        max_gap = max(gap_lengths, default=0.0)
        edge_start_gap = gaps[0][1] - gaps[0][0] if gaps and gaps[0][0] <= 1e-8 else 0.0
        edge_end_gap = gaps[-1][1] - gaps[-1][0] if gaps and gaps[-1][1] >= length - 1e-8 else 0.0
        internal_gap_lengths = [
            end - start for start, end in gaps if start > 1e-8 and end < length - 1e-8
        ]
        if not lane_ids:
            support_state = "sd_only"
            reason = "no_eligible_lane_evidence"
        elif coverage >= full_coverage and max_gap <= max_gap_m:
            support_state = "hp_supported"
            reason = "full_longitudinal_support"
        else:
            support_state = "partial_hp_supported"
            reason = "longitudinal_support_has_gap"
        rows.append(
            {
                "swsd_unit_id": road_id,
                "road_length_m": length,
                "eligible_lane_count": len(lane_ids),
                "eligible_lane_ids": ";".join(sorted(lane_ids)),
                "evidence_patch_ids": ";".join(sorted(patch_ids)),
                "support_interval_count": len(support),
                "gap_interval_count": len(gaps),
                "support_length_m": support_length,
                "gap_length_m": max(0.0, length - support_length),
                "support_coverage_ratio": coverage,
                "max_gap_m": max_gap,
                "max_internal_gap_m": max(internal_gap_lengths, default=0.0),
                "start_gap_m": edge_start_gap,
                "end_gap_m": edge_end_gap,
                "support_state": support_state,
                "support_reason": reason,
            }
        )
        for interval_state, intervals in (("hp_supported", support), ("sd_gap", gaps)):
            for index, (start, end) in enumerate(intervals):
                interval_rows.append(
                    {
                        "swsd_unit_id": road_id,
                        "interval_state": interval_state,
                        "interval_index": index,
                        "start_m": start,
                        "end_m": end,
                        "start_fraction": start / length if length > 1e-8 else 0.0,
                        "end_fraction": end / length if length > 1e-8 else 1.0,
                        "interval_length_m": end - start,
                        "source_lane_ids": ";".join(sorted(lane_ids)) if interval_state == "hp_supported" else "",
                        "source_patch_ids": ";".join(sorted(patch_ids)) if interval_state == "hp_supported" else "",
                        "geometry_source": "hp_interval_candidate" if interval_state == "hp_supported" else "swsd_retained",
                        "geometry": line_part(road.geometry, start, end),
                    }
                )
    return pd.DataFrame(rows), interval_rows


def quantiles(series: pd.Series) -> dict[str, float | None]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return {"p10": None, "p50": None, "p90": None, "p95": None, "max": None}
    return {
        "p10": float(numeric.quantile(0.10)),
        "p50": float(numeric.quantile(0.50)),
        "p90": float(numeric.quantile(0.90)),
        "p95": float(numeric.quantile(0.95)),
        "max": float(numeric.max()),
    }


def quality_summary(lanes: gpd.GeoDataFrame, topology: gpd.GeoDataFrame) -> dict[str, Any]:
    width_counts = Counter(lanes["width_state"].fillna("missing"))
    patch_7930 = lanes[lanes["source_patch_ids"].astype(str).eq("5417631180197930")]
    return {
        "lane_count": int(len(lanes)),
        "width_state_counts": dict(sorted(width_counts.items())),
        "known_quality_counts": {
            "narrow_lane": int(width_counts["narrow_candidate"]),
            "wide_or_boundary_gap": int(width_counts["wide_or_boundary_gap"]),
            "width_unstable": int(width_counts["unstable"]),
            "patch_5417631180197930_boundary_insufficient": int(
                patch_7930["width_state"].eq("insufficient_evidence").sum()
            ),
            "cross_road_shared_node_direction_review": int(
                topology["lane_topo_state"].eq("cross_owner_shared_node_review").sum()
            ),
            "cross_road_semantic_node_anomaly": int(
                topology["lane_topo_state"].eq("cross_owner_semantic_unconnected_review").sum()
            ),
        },
        "road_conflict_from_quality_flags": 0,
        "quality_to_road_conflict_rule": "forbidden",
    }


def main() -> None:
    args = parse_args()
    run_root = args.m1_run.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    lanes = gpd.read_file(run_root / "p04_lane_decisions.gpkg", layer="lane_decisions").to_crs(
        args.analysis_crs
    )
    roads = gpd.read_file(run_root / "p04_swsd_skeleton.gpkg", layer="road_sections").to_crs(
        args.analysis_crs
    )
    topology = gpd.read_file(
        run_root / "p04_lane_topo_readiness.gpkg", layer="lane_topo_links"
    ).to_crs(args.analysis_crs)
    roads["swsd_unit_id"] = roads["swsd_unit_id"].astype(str)
    lanes["lane_id"] = lanes["lane_id"].astype(str)
    lanes["swsd_unit_id"] = lanes["swsd_unit_id"].astype(str)
    roads_by_id = dict(zip(roads["swsd_unit_id"], roads.geometry, strict=True))

    lane_metrics = lane_projection_rows(lanes, roads_by_id, args.projection_spacing_m)
    lane_metrics.to_csv(output_dir / "lane_projection_metrics.csv", index=False, encoding="utf-8-sig")

    sensitivity_rows: list[dict[str, Any]] = []
    selected_metrics: pd.DataFrame | None = None
    selected_intervals: list[dict[str, Any]] | None = None
    cohort_summary: dict[str, Any] = {}
    for cohort_name, predicate in COHORTS.items():
        cohort_lanes = lanes[predicate(lanes)]
        eligible_ids = set(cohort_lanes["lane_id"].astype(str))
        cohort_summary[cohort_name] = {
            "lane_count": int(len(cohort_lanes)),
            "road_with_lane_count": int(cohort_lanes["swsd_unit_id"].nunique()),
        }
        for padding_m, full_coverage, max_gap_m in POLICY_GRID:
            metrics, _ = road_metrics(
                roads,
                lane_metrics,
                eligible_ids,
                padding_m=padding_m,
                full_coverage=full_coverage,
                max_gap_m=max_gap_m,
            )
            states = Counter(metrics["support_state"])
            sensitivity_rows.append(
                {
                    "cohort": cohort_name,
                    "padding_m": padding_m,
                    "full_coverage": full_coverage,
                    "max_gap_m": max_gap_m,
                    "hp_supported": states["hp_supported"],
                    "partial_hp_supported": states["partial_hp_supported"],
                    "sd_only": states["sd_only"],
                    "conflict_retained": 0,
                    "road_total": int(len(metrics)),
                    "coverage_p50": float(metrics["support_coverage_ratio"].median()),
                    "coverage_p90": float(metrics["support_coverage_ratio"].quantile(0.90)),
                }
            )
        if cohort_name == args.selected_cohort:
            selected_metrics, selected_intervals = road_metrics(
                roads,
                lane_metrics,
                eligible_ids,
                padding_m=args.selected_padding_m,
                full_coverage=args.selected_full_coverage,
                max_gap_m=args.selected_max_gap_m,
            )

    if selected_metrics is None or selected_intervals is None:
        raise AssertionError("selected cohort was not evaluated")
    sensitivity = pd.DataFrame(sensitivity_rows)
    sensitivity.to_csv(output_dir / "policy_sensitivity.csv", index=False, encoding="utf-8-sig")
    selected_metrics.to_csv(output_dir / "selected_road_metrics.csv", index=False, encoding="utf-8-sig")
    interval_gdf = gpd.GeoDataFrame(selected_intervals, geometry="geometry", crs=args.analysis_crs)
    interval_gdf.to_file(
        output_dir / "selected_support_intervals.gpkg",
        layer="support_intervals",
        driver="GPKG",
        index=False,
    )

    selected_states = Counter(selected_metrics["support_state"])
    credible_projection_issues = lane_metrics[
        lane_metrics["owner_state"].eq("accepted")
        & (
            lane_metrics["projection_monotonicity"].lt(0.80)
            | lane_metrics["projected_span_to_lane_ratio"].lt(0.60)
        )
    ]
    summary = {
        "analysis_crs": args.analysis_crs,
        "m1_run": str(run_root),
        "road_count": int(len(roads)),
        "lane_count": int(len(lanes)),
        "cohorts": cohort_summary,
        "quality": quality_summary(lanes, topology),
        "projection_metrics": {
            "owner_accepted_lane_count": int(lane_metrics["owner_state"].eq("accepted").sum()),
            "monotonicity_quantiles": quantiles(
                lane_metrics.loc[lane_metrics["owner_state"].eq("accepted"), "projection_monotonicity"]
            ),
            "span_ratio_quantiles": quantiles(
                lane_metrics.loc[
                    lane_metrics["owner_state"].eq("accepted"), "projected_span_to_lane_ratio"
                ]
            ),
            "credible_projection_review_count": int(len(credible_projection_issues)),
            "credible_projection_review_lane_ids": credible_projection_issues["lane_id"].tolist(),
            "note": "projection review is a candidate diagnostic, not an automatic Road conflict",
        },
        "selected_policy": {
            "cohort": args.selected_cohort,
            "padding_m": args.selected_padding_m,
            "full_coverage": args.selected_full_coverage,
            "max_gap_m": args.selected_max_gap_m,
            "support_state_counts": {
                "hp_supported": int(selected_states["hp_supported"]),
                "partial_hp_supported": int(selected_states["partial_hp_supported"]),
                "sd_only": int(selected_states["sd_only"]),
                "conflict_retained": 0,
            },
            "road_conservation": int(sum(selected_states.values())) == int(len(roads)),
            "support_coverage_quantiles": quantiles(selected_metrics["support_coverage_ratio"]),
            "max_gap_quantiles_m": quantiles(selected_metrics["max_gap_m"]),
            "max_internal_gap_quantiles_m": quantiles(selected_metrics["max_internal_gap_m"]),
            "start_gap_quantiles_m": quantiles(selected_metrics["start_gap_m"]),
            "end_gap_quantiles_m": quantiles(selected_metrics["end_gap_m"]),
        },
        "interpretation_limits": [
            "All thresholds are single-Case POC candidates, not production rules.",
            "Input quality flags do not directly create conflict_retained.",
            "restriction, Laneinfo, RoadSplit and movement legality are excluded from Milestone 2.",
        ],
    }
    (output_dir / "analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
