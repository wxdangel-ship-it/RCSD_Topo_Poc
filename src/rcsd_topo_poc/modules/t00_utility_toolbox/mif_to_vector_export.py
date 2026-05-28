from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fiona
from pyproj import CRS

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    announce,
    build_logger,
    build_run_id,
    close_logger,
    normalize_runtime_path,
    remove_existing_output,
    write_json,
)


RUN_ID_PREFIX = "t00_tool11_mif_to_vector"
PROGRESS_INTERVAL = 10000
DEFAULT_INNERNET_MIF_DIR = Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/SW/MIF")


@dataclass(frozen=True)
class MifToVectorConfig:
    input_path: Path
    default_crs_text: str | None = None
    progress_interval: int = PROGRESS_INTERVAL
    run_id: str | None = None


def _sanitize_layer_name(name: str) -> str:
    sanitized = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(name)).strip("_")
    if not sanitized:
        sanitized = "layer"
    if sanitized[0].isdigit():
        sanitized = f"layer_{sanitized}"
    return sanitized


def _plain_properties(properties: Any) -> dict[str, Any]:
    if properties is None:
        return {}
    if isinstance(properties, dict):
        return dict(properties)
    if hasattr(properties, "items"):
        return dict(properties)
    return {}


def _resolve_source_crs(source: Any, input_path: Path, default_crs_text: str | None) -> tuple[CRS, str]:
    crs_wkt = getattr(source, "crs_wkt", None)
    if crs_wkt:
        return CRS.from_wkt(crs_wkt), "layer.crs_wkt"
    crs_mapping = getattr(source, "crs", None)
    if crs_mapping:
        return CRS.from_user_input(crs_mapping), "layer.crs"
    if default_crs_text:
        return CRS.from_user_input(default_crs_text), "default"
    raise ValueError(f"CRS not found for MIF and no default CRS configured: {input_path}")


def _safe_feature_count(source: Any) -> int | None:
    try:
        return len(source)
    except Exception:
        return None


def _discover_mif_inputs(input_path: Path) -> tuple[str, list[Path]]:
    if input_path.is_dir():
        paths = sorted(
            [path for path in input_path.iterdir() if path.is_file() and path.suffix.lower() == ".mif"],
            key=lambda path: path.name.lower(),
        )
        return "directory", paths
    if input_path.is_file():
        if input_path.suffix.lower() != ".mif":
            raise ValueError(f"single-file Tool11 input must be a .mif file: {input_path}")
        return "file", [input_path]
    raise ValueError(f"Tool11 input path does not exist: {input_path}")


def _should_report_progress(index: int, interval: int) -> bool:
    return index == 1 or (interval > 0 and index % interval == 0)


