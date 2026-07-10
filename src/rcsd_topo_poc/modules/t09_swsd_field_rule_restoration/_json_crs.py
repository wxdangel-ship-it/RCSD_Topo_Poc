from __future__ import annotations

from pathlib import Path
from typing import Any

from pyproj import CRS
from pyproj.exceptions import CRSError


def declared_json_crs(payload: Any, *, path: Path) -> str | None:
    if not isinstance(payload, dict):
        return None
    top_level = _normalize_json_crs(payload.get("crs"))
    features = payload.get("features")
    spatial_features = [
        (index, feature)
        for index, feature in enumerate(features, start=1)
        if isinstance(features, list)
        and isinstance(feature, dict)
        and feature.get("geometry") is not None
    ] if isinstance(features, list) else []
    feature_values = [
        (index, _normalize_json_crs(feature.get("crs")))
        for index, feature in spatial_features
    ]
    if spatial_features and not top_level:
        missing = [str(index) for index, value in feature_values if not value]
        if missing:
            raise ValueError(
                f"Spatial JSON input {path} requires a declared CRS; "
                f"feature CRS is missing at indexes {', '.join(missing)}"
            )
    declared_values = [
        value
        for value in [top_level, *(item[1] for item in feature_values)]
        if value
    ]
    if not declared_values:
        return None
    parsed_values: list[CRS] = []
    for value in declared_values:
        try:
            parsed_values.append(CRS.from_user_input(value))
        except (CRSError, TypeError, ValueError) as exc:
            raise ValueError(f"JSON input {path} declares invalid CRS {value!r}") from exc
    first = parsed_values[0]
    if any(value != first for value in parsed_values[1:]):
        raise ValueError(
            f"JSON input {path} declares mixed CRS values: "
            + " | ".join(declared_values)
        )
    return first.to_string()


def parse_json_crs(value: str, *, path: Path) -> CRS:
    try:
        return CRS.from_user_input(value)
    except (CRSError, TypeError, ValueError) as exc:
        raise ValueError(f"JSON input {path} declares invalid CRS {value!r}") from exc


def _normalize_json_crs(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict) and properties.get("name") not in {None, ""}:
            return str(properties["name"]).strip()
        if value.get("name") not in {None, ""}:
            return str(value["name"]).strip()
    return str(value).strip()
