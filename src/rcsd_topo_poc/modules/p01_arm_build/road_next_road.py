from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.p01_arm_build.io import normalise_id
from rcsd_topo_poc.modules.p01_arm_build.models import RawRoadNextRoad


def _first_present(properties: dict[str, Any], names: tuple[str, ...]) -> Any:
    lower = {str(key).lower(): value for key, value in properties.items()}
    for name in names:
        if name in properties:
            return properties[name]
        value = lower.get(name.lower())
        if value is not None:
            return value
    return None


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


def read_road_next_road(path: Path | None) -> tuple[RawRoadNextRoad, ...]:
    if path is None:
        return tuple()
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_records = _records_from_payload(payload)
    records: list[RawRoadNextRoad] = []
    for index, properties in enumerate(raw_records, start=1):
        raw_id = normalise_id(_first_present(properties, ("id", "raw_id"))) or f"rnr_{index:06d}"
        road_id = normalise_id(_first_present(properties, ("road_id", "roadId", "roadid")))
        next_road_id = normalise_id(_first_present(properties, ("next_road_id", "nextRoadId", "nextroadid")))
        if not road_id and not next_road_id:
            continue
        records.append(
            RawRoadNextRoad(
                raw_id=raw_id,
                road_id=road_id,
                next_road_id=next_road_id,
                raw_type=normalise_id(_first_present(properties, ("type", "raw_type"))),
                raw_turn_type=normalise_id(_first_present(properties, ("turnType", "turntype", "raw_turn_type"))),
                source=normalise_id(_first_present(properties, ("source",))),
                raw_properties={str(key): value for key, value in properties.items()},
            )
        )
    return tuple(records)
