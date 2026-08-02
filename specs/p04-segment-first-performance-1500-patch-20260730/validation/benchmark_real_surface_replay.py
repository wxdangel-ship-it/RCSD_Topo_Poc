from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys
import time

import geopandas as gpd
from shapely import from_wkb, get_num_coordinates
from shapely.geometry import LineString


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_geometry_cache import (  # noqa: E402
    buffered_union,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_geometry_metrics import (  # noqa: E402
    surface_coverage,
    surface_coverage_at_least,
    surface_coverage_runtime_stats,
)


REPLAY_LINE_LAYERS = (
    "road_carriers",
    "road_geometry_sources",
    "node_connection_evidence",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay exact P04 surface coverage with DriveZone and line "
            "geometries retained in one historical Segment-first run."
        )
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--buffer-m", type=float, default=1.0)
    parser.add_argument("--minimum-speedup", type=float, default=2.0)
    parser.add_argument("--minimum-coverage", type=float, default=0.9)
    parser.add_argument("--stress-query-count", type=int, default=5000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_root = args.run_root.resolve()
    comparison_path = run_root / "p04_segment_first_comparison.gpkg"
    audit_path = run_root / "p04_segment_first_audit.gpkg"
    if not comparison_path.is_file() or not audit_path.is_file():
        raise FileNotFoundError(
            "run root must contain comparison and audit GPKGs"
        )

    drivezones = gpd.read_file(comparison_path, layer="drivezones")
    surface = buffered_union(drivezones, args.buffer_m)
    lines: list[object] = []
    line_counts: dict[str, int] = {}
    for layer_name in REPLAY_LINE_LAYERS:
        frame = gpd.read_file(audit_path, layer=layer_name)
        selected = [
            geometry
            for geometry in frame.geometry
            if geometry is not None
            and not geometry.is_empty
            and geometry.geom_type in {"LineString", "MultiLineString"}
            and geometry.length > 1e-9
        ]
        line_counts[layer_name] = len(selected)
        lines.extend(selected)
    if not lines:
        raise ValueError("no replay line geometry was found")
    actual_line_count = len(lines)
    rng = random.Random(20260802)
    min_x, min_y, max_x, max_y = surface.bounds
    for _ in range(max(0, args.stress_query_count)):
        x1 = rng.uniform(min_x - 200.0, max_x + 200.0)
        y1 = rng.uniform(min_y - 200.0, max_y + 200.0)
        x2 = x1 + rng.uniform(-600.0, 600.0)
        y2 = y1 + rng.uniform(-600.0, 600.0)
        lines.append(LineString([(x1, y1), (x2, y2)]))

    started = time.perf_counter()
    expected_coverages = [
        float(line.intersection(surface).length / line.length)
        for line in lines
    ]
    direct_seconds = time.perf_counter() - started
    expected_decisions = [
        coverage + 1e-9 >= args.minimum_coverage
        for coverage in expected_coverages
    ]

    started = time.perf_counter()
    actual_decisions = [
        surface_coverage_at_least(
            line,
            surface,
            args.minimum_coverage,
            epsilon=1e-9,
        )
        for line in lines
    ]
    predicate_seconds = time.perf_counter() - started

    numeric_surface = from_wkb(surface.wkb)
    started = time.perf_counter()
    actual_coverages = [
        surface_coverage(line, numeric_surface)
        for line in lines
    ]
    numeric_seconds = time.perf_counter() - started
    runtime_stats = surface_coverage_runtime_stats()
    decision_mismatch_count = sum(
        expected_value != actual_value
        for expected_value, actual_value in zip(
            expected_decisions,
            actual_decisions,
            strict=True,
        )
    )
    numeric_mismatch_count = sum(
        expected_value != actual_value
        for expected_value, actual_value in zip(
            expected_coverages,
            actual_coverages,
            strict=True,
        )
    )
    maximum_absolute_difference = max(
        (
            abs(expected_value - actual_value)
            for expected_value, actual_value in zip(
                expected_coverages,
                actual_coverages,
                strict=True,
            )
        ),
        default=0.0,
    )
    speedup = (
        direct_seconds / predicate_seconds
        if predicate_seconds > 1e-12
        else float("inf")
    )
    numeric_speedup = (
        direct_seconds / numeric_seconds
        if numeric_seconds > 1e-12
        else float("inf")
    )
    passed = (
        decision_mismatch_count == 0
        and numeric_mismatch_count == 0
        and speedup >= args.minimum_speedup
        and numeric_speedup >= args.minimum_speedup
        and int(runtime_stats["unsafe_local_reconstruction_count"]) == 0
    )
    payload = {
        "status": "passed" if passed else "failed",
        "run_root": str(run_root),
        "drivezone_rows": len(drivezones),
        "surface_geometry_type": surface.geom_type,
        "surface_component_count": (
            len(surface.geoms)
            if hasattr(surface, "geoms")
            else 1
        ),
        "surface_coordinate_count": int(get_num_coordinates(surface)),
        "line_counts": line_counts,
        "actual_line_count": actual_line_count,
        "stress_query_count": max(0, args.stress_query_count),
        "query_count": len(lines),
        "direct_seconds": direct_seconds,
        "predicate_seconds": predicate_seconds,
        "numeric_seconds": numeric_seconds,
        "speedup": speedup,
        "numeric_speedup": numeric_speedup,
        "minimum_speedup": args.minimum_speedup,
        "minimum_coverage": args.minimum_coverage,
        "decision_mismatch_count": decision_mismatch_count,
        "numeric_exact_mismatch_count": numeric_mismatch_count,
        "maximum_absolute_difference": maximum_absolute_difference,
        "runtime_stats": runtime_stats,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    report_path = args.report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
