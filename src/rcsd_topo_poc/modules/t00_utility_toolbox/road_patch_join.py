from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    aggregate_bounds,
    announce,
    build_logger,
    build_run_id,
    close_logger,
    read_shapefile_features,
    remove_existing_output,
    resolve_case_insensitive_field_name,
    write_geojson,
    write_json,
)


RUN_ID_PREFIX = "t00_tool4_a200_patch_join"
PROGRESS_INTERVAL = 1000


@dataclass(frozen=True)
class RoadPatchJoinConfig:
    a200_input_path: Path
    rc_patch_road_input_path: Path
    output_path: Path
    unmatched_output_path: Path
    target_epsg: int = 3857
    default_input_crs_text: str | None = None
    run_id: str | None = None


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


def _resolve_field_name(features: list[Any], candidates: Iterable[str], label: str) -> str:
    for feature in features:
        resolved = resolve_case_insensitive_field_name(feature.properties, candidates)
        if resolved is not None:
            return resolved
    raise ValueError(f"Required field {list(candidates)} not found in {label}")


def _should_report_progress(index: int, total: int, interval: int = PROGRESS_INTERVAL) -> bool:
    return index == 1 or index == total or index % interval == 0


def _reason_counter(features: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter()
    for feature in features:
        reason = feature.get("properties", {}).get("unmatched_reason")
        if reason:
            counter[str(reason)] += 1
    return dict(counter)


def run_road_patch_join(config: RoadPatchJoinConfig) -> dict[str, Any]:
    a200_input_path = config.a200_input_path.expanduser().resolve()
    rc_input_path = config.rc_patch_road_input_path.expanduser().resolve()
    output_path = config.output_path.expanduser().resolve()
    unmatched_output_path = config.unmatched_output_path.expanduser().resolve()
    target_crs_text = f"EPSG:{config.target_epsg}"

    if not a200_input_path.is_file():
        raise ValueError(f"A200 input does not exist: {a200_input_path}")
    if not rc_input_path.is_file():
        raise ValueError(f"rc_patch_road input does not exist: {rc_input_path}")

    run_id = config.run_id or build_run_id(RUN_ID_PREFIX)
    log_dir = output_path.parent
    log_path = log_dir / f"{run_id}.log"
    summary_path = log_dir / f"{run_id}_summary.json"
    logger = build_logger(log_path, run_id)

    try:
        remove_existing_output(output_path)
        remove_existing_output(unmatched_output_path)

        announce(logger, f"Tool4 road patch join started. a200_input_path={a200_input_path}")
        announce(logger, "[Stage 1/4] Read A200_road and rc_patch_road inputs.")

        a200_result = read_shapefile_features(
            a200_input_path,
            default_crs_text=config.default_input_crs_text,
            target_crs_text=target_crs_text,
        )
        rc_result = read_shapefile_features(
            rc_input_path,
            default_crs_text=config.default_input_crs_text,
            target_crs_text=target_crs_text,
        )

        total_a200_count = len(a200_result.features)
        total_rc_count = len(rc_result.features)
        if total_a200_count == 0:
            raise ValueError("A200_road input contains no features")
        if total_rc_count == 0:
            raise ValueError("rc_patch_road input contains no features")

        a200_id_field = _resolve_field_name(a200_result.features, ["id"], "A200_road")
        rc_road_id_field = _resolve_field_name(rc_result.features, ["road_id"], "rc_patch_road")
        rc_patch_id_field = _resolve_field_name(rc_result.features, ["patch_id"], "rc_patch_road")

        announce(
            logger,
            "[Stage 2/4] Build road_id -> patch_id mapping from rc_patch_road.",
        )
        rc_mapping: dict[str, dict[str, Any]] = {}
        invalid_rc_count = 0
        for index, feature in enumerate(rc_result.features, start=1):
            road_key = _normalize_join_value(feature.properties.get(rc_road_id_field))
            patch_key = _normalize_join_value(feature.properties.get(rc_patch_id_field))

            if road_key is None or patch_key is None:
                invalid_rc_count += 1
                continue

            entry = rc_mapping.setdefault(
                road_key,
                {
                    "record_count": 0,
                    "patch_values": {},
                },
            )
            entry["record_count"] += 1
            entry["patch_values"][patch_key] = feature.properties.get(rc_patch_id_field)

            if _should_report_progress(index, total_rc_count):
                announce(logger, f"[rc_patch_road {index}/{total_rc_count}] mapping progress")

        duplicate_road_id_count = sum(1 for entry in rc_mapping.values() if entry["record_count"] > 1)
        conflicting_patch_id_count = sum(1 for entry in rc_mapping.values() if len(entry["patch_values"]) > 1)

        announce(logger, "[Stage 3/4] Join patch_id back to A200_road.")
        matched_features: list[dict[str, Any]] = []
        unmatched_features: list[dict[str, Any]] = []

        for index, feature in enumerate(a200_result.features, start=1):
            properties = dict(feature.properties)
            road_key = _normalize_join_value(properties.get(a200_id_field))
            unmatched_reason: str | None = None

            if road_key is None:
                unmatched_reason = "missing A200 id"
            else:
                entry = rc_mapping.get(road_key)
                if entry is None:
                    unmatched_reason = "no rc_patch_road match"
                elif len(entry["patch_values"]) > 1:
                    unmatched_reason = "conflicting patch_id candidates"
                    properties["conflicting_patch_ids"] = "|".join(sorted(entry["patch_values"].keys()))
                else:
                    properties["patch_id"] = next(iter(entry["patch_values"].values()))

            if unmatched_reason is None:
                matched_features.append(
                    {
                        "properties": properties,
                        "geometry": feature.geometry,
                    }
                )
            else:
                properties["patch_id"] = None
                properties["unmatched_reason"] = unmatched_reason
                unmatched_features.append(
                    {
                        "properties": properties,
                        "geometry": feature.geometry,
                    }
                )

            if _should_report_progress(index, total_a200_count):
                announce(logger, f"[A200_road {index}/{total_a200_count}] join progress")

        announce(logger, "[Stage 4/4] Write Tool4 outputs and summary.")
        write_geojson(output_path, matched_features, crs_text=target_crs_text)
        write_geojson(unmatched_output_path, unmatched_features, crs_text=target_crs_text)

        summary = {
            "run_id": run_id,
            "tool": "Tool4",
            "target_epsg": config.target_epsg,
            "a200_input_path": str(a200_input_path),
            "rc_patch_road_input_path": str(rc_input_path),
            "output_path": str(output_path),
            "unmatched_output_path": str(unmatched_output_path),
            "log_path": str(log_path),
            "summary_path": str(summary_path),
            "field_audit": {
                "a200_id_field": a200_id_field,
                "rc_road_id_field": rc_road_id_field,
                "rc_patch_id_field": rc_patch_id_field,
            },
            "total_a200_count": total_a200_count,
            "total_rc_patch_road_count": total_rc_count,
            "matched_count": len(matched_features),
            "unmatched_count": len(unmatched_features),
            "duplicate_road_id_count": duplicate_road_id_count,
            "conflicting_patch_id_count": conflicting_patch_id_count,
            "invalid_rc_count": invalid_rc_count,
            "matched_output_bounds": aggregate_bounds(feature["geometry"] for feature in matched_features),
            "unmatched_output_bounds": aggregate_bounds(feature["geometry"] for feature in unmatched_features),
            "unmatched_reason_summary": _reason_counter(unmatched_features),
        }
        write_json(summary_path, summary)
        announce(
            logger,
            "Tool4 road patch join finished. "
            f"matched_count={summary['matched_count']} unmatched_count={summary['unmatched_count']} "
            f"duplicate_road_id_count={duplicate_road_id_count} conflicting_patch_id_count={conflicting_patch_id_count}",
        )
        return summary
    finally:
        close_logger(logger)
