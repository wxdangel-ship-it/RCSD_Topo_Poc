from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    announce,
    build_logger,
    build_run_id,
    close_logger,
    geometry_bounds,
    list_patch_dirs,
    minimal_repair,
    polygon_part_count,
    read_geojson_features,
    remove_existing_output,
    simplify_polygonal,
    write_geojson,
    write_json,
)


RUN_ID_PREFIX = "t00_tool2_drivezone_merge"


@dataclass(frozen=True)
class DriveZoneMergeConfig:
    patch_all_root: Path
    default_input_crs_text: str = "EPSG:4326"
    buffer_distance_meters: float = 5.0
    patch_simplify_tolerance_meters: float = 0.5
    output_name: str = "DriveZone.geojson"
    run_id: str | None = None


def _error_counter(patch_results: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter()
    for item in patch_results:
        reason = item.get("error_reason")
        if reason:
            counter[reason] += 1
    return dict(counter)


def _aggregate_bounds(geometries: list[Any]) -> list[float] | None:
    bounds_values = [geometry_bounds(geometry) for geometry in geometries]
    bounds_values = [bounds for bounds in bounds_values if bounds is not None]
    if not bounds_values:
        return None

    min_x = min(bounds[0] for bounds in bounds_values)
    min_y = min(bounds[1] for bounds in bounds_values)
    max_x = max(bounds[2] for bounds in bounds_values)
    max_y = max(bounds[3] for bounds in bounds_values)
    return [float(min_x), float(min_y), float(max_x), float(max_y)]


def run_drivezone_merge(config: DriveZoneMergeConfig) -> dict[str, Any]:
    patch_all_root = config.patch_all_root.expanduser().resolve()
    if not patch_all_root.is_dir():
        raise ValueError(f"patch_all root does not exist or is not a directory: {patch_all_root}")

    run_id = config.run_id or build_run_id(RUN_ID_PREFIX)
    output_path = patch_all_root / config.output_name
    log_path = patch_all_root / f"{run_id}.log"
    summary_path = patch_all_root / f"{run_id}_summary.json"
    logger = build_logger(log_path, run_id)

    try:
        patch_dirs = list_patch_dirs(patch_all_root)
        total_patch_count = len(patch_dirs)
        remove_existing_output(output_path)

        announce(logger, f"Tool2 DriveZone merge started. patch_all_root={patch_all_root}")
        announce(logger, f"[Stage 1/4] Discover patch directories. total_patch_count={total_patch_count}")

        patch_results: list[dict[str, Any]] = []
        processed_items: list[dict[str, Any]] = []
        input_found_count = 0
        processed_patch_count = 0
        skip_missing_count = 0
        skip_error_count = 0
        total_input_feature_count = 0

        announce(logger, "[Stage 2/4] Preprocess per-patch DriveZone and collect patch-level outputs.")
        for index, patch_dir in enumerate(patch_dirs, start=1):
            patch_id = patch_dir.name
            input_path = patch_dir / "Vector" / "DriveZone.geojson"
            announce(logger, f"[Patch {index}/{total_patch_count}] patch_id={patch_id} start")

            if not input_path.is_file():
                skip_missing_count += 1
                patch_results.append(
                    {
                        "patch_id": patch_id,
                        "status": "skip_missing",
                        "input_path": str(input_path),
                        "input_feature_count": 0,
                        "output_polygon_count": 0,
                        "output_area_m2": 0.0,
                        "error_reason": "missing DriveZone.geojson",
                    }
                )
                announce(logger, f"[Patch {index}/{total_patch_count}] patch_id={patch_id} missing DriveZone.geojson")
                continue

            input_found_count += 1
            try:
                read_result = read_geojson_features(
                    input_path,
                    default_crs_text=config.default_input_crs_text,
                )
                total_input_feature_count += len(read_result.features)
                polygon_geometries = []
                for feature in read_result.features:
                    repaired = minimal_repair(feature.geometry)
                    if repaired is not None:
                        polygon_geometries.append(repaired)

                if not polygon_geometries:
                    raise ValueError("no valid polygonal geometry remained after repair")

                merged_geometry = minimal_repair(unary_union(polygon_geometries))
                if merged_geometry is None:
                    raise ValueError("single-patch dissolve produced no valid polygonal geometry")

                buffered_geometry = minimal_repair(merged_geometry.buffer(config.buffer_distance_meters))
                if buffered_geometry is None:
                    raise ValueError("single-patch positive buffer produced no valid polygonal geometry")

                eroded_geometry = minimal_repair(buffered_geometry.buffer(-config.buffer_distance_meters))
                if eroded_geometry is None:
                    raise ValueError("single-patch negative buffer produced no valid polygonal geometry")

                simplified_geometry = simplify_polygonal(eroded_geometry, config.patch_simplify_tolerance_meters)
                if simplified_geometry is None:
                    raise ValueError("single-patch simplify produced no valid polygonal geometry")

                processed_items.append(
                    {
                        "patch_id": patch_id,
                        "geometry": simplified_geometry,
                    }
                )
                processed_patch_count += 1
                patch_results.append(
                    {
                        "patch_id": patch_id,
                        "status": "processed",
                        "input_path": str(input_path),
                        "input_feature_count": len(read_result.features),
                        "source_crs": read_result.source_crs.to_string(),
                        "crs_source": read_result.crs_source,
                        "output_polygon_count": polygon_part_count(simplified_geometry),
                        "output_area_m2": float(simplified_geometry.area),
                        "error_reason": None,
                    }
                )
                announce(
                    logger,
                    f"[Patch {index}/{total_patch_count}] patch_id={patch_id} processed "
                    f"input_feature_count={len(read_result.features)} output_polygon_count={polygon_part_count(simplified_geometry)}",
                )
            except Exception as exc:
                skip_error_count += 1
                patch_results.append(
                    {
                        "patch_id": patch_id,
                        "status": "skip_error",
                        "input_path": str(input_path),
                        "input_feature_count": 0,
                        "output_polygon_count": 0,
                        "output_area_m2": 0.0,
                        "error_reason": str(exc),
                    }
                )
                announce(
                    logger,
                    f"[Patch {index}/{total_patch_count}] patch_id={patch_id} skip_error reason={exc}",
                )

        announce(logger, "[Stage 3/4] Aggregate per-patch DriveZone outputs into the global file.")
        output_features: list[dict[str, Any]] = []
        output_polygon_count = 0
        output_area_m2 = 0.0
        output_bounds = None
        if processed_items:
            output_features = [
                {
                    "properties": {},
                    "geometry": item["geometry"],
                }
                for item in processed_items
            ]
            output_polygon_count = sum(polygon_part_count(item["geometry"]) for item in processed_items)
            output_area_m2 = sum(float(item["geometry"].area) for item in processed_items)
            output_bounds = _aggregate_bounds([item["geometry"] for item in processed_items])

        write_geojson(output_path, output_features)

        announce(logger, "[Stage 4/4] Write summary and finish Tool2.")
        summary = {
            "run_id": run_id,
            "tool": "Tool2",
            "patch_all_root": str(patch_all_root),
            "output_path": str(output_path),
            "log_path": str(log_path),
            "summary_path": str(summary_path),
            "total_patch_count": total_patch_count,
            "input_found_count": input_found_count,
            "processed_patch_count": processed_patch_count,
            "skip_missing_count": skip_missing_count,
            "skip_error_count": skip_error_count,
            "total_input_feature_count": total_input_feature_count,
            "output_feature_count": len(output_features),
            "output_polygon_count": output_polygon_count,
            "output_area_m2": output_area_m2,
            "output_bounds_3857": output_bounds,
            "buffer_distance_meters": config.buffer_distance_meters,
            "patch_simplify_tolerance_meters": config.patch_simplify_tolerance_meters,
            "error_reason_summary": _error_counter(patch_results),
            "patch_results": patch_results,
        }
        write_json(summary_path, summary)
        announce(
            logger,
            "Tool2 DriveZone merge finished. "
            f"processed_patch_count={processed_patch_count} skip_missing_count={skip_missing_count} "
            f"skip_error_count={skip_error_count} output_feature_count={len(output_features)}",
        )
        return summary
    finally:
        close_logger(logger)
