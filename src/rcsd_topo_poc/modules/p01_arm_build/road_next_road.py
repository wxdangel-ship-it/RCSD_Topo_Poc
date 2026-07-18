from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import ijson

from rcsd_topo_poc.modules.p01_arm_build.io import normalise_id
from rcsd_topo_poc.modules.p01_arm_build.models import RawRoadNextRoad
from rcsd_topo_poc.utils.field_names import get_case_insensitive_property


def _first_present(properties: dict[str, Any], names: tuple[str, ...]) -> Any:
    return get_case_insensitive_property(properties, names)


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item or {}) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("features"), list):
        records: list[dict[str, Any]] = []
        for feature in payload["features"]:
            if not isinstance(feature, dict):
                continue
            properties = dict(feature.get("properties") or {})
            if "id" not in properties and feature.get("id") is not None:
                properties["id"] = feature.get("id")
            records.append(properties)
        return records
    for key in ("records", "data", "items"):
        if isinstance(payload.get(key), list):
            return [dict(item or {}) for item in payload[key] if isinstance(item, dict)]
    return [payload]


def _stream_prefix_from_header(path: Path) -> str | None:
    with path.open("rb") as fh:
        sample = fh.read(8192).decode("utf-8", errors="ignore")
    stripped = sample.lstrip()
    if not stripped:
        return None
    if stripped.startswith("["):
        return "item"
    for key in ("features", "records", "data", "items", "roadNodeRoads", "road_next_roads", "RoadNextRoad"):
        if re.search(rf'"{re.escape(key)}"\s*:', sample):
            return f"{key}.item"
    return None


def _properties_from_stream_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    if isinstance(item.get("properties"), dict):
        properties = dict(item.get("properties") or {})
        if "id" not in properties and item.get("id") is not None:
            properties["id"] = item.get("id")
        return properties
    return dict(item)


def _raw_record_from_properties(index: int, properties: dict[str, Any]) -> RawRoadNextRoad | None:
    raw_id = normalise_id(_first_present(properties, ("id", "raw_id"))) or f"rnr_{index:06d}"
    road_id = normalise_id(_first_present(properties, ("road_id", "roadId", "roadid")))
    next_road_id = normalise_id(_first_present(properties, ("next_road_id", "nextRoadId", "nextroadid")))
    if not road_id and not next_road_id:
        return None
    return RawRoadNextRoad(
        raw_id=raw_id,
        road_id=road_id,
        next_road_id=next_road_id,
        raw_type=normalise_id(_first_present(properties, ("type", "raw_type"))),
        raw_turn_type=normalise_id(_first_present(properties, ("turnType", "turntype", "raw_turn_type"))),
        source=normalise_id(_first_present(properties, ("source",))),
        raw_properties={str(key): value for key, value in properties.items()},
    )


def _read_road_next_road_streamed(path: Path, selected_road_ids: set[str]) -> tuple[RawRoadNextRoad, ...] | None:
    prefix = _stream_prefix_from_header(path)
    if not prefix:
        return None
    records: list[RawRoadNextRoad] = []
    with path.open("rb") as fh:
        for index, item in enumerate(ijson.items(fh, prefix, use_float=True), start=1):
            properties = _properties_from_stream_item(item)
            if properties is None:
                continue
            record = _raw_record_from_properties(index, properties)
            if record is None:
                continue
            if record.road_id not in selected_road_ids and record.next_road_id not in selected_road_ids:
                continue
            records.append(record)
    return tuple(records)


def read_road_next_road(
    path: Path | None,
    *,
    selected_road_ids: set[str] | frozenset[str] | None = None,
) -> tuple[RawRoadNextRoad, ...]:
    if path is None:
        return tuple()
    selected = {normalise_id(road_id) for road_id in selected_road_ids or set() if normalise_id(road_id)}
    if selected:
        streamed = _read_road_next_road_streamed(path, selected)
        if streamed is not None:
            return streamed
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_records = _records_from_payload(payload)
    records: list[RawRoadNextRoad] = []
    for index, properties in enumerate(raw_records, start=1):
        record = _raw_record_from_properties(index, properties)
        if record is None:
            continue
        if selected and record.road_id not in selected and record.next_road_id not in selected:
            continue
        records.append(record)
    return tuple(records)
