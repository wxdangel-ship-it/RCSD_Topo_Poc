from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fiona
from pyproj import CRS

from rcsd_topo_poc.modules.t08_preprocess.output_naming import ensure_tool_output_name
from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    ensure_geojson_path,
    ensure_gpkg_path,
    ensure_shp_path,
    resolve_source_crs,
    to_plain,
    write_geojson_from_fiona_collection,
    write_gpkg_from_fiona_collection,
    write_json,
)


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class Tool1ConversionResult:
    input_path: Path
    output_path: Path
    conversion: str
    input_crs: str
    output_crs: str
    crs_source: str
    feature_count: int
    layer_name: str


ShpToGpkgResult = Tool1ConversionResult


def run_t08_tool1_conversions(
    *,
    input_shp_paths: list[str | Path] | None = None,
    input_geojson_paths: list[str | Path] | None = None,
    input_gpkg_paths: list[str | Path] | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int | None = None,
    default_crs_text: str | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_interval: int = 10000,
) -> dict[str, Any]:
    input_specs = _build_input_specs(
        input_shp_paths=input_shp_paths or [],
        input_geojson_paths=input_geojson_paths or [],
        input_gpkg_paths=input_gpkg_paths or [],
    )
    if not input_specs:
        raise ValueError("At least one Tool1 input path is required")
    _validate_no_path_collisions(input_specs)

    summary_path = (
        ensure_tool_output_name(summary_output, tool_number=1, label="--summary-output")
        if summary_output
        else input_specs[0]["input_path"].parent / "t08_tool1_conversion_summary_tool1.json"
    )

    file_results: list[dict[str, Any]] = []
    failed_results: list[dict[str, Any]] = []
    converted_count = 0
    total_feature_count = 0

    _emit_progress(progress_callback, f"[T08 Tool1] queued {len(input_specs)} input file(s)")
    run_started = time.perf_counter()
    for index, spec in enumerate(input_specs, start=1):
        input_path = spec["input_path"]
        output_path = spec["output_path"]
        conversion = spec["conversion"]
        _emit_progress(progress_callback, f"[T08 Tool1] ({index}/{len(input_specs)}) start {conversion}: {input_path}")
        try:
            convert_info = _convert_vector_streaming(
                input_path=input_path,
                output_path=output_path,
                conversion=conversion,
                default_crs_text=default_crs_text,
                target_epsg=target_epsg,
                progress_callback=progress_callback,
                progress_interval=progress_interval,
            )
            converted_count += 1
            total_feature_count += convert_info["feature_count"]
            file_results.append(
                {
                    "input_path": input_path,
                    "output_path": output_path,
                    "conversion": conversion,
                    "status": "converted",
                    **convert_info,
                }
            )
            _emit_progress(
                progress_callback,
                (
                    f"[T08 Tool1] ({index}/{len(input_specs)}) done {output_path} "
                    f"features={convert_info['feature_count']} elapsed={convert_info['elapsed_seconds']:.2f}s"
                ),
            )
        except Exception as exc:
            failed_results.append(
                {
                    "input_path": input_path,
                    "output_path": output_path,
                    "conversion": conversion,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            _emit_progress(progress_callback, f"[T08 Tool1] ({index}/{len(input_specs)}) failed {input_path}: {exc}")

    elapsed_seconds = time.perf_counter() - run_started

    summary = {
        "tool": "T08 Tool1",
        "input_count": len(input_specs),
        "converted_count": converted_count,
        "failed_count": len(failed_results),
        "total_feature_count": total_feature_count,
        "elapsed_seconds": round(elapsed_seconds, 6),
        "features_per_second": _features_per_second(total_feature_count, elapsed_seconds),
        "output_rule": "same_directory_same_stem_different_extension",
        "summary_output": summary_path,
        "target_epsg": target_epsg,
        "default_crs_text": default_crs_text,
        "supported_conversions": ["shp_to_gpkg", "geojson_to_gpkg", "gpkg_to_geojson"],
        "file_results": file_results,
        "failed_results": failed_results,
    }
    write_json(summary_path, summary)
    _emit_progress(
        progress_callback,
        (
            f"[T08 Tool1] finished converted={converted_count} failed={len(failed_results)} "
            f"features={total_feature_count} elapsed={elapsed_seconds:.2f}s summary={summary_path}"
        ),
    )
    return to_plain(summary)


def run_t08_tool1_shp_to_gpkg(
    *,
    input_shp_paths: list[str | Path],
    out_dir: str | Path | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int | None = None,
    default_crs_text: str | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_interval: int = 10000,
) -> dict[str, Any]:
    if out_dir is not None:
        raise ValueError("Tool1 no longer accepts out_dir; outputs are written next to each input file with the converted extension")
    return run_t08_tool1_conversions(
        input_shp_paths=input_shp_paths,
        summary_output=summary_output,
        target_epsg=target_epsg,
        default_crs_text=default_crs_text,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )


def _build_input_specs(
    *,
    input_shp_paths: list[str | Path],
    input_geojson_paths: list[str | Path],
    input_gpkg_paths: list[str | Path],
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for raw_path in input_shp_paths:
        input_path = ensure_shp_path(raw_path, label="--input-shp")
        specs.append(
            {
                "input_path": input_path,
                "output_path": input_path.with_suffix(".gpkg"),
                "conversion": "shp_to_gpkg",
            }
        )
    for raw_path in input_geojson_paths:
        input_path = ensure_geojson_path(raw_path, label="--input-geojson")
        specs.append(
            {
                "input_path": input_path,
                "output_path": input_path.with_suffix(".gpkg"),
                "conversion": "geojson_to_gpkg",
            }
        )
    for raw_path in input_gpkg_paths:
        input_path = ensure_gpkg_path(raw_path, label="--input-gpkg")
        specs.append(
            {
                "input_path": input_path,
                "output_path": input_path.with_suffix(".geojson"),
                "conversion": "gpkg_to_geojson",
            }
        )
    return specs


def _validate_no_path_collisions(input_specs: list[dict[str, Any]]) -> None:
    input_paths = {spec["input_path"] for spec in input_specs}
    output_paths: set[Path] = set()
    for spec in input_specs:
        output_path = spec["output_path"]
        if output_path in input_paths:
            raise ValueError(f"Tool1 output would overwrite an input in the same run: {output_path}")
        if output_path in output_paths:
            raise ValueError(f"Tool1 inputs resolve to the same output path: {output_path}")
        output_paths.add(output_path)


def _convert_vector_streaming(
    *,
    input_path: Path,
    output_path: Path,
    conversion: str,
    default_crs_text: str | None,
    target_epsg: int | None,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    with fiona.open(str(input_path)) as source:
        source_crs, crs_source = resolve_source_crs(
            path=input_path,
            default_crs_text=default_crs_text,
            crs_wkt=getattr(source, "crs_wkt", None),
            crs_mapping=getattr(source, "crs", None),
        )
        output_crs = CRS.from_epsg(target_epsg) if target_epsg is not None else source_crs
        source_count = _safe_feature_count(source)
        layer_name = getattr(source, "name", None) or input_path.stem
        if output_path.suffix.lower() == ".gpkg":
            write_result = write_gpkg_from_fiona_collection(
                output_path,
                source,
                source_crs=source_crs,
                output_crs=output_crs,
                layer_name=input_path.stem,
                progress_callback=progress_callback,
                progress_interval=progress_interval,
            )
        else:
            write_result = write_geojson_from_fiona_collection(
                output_path,
                source,
                source_crs=source_crs,
                output_crs=output_crs,
                layer_name=input_path.stem,
                progress_callback=progress_callback,
                progress_interval=progress_interval,
            )

    elapsed_seconds = time.perf_counter() - started
    feature_count = int(write_result["feature_count"])
    return {
        "input_crs": source_crs.to_string(),
        "output_crs": output_crs.to_string(),
        "crs_source": crs_source,
        "feature_count": feature_count,
        "layer_name": layer_name,
        "source_feature_count": source_count,
        "size_bytes": write_result["size_bytes"],
        "elapsed_seconds": round(elapsed_seconds, 6),
        "features_per_second": _features_per_second(feature_count, elapsed_seconds),
    }


def _safe_feature_count(source: Any) -> int | None:
    try:
        return len(source)
    except Exception:
        return None


def _features_per_second(feature_count: int, elapsed_seconds: float) -> float | None:
    if elapsed_seconds <= 0:
        return None
    return round(feature_count / elapsed_seconds, 3)


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)
