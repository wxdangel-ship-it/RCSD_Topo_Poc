from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import shapefile
from pyproj import CRS
from shapely.geometry import shape

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    announce,
    build_logger,
    build_run_id,
    close_logger,
    minimal_geometry_repair,
    remove_existing_output,
    resolve_shapefile_crs,
    transform_geometry_to_target,
    write_geojson,
    write_json,
)


RUN_ID_PREFIX = "t00_tool6_node_export"
PROGRESS_INTERVAL = 1000
PROJECT_GEOJSON_NOTE = (
    "GeoJSON output is written in EPSG:3857 per project convention. "
    "This is a project-internal export and may not fully satisfy standard GeoJSON interoperability expectations."
)


@dataclass(frozen=True)
class ShapefileGeoJsonExportConfig:
    input_path: Path
    output_path: Path
    target_epsg: int = 3857
    default_input_crs_text: str | None = None
    run_id: str | None = None


def _should_report_progress(index: int, total: int, interval: int = PROGRESS_INTERVAL) -> bool:
    return index == 1 or index == total or index % interval == 0


def _write_summary(summary_path: Path, summary: dict[str, Any]) -> None:
    write_json(summary_path, summary)


def run_shapefile_geojson_export(config: ShapefileGeoJsonExportConfig) -> dict[str, Any]:
    input_path = config.input_path.expanduser().resolve()
    output_path = config.output_path.expanduser().resolve()
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = config.run_id or build_run_id(RUN_ID_PREFIX)
    log_path = output_dir / f"{run_id}.log"
    summary_path = output_dir / f"{run_id}_summary.json"
    logger = build_logger(log_path, run_id)
    target_crs = CRS.from_epsg(config.target_epsg)
    target_crs_text = target_crs.to_string()

    summary: dict[str, Any] = {
        "run_id": run_id,
        "tool": "Tool6",
        "status": "started",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "log_path": str(log_path),
        "summary_path": str(summary_path),
        "input_feature_count": 0,
        "output_feature_count": 0,
        "input_crs": None,
        "output_crs": target_crs_text,
        "repaired_feature_count": 0,
        "failed_feature_count": 0,
        "field_names": [],
        "geometry_type_summary": {},
        "failed_feature_indexes": [],
        "error_reason_summary": {},
        "blocking_reason": None,
        "geojson_interop_note": PROJECT_GEOJSON_NOTE,
    }

    try:
        announce(logger, f"Tool6 node export started. input_path={input_path}")

        if not input_path.is_file():
            summary["status"] = "blocked"
            summary["blocking_reason"] = f"input shapefile does not exist: {input_path}"
            announce(logger, f"Tool6 blocked. reason={summary['blocking_reason']}")
            _write_summary(summary_path, summary)
            return summary

        announce(logger, "[Stage 1/4] Read shapefile metadata and resolve CRS.")
        try:
            source_crs, crs_source = resolve_shapefile_crs(input_path, config.default_input_crs_text)
        except Exception as exc:
            summary["status"] = "blocked"
            summary["blocking_reason"] = str(exc)
            announce(logger, f"Tool6 blocked. reason={exc}")
            _write_summary(summary_path, summary)
            return summary

        reader = shapefile.Reader(str(input_path))
        field_names = [field[0] for field in reader.fields[1:]]
        total_feature_count = len(reader)
        summary["input_feature_count"] = total_feature_count
        summary["input_crs"] = source_crs.to_string()
        summary["input_crs_source"] = crs_source
        summary["field_names"] = field_names
        summary["target_epsg"] = config.target_epsg

        announce(
            logger,
            "[Stage 2/4] Transform geometries to target CRS and minimally repair invalid features. "
            f"target_crs={target_crs_text}",
        )
        remove_existing_output(output_path)

        geometry_type_counter = Counter()
        error_reason_counter = Counter()
        failed_feature_indexes: list[int] = []
        repaired_feature_count = 0
        output_features: list[dict[str, Any]] = []

        for index, shape_record in enumerate(reader.iterShapeRecords(), start=1):
            try:
                raw_geometry = shape(shape_record.shape.__geo_interface__)
                geometry_type_counter[raw_geometry.geom_type] += 1
                transformed_geometry = transform_geometry_to_target(raw_geometry, source_crs, target_crs)

                if transformed_geometry.is_empty:
                    raise ValueError("geometry became empty after transform")

                repaired_geometry = transformed_geometry
                if not transformed_geometry.is_valid:
                    repaired_geometry = minimal_geometry_repair(transformed_geometry)
                    if repaired_geometry is None:
                        raise ValueError("minimal repair failed")
                    repaired_feature_count += 1

                properties = {
                    field_names[field_index]: shape_record.record[field_index]
                    for field_index in range(len(field_names))
                }
                output_features.append(
                    {
                        "properties": properties,
                        "geometry": repaired_geometry,
                    }
                )
            except Exception as exc:
                failed_feature_indexes.append(index)
                error_reason_counter[str(exc)] += 1

            if _should_report_progress(index, total_feature_count):
                announce(logger, f"[Feature {index}/{total_feature_count}] export progress")

        announce(logger, "[Stage 3/4] Write nodes.geojson output.")
        write_geojson(output_path, output_features, crs_text=target_crs_text)

        announce(logger, "[Stage 4/4] Write summary and finish Tool6.")
        summary["status"] = "completed"
        summary["output_feature_count"] = len(output_features)
        summary["repaired_feature_count"] = repaired_feature_count
        summary["failed_feature_count"] = len(failed_feature_indexes)
        summary["geometry_type_summary"] = dict(geometry_type_counter)
        summary["failed_feature_indexes"] = failed_feature_indexes
        summary["error_reason_summary"] = dict(error_reason_counter)
        _write_summary(summary_path, summary)
        announce(
            logger,
            "Tool6 node export finished. "
            f"input_feature_count={total_feature_count} output_feature_count={len(output_features)} "
            f"repaired_feature_count={repaired_feature_count} failed_feature_count={len(failed_feature_indexes)}",
        )
        return summary
    finally:
        close_logger(logger)
