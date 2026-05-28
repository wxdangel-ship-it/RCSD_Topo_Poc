from __future__ import annotations

import shutil
import subprocess
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
from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    write_geojson_from_fiona_collection,
    write_gpkg_from_fiona_collection,
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


def _features_per_second(feature_count: int, elapsed_seconds: float) -> float | None:
    if elapsed_seconds <= 0:
        return None
    return round(feature_count / elapsed_seconds, 3)


def _progress_to_announce(logger: Any) -> Any:
    def _callback(message: str) -> None:
        announce(logger, message.replace("[T08 IO]", "[Tool11 IO]", 1))

    return _callback


def _crs_command_arg(crs: CRS) -> str:
    authority = crs.to_authority()
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.to_wkt()


def _output_feature_count(path: Path, layer_name: str | None = None) -> int:
    with fiona.open(str(path), layer=layer_name) as source:
        return len(source)


def _run_ogr2ogr(
    input_path: Path,
    output_path: Path,
    *,
    driver: str,
    layer_name: str | None,
    source_crs: CRS,
    source_feature_count: int | None,
    progress_interval: int,
    logger: Any,
) -> dict[str, Any]:
    ogr2ogr_path = shutil.which("ogr2ogr")
    if ogr2ogr_path is None:
        raise RuntimeError("ogr2ogr executable not found")

    started = time.perf_counter()
    remove_existing_output(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ogr2ogr_path,
        "-overwrite",
        "-f",
        driver,
        "-a_srs",
        _crs_command_arg(source_crs),
    ]
    if driver == "GeoJSON":
        cmd.extend(["-lco", "RFC7946=NO"])
    if driver == "GPKG":
        cmd.extend(["-lco", "SPATIAL_INDEX=YES"])
    if layer_name:
        cmd.extend(["-nln", layer_name])
    cmd.extend([str(output_path), str(input_path)])

    announce(logger, f"[Tool11 IO] {output_path.name}: start ogr2ogr {driver} conversion")
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        if output_path.exists():
            output_path.unlink()
        stderr_tail = "\n".join(result.stderr.strip().splitlines()[-20:])
        raise RuntimeError(f"ogr2ogr {driver} failed with exit code {result.returncode}: {stderr_tail}")

    elapsed_seconds = time.perf_counter() - started
    count_layer_name = layer_name if driver == "GPKG" else None
    feature_count = source_feature_count if source_feature_count is not None else _output_feature_count(output_path, count_layer_name)
    announce(
        logger,
        f"[Tool11 IO] {output_path.name}: completed ogr2ogr {driver} conversion "
        f"features={feature_count} elapsed={elapsed_seconds:.2f}s",
    )
    return {
        "feature_count": feature_count,
        "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "write_engine": f"ogr2ogr-{driver.lower()}",
        "elapsed_seconds": round(elapsed_seconds, 6),
        "features_per_second": _features_per_second(feature_count, elapsed_seconds),
        "progress_interval": progress_interval,
    }


def _write_geojson(
    input_path: Path,
    output_path: Path,
    *,
    source_crs: CRS,
    source_feature_count: int | None,
    progress_interval: int,
    logger: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        write_result = _run_ogr2ogr(
            input_path,
            output_path,
            driver="GeoJSON",
            layer_name=input_path.stem,
            source_crs=source_crs,
            source_feature_count=source_feature_count,
            progress_interval=progress_interval,
            logger=logger,
        )
    except Exception as exc:
        announce(logger, f"[Tool11 IO] {output_path.name}: ogr2ogr fallback to streaming JSON. reason={exc}")
        remove_existing_output(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with fiona.open(str(input_path)) as source:
            write_result = write_geojson_from_fiona_collection(
                output_path,
                source,
                source_crs=source_crs,
                output_crs=source_crs,
                layer_name=input_path.stem,
                progress_callback=_progress_to_announce(logger),
                progress_interval=progress_interval,
            )
        write_result = {
            **write_result,
            "write_engine": "streaming-json",
        }

    elapsed_seconds = time.perf_counter() - started
    feature_count = int(write_result["feature_count"])
    return {
        "output_path": str(output_path),
        "output_format": "GeoJSON",
        "output_crs": source_crs.to_string(),
        "feature_count": feature_count,
        "failed_feature_count": 0,
        "geometry_type_summary": {},
        "error_reason_summary": {},
        "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "write_engine": write_result["write_engine"],
        "elapsed_seconds": round(elapsed_seconds, 6),
        "features_per_second": _features_per_second(feature_count, elapsed_seconds),
    }


def _write_gpkg(
    input_path: Path,
    output_path: Path,
    *,
    source_crs: CRS,
    source_feature_count: int | None,
    progress_interval: int,
    logger: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    layer_name = _sanitize_layer_name(input_path.stem)
    try:
        write_result = _run_ogr2ogr(
            input_path,
            output_path,
            driver="GPKG",
            layer_name=layer_name,
            source_crs=source_crs,
            source_feature_count=source_feature_count,
            progress_interval=progress_interval,
            logger=logger,
        )
    except Exception as exc:
        announce(logger, f"[Tool11 IO] {output_path.name}: ogr2ogr fallback to sqlite GPKG. reason={exc}")
        remove_existing_output(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with fiona.open(str(input_path)) as source:
            write_result = write_gpkg_from_fiona_collection(
                output_path,
                source,
                source_crs=source_crs,
                output_crs=source_crs,
                layer_name=layer_name,
                progress_callback=_progress_to_announce(logger),
                progress_interval=progress_interval,
            )
        write_result = {
            **write_result,
            "write_engine": "sqlite-gpkg",
        }

    elapsed_seconds = time.perf_counter() - started
    feature_count = int(write_result["feature_count"])
    return {
        "output_path": str(output_path),
        "output_format": "GPKG",
        "output_crs": source_crs.to_string(),
        "layer_name": layer_name,
        "feature_count": feature_count,
        "failed_feature_count": 0,
        "geometry_type_summary": {},
        "error_reason_summary": {},
        "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "write_engine": write_result["write_engine"],
        "elapsed_seconds": round(elapsed_seconds, 6),
        "features_per_second": _features_per_second(feature_count, elapsed_seconds),
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
        source_feature_count=source_feature_count,
        progress_interval=progress_interval,
        logger=logger,
    )
    gpkg_summary = _write_gpkg(
        input_path,
        gpkg_output_path,
        source_crs=source_crs,
        source_feature_count=source_feature_count,
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
        "features_per_second": _features_per_second(
            max(int(geojson_summary["feature_count"]), int(gpkg_summary["feature_count"])),
            elapsed_seconds,
        ),
        "write_engines": {
            "geojson": geojson_summary["write_engine"],
            "gpkg": gpkg_summary["write_engine"],
        },
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
