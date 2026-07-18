from __future__ import annotations

import json
import math
import os
import platform
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from pyproj import CRS, Transformer
from shapely.geometry import LineString

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg, write_json
from rcsd_topo_poc.utils.field_names import PropertyLookup, get_case_insensitive_property, normalize_field_name


TRAJECTORY_FILE_NAME = "raw_dat_pose.geojson"
OUTPUT_FILE_NAME = "raw_dat_pose.gpkg"
SUMMARY_FILE_NAME = "raw_dat_pose_summary_tool10.json"
OUTPUT_LAYER_NAME = "raw_dat_pose"
OUTPUT_CRS = CRS.from_epsg(3857)
ORDER_FIELDS = ("seq", "frame_id", "idx", "index")
TIMESTAMP_FIELDS = ("time_stamp", "timestamp", "ts", "time", "timeStamp")


@dataclass(frozen=True)
class T08TrajectoryAggregationArtifacts:
    output_gpkg: Path
    summary_json: Path


@dataclass(frozen=True)
class _TrajectoryPoint:
    xyz: tuple[float, float, float]
    seq: int
    timestamp_s: float | None
    timestamp_raw: str | None
    order_source: str
    drive_id: str | None
    feature_index: int


@dataclass(frozen=True)
class _LoadedTrajectory:
    path: Path
    source_crs: CRS
    crs_source: str
    points: tuple[_TrajectoryPoint, ...]
    timestamp_unparseable_count: int


