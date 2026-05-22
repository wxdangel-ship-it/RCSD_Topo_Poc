from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    PROCESS_CRS_TEXT,
    VectorFeature,
    aggregate_bounds,
    ensure_gpkg_path,
    get_case_insensitive_property,
    read_vector,
    resolve_field_name,
    to_plain,
    unique_field_names,
    write_gpkg,
    write_json,
)


@dataclass(frozen=True)
class T08RoadPreprocessArtifacts:
    road_patch_output: Path
    road_patch_unmatched_output: Path
    road_patch_kind_output: Path
    patch_summary_output: Path
    kind_summary_output: Path
    summary_output: Path


def run_t08_road_preprocess(
    *,
    road_gpkg: str | Path,
    patch_road_gpkg: str | Path,
    raw_kind_road_gpkg: str | Path,
    road_patch_output: str | Path,
    road_patch_unmatched_output: str | Path,
    road_patch_kind_output: str | Path,
    road_layer: str | None = None,
    patch_road_layer: str | None = None,
    raw_kind_road_layer: str | None = None,
    patch_summary_output: str | Path | None = None,
    kind_summary_output: str | Path | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int = 3857,
    road_default_crs_text: str | None = None,
    patch_road_default_crs_text: str | None = None,
    raw_kind_road_default_crs_text: str | None = None,
    buffer_distance_meters: float = 1.0,
    spatial_predicate: str = "covers",
) -> T08RoadPreprocessArtifacts:
    road_path = ensure_gpkg_path(road_gpkg, label="--road-gpkg")
    patch_road_path = ensure_gpkg_path(patch_road_gpkg, label="--patch-road-gpkg")
    raw_kind_road_path = ensure_gpkg_path(raw_kind_road_gpkg, label="--raw-kind-road-gpkg")
    road_patch_path = ensure_gpkg_path(road_patch_output, label="--road-patch-output")
    unmatched_path = ensure_gpkg_path(road_patch_unmatched_output, label="--road-patch-unmatched-output")
    kind_path = ensure_gpkg_path(road_patch_kind_output, label="--road-patch-kind-output")

    patch_summary_path = (
        Path(patch_summary_output).expanduser().resolve()
        if patch_summary_output
        else road_patch_path.with_name("t08_road_patch_summary.json")
    )
    kind_summary_path = (
        Path(kind_summary_output).expanduser().resolve()
        if kind_summary_output
        else kind_path.with_name("t08_road_kind_summary.json")
    )
    combined_summary_path = (
        Path(summary_output).expanduser().resolve()
        if summary_output
        else kind_path.with_name("t08_road_preprocess_summary.json")
    )

    patch_summary, road_patch_features = _run_patch_join(
        road_gpkg=road_path,
        patch_road_gpkg=patch_road_path,
        road_patch_output=road_patch_path,
        road_patch_unmatched_output=unmatched_path,
        summary_output=patch_summary_path,
        road_layer=road_layer,
        patch_road_layer=patch_road_layer,
        target_epsg=target_epsg,
        road_default_crs_text=road_default_crs_text,
        patch_road_default_crs_text=patch_road_default_crs_text,
    )
    kind_summary = _run_kind_enrich(
        road_patch_features=road_patch_features,
        road_patch_field_names=patch_summary["field_names"]["road"],
        raw_kind_road_gpkg=raw_kind_road_path,
        road_patch_kind_output=kind_path,
        summary_output=kind_summary_path,
        raw_kind_road_layer=raw_kind_road_layer,
        target_epsg=target_epsg,
        raw_kind_road_default_crs_text=raw_kind_road_default_crs_text,
        buffer_distance_meters=buffer_distance_meters,
        spatial_predicate=spatial_predicate,
    )
    combined_summary = {
        "tool": "T08 Tool2",
        "target_epsg": target_epsg,
        "input_paths": {
            "road_gpkg": road_path,
            "patch_road_gpkg": patch_road_path,
            "raw_kind_road_gpkg": raw_kind_road_path,
        },
        "output_paths": {
            "road_patch_output": road_patch_path,
            "road_patch_unmatched_output": unmatched_path,
            "road_patch_kind_output": kind_path,
            "patch_summary_output": patch_summary_path,
            "kind_summary_output": kind_summary_path,
            "summary_output": combined_summary_path,
        },
        "counts": {
            "road_count": patch_summary["total_road_count"],
            "patch_join_matched_count": patch_summary["matched_count"],
            "patch_join_unmatched_count": patch_summary["unmatched_count"],
            "kind_matched_count": kind_summary["matched_kind_count"],
            "kind_unmatched_count": kind_summary["unmatched_kind_count"],
            "kind_empty_count": kind_summary["empty_kind_count"],
        },
        "params": {
            "buffer_distance_meters": buffer_distance_meters,
            "spatial_predicate": spatial_predicate,
            "road_layer": road_layer,
            "patch_road_layer": patch_road_layer,
            "raw_kind_road_layer": raw_kind_road_layer,
        },
    }
    write_json(combined_summary_path, combined_summary)
    return T08RoadPreprocessArtifacts(
        road_patch_output=road_patch_path,
        road_patch_unmatched_output=unmatched_path,
        road_patch_kind_output=kind_path,
        patch_summary_output=patch_summary_path,
        kind_summary_output=kind_summary_path,
        summary_output=combined_summary_path,
    )


