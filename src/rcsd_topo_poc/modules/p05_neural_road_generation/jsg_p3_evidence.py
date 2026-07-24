from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, MutableMapping

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_context import count_bucket
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_truth import (
    _canonical_crs,
    _property,
    _read_properties,
    _semantic_node_index,
    _string_list,
    _t01_access_nodes,
    _text,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import read_vector_payloads
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


GroupKey = tuple[str, str, str]


def _direction(value: Any) -> str:
    text = _text(value)
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return "UNKNOWN"


def _access_profile(
    segment: Mapping[str, Any] | None,
    junction_id: str,
    *,
    road_properties: Mapping[str, Mapping[str, Any]],
    node_index: Mapping[str, Mapping[str, Any]],
    node_members: Mapping[str, set[str]],
) -> Counter[str]:
    result: Counter[str] = Counter()
    if not segment or not junction_id:
        result["missing"] = 1
        return result
    access_nodes = set(_t01_access_nodes(junction_id, node_index, node_members))
    result["access_node"] = len(access_nodes)
    road_ids = tuple(_string_list(segment.get("roads")))
    result["road"] = len(road_ids)
    for road_id in road_ids:
        properties = road_properties.get(str(road_id))
        if properties is None:
            result["road_missing"] += 1
            continue
        direction = _direction(_property(properties, "direction"))
        result[f"direction_{direction}"] += 1
        start = _text(_property(properties, "snodeid"))
        end = _text(_property(properties, "enodeid"))
        if start in access_nodes:
            result[f"start_touch_direction_{direction}"] += 1
        if end in access_nodes:
            result[f"end_touch_direction_{direction}"] += 1
    return result


def _add_profile(tokens: set[str], prefix: str, profile: Mapping[str, int]) -> None:
    for name, count in sorted(profile.items()):
        tokens.add(f"raw_{prefix}_{name}={count_bucket(int(count))}")


def build_relative_evidence_tokens(
    metadata: Mapping[GroupKey, Mapping[str, Any]],
    evidence_paths: Mapping[str, Mapping[str, str]],
) -> dict[GroupKey, tuple[str, ...]]:
    tokens_by_group: MutableMapping[GroupKey, set[str]] = defaultdict(set)
    metadata_by_case: dict[str, list[tuple[GroupKey, Mapping[str, Any]]]] = defaultdict(list)
    for key, row in metadata.items():
        metadata_by_case[key[0]].append((key, row))
    for case_key, group_rows in sorted(metadata_by_case.items()):
        paths = evidence_paths.get(case_key, {})
        segment_path = normalize_runtime_path(paths.get("t01_segment") or "").resolve(
            strict=True
        )
        node_path = normalize_runtime_path(paths.get("t01_nodes") or "").resolve(strict=True)
        road_path = normalize_runtime_path(paths.get("t01_roads") or "").resolve(strict=True)
        segment_rows, segment_crs = _read_properties(segment_path)
        node_rows, node_crs = _read_properties(node_path)
        road_payloads, road_meta = read_vector_payloads(
            road_path, source_role="p3_t01_relative_evidence"
        )
        crs_values = {
            _canonical_crs(segment_crs),
            _canonical_crs(node_crs),
            _canonical_crs(str(road_meta.get("crs_wkt") or "")),
        }
        crs_values.discard("")
        if len(crs_values) != 1:
            raise ValueError(f"{case_key}: P3 relative evidence CRS mismatch {sorted(crs_values)}")
        segments = {_text(row.get("id")): row for row in segment_rows}
        normal_segments = {
            segment_id: row
            for segment_id, row in segments.items()
            if (_text(row.get("segment_type")) or "normal") != "advance_right"
        }
        incident: Counter[str] = Counter()
        for row in normal_segments.values():
            incident.update(_string_list(row.get("pair_nodes")))
            incident.update(_string_list(row.get("junc_nodes")))
        road_properties = {
            str(road_id): dict(payload.get("properties") or {})
            for road_id, payload in road_payloads.items()
        }
        node_index, node_members = _semantic_node_index(node_rows)
        for key, row in group_rows:
            object_type = str(row.get("object_type") or "")
            tokens = tokens_by_group[key]
            if object_type == "STANDARD_SEGMENT":
                segment = segments.get(str(row.get("segment_id") or ""))
                if segment is None:
                    tokens.add("raw_segment_missing=true")
                    continue
                road_ids = tuple(_string_list(segment.get("roads")))
                tokens.add(f"raw_segment_road_count={count_bucket(len(road_ids))}")
                direction_counts = Counter(
                    _direction(_property(road_properties.get(road_id, {}), "direction"))
                    for road_id in road_ids
                )
                _add_profile(tokens, "segment", {f"direction_{k}": v for k, v in direction_counts.items()})
                endpoints = tuple(_string_list(segment.get("pair_nodes")))
                for position, junction_id in zip(("start", "end"), endpoints[:2]):
                    _add_profile(
                        tokens,
                        f"segment_{position}",
                        _access_profile(
                            segment,
                            junction_id,
                            road_properties=road_properties,
                            node_index=node_index,
                            node_members=node_members,
                        ),
                    )
            elif object_type == "RELATION":
                segment = segments.get(str(row.get("segment_id") or ""))
                _add_profile(
                    tokens,
                    "relation_access",
                    _access_profile(
                        segment,
                        str(row.get("junction_id") or ""),
                        road_properties=road_properties,
                        node_index=node_index,
                        node_members=node_members,
                    ),
                )
            elif object_type == "PHYSICAL_MOVEMENT":
                junction_id = str(row.get("junction_id") or "")
                for role in ("from", "to"):
                    segment_id = str(row.get(f"{role}_segment_access") or "").partition("@")[0]
                    _add_profile(
                        tokens,
                        f"movement_{role}",
                        _access_profile(
                            segments.get(segment_id),
                            junction_id,
                            road_properties=road_properties,
                            node_index=node_index,
                            node_members=node_members,
                        ),
                    )
            elif object_type == "SEGMENT_CONNECTOR":
                segment = segments.get(str(row.get("connector_id") or ""))
                if segment is None:
                    tokens.add("raw_connector_missing=true")
                    continue
                road_ids = tuple(_string_list(segment.get("roads")))
                endpoints = tuple(_string_list(segment.get("pair_nodes")))
                attached = tuple(_string_list(segment.get("junc_nodes")))
                tokens.add(f"raw_connector_road_count={count_bucket(len(road_ids))}")
                tokens.add(f"raw_connector_endpoint_count={count_bucket(len(endpoints))}")
                tokens.add(f"raw_connector_attached_count={count_bucket(len(attached))}")
                tokens.add(
                    f"raw_connector_endpoint_incident_sum={count_bucket(sum(incident[value] for value in endpoints))}"
                )
                direction_counts = Counter(
                    _direction(_property(road_properties.get(road_id, {}), "direction"))
                    for road_id in road_ids
                )
                _add_profile(
                    tokens,
                    "connector",
                    {f"direction_{key}": value for key, value in direction_counts.items()},
                )
                for position, junction_id in zip(("start", "end"), endpoints[:2]):
                    _add_profile(
                        tokens,
                        f"connector_{position}",
                        _access_profile(
                            segment,
                            junction_id,
                            road_properties=road_properties,
                            node_index=node_index,
                            node_members=node_members,
                        ),
                    )
    return {key: tuple(sorted(values)) for key, values in tokens_by_group.items()}


__all__ = ["build_relative_evidence_tokens"]