def run_t08_trajectory_aggregation(
    *,
    patch_dir: str | Path,
    default_crs_text: str | None = None,
    max_distance_gap_m: float = 10.0,
    max_time_gap_s: float = 1.0,
    max_seq_gap: int = 20_000_000,
    overwrite: bool = False,
    progress_callback: Callable[[str], None] | None = None,
    progress_interval: int = 10_000,
) -> T08TrajectoryAggregationArtifacts:
    """Aggregate every Patch Traj PointZ source into one EPSG:3857 LineStringZ GPKG."""

    started = time.perf_counter()
    patch_path = Path(patch_dir).expanduser().resolve()
    if not patch_path.is_dir():
        raise ValueError(f"Patch directory does not exist: {patch_path}")
    traj_root = patch_path / "Traj"
    if not traj_root.is_dir():
        raise ValueError(f"Patch Traj directory does not exist: {traj_root}")

    distance_threshold = _positive_finite(max_distance_gap_m, label="max_distance_gap_m")
    time_threshold = _positive_finite(max_time_gap_s, label="max_time_gap_s")
    seq_threshold = int(max_seq_gap)
    if seq_threshold < 0:
        raise ValueError(f"max_seq_gap must be >= 0: {max_seq_gap}")
    interval = int(progress_interval)
    if interval <= 0:
        raise ValueError(f"progress_interval must be > 0: {progress_interval}")

    output_gpkg = traj_root / OUTPUT_FILE_NAME
    summary_json = traj_root / SUMMARY_FILE_NAME
    _check_output_conflicts((output_gpkg, summary_json), overwrite=overwrite)

    source_paths = sorted(path.resolve() for path in traj_root.glob(f"*/{TRAJECTORY_FILE_NAME}") if path.is_file())
    if not source_paths:
        raise ValueError(f"No trajectory inputs found: {traj_root}/*/{TRAJECTORY_FILE_NAME}")

    _emit(progress_callback, f"Tool10 discovered {len(source_paths)} trajectory source file(s).")
    records: list[dict[str, Any]] = []
    input_audit: list[dict[str, Any]] = []
    split_examples: list[dict[str, Any]] = []
    split_counts = {"distance": 0, "time": 0, "seq": 0}
    split_distance_gaps: list[float] = []
    split_time_gaps: list[float] = []
    split_seq_gaps: list[int] = []
    discarded_single_points: list[dict[str, Any]] = []
    total_points = 0
    total_timestamp_unparseable = 0
    z_min = math.inf
    z_max = -math.inf
    load_started = time.perf_counter()

    for source_index, source_path in enumerate(source_paths, start=1):
        loaded = _load_trajectory(
            source_path,
            default_crs_text=default_crs_text,
        )
        source_traj_id = source_path.parent.name
        source_records, source_stats = _split_trajectory(
            loaded.points,
            source_traj_id=source_traj_id,
            source_path=source_path,
            relative_source_path=source_path.relative_to(patch_path).as_posix(),
            max_distance_gap_m=distance_threshold,
            max_time_gap_s=time_threshold,
            max_seq_gap=seq_threshold,
        )
        records.extend(source_records)
        point_count = len(loaded.points)
        total_points += point_count
        total_timestamp_unparseable += loaded.timestamp_unparseable_count
        source_z_values = [point.xyz[2] for point in loaded.points]
        source_z_min = min(source_z_values)
        source_z_max = max(source_z_values)
        z_min = min(z_min, source_z_min)
        z_max = max(z_max, source_z_max)
        for reason in split_counts:
            split_counts[reason] += int(source_stats["split_counts"][reason])
        split_distance_gaps.extend(source_stats["split_distance_gaps"])
        split_time_gaps.extend(source_stats["split_time_gaps"])
        split_seq_gaps.extend(source_stats["split_seq_gaps"])
        split_examples.extend(source_stats["split_examples"])
        source_discarded_single_points = source_stats["discarded_single_points"]
        discarded_single_points.extend(source_discarded_single_points)
        input_audit.append(
            {
                "source_traj_id": source_traj_id,
                "source_path": source_path.relative_to(patch_path).as_posix(),
                "size_bytes": source_path.stat().st_size,
                "source_crs": loaded.source_crs.to_string(),
                "crs_source": loaded.crs_source,
                "point_count": point_count,
                "segment_count": len(source_records),
                "discarded_single_point_count": len(source_discarded_single_points),
                "split_applied": bool(source_stats["split_applied"]),
                "order_sources": sorted({point.order_source for point in loaded.points}),
                "timestamp_unparseable_count": loaded.timestamp_unparseable_count,
                "z_min": source_z_min,
                "z_max": source_z_max,
            }
        )
        _emit(
            progress_callback,
            f"Tool10 processed source {source_index}/{len(source_paths)}: "
            f"{source_path.parent.name}, points={point_count}, segments={len(source_records)}, "
            f"discarded_single_points={len(source_discarded_single_points)}.",
        )
        if total_points >= interval and total_points % interval < point_count:
            _emit(progress_callback, f"Tool10 validated {total_points} input point(s).")

    load_elapsed = time.perf_counter() - load_started
    if not records:
        raise ValueError(
            "No output trajectory segments were produced after excluding "
            f"{len(discarded_single_points)} audited single-point segment(s)"
        )
    output_point_count = sum(int(record["properties"]["point_count"]) for record in records)
    accounted_point_count = output_point_count + len(discarded_single_points)
    if accounted_point_count != total_points:
        raise ValueError(
            "Trajectory point accounting failed: "
            f"input={total_points}, output={output_point_count}, "
            f"discarded_single_points={len(discarded_single_points)}"
        )
    for index, record in enumerate(records, start=1):
        geometry = record.get("geometry")
        if not isinstance(geometry, LineString) or geometry.is_empty or not geometry.has_z:
            raise ValueError(f"Output segment {index} is not a non-empty LineStringZ")

    token = uuid.uuid4().hex
    temp_gpkg = traj_root / f".{OUTPUT_FILE_NAME}.{token}.tmp.gpkg"
    temp_summary = traj_root / f".{SUMMARY_FILE_NAME}.{token}.tmp.json"
    backup_gpkg = traj_root / f".{OUTPUT_FILE_NAME}.{token}.backup.gpkg"
    backup_summary = traj_root / f".{SUMMARY_FILE_NAME}.{token}.backup.json"
    write_started = time.perf_counter()
    try:
        write_stats = write_gpkg(
            temp_gpkg,
            records,
            crs_text=OUTPUT_CRS.to_string(),
            layer_name=OUTPUT_LAYER_NAME,
            geometry_type="LineString",
        )
        write_elapsed = time.perf_counter() - write_started
        elapsed = time.perf_counter() - started
        summary = {
            "tool": "T08 Tool10 trajectory aggregation",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "patch_id": patch_path.name,
            "inputs": {
                "patch_dir": str(patch_path),
                "traj_root": str(traj_root),
                "glob": f"Traj/*/{TRAJECTORY_FILE_NAME}",
                "files": input_audit,
            },
            "outputs": {
                "gpkg": str(output_gpkg),
                "summary_json": str(summary_json),
                "layer_name": OUTPUT_LAYER_NAME,
                "geometry_type": "LineStringZ",
                "crs": OUTPUT_CRS.to_string(),
                "size_bytes": int(write_stats.get("size_bytes", 0)),
            },
            "parameters": {
                "default_crs": default_crs_text,
                "max_distance_gap_m": distance_threshold,
                "max_time_gap_s": time_threshold,
                "max_seq_gap": seq_threshold,
                "missing_time_contiguous_seq_distance_multiplier": 2.5,
                "overwrite": bool(overwrite),
            },
            "counts": {
                "source_file_count": len(source_paths),
                "input_point_count": total_points,
                "output_point_count": output_point_count,
                "discarded_single_point_count": len(discarded_single_points),
                "accounted_point_count": accounted_point_count,
                "output_segment_count": len(records),
                "split_source_count": sum(1 for row in input_audit if row["split_applied"]),
                "split_by_distance_count": split_counts["distance"],
                "split_by_time_count": split_counts["time"],
                "split_by_seq_count": split_counts["seq"],
                "timestamp_unparseable_count": total_timestamp_unparseable,
                "missing_z_count": 0,
                "nonfinite_z_count": 0,
            },
            "z_audit": {
                "z_preservation": "source_value_unchanged",
                "z_min": z_min,
                "z_max": z_max,
            },
            "split_audit": {
                "distance_gap_m_p50": _percentile(split_distance_gaps, 50.0),
                "distance_gap_m_p90": _percentile(split_distance_gaps, 90.0),
                "distance_gap_m_max": _maximum(split_distance_gaps),
                "time_gap_s_p50": _percentile(split_time_gaps, 50.0),
                "time_gap_s_p90": _percentile(split_time_gaps, 90.0),
                "time_gap_s_max": _maximum(split_time_gaps),
                "seq_gap_p50": _percentile(split_seq_gaps, 50.0),
                "seq_gap_p90": _percentile(split_seq_gaps, 90.0),
                "seq_gap_max": _maximum(split_seq_gaps),
                "examples": split_examples[:20],
                "discarded_single_points": discarded_single_points,
            },
            "geometry_audit": {
                "point_conservation_passed": accounted_point_count == total_points,
                "point_conservation_formula": "output_point_count + discarded_single_point_count = input_point_count",
                "single_point_policy": "excluded_from_linestring_with_explicit_audit",
                "silent_geometry_fix_applied": False,
                "smoothing_applied": False,
                "simplification_applied": False,
                "z_transformation_applied": False,
            },
            "performance": {
                "elapsed_seconds": elapsed,
                "load_transform_split_seconds": load_elapsed,
                "write_gpkg_seconds": write_elapsed,
                "points_per_second": total_points / elapsed if elapsed > 0.0 else None,
            },
            "runtime": {
                "python_version": sys.version.split()[0],
                "platform": platform.platform(),
            },
        }
        write_json(temp_summary, summary)
        _commit_outputs(
            temp_pairs=((temp_gpkg, output_gpkg, backup_gpkg), (temp_summary, summary_json, backup_summary)),
            overwrite=overwrite,
        )
    finally:
        for temporary in (temp_gpkg, temp_summary, backup_gpkg, backup_summary):
            if temporary.exists():
                temporary.unlink()

    _emit(
        progress_callback,
        f"Tool10 completed: points={total_points}, segments={len(records)}, output={output_gpkg}.",
    )
    return T08TrajectoryAggregationArtifacts(output_gpkg=output_gpkg, summary_json=summary_json)


