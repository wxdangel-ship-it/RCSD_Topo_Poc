from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    ensure_shp_path,
    read_vector,
    to_plain,
    unique_field_names,
    write_gpkg,
    write_json,
)


@dataclass(frozen=True)
class ShpToGpkgResult:
    input_path: Path
    output_path: Path
    input_crs: str
    output_crs: str
    crs_source: str
    feature_count: int
    layer_name: str


def run_t08_tool1_shp_to_gpkg(
    *,
    input_shp_paths: list[str | Path],
    out_dir: str | Path,
    summary_output: str | Path | None = None,
    target_epsg: int | None = None,
    default_crs_text: str | None = None,
) -> dict[str, Any]:
    if not input_shp_paths:
        raise ValueError("At least one --input-shp path is required")

    output_dir = Path(out_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = Path(summary_output).expanduser().resolve() if summary_output else output_dir / "t08_tool1_shp_to_gpkg_summary.json"

    file_results: list[dict[str, Any]] = []
    failed_results: list[dict[str, Any]] = []
    converted_count = 0
    total_feature_count = 0

    for raw_input_path in input_shp_paths:
        input_path = ensure_shp_path(raw_input_path, label="Tool1 input")
        output_path = output_dir / f"{input_path.stem}.gpkg"
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
            write_info = write_gpkg(
                output_path,
                features,
                crs_text=read_result.output_crs.to_string(),
                layer_name=input_path.stem,
                empty_fields=unique_field_names(read_result.field_names),
            )
            converted_count += 1
            total_feature_count += len(features)
            file_results.append(
                {
                    "input_path": input_path,
                    "output_path": output_path,
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
                    "status": "failed",
                    "error": str(exc),
                }
            )

    summary = {
        "tool": "T08 Tool1",
        "input_count": len(input_shp_paths),
        "converted_count": converted_count,
        "failed_count": len(failed_results),
        "total_feature_count": total_feature_count,
        "out_dir": output_dir,
        "summary_output": summary_path,
        "target_epsg": target_epsg,
        "default_crs_text": default_crs_text,
        "file_results": file_results,
        "failed_results": failed_results,
    }
    write_json(summary_path, summary)
    return to_plain(summary)
