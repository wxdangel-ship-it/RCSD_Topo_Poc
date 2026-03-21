from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    aggregate_bounds,
    announce,
    build_logger,
    build_run_id,
    close_logger,
    read_geojson_features,
    remove_existing_output,
    resolve_case_insensitive_field_name,
    write_geojson,
    write_json,
)


RUN_ID_PREFIX = "t00_tool5_a200_kind_enrich"
PROGRESS_INTERVAL = 1000


@dataclass(frozen=True)
class RoadKindEnrichConfig:
    a200_patch_input_path: Path
    sw_input_path: Path
    output_path: Path
    target_epsg: int = 3857
    default_input_crs_text: str | None = None
    buffer_distance_meters: float = 1.0
    spatial_predicate: str = "covers"
    run_id: str | None = None


def _resolve_field_name(features: list[Any], candidates: Iterable[str], label: str) -> str:
    for feature in features:
        resolved = resolve_case_insensitive_field_name(feature.properties, candidates)
        if resolved is not None:
            return resolved
    raise ValueError(f"Required field {list(candidates)} not found in {label}")


def _get_case_insensitive_property(
    properties: dict[str, Any],
    candidates: Iterable[str],
    *,
    preferred: str | None = None,
) -> Any:
    if preferred is not None and preferred in properties:
        return properties.get(preferred)

    resolved = resolve_case_insensitive_field_name(properties, candidates)
    if resolved is None:
        return None
    return properties.get(resolved)


def _split_kind_tokens(value: Any) -> list[str]:
    if value is None:
        return []
    tokens = []
    for raw_token in str(value).split("|"):
        token = raw_token.strip()
        if token:
            tokens.append(token)
    return tokens


def _unique_preserve_order(tokens: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def _should_report_progress(index: int, total: int, interval: int = PROGRESS_INTERVAL) -> bool:
    return index == 1 or index == total or index % interval == 0


def run_road_kind_enrich(config: RoadKindEnrichConfig) -> dict[str, Any]:
    a200_patch_input_path = config.a200_patch_input_path.expanduser().resolve()
    sw_input_path = config.sw_input_path.expanduser().resolve()
    output_path = config.output_path.expanduser().resolve()
    target_crs_text = f"EPSG:{config.target_epsg}"

    if not a200_patch_input_path.is_file():
        raise ValueError(f"A200_road_patch input does not exist: {a200_patch_input_path}")
    if not sw_input_path.is_file():
        raise ValueError(f"SW input does not exist: {sw_input_path}")

    run_id = config.run_id or build_run_id(RUN_ID_PREFIX)
    log_dir = output_path.parent
    log_path = log_dir / f"{run_id}.log"
    summary_path = log_dir / f"{run_id}_summary.json"
    logger = build_logger(log_path, run_id)

    try:
        remove_existing_output(output_path)

        announce(logger, f"Tool5 road kind enrich started. a200_patch_input_path={a200_patch_input_path}")
        announce(logger, "[Stage 1/4] Read Tool4 output and SW road inputs.")

        a200_result = read_geojson_features(
            a200_patch_input_path,
            default_crs_text=config.default_input_crs_text,
            target_crs_text=target_crs_text,
        )
        sw_result = read_geojson_features(
            sw_input_path,
            default_crs_text=config.default_input_crs_text,
            target_crs_text=target_crs_text,
        )

        total_a200_patch_count = len(a200_result.features)
        sw_feature_count = len(sw_result.features)
        if total_a200_patch_count == 0:
            raise ValueError("A200_road_patch input contains no features")

        sw_kind_field = _resolve_field_name(sw_result.features, ["Kind", "kind"], "SW road input")

        announce(logger, "[Stage 2/4] Build spatial index for SW road geometries.")
        sw_geometries = [feature.geometry for feature in sw_result.features]
        sw_tree = STRtree(sw_geometries) if sw_geometries else None

        announce(logger, "[Stage 3/4] Enrich A200_road_patch with deduplicated SW kind values.")
        output_features: list[dict[str, Any]] = []
        matched_kind_count = 0
        unmatched_kind_count = 0
        empty_kind_count = 0
        error_counter = Counter()

        for index, feature in enumerate(a200_result.features, start=1):
            properties = dict(feature.properties)
            kind_value: str | None = None

            try:
                candidate_indexes = []
                if sw_tree is not None:
                    buffer_geometry = feature.geometry.buffer(config.buffer_distance_meters)
                    candidate_indexes = list(sw_tree.query(buffer_geometry, predicate=config.spatial_predicate))

                if not candidate_indexes:
                    unmatched_kind_count += 1
                else:
                    tokens: list[str] = []
                    for candidate_index in candidate_indexes:
                        sw_properties = sw_result.features[int(candidate_index)].properties
                        tokens.extend(
                            _split_kind_tokens(
                                _get_case_insensitive_property(
                                    sw_properties,
                                    ["Kind", "kind"],
                                    preferred=sw_kind_field,
                                )
                            )
                        )

                    unique_tokens = _unique_preserve_order(tokens)
                    if unique_tokens:
                        kind_value = "|".join(unique_tokens)
                        matched_kind_count += 1
                    else:
                        empty_kind_count += 1
            except Exception as exc:
                error_counter[str(exc)] += 1

            properties["kind"] = kind_value
            output_features.append(
                {
                    "properties": properties,
                    "geometry": feature.geometry,
                }
            )

            if _should_report_progress(index, total_a200_patch_count):
                announce(logger, f"[A200_road_patch {index}/{total_a200_patch_count}] kind enrich progress")

        announce(logger, "[Stage 4/4] Write Tool5 output and summary.")
        write_geojson(output_path, output_features, crs_text=target_crs_text)

        summary = {
            "run_id": run_id,
            "tool": "Tool5",
            "target_epsg": config.target_epsg,
            "a200_patch_input_path": str(a200_patch_input_path),
            "sw_input_path": str(sw_input_path),
            "output_path": str(output_path),
            "log_path": str(log_path),
            "summary_path": str(summary_path),
            "kind_field": sw_kind_field,
            "spatial_predicate": config.spatial_predicate,
            "buffer_distance_meters": config.buffer_distance_meters,
            "total_a200_patch_count": total_a200_patch_count,
            "sw_feature_count": sw_feature_count,
            "matched_kind_count": matched_kind_count,
            "unmatched_kind_count": unmatched_kind_count,
            "empty_kind_count": empty_kind_count,
            "output_feature_count": len(output_features),
            "output_bounds": aggregate_bounds(feature["geometry"] for feature in output_features),
            "error_reason_summary": dict(error_counter),
        }
        write_json(summary_path, summary)
        announce(
            logger,
            "Tool5 road kind enrich finished. "
            f"matched_kind_count={matched_kind_count} unmatched_kind_count={unmatched_kind_count} "
            f"empty_kind_count={empty_kind_count}",
        )
        return summary
    finally:
        close_logger(logger)