def _load_trajectory(path: Path, *, default_crs_text: str | None) -> _LoadedTrajectory:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"Failed to parse trajectory GeoJSON {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError(f"Trajectory input must be a GeoJSON FeatureCollection: {path}")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError(f"Trajectory FeatureCollection has no features list: {path}")
    if len(features) < 2:
        raise ValueError(f"Trajectory source must contain at least 2 points: {path}")

    source_crs, crs_source = _resolve_geojson_crs(payload, path=path, default_crs_text=default_crs_text)
    transformer = Transformer.from_crs(source_crs, OUTPUT_CRS, always_xy=True)
    points: list[_TrajectoryPoint] = []
    timestamp_unparseable_count = 0
    for feature_index, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise ValueError(f"Feature {feature_index + 1} is not an object: {path}")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "Point":
            raise ValueError(f"Feature {feature_index + 1} must be Point geometry: {path}")
        coords = geometry.get("coordinates")
        if not isinstance(coords, (list, tuple)) or len(coords) < 3:
            raise ValueError(f"Feature {feature_index + 1} is missing Z: {path}")
        x = _finite_coordinate(coords[0], label="X", path=path, feature_index=feature_index)
        y = _finite_coordinate(coords[1], label="Y", path=path, feature_index=feature_index)
        z = _finite_coordinate(coords[2], label="Z", path=path, feature_index=feature_index)
        try:
            metric_x, metric_y = transformer.transform(x, y)
        except Exception as exc:
            raise ValueError(f"Feature {feature_index + 1} CRS transform failed in {path}: {exc}") from exc
        if not math.isfinite(float(metric_x)) or not math.isfinite(float(metric_y)):
            raise ValueError(f"Feature {feature_index + 1} produced non-finite metric XY: {path}")
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            raise ValueError(f"Feature {feature_index + 1} properties must be an object: {path}")
        timestamp_s, timestamp_raw, timestamp_key, timestamp_invalid = _extract_timestamp(properties)
        timestamp_unparseable_count += int(timestamp_invalid)
        seq, order_source = _extract_order(
            properties,
            fallback_index=feature_index,
            timestamp_s=timestamp_s,
            timestamp_key=timestamp_key,
        )
        drive_value = _case_insensitive_value(properties, "drive_id")
        points.append(
            _TrajectoryPoint(
                xyz=(float(metric_x), float(metric_y), z),
                seq=seq,
                timestamp_s=timestamp_s,
                timestamp_raw=timestamp_raw,
                order_source=order_source,
                drive_id=None if drive_value is None else str(drive_value),
                feature_index=feature_index,
            )
        )
    ordered = tuple(sorted(points, key=lambda point: (point.seq, point.feature_index)))
    return _LoadedTrajectory(
        path=path,
        source_crs=source_crs,
        crs_source=crs_source,
        points=ordered,
        timestamp_unparseable_count=timestamp_unparseable_count,
    )


