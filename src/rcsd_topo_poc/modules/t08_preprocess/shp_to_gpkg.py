from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    ensure_geojson_path,
    ensure_gpkg_path,
    ensure_shp_path,
    read_vector,
    to_plain,
    unique_field_names,
    write_geojson,
    write_gpkg,
    write_json,
)


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
        Path(summary_output).expanduser().resolve()
        if summary_output
        else input_specs[0]["input_path"].parent / "t08_tool1_conversion_summary.json"
    )

    file_results: list[dict[str, Any]] = []
    failed_results: list[dict[str, Any]] = []
    converted_count = 0
    total_feature_count = 0

    for spec in input_specs:
        input_path = spec["input_path"]
        output_path = spec["output_path"]
        conversion = spec["conversion"]
        try:
            read_result = read_vector(
                input_path,
                default_crs_text=default_crs_text,
                target_epsg=target_epsg,
            )
            features = [
                {"properties": feature.properties, "geometry": feature.geometry}
                for feature in read_result.features
            ]
            if output_path.suffix.lower() == ".gpkg":
                write_info = write_gpkg(
                    output_path,
                    features,
                    crs_text=read_result.output_crs.to_string(),
                    layer_name=input_path.stem,
                    empty_fields=unique_field_names(read_result.field_names),
                )
            else:
                write_info = write_geojson(
                    output_path,
                    features,
                    crs_text=read_result.output_crs.to_string(),
                    empty_fields=unique_field_names(read_result.field_names),
                )
            converted_count += 1
            total_feature_count += len(features)
            file_results.append(
                {
                    "input_path": input_path,
                    "output_path": output_path,
                    "conversion": conversion,
                    "input_crs": read_result.source_crs.to_string(),
                    "output_crs": read_result.output_crs.to_string(),
                    "crs_source": read_result.crs_source,
                    "feature_count": len(features),
                    "layer_name": input_path.stem,
                    "size_bytes": write_info["size_bytes"],
                    "status": "converted",
                }
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

    summary = {
        "tool": "T08 Tool1",
        "input_count": len(input_specs),
        "converted_count": converted_count,
        "failed_count": len(failed_results),
        "total_feature_count": total_feature_count,
        "output_rule": "same_directory_same_stem",
        "summary_output": summary_path,
        "target_epsg": target_epsg,
        "default_crs_text": default_crs_text,
        "supported_conversions": ["shp_to_gpkg", "geojson_to_gpkg", "gpkg_to_geojson"],
        "file_results": file_results,
        "failed_results": failed_results,
    }
    write_json(summary_path, summary)
    return to_plain(summary)


def run_t08_tool1_shp_to_gpkg(
    *,
    input_shp_paths: list[str | Path],
    out_dir: str | Path | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int | None = None,
    default_crs_text: str | None = None,
) -> dict[str, Any]:
    if out_dir is not None:
        raise ValueError("Tool1 no longer accepts out_dir; outputs are written next to each input file")
    return run_t08_tool1_conversions(
        input_shp_paths=input_shp_paths,
        summary_output=summary_output,
        target_epsg=target_epsg,
        default_crs_text=default_crs_text,
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