def _run_patch_join(
    *,
    road_gpkg: Path,
    patch_road_gpkg: Path,
    road_patch_output: Path,
    road_patch_unmatched_output: Path,
    summary_output: Path,
    road_layer: str | None,
    patch_road_layer: str | None,
    target_epsg: int,
    road_default_crs_text: str | None,
    patch_road_default_crs_text: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    road_result = read_vector(
        road_gpkg,
        layer_name=road_layer,
        default_crs_text=road_default_crs_text,
        target_epsg=target_epsg,
    )
    patch_road_result = read_vector(
        patch_road_gpkg,
        layer_name=patch_road_layer,
        default_crs_text=patch_road_default_crs_text,
        target_epsg=target_epsg,
    )
    if not road_result.features:
        raise ValueError("Road input contains no features")
    if not patch_road_result.features:
        raise ValueError("Patch road input contains no features")

    road_id_field = resolve_field_name(road_result.features, ["id"], "road input")
    patch_road_id_field = resolve_field_name(patch_road_result.features, ["road_id"], "patch road input")
    patch_id_field = resolve_field_name(patch_road_result.features, ["patch_id"], "patch road input")

    patch_mapping: dict[str, dict[str, Any]] = {}
    invalid_patch_record_count = 0
    for feature in patch_road_result.features:
        road_key = _normalize_join_value(feature.properties.get(patch_road_id_field))
        patch_key = _normalize_join_value(feature.properties.get(patch_id_field))
        if road_key is None or patch_key is None:
            invalid_patch_record_count += 1
            continue
        entry = patch_mapping.setdefault(road_key, {"record_count": 0, "patch_values": {}})
        entry["record_count"] += 1
        entry["patch_values"][patch_key] = feature.properties.get(patch_id_field)

    matched_features: list[dict[str, Any]] = []
    unmatched_features: list[dict[str, Any]] = []
    multi_patch_assignment_count = 0
    for feature in road_result.features:
        properties = dict(feature.properties)
        road_key = _normalize_join_value(properties.get(road_id_field))
        unmatched_reason: str | None = None
        if road_key is None:
            unmatched_reason = "missing road id"
        else:
            entry = patch_mapping.get(road_key)
            if entry is None:
                unmatched_reason = "no patch road match"
            else:
                patch_ids = sorted(entry["patch_values"].keys(), key=_patch_id_sort_key)
                properties["patch_id"] = ",".join(patch_ids)
                if len(patch_ids) > 1:
                    multi_patch_assignment_count += 1

        if unmatched_reason is None:
            matched_features.append({"properties": properties, "geometry": feature.geometry})
        else:
            properties["patch_id"] = None
            properties["unmatched_reason"] = unmatched_reason
            unmatched_features.append({"properties": properties, "geometry": feature.geometry})

    road_fields = unique_field_names(road_result.field_names, extra=("patch_id",))
    unmatched_fields = unique_field_names(road_result.field_names, extra=("patch_id", "unmatched_reason"))
    write_gpkg(road_patch_output, matched_features, crs_text=PROCESS_CRS_TEXT, empty_fields=road_fields)
    write_gpkg(road_patch_unmatched_output, unmatched_features, crs_text=PROCESS_CRS_TEXT, empty_fields=unmatched_fields)

    duplicate_road_id_count = sum(1 for entry in patch_mapping.values() if entry["record_count"] > 1)
    conflicting_patch_id_count = sum(1 for entry in patch_mapping.values() if len(entry["patch_values"]) > 1)
    summary = {
        "tool": "T08 Tool2",
        "stage": "patch_join",
        "target_epsg": target_epsg,
        "input_paths": {"road_gpkg": road_gpkg, "patch_road_gpkg": patch_road_gpkg},
        "output_paths": {"road_patch_output": road_patch_output, "road_patch_unmatched_output": road_patch_unmatched_output},
        "summary_output": summary_output,
        "input_crs": {
            "road": road_result.source_crs.to_string(),
            "road_crs_source": road_result.crs_source,
            "patch_road": patch_road_result.source_crs.to_string(),
            "patch_road_crs_source": patch_road_result.crs_source,
        },
        "field_audit": {
            "road_id_field": road_id_field,
            "patch_road_id_field": patch_road_id_field,
            "patch_id_field": patch_id_field,
        },
        "field_names": {"road": road_fields},
        "total_road_count": len(road_result.features),
        "total_patch_road_count": len(patch_road_result.features),
        "matched_count": len(matched_features),
        "unmatched_count": len(unmatched_features),
        "duplicate_road_id_count": duplicate_road_id_count,
        "conflicting_patch_id_count": conflicting_patch_id_count,
        "multi_patch_assignment_count": multi_patch_assignment_count,
        "invalid_patch_record_count": invalid_patch_record_count,
        "matched_output_bounds": aggregate_bounds(feature["geometry"] for feature in matched_features),
        "unmatched_output_bounds": aggregate_bounds(feature["geometry"] for feature in unmatched_features),
        "unmatched_reason_summary": _reason_counter(unmatched_features),
    }
    write_json(summary_output, summary)
    return to_plain(summary), matched_features


def _run_kind_enrich(
    *,
    road_patch_features: list[dict[str, Any]],
    road_patch_field_names: list[str],
    raw_kind_road_gpkg: Path,
    road_patch_kind_output: Path,
    summary_output: Path,
    raw_kind_road_layer: str | None,
    target_epsg: int,
    raw_kind_road_default_crs_text: str | None,
    buffer_distance_meters: float,
    spatial_predicate: str,
) -> dict[str, Any]:
    raw_kind_result = read_vector(
        raw_kind_road_gpkg,
        layer_name=raw_kind_road_layer,
        default_crs_text=raw_kind_road_default_crs_text,
        target_epsg=target_epsg,
    )
    if not raw_kind_result.features:
        raise ValueError("Raw kind road input contains no features")
    kind_field = resolve_field_name(raw_kind_result.features, ["Kind", "kind"], "raw kind road input")
    raw_geometries = [feature.geometry for feature in raw_kind_result.features]
    raw_tree = STRtree(raw_geometries)

    output_features: list[dict[str, Any]] = []
    matched_kind_count = 0
    unmatched_kind_count = 0
    empty_kind_count = 0
    spatial_candidate_count = 0
    error_counter = Counter()

    for feature in road_patch_features:
        properties = dict(feature["properties"])
        kind_value: str | None = None
        try:
            search_geometry = feature["geometry"].buffer(buffer_distance_meters)
            candidate_indexes = list(raw_tree.query(search_geometry, predicate=spatial_predicate))
            spatial_candidate_count += len(candidate_indexes)
            if not candidate_indexes:
                unmatched_kind_count += 1
            else:
                tokens: list[str] = []
                for candidate_index in candidate_indexes:
                    raw_properties = raw_kind_result.features[int(candidate_index)].properties
                    tokens.extend(
                        _split_kind_tokens(
                            get_case_insensitive_property(raw_properties, ["Kind", "kind"], preferred=kind_field)
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
        output_features.append({"properties": properties, "geometry": feature["geometry"]})

    output_fields = unique_field_names(road_patch_field_names, extra=("patch_id", "kind"))
    write_gpkg(road_patch_kind_output, output_features, crs_text=PROCESS_CRS_TEXT, empty_fields=output_fields)
    summary = {
        "tool": "T08 Tool2",
        "stage": "kind_enrich",
        "target_epsg": target_epsg,
        "input_paths": {"raw_kind_road_gpkg": raw_kind_road_gpkg},
        "output_paths": {"road_patch_kind_output": road_patch_kind_output},
        "summary_output": summary_output,
        "input_crs": {
            "raw_kind_road": raw_kind_result.source_crs.to_string(),
            "raw_kind_road_crs_source": raw_kind_result.crs_source,
        },
        "kind_field": kind_field,
        "buffer_distance_meters": buffer_distance_meters,
        "spatial_predicate": spatial_predicate,
        "road_patch_feature_count": len(road_patch_features),
        "raw_kind_feature_count": len(raw_kind_result.features),
        "spatial_candidate_count": spatial_candidate_count,
        "matched_kind_count": matched_kind_count,
        "unmatched_kind_count": unmatched_kind_count,
        "empty_kind_count": empty_kind_count,
        "output_feature_count": len(output_features),
        "output_bounds": aggregate_bounds(feature["geometry"] for feature in output_features),
        "error_reason_summary": dict(error_counter),
    }
    write_json(summary_output, summary)
    return to_plain(summary)


def _normalize_join_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        number_part = text[:-2]
        if number_part.lstrip("-").isdigit():
            return number_part
    return text


def _patch_id_sort_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdigit() else (1, value)


def _reason_counter(features: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter()
    for feature in features:
        reason = feature.get("properties", {}).get("unmatched_reason")
        if reason:
            counter[str(reason)] += 1
    return dict(counter)


def _split_kind_tokens(value: Any) -> list[str]:
    if value is None:
        return []
    tokens: list[str] = []
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