def _split_trajectory(
    points: Sequence[_TrajectoryPoint],
    *,
    source_traj_id: str,
    source_path: Path,
    relative_source_path: str,
    max_distance_gap_m: float,
    max_time_gap_s: float,
    max_seq_gap: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    split_points: list[tuple[int, str]] = [(0, "")]
    split_counts = {"distance": 0, "time": 0, "seq": 0}
    distance_gaps: list[float] = []
    time_gaps: list[float] = []
    seq_gaps: list[int] = []
    examples: list[dict[str, Any]] = []
    for index in range(1, len(points)):
        previous = points[index - 1]
        current = points[index]
        distance_gap = math.hypot(current.xyz[0] - previous.xyz[0], current.xyz[1] - previous.xyz[1])
        time_gap = (
            current.timestamp_s - previous.timestamp_s
            if current.timestamp_s is not None and previous.timestamp_s is not None
            else None
        )
        seq_gap = current.seq - previous.seq
        effective_distance_threshold = max_distance_gap_m
        if time_gap is None and abs(seq_gap) <= 1:
            effective_distance_threshold = max(max_distance_gap_m, max_distance_gap_m * 2.5)
        reasons: list[str] = []
        if distance_gap > effective_distance_threshold:
            reasons.append("distance")
            split_counts["distance"] += 1
            distance_gaps.append(distance_gap)
        if time_gap is not None and math.isfinite(time_gap) and time_gap > max_time_gap_s:
            reasons.append("time")
            split_counts["time"] += 1
            time_gaps.append(time_gap)
        if seq_gap > max_seq_gap:
            reasons.append("seq")
            split_counts["seq"] += 1
            seq_gaps.append(seq_gap)
        if not reasons:
            continue
        reason = "+".join(reasons)
        split_points.append((index, reason))
        examples.append(
            {
                "source_traj_id": source_traj_id,
                "source_path": relative_source_path,
                "reason": reason,
                "distance_gap_m": round(distance_gap, 3),
                "time_gap_s": round(time_gap, 3) if time_gap is not None and math.isfinite(time_gap) else None,
                "seq_gap": seq_gap,
                "prev_seq": previous.seq,
                "next_seq": current.seq,
            }
        )
    split_points.append((len(points), ""))

    records: list[dict[str, Any]] = []
    source_split = len(split_points) > 2
    discarded_single_points: list[dict[str, Any]] = []
    for segment_index, ((start_index, reason_before), (end_index, reason_after)) in enumerate(
        zip(split_points[:-1], split_points[1:]),
        start=1,
    ):
        segment_points = points[start_index:end_index]
        if len(segment_points) < 2:
            point = segment_points[0]
            discarded_single_points.append(
                {
                    "source_traj_id": source_traj_id,
                    "source_path": relative_source_path,
                    "segment_index": segment_index,
                    "point_index": start_index,
                    "feature_index": point.feature_index,
                    "seq": point.seq,
                    "timestamp": point.timestamp_raw,
                    "order_source": point.order_source,
                    "drive_id": point.drive_id,
                    "xyz": list(point.xyz),
                    "split_reason_before": reason_before,
                    "split_reason_after": reason_after,
                    "discard_reason": "cannot_form_linestring",
                }
            )
            continue
        geometry = LineString([point.xyz for point in segment_points])
        if geometry.is_empty or not geometry.has_z:
            raise ValueError(f"Failed to build LineStringZ: {source_path}, segment={segment_index}")
        drive_ids = sorted({point.drive_id for point in segment_points if point.drive_id is not None})
        records.append(
            {
                "properties": {
                    "traj_id": f"{source_traj_id}__seg{segment_index:04d}",
                    "source_traj_id": source_traj_id,
                    "segment_index": segment_index,
                    "point_count": len(segment_points),
                    "split_applied": source_split,
                    "order_source": "+".join(sorted({point.order_source for point in segment_points})),
                    "start_seq": segment_points[0].seq,
                    "end_seq": segment_points[-1].seq,
                    "start_timestamp": segment_points[0].timestamp_raw,
                    "end_timestamp": segment_points[-1].timestamp_raw,
                    "drive_ids": json.dumps(drive_ids, ensure_ascii=False, separators=(",", ":")),
                    "split_reason_before": reason_before,
                    "source_path": relative_source_path,
                },
                "geometry": geometry,
            }
        )
    return records, {
        "split_counts": split_counts,
        "split_distance_gaps": distance_gaps,
        "split_time_gaps": time_gaps,
        "split_seq_gaps": seq_gaps,
        "split_examples": examples,
        "discarded_single_points": discarded_single_points,
        "split_applied": source_split,
    }


def _resolve_geojson_crs(
    payload: dict[str, Any],
    *,
    path: Path,
    default_crs_text: str | None,
) -> tuple[CRS, str]:
    crs_payload = payload.get("crs")
    if crs_payload is None:
        if default_crs_text is None or not str(default_crs_text).strip():
            raise ValueError(f"CRS not found and no default CRS configured: {path}")
        try:
            return CRS.from_user_input(default_crs_text), "default"
        except Exception as exc:
            raise ValueError(f"Invalid default CRS for {path}: {default_crs_text}") from exc
    try:
        if isinstance(crs_payload, str):
            return CRS.from_user_input(crs_payload), "geojson.crs"
        if not isinstance(crs_payload, dict):
            raise ValueError("crs must be an object or string")
        crs_type = str(crs_payload.get("type", "")).strip().lower()
        properties = crs_payload.get("properties") or {}
        if not isinstance(properties, dict):
            raise ValueError("crs.properties must be an object")
        if crs_type == "name" and properties.get("name"):
            return CRS.from_user_input(properties["name"]), "geojson.crs.name"
        if crs_type == "epsg" and properties.get("code") is not None:
            return CRS.from_epsg(int(properties["code"])), "geojson.crs.epsg"
        if properties.get("name"):
            return CRS.from_user_input(properties["name"]), "geojson.crs.name"
        raise ValueError("unsupported GeoJSON CRS object")
    except Exception as exc:
        raise ValueError(f"Invalid GeoJSON CRS in {path}: {crs_payload}") from exc


def _extract_order(
    properties: dict[str, Any],
    *,
    fallback_index: int,
    timestamp_s: float | None,
    timestamp_key: str | None,
) -> tuple[int, str]:
    lookup = PropertyLookup(properties)
    for field in ORDER_FIELDS:
        if not lookup.has(field):
            continue
        numeric = _finite_number(lookup.get(field))
        if numeric is not None:
            return int(round(numeric)), normalize_field_name(field)
    if timestamp_s is not None and math.isfinite(timestamp_s):
        return int(round(timestamp_s * 1000.0)), timestamp_key or "timestamp"
    return int(fallback_index), "feature_index"


def _extract_timestamp(properties: dict[str, Any]) -> tuple[float | None, str | None, str | None, bool]:
    lookup = PropertyLookup(properties)
    seen_key: str | None = None
    seen_raw: str | None = None
    for field in dict.fromkeys(normalize_field_name(name) for name in TIMESTAMP_FIELDS):
        if not lookup.has(field):
            continue
        value = lookup.get(field)
        seen_key = field
        seen_raw = None if value is None else str(value)
        parsed = _parse_timestamp_seconds(value)
        if parsed is not None:
            return parsed, seen_raw, field, False
    return None, seen_raw, seen_key, seen_key is not None


def _parse_timestamp_seconds(value: Any) -> float | None:
    numeric = _finite_number(value)
    if numeric is not None:
        absolute = abs(numeric)
        if absolute > 1e14:
            return numeric / 1_000_000.0
        if absolute > 1e11:
            return numeric / 1000.0
        return numeric
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None
    return parsed if math.isfinite(parsed) else None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def _finite_coordinate(value: Any, *, label: str, path: Path, feature_index: int) -> float:
    numeric = _finite_number(value)
    if numeric is None:
        raise ValueError(f"Feature {feature_index + 1} has non-finite or invalid {label}: {path}")
    return numeric


def _case_insensitive_value(properties: dict[str, Any], name: str) -> Any:
    return get_case_insensitive_property(properties, name)


def _positive_finite(value: Any, *, label: str) -> float:
    numeric = _finite_number(value)
    if numeric is None or numeric <= 0.0:
        raise ValueError(f"{label} must be a finite value > 0: {value}")
    return numeric


def _percentile(values: Sequence[float] | Sequence[int], percentile: float) -> float | None:
    cleaned = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    rank = (len(cleaned) - 1) * max(0.0, min(100.0, percentile)) / 100.0
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return cleaned[lower]
    weight = rank - lower
    return cleaned[lower] * (1.0 - weight) + cleaned[upper] * weight


def _maximum(values: Sequence[float] | Sequence[int]) -> float | None:
    cleaned = [float(value) for value in values if math.isfinite(float(value))]
    return max(cleaned) if cleaned else None


def _check_output_conflicts(paths: Iterable[Path], *, overwrite: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not overwrite:
        raise ValueError("Output already exists; use overwrite=True: " + ", ".join(str(path) for path in existing))


def _commit_outputs(
    *,
    temp_pairs: Sequence[tuple[Path, Path, Path]],
    overwrite: bool,
) -> None:
    if not overwrite:
        _check_output_conflicts((final for _, final, _ in temp_pairs), overwrite=False)
    backed_up: list[tuple[Path, Path]] = []
    committed: list[Path] = []
    try:
        if overwrite:
            for _, final, backup in temp_pairs:
                if final.exists():
                    os.replace(final, backup)
                    backed_up.append((final, backup))
        for temporary, final, _ in temp_pairs:
            os.replace(temporary, final)
            committed.append(final)
    except Exception:
        for final in committed:
            if final.exists():
                final.unlink()
        for final, backup in reversed(backed_up):
            if backup.exists():
                os.replace(backup, final)
        raise
    for _, backup in backed_up:
        if backup.exists():
            backup.unlink()


def _emit(progress_callback: Callable[[str], None] | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


__all__ = ["T08TrajectoryAggregationArtifacts", "run_t08_trajectory_aggregation"]
