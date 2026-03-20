from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    announce,
    build_logger,
    build_run_id,
    close_logger,
    list_patch_dirs,
    minimal_repair,
    polygon_part_count,
    read_geojson_features,
    remove_existing_output,
    simplify_polygonal,
    write_geojson,
    write_json,
)


RUN_ID_PREFIX = "t00_tool3_intersection_merge"


@dataclass(frozen=True)
class IntersectionMergeConfig:
    patch_all_root: Path
    default_input_crs_text: str = "EPSG:4326"
    simplify_tolerance_meters: float = 0.3
    output_name: str = "Intersection.geojson"
    run_id: str | None = None


def _error_counter(patch_results: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter()
    for item in patch_results:
        reason = item.get("error_reason")
        if reason:
            counter[reason] += 1
    return dict(counter)


def _aggregate_bounds(features: list[dict[str, Any]]) -> list[float] | None:
    bounds_values = [
        feature["geometry"].bounds
        for feature in features
        if feature.get("geometry") is not None and not feature["geometry"].is_empty
    ]
    if not bounds_values:
        return None

    min_x = min(item[0] for item in bounds_values)
    min_y = min(item[1] for item in bounds_values)
    max_x = max(item[2] for item in bounds_values)
    max_y = max(item[3] for item in bounds_values)
    return [float(min_x), float(min_y), float(max_x), float(max_y)]


def run_intersection_merge(config: IntersectionMergeConfig) -> dict[str, Any]:
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

        announce(logger, f"Tool3 Intersection merge started. patch_all_root={patch_all_root}")
        announce(logger, f"[Stage 1/4] Discover patch directories. total_patch_count={total_patch_count}")

        patch_results: list[dict[str, Any]] = []
        output_features: list[dict[str, Any]] = []
        input_found_count = 0
        processed_patch_count = 0
        skip_missing_count = 0
        skip_error_count = 0
        total_input_feature_count = 0
        patchid_collision_count = 0

        announce(logger, "[Stage 2/4] Preprocess per-patch Intersection features and append patchid.")
        for index, patch_dir in enumerate(patch_dirs, start=1):
            patch_id = patch_dir.name
            input_path = patch_dir / "Vector" / "Intersection.geojson"
            announce(logger, f"[Patch {index}/{total_patch_count}] patch_id={patch_id} start")

            if not input_path.is_file():
                skip_missing_count += 1
                patch_results.append(
                    {
                        "patch_id": patch_id,
                        "status": "skip_missing",
                        "input_path": str(input_path),
                        "input_feature_count": 0,
                        "output_feature_count": 0,
                        "patchid_collision_count": 0,
                        "error_reason": "missing Intersection.geojson",
                    }
                )
                announce(logger, f"[Patch {index}/{total_patch_count}] patch_id={patch_id} missing Intersection.geojson")
                continue

            input_found_count += 1
            try:
                read_result = read_geojson_features(
                    input_path,
                    default_crs_text=config.default_input_crs_text,
                )
                total_input_feature_count += len(read_result.features)
                patch_output_feature_count = 0
                patch_collision_count = 0

                for feature in read_result.features:
                    repaired = minimal_repair(feature.geometry)
                    if repaired is None:
                        continue
                    simplified = simplify_polygonal(repaired, config.simplify_tolerance_meters)
                    if simplified is None:
                        continue

                    properties = dict(feature.properties)
                    if "patchid" in properties:
                        properties["patchid_orig"] = properties["patchid"]
                        patch_collision_count += 1
                    properties["patchid"] = patch_id

                    output_features.append(
                        {
                            "properties": properties,
                            "geometry": simplified,
                        }
                    )
                    patch_output_feature_count += 1

                if patch_output_feature_count == 0:
                    raise ValueError("no valid polygonal features remained after repair and simplify")

                patchid_collision_count += patch_collision_count
                processed_patch_count += 1
                patch_results.append(
                    {
                        "patch_id": patch_id,
                        "status": "processed",
                        "input_path": str(input_path),
                        "input_feature_count": len(read_result.features),
                        "source_crs": read_result.source_crs.to_string(),
                        "crs_source": read_result.crs_source,
                        "output_feature_count": patch_output_feature_count,
                        "patchid_collision_count": patch_collision_count,
                        "error_reason": None,
                    }
                )
                announce(
                    logger,
                    f"[Patch {index}/{total_patch_count}] patch_id={patch_id} processed "
                    f"input_feature_count={len(read_result.features)} output_feature_count={patch_output_feature_count}",
                )
            except Exception as exc:
                skip_error_count += 1
                patch_results.append(
                    {
                        "patch_id": patch_id,
                        "status": "skip_error",
                        "input_path": str(input_path),
                        "input_feature_count": 0,
                        "output_feature_count": 0,
                        "patchid_collision_count": 0,
                        "error_reason": str(exc),
                    }
                )
                announce(
                    logger,
                    f"[Patch {index}/{total_patch_count}] patch_id={patch_id} skip_error reason={exc}",
                )

        announce(logger, "[Stage 3/4] Write the aggregated global Intersection output.")
        write_geojson(output_path, output_features)

        announce(logger, "[Stage 4/4] Write summary and finish Tool3.")
        summary = {
            "run_id": run_id,
            "tool": "Tool3",
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
            "output_polygon_count": sum(polygon_part_count(item["geometry"]) for item in output_features),
            "patchid_collision_count": patchid_collision_count,
            "output_bounds_3857": _aggregate_bounds(output_features),
            "simplify_tolerance_meters": config.simplify_tolerance_meters,
            "error_reason_summary": _error_counter(patch_results),
            "patch_results": patch_results,
        }
        write_json(summary_path, summary)
        announce(
            logger,
            "Tool3 Intersection merge finished. "
            f"processed_patch_count={processed_patch_count} skip_missing_count={skip_missing_count} "
            f"skip_error_count={skip_error_count} output_feature_count={len(output_features)}",
        )
        return summary
    finally:
        close_logger(logger)
