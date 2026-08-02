from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
from shapely import union_all
from shapely.geometry import LineString, box

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_geometry_metrics import (
    surface_coverage,
    surface_coverage_runtime_stats,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark exact P04 coverage against a 1500-part surface.",
    )
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--component-count", type=int, default=1500)
    parser.add_argument("--query-count", type=int, default=2000)
    parser.add_argument("--minimum-speedup", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    polygons = np.asarray(
        [
            box(
                (index % 50) * 100.0,
                (index // 50) * 100.0,
                (index % 50) * 100.0 + 20.0,
                (index // 50) * 100.0 + 20.0,
            )
            for index in range(args.component_count)
        ],
        dtype=object,
    )
    surface = union_all(polygons).buffer(1.0)
    lines = [
        LineString(
            [
                (
                    (index % 500) * 10.0 + (index // 500) * 0.123,
                    ((index * 17) % 300) * 10.0 + 10.0,
                ),
                (
                    (index % 500) * 10.0 + (index // 500) * 0.123 + 15.0,
                    ((index * 17) % 300) * 10.0 + 10.0,
                ),
            ]
        )
        for index in range(args.query_count)
    ]

    started = time.perf_counter()
    expected = [
        float(line.intersection(surface).length / line.length)
        for line in lines
    ]
    direct_seconds = time.perf_counter() - started

    started = time.perf_counter()
    actual = [surface_coverage(line, surface) for line in lines]
    indexed_seconds = time.perf_counter() - started

    mismatch_count = sum(
        expected_value != actual_value
        for expected_value, actual_value in zip(expected, actual, strict=True)
    )
    maximum_absolute_difference = max(
        (
            abs(expected_value - actual_value)
            for expected_value, actual_value in zip(expected, actual, strict=True)
        ),
        default=0.0,
    )
    speedup = (
        direct_seconds / indexed_seconds
        if indexed_seconds > 1e-12
        else float("inf")
    )
    passed = mismatch_count == 0 and speedup >= args.minimum_speedup
    runtime_stats = surface_coverage_runtime_stats()
    payload = {
        "status": "passed" if passed else "failed",
        "component_count": args.component_count,
        "surface_geometry_type": surface.geom_type,
        "query_count": args.query_count,
        "direct_seconds": direct_seconds,
        "indexed_seconds": indexed_seconds,
        "speedup": speedup,
        "minimum_speedup": args.minimum_speedup,
        "exact_mismatch_count": mismatch_count,
        "maximum_absolute_difference": maximum_absolute_difference,
        "runtime_stats": runtime_stats,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report_path is not None:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