def _write_geojson(
    input_path: Path,
    output_path: Path,
    *,
    source_crs: CRS,
    default_crs_text: str | None,
    progress_interval: int,
    logger: Any,
) -> dict[str, Any]:
    remove_existing_output(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    geometry_counter: Counter[str] = Counter()
    error_counter: Counter[str] = Counter()
    feature_count = 0
    failed_feature_count = 0

    with fiona.open(str(input_path)) as source:
        schema = dict(source.schema or {})
        with fiona.open(
            str(output_path),
            mode="w",
            driver="GeoJSON",
            schema=schema,
            crs_wkt=source_crs.to_wkt(),
            encoding="UTF-8",
        ) as target:
            for index, feature in enumerate(source, start=1):
                try:
                    geometry = feature.get("geometry")
                    if geometry is None:
                        raise ValueError("missing geometry")
                    geometry_type = str(geometry.get("type") if hasattr(geometry, "get") else "") or "Unknown"
                    payload = {
                        "type": "Feature",
                        "properties": _plain_properties(feature.get("properties")),
                        "geometry": geometry,
                    }
                    target.write(payload)
                    geometry_counter[geometry_type] += 1
                    feature_count += 1
                    if _should_report_progress(index, progress_interval):
                        announce(logger, f"[Tool11] {output_path.name}: wrote {feature_count} GeoJSON feature(s)")
                except Exception as exc:
                    failed_feature_count += 1
                    error_counter[str(exc)] += 1

    return {
        "output_path": str(output_path),
        "output_format": "GeoJSON",
        "output_crs": source_crs.to_string(),
        "feature_count": feature_count,
        "failed_feature_count": failed_feature_count,
        "geometry_type_summary": dict(geometry_counter),
        "error_reason_summary": dict(error_counter),
        "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
    }


def _write_gpkg(
    input_path: Path,
    output_path: Path,
    *,
    source_crs: CRS,
    default_crs_text: str | None,
    progress_interval: int,
    logger: Any,
) -> dict[str, Any]:
    remove_existing_output(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    layer_name = _sanitize_layer_name(input_path.stem)
    geometry_counter: Counter[str] = Counter()
    error_counter: Counter[str] = Counter()
    feature_count = 0
    failed_feature_count = 0

    with fiona.open(str(input_path)) as source:
        schema = dict(source.schema or {})
        with fiona.open(
            str(output_path),
            mode="w",
            driver="GPKG",
            layer=layer_name,
            schema=schema,
            crs_wkt=source_crs.to_wkt(),
        ) as target:
            for index, feature in enumerate(source, start=1):
                try:
                    geometry = feature.get("geometry")
                    if geometry is None:
                        raise ValueError("missing geometry")
                    geometry_type = str(geometry.get("type") if hasattr(geometry, "get") else "") or "Unknown"
                    payload = {
                        "type": "Feature",
                        "properties": _plain_properties(feature.get("properties")),
                        "geometry": geometry,
                    }
                    target.write(payload)
                    geometry_counter[geometry_type] += 1
                    feature_count += 1
                    if _should_report_progress(index, progress_interval):
                        announce(logger, f"[Tool11] {output_path.name}: wrote {feature_count} GPKG feature(s)")
                except Exception as exc:
                    failed_feature_count += 1
                    error_counter[str(exc)] += 1

    return {
        "output_path": str(output_path),
        "output_format": "GPKG",
        "output_crs": source_crs.to_string(),
        "layer_name": layer_name,
        "feature_count": feature_count,
        "failed_feature_count": failed_feature_count,
        "geometry_type_summary": dict(geometry_counter),
        "error_reason_summary": dict(error_counter),
        "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
    }


def _convert_single_mif(
    input_path: Path,
    *,
    default_crs_text: str | None,
    progress_interval: int,
    logger: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    geojson_output_path = input_path.with_suffix(".geojson")
    gpkg_output_path = input_path.with_suffix(".gpkg")

    with fiona.open(str(input_path)) as source:
        source_crs, crs_source = _resolve_source_crs(source, input_path, default_crs_text)
        source_feature_count = _safe_feature_count(source)
        field_names = list((source.schema.get("properties") if source.schema else {}) or {})
        input_driver = getattr(source, "driver", None)
        input_schema = dict(source.schema or {})

    geojson_summary = _write_geojson(
        input_path,
        geojson_output_path,
        source_crs=source_crs,
        default_crs_text=default_crs_text,
        progress_interval=progress_interval,
        logger=logger,
    )
    gpkg_summary = _write_gpkg(
        input_path,
        gpkg_output_path,
        source_crs=source_crs,
        default_crs_text=default_crs_text,
        progress_interval=progress_interval,
        logger=logger,
    )

    failed_feature_count = int(geojson_summary["failed_feature_count"]) + int(gpkg_summary["failed_feature_count"])
    elapsed_seconds = time.perf_counter() - started
    return {
        "input_path": str(input_path),
        "status": "converted" if failed_feature_count == 0 else "converted_with_feature_errors",
        "input_driver": input_driver,
        "input_schema": input_schema,
        "input_crs": source_crs.to_string(),
        "crs_source": crs_source,
        "source_feature_count": source_feature_count,
        "field_names": field_names,
        "geojson_output": geojson_summary,
        "gpkg_output": gpkg_summary,
        "failed_feature_count": failed_feature_count,
        "elapsed_seconds": round(elapsed_seconds, 6),
    }


def run_mif_to_vector_export(config: MifToVectorConfig) -> dict[str, Any]:
    input_path = normalize_runtime_path(config.input_path).expanduser().resolve()
    input_mode, mif_paths = _discover_mif_inputs(input_path)
    output_dir = input_path if input_mode == "directory" else input_path.parent
    run_id = config.run_id or build_run_id(RUN_ID_PREFIX)
    log_path = output_dir / f"{run_id}.log"
    summary_path = output_dir / f"{run_id}_summary.json"
    logger = build_logger(log_path, run_id)

    summary: dict[str, Any] = {
        "run_id": run_id,
        "tool": "Tool11",
        "status": "started",
        "input_path": str(input_path),
        "input_mode": input_mode,
        "log_path": str(log_path),
        "summary_path": str(summary_path),
        "default_crs_text": config.default_crs_text,
        "mif_file_count": len(mif_paths),
        "converted_file_count": 0,
        "failed_file_count": 0,
        "total_source_feature_count": 0,
        "total_geojson_feature_count": 0,
        "total_gpkg_feature_count": 0,
        "total_failed_feature_count": 0,
        "file_results": [],
        "error_reason_summary": {},
        "scan_scope": "top-level" if input_mode == "directory" else "single-file",
        "output_rule": "same_directory_same_stem",
        "output_formats": ["GeoJSON", "GPKG"],
    }

    try:
        announce(logger, f"Tool11 MIF to GeoJSON/GPKG export started. input_path={input_path}")
        announce(logger, f"[Stage 1/3] Resolve inputs. mode={input_mode} mif_file_count={len(mif_paths)}")
        error_counter: Counter[str] = Counter()
        file_results: list[dict[str, Any]] = []
        converted_file_count = 0
        failed_file_count = 0
        total_source_feature_count = 0
        total_geojson_feature_count = 0
        total_gpkg_feature_count = 0
        total_failed_feature_count = 0

        announce(logger, "[Stage 2/3] Convert each MIF into sibling GeoJSON and GPKG outputs.")
        for index, mif_path in enumerate(mif_paths, start=1):
            announce(logger, f"[File {index}/{len(mif_paths)}] start input_path={mif_path.name}")
            try:
                file_summary = _convert_single_mif(
                    mif_path,
                    default_crs_text=config.default_crs_text,
                    progress_interval=config.progress_interval,
                    logger=logger,
                )
                file_results.append(file_summary)
                converted_file_count += 1
                total_source_feature_count += int(file_summary["source_feature_count"] or 0)
                total_geojson_feature_count += int(file_summary["geojson_output"]["feature_count"])
                total_gpkg_feature_count += int(file_summary["gpkg_output"]["feature_count"])
                total_failed_feature_count += int(file_summary["failed_feature_count"])
                for output_key in ("geojson_output", "gpkg_output"):
                    for reason, count in file_summary[output_key]["error_reason_summary"].items():
                        error_counter[reason] += count
                announce(
                    logger,
                    f"[File {index}/{len(mif_paths)}] completed input_path={mif_path.name} "
                    f"geojson_features={file_summary['geojson_output']['feature_count']} "
                    f"gpkg_features={file_summary['gpkg_output']['feature_count']} "
                    f"failed_features={file_summary['failed_feature_count']}",
                )
            except Exception as exc:
                failed_file_count += 1
                error_counter[str(exc)] += 1
                file_results.append(
                    {
                        "input_path": str(mif_path),
                        "status": "failed",
                        "error": str(exc),
                        "geojson_output_path": str(mif_path.with_suffix(".geojson")),
                        "gpkg_output_path": str(mif_path.with_suffix(".gpkg")),
                    }
                )
                announce(logger, f"[File {index}/{len(mif_paths)}] failed input_path={mif_path.name} reason={exc}")

        announce(logger, "[Stage 3/3] Write summary and finish Tool11.")
        summary.update(
            {
                "status": "completed",
                "converted_file_count": converted_file_count,
                "failed_file_count": failed_file_count,
                "total_source_feature_count": total_source_feature_count,
                "total_geojson_feature_count": total_geojson_feature_count,
                "total_gpkg_feature_count": total_gpkg_feature_count,
                "total_failed_feature_count": total_failed_feature_count,
                "file_results": file_results,
                "error_reason_summary": dict(error_counter),
            }
        )
        write_json(summary_path, summary)
        announce(
            logger,
            "Tool11 MIF export finished. "
            f"mif_file_count={len(mif_paths)} converted_file_count={converted_file_count} "
            f"failed_file_count={failed_file_count} total_failed_feature_count={total_failed_feature_count}",
        )
        return summary
    except Exception as exc:
        summary["status"] = "failed"
        summary["error_reason_summary"] = {str(exc): 1}
        write_json(summary_path, summary)
        raise
    finally:
        close_logger(logger)
