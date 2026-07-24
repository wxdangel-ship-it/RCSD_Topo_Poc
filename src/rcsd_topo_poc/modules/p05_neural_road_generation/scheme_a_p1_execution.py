from __future__ import annotations

import platform
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona
from pyproj import CRS
from shapely.geometry import shape

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import (
    split_segment_access,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


FORWARD_DIRECTIONS = {"0", "1", "2"}
REVERSE_DIRECTIONS = {"0", "1", "3"}

NODE_CARRIER_FIELDS = (
    "id",
    "kind",
    "grade",
    "closed_con",
    "cross_flag",
    "intersecti",
    "cross_lid",
    "mainnodeid",
    "subnodeid",
    "node_lid",
    "source",
    "kind_2",
    "grade_2",
    "sgrade",
    "segmentid",
)
ROAD_CARRIER_FIELDS = (
    "id",
    "snodeid",
    "enodeid",
    "direction",
    "const_st",
    "length",
    "roadtype",
    "road_kind",
    "source",
    "alias_id",
    "formway",
    "uflag",
    "patch_id",
    "kind",
    "sgrade",
    "segmentid",
    "segment_build_source",
)
IDENTIFIER_FIELDS = {"id", "snodeid", "enodeid", "mainnodeid"}


def select_effective_candidate(
    candidates: Sequence[Mapping[str, Any]],
    *,
    selected_candidate_id: str,
    confidence: float,
    anomaly_probability: float,
    confidence_threshold: float,
    anomaly_threshold: float,
    hard_unsafe: bool,
) -> dict[str, Any]:
    by_id = {str(row["candidate_id"]): dict(row) for row in candidates}
    selected = by_id.get(selected_candidate_id)
    if selected is None:
        raise ValueError(f"selected candidate is outside group: {selected_candidate_id}")
    fallback_reason = ""
    decision = "PUBLISH_CANDIDATE"
    if hard_unsafe:
        decision, fallback_reason = "HARD_FALLBACK", "hard_unsafe"
    elif str(selected.get("candidate_target")) == "REVIEW_FALLBACK":
        decision, fallback_reason = "MODEL_FALLBACK", "model_selected_fallback"
    elif confidence < confidence_threshold:
        decision, fallback_reason = "MODEL_FALLBACK", "low_confidence"
    elif anomaly_probability >= anomaly_threshold:
        decision, fallback_reason = "MODEL_FALLBACK", "high_anomaly_probability"
    effective = selected
    if decision != "PUBLISH_CANDIDATE":
        swsd = [
            dict(row)
            for row in candidates
            if "SWSD_IDENTITY" in set(row.get("source_kinds") or [])
            and row.get("target_payload")
            and str(row.get("target_kind")) in {"ROAD", "NODE"}
        ]
        if swsd:
            effective = min(
                swsd,
                key=lambda row: (
                    str(row.get("candidate_target")) != "KEEP_SWSD",
                    len(row.get("source_kinds") or []),
                    str(row["candidate_id"]),
                ),
            )
        else:
            effective = selected
            decision = "FAIL"
            fallback_reason = "no_legal_swsd_carrier"
    source_kinds = set(effective.get("source_kinds") or [])
    if decision != "PUBLISH_CANDIDATE" or str(effective.get("candidate_target")) == "KEEP_SWSD":
        effective_source_kind = "SWSD_IDENTITY"
    elif "REGISTERED_STRATEGY_PROPOSAL" in source_kinds:
        effective_source_kind = "REGISTERED_STRATEGY_PROPOSAL"
    else:
        effective_source_kind = next(iter(sorted(source_kinds)), "")
    return {
        "decision": decision,
        "fallback_reason": fallback_reason,
        "selected_candidate_id": selected_candidate_id,
        "effective_candidate_id": str(effective["candidate_id"]),
        "effective_candidate_target": str(effective.get("candidate_target") or ""),
        "effective_source_kind": effective_source_kind,
        "effective_target_kind": str(effective.get("target_kind") or ""),
        "effective_target_payload": list(effective.get("target_payload") or []),
    }


def expand_movement_fallback_closure(
    predictions: Sequence[Mapping[str, Any]],
    candidates_by_group: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in predictions]
    movement_rows = [row for row in rows if row["object_type"] == "MOVEMENT"]
    selected_nodes: dict[str, tuple[str, ...]] = {}
    node_uses: Counter[str] = Counter()
    for row in movement_rows:
        candidates = candidates_by_group[str(row["group_id"])]
        selected = next(
            (
                candidate
                for candidate in candidates
                if str(candidate["candidate_id"])
                == str(row["effective_candidate_id"])
            ),
            None,
        )
        if selected is None or not selected.get("target_payload"):
            selected = next(
                (
                    candidate
                    for candidate in candidates
                    if "SWSD_IDENTITY" in set(candidate.get("source_kinds") or [])
                    and candidate.get("target_payload")
                ),
                None,
            )
        payload = tuple(str(value) for value in (selected or {}).get("target_payload") or [])
        selected_nodes[str(row["group_id"])] = payload
        node_uses.update(payload)
    junction_fallbacks: set[str] = set()
    for row in movement_rows:
        if row["decision"] not in {"MODEL_FALLBACK", "HARD_FALLBACK", "FAIL"}:
            continue
        payload = selected_nodes[str(row["group_id"])]
        shared = any(node_uses[node_id] > 1 for node_id in payload)
        candidates = candidates_by_group[str(row["group_id"])]
        explicit_junction_conflict = any(
            "PROPOSAL_JUNCTION_CONFLICT:True" in set(candidate.get("object_tokens") or [])
            for candidate in candidates
        )
        if shared or explicit_junction_conflict:
            junction_fallbacks.add(_movement_parts(str(row["object_id"]))[0])
    if not junction_fallbacks:
        for row in rows:
            row.setdefault("fallback_unit", row["object_type"])
        return rows
    segment_ids: set[str] = set()
    for row in movement_rows:
        junction_id, from_segment, to_segment = _movement_parts(str(row["object_id"]))
        if junction_id in junction_fallbacks:
            segment_ids.update({from_segment, to_segment})
            if row["decision"] == "PUBLISH_CANDIDATE":
                _force_swsd(row, candidates_by_group[str(row["group_id"])], "junction_closure")
            row["fallback_unit"] = "JUNCTION"
    for row in rows:
        if row["object_type"] == "SEGMENT" and row["object_id"] in segment_ids:
            if row["decision"] == "PUBLISH_CANDIDATE":
                _force_swsd(row, candidates_by_group[str(row["group_id"])], "junction_closure")
            row["fallback_unit"] = "JUNCTION"
        elif "fallback_unit" not in row:
            row["fallback_unit"] = row["object_type"]
    return rows


def fallback_conflicting_groups_to_swsd(
    predictions: Sequence[Mapping[str, Any]],
    candidates_by_group: Mapping[str, Sequence[Mapping[str, Any]]],
    failure_group_ids: Iterable[str],
    *,
    reason: str,
) -> tuple[list[dict[str, Any]], int]:
    target_groups = {str(value) for value in failure_group_ids}
    rows = [dict(row) for row in predictions]
    before = {
        str(row["group_id"]): (
            str(row.get("decision") or ""),
            str(row.get("effective_candidate_id") or ""),
        )
        for row in rows
    }
    for row in rows:
        if str(row["group_id"]) not in target_groups:
            continue
        _force_swsd(row, candidates_by_group[str(row["group_id"])], reason)
        row["fallback_unit"] = row["object_type"]
    rows = expand_movement_fallback_closure(rows, candidates_by_group)
    changed = sum(
        before[str(row["group_id"])]
        != (
            str(row.get("decision") or ""),
            str(row.get("effective_candidate_id") or ""),
        )
        for row in rows
    )
    return rows, changed


def fallback_case_to_swsd(
    predictions: Sequence[Mapping[str, Any]],
    candidates_by_group: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    reason: str,
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in predictions]
    for row in rows:
        _force_swsd(row, candidates_by_group[str(row["group_id"])], reason)
        if row["decision"] != "FAIL":
            row["decision"] = "HARD_FALLBACK"
            row["fallback_unit"] = row["object_type"]
    return expand_movement_fallback_closure(rows, candidates_by_group)


def _force_swsd(
    row: dict[str, Any], candidates: Sequence[Mapping[str, Any]], reason: str
) -> bool:
    before = (
        str(row.get("decision") or ""),
        str(row.get("effective_candidate_id") or ""),
    )
    swsd_candidates = [
        candidate
        for candidate in candidates
        if "SWSD_IDENTITY" in set(candidate.get("source_kinds") or [])
        and candidate.get("target_payload")
    ]
    if not swsd_candidates:
        row["decision"] = "FAIL"
        row["fallback_reason"] = "no_legal_swsd_carrier"
        return before != (
            str(row.get("decision") or ""),
            str(row.get("effective_candidate_id") or ""),
        )
    swsd = min(
        swsd_candidates,
        key=lambda candidate: (
            str(candidate.get("candidate_target")) != "KEEP_SWSD",
            len(candidate.get("source_kinds") or []),
            str(candidate["candidate_id"]),
        ),
    )
    row["decision"] = "HARD_FALLBACK"
    row["fallback_reason"] = reason
    row["effective_candidate_id"] = str(swsd["candidate_id"])
    row["effective_candidate_target"] = str(swsd["candidate_target"])
    row["effective_source_kind"] = "SWSD_IDENTITY"
    row["effective_target_kind"] = str(swsd["target_kind"])
    row["effective_target_payload"] = list(swsd.get("target_payload") or [])
    return before != (
        str(row.get("decision") or ""),
        str(row.get("effective_candidate_id") or ""),
    )


def materialize_case_roadgraph(
    case_key: str,
    predictions: Sequence[Mapping[str, Any]],
    candidates_by_id: Mapping[str, Mapping[str, Any]],
    lineage_by_role: Mapping[str, str],
    *,
    expected_crs: str = "EPSG:3857",
    vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]] | None = None,
    payload_signature_cache: dict[int, str] | None = None,
    node_payload_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    node_source_overrides: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if vector_cache is None:
        vector_cache = {}
    if payload_signature_cache is None:
        payload_signature_cache = {}

    def payload_signature(payload: Mapping[str, Any]) -> str:
        key = id(payload)
        if key not in payload_signature_cache:
            payload_signature_cache[key] = _payload_signature(payload)
        return payload_signature_cache[key]
    semantic_signature_cache: dict[int, str] = {}

    def semantic_signature(payload: Mapping[str, Any]) -> str:
        key = id(payload)
        if key not in semantic_signature_cache:
            semantic_signature_cache[key] = _semantic_payload_signature(payload)
        return semantic_signature_cache[key]

    road_payloads: dict[str, dict[str, Any]] = {}
    node_payloads: dict[str, dict[str, Any]] = {}
    road_sources: dict[str, set[str]] = defaultdict(set)
    node_sources: dict[str, set[str]] = defaultdict(set)
    road_groups: dict[str, set[str]] = defaultdict(set)
    node_groups: dict[str, set[str]] = defaultdict(set)
    failures: list[str] = []
    failure_group_ids: set[str] = set()
    equivalent_payload_ids: set[str] = set()
    selected_candidates: list[dict[str, Any]] = []
    for prediction in sorted(predictions, key=lambda row: str(row["group_id"])):
        group_id = str(prediction["group_id"])
        candidate_id = str(prediction["effective_candidate_id"])
        candidate = dict(candidates_by_id[candidate_id])
        effective_source_kind = str(prediction.get("effective_source_kind") or "")
        selected_candidates.append(
            {
                "group_id": prediction["group_id"],
                "object_type": prediction["object_type"],
                "object_id": prediction["object_id"],
                "decision": prediction["decision"],
                "candidate_id": candidate_id,
                "target_kind": candidate["target_kind"],
                "target_payload": candidate["target_payload"],
                "effective_source_kind": effective_source_kind,
            }
        )
        target = road_payloads if candidate["target_kind"] == "ROAD" else node_payloads
        sources = road_sources if candidate["target_kind"] == "ROAD" else node_sources
        groups = road_groups if candidate["target_kind"] == "ROAD" else node_groups
        for payload_id in candidate.get("target_payload") or []:
            provenance = [
                item
                for item in candidate.get("payload_artifact_by_id") or []
                if str(item[0]) == str(payload_id)
            ]
            if len(provenance) > 1:
                if effective_source_kind == "SWSD_IDENTITY":
                    provenance = [item for item in provenance if str(item[1]).startswith("t01_")]
                elif effective_source_kind == "REGISTERED_STRATEGY_PROPOSAL":
                    provenance = [
                        item for item in provenance if str(item[1]).startswith("proposal_")
                    ]
            if provenance:
                roles = [str(item[1]) for item in provenance]
                paths = [str(item[2]) for item in provenance]
            else:
                artifacts = list(candidate.get("payload_artifacts") or [])
                if effective_source_kind == "SWSD_IDENTITY":
                    artifacts = [item for item in artifacts if str(item[0]).startswith("t01_")]
                elif effective_source_kind == "REGISTERED_STRATEGY_PROPOSAL":
                    artifacts = [
                        item for item in artifacts if str(item[0]).startswith("proposal_")
                    ]
                roles = [str(item[0]) for item in artifacts]
                paths = [str(item[1]) for item in artifacts]
            matches: list[tuple[dict[str, Any], str]] = []
            for role, path in zip(roles, paths, strict=True):
                payloads, crs = _read_vector(path, vector_cache)
                if _canonical_crs(crs) != expected_crs:
                    failures.append(f"CRS mismatch {role}: {_canonical_crs(crs)}")
                    failure_group_ids.add(group_id)
                if str(payload_id) in payloads:
                    matches.append((payloads[str(payload_id)], role))
            if not matches:
                failures.append(f"candidate payload missing: {candidate_id}/{payload_id}")
                failure_group_ids.add(group_id)
                continue
            signatures = {payload_signature(payload) for payload, _ in matches}
            semantic_signatures = {semantic_signature(payload) for payload, _ in matches}
            if len(semantic_signatures) > 1:
                failures.append(f"duplicate ID has different payload: {payload_id}")
                failure_group_ids.add(group_id)
                continue
            if len(signatures) > 1:
                equivalent_payload_ids.add(str(payload_id))
            existing = target.get(str(payload_id))
            if existing is not None:
                if semantic_signature(existing) not in semantic_signatures:
                    failures.append(f"duplicate ID has different selected payload: {payload_id}")
                    failure_group_ids.update(groups.get(str(payload_id), set()))
                    failure_group_ids.add(group_id)
                    continue
                if payload_signature(existing) not in signatures:
                    equivalent_payload_ids.add(str(payload_id))
            target[str(payload_id)] = matches[0][0]
            sources[str(payload_id)].update(role for _, role in matches)
            groups[str(payload_id)].add(group_id)

    endpoint_ids: set[str] = set()
    endpoint_roles: dict[str, set[str]] = defaultdict(set)
    endpoint_groups: dict[str, set[str]] = defaultdict(set)
    directed_edges: set[tuple[str, str]] = set()
    directed_edge_groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for road_id, payload in sorted(road_payloads.items()):
        properties = dict(payload.get("properties") or {})
        start = _text(_property(properties, "snodeid"))
        end = _text(_property(properties, "enodeid"))
        direction = _text(_property(properties, "direction"))
        if not start or not end:
            failures.append(f"Road endpoint missing: {road_id}")
            failure_group_ids.update(road_groups.get(road_id, set()))
            continue
        endpoint_ids.update({start, end})
        endpoint_groups[start].update(road_groups.get(road_id, set()))
        endpoint_groups[end].update(road_groups.get(road_id, set()))
        node_role = (
            "proposal_nodes"
            if "proposal_roads" in road_sources.get(road_id, set())
            else "t01_nodes"
        )
        endpoint_roles[start].add(node_role)
        endpoint_roles[end].add(node_role)
        if direction not in FORWARD_DIRECTIONS | REVERSE_DIRECTIONS:
            failures.append(f"Road direction invalid: {road_id}/{direction}")
            failure_group_ids.update(road_groups.get(road_id, set()))
        if direction in FORWARD_DIRECTIONS:
            directed_edges.add((start, end))
            directed_edge_groups[(start, end)].update(road_groups.get(road_id, set()))
        if direction in REVERSE_DIRECTIONS:
            directed_edges.add((end, start))
            directed_edge_groups[(end, start)].update(road_groups.get(road_id, set()))
        failure_count_before_geometry = len(failures)
        _validate_geometry("Road", road_id, payload, failures)
        if len(failures) > failure_count_before_geometry:
            failure_group_ids.update(road_groups.get(road_id, set()))
    for node_id in sorted(endpoint_ids):
        override = (node_payload_overrides or {}).get(node_id)
        if override is not None:
            matches = [
                (
                    dict(override),
                    str((node_source_overrides or {}).get(node_id) or "explicit_node_carrier"),
                )
            ]
        else:
            matches = []
            expected_roles = endpoint_roles.get(node_id) or {"proposal_nodes", "t01_nodes"}
            for role in sorted(expected_roles):
                path = lineage_by_role.get(role, "")
                if not path:
                    continue
                payloads, crs = _read_vector(path, vector_cache)
                if _canonical_crs(crs) != expected_crs:
                    failures.append(f"CRS mismatch {role}: {_canonical_crs(crs)}")
                    failure_group_ids.update(endpoint_groups.get(node_id, set()))
                if node_id in payloads:
                    matches.append((payloads[node_id], role))
        if not matches:
            failures.append(f"Road endpoint Node missing: {node_id}")
            failure_group_ids.update(endpoint_groups.get(node_id, set()))
            continue
        signatures = {payload_signature(payload) for payload, _ in matches}
        semantic_signatures = {semantic_signature(payload) for payload, _ in matches}
        if len(semantic_signatures) > 1:
            failures.append(f"duplicate Node ID has different selected payload: {node_id}")
            failure_group_ids.update(endpoint_groups.get(node_id, set()))
            failure_group_ids.update(node_groups.get(node_id, set()))
            continue
        if len(signatures) > 1:
            equivalent_payload_ids.add(node_id)
        existing = node_payloads.get(node_id)
        if existing is not None:
            if semantic_signature(existing) not in semantic_signatures:
                failures.append(f"duplicate Node ID has different selected payload: {node_id}")
                failure_group_ids.update(endpoint_groups.get(node_id, set()))
                failure_group_ids.update(node_groups.get(node_id, set()))
                continue
            if payload_signature(existing) not in signatures:
                equivalent_payload_ids.add(node_id)
        node_payloads[node_id] = matches[0][0]
        node_sources[node_id].update(role for _, role in matches)
        node_groups[node_id].update(endpoint_groups.get(node_id, set()))
    for node_id, payload in sorted(node_payloads.items()):
        failure_count_before_geometry = len(failures)
        _validate_geometry("Node", node_id, payload, failures)
        if len(failures) > failure_count_before_geometry:
            failure_group_ids.update(node_groups.get(node_id, set()))
    for start, end in sorted(directed_edges):
        if start in node_payloads and end in node_payloads:
            continue
        failures.append(f"directed edge endpoint missing: {start}->{end}")
        failure_group_ids.update(directed_edge_groups.get((start, end), set()))
    for row in predictions:
        if row["decision"] != "FAIL":
            continue
        group_id = str(row["group_id"])
        failures.append(f"execution decision failed: {group_id}")
        failure_group_ids.add(group_id)
    payload = {
        "schema_version": "p05-scheme-a-p1-roadgraph-v1",
        "case_key": case_key,
        "crs": expected_crs,
        "selected_candidates": selected_candidates,
        "road_ids": sorted(road_payloads),
        "node_ids": sorted(node_payloads),
        "directed_edges": [list(edge) for edge in sorted(directed_edges)],
        "road_payload_signatures": {
            key: payload_signature(value) for key, value in sorted(road_payloads.items())
        },
        "node_payload_signatures": {
            key: payload_signature(value) for key, value in sorted(node_payloads.items())
        },
        "road_sources": {key: sorted(value) for key, value in sorted(road_sources.items())},
        "node_sources": {key: sorted(value) for key, value in sorted(node_sources.items())},
        "audit": {
            "legal": not failures,
            "failure_count": len(failures),
            "failures": sorted(set(failures)),
            "failure_group_ids": sorted(failure_group_ids),
            "semantically_equivalent_payload_coalesce_count": len(equivalent_payload_ids),
            "semantically_equivalent_payload_ids": sorted(equivalent_payload_ids),
            "road_count": len(road_payloads),
            "node_count": len(node_payloads),
            "directed_edge_count": len(directed_edges),
            "relaxation": False,
            "content_repair": False,
            "silent_fix": False,
            "skeleton_mutation_count": 0,
        },
    }
    if node_payload_overrides is not None:
        payload["audit"]["explicit_node_carrier_override_count"] = len(
            set(endpoint_ids) & set(node_payload_overrides)
        )
    payload["roadgraph_signature"] = canonical_sha256(payload)
    return payload


def _movement_parts(object_id: str) -> tuple[str, str, str]:
    junction_id, _, movement = object_id.partition(":")
    source_access, separator, target_access = movement.partition("->")
    if not junction_id or not separator:
        raise ValueError(f"invalid Movement object ID: {object_id}")
    source_segment = (
        split_segment_access(source_access)[0] if "@" in source_access else source_access
    )
    target_segment = (
        split_segment_access(target_access)[0] if "@" in target_access else target_access
    )
    return junction_id, source_segment, target_segment


def _read_vector(
    path: str, cache: dict[str, tuple[dict[str, dict[str, Any]], str]]
) -> tuple[dict[str, dict[str, Any]], str]:
    if path in cache:
        return cache[path]
    io_path = _io_path(path)
    layers = fiona.listlayers(io_path)
    if len(layers) != 1:
        raise ValueError(f"expected one vector layer: {path}")
    rows: dict[str, dict[str, Any]] = {}
    with fiona.open(io_path, layer=layers[0]) as source:
        crs = source.crs_wkt or str(source.crs)
        for feature in source:
            properties = dict(feature["properties"])
            identifier = _text(_property(properties, "id"))
            if not identifier:
                continue
            rows[identifier] = {
                "properties": properties,
                "geometry": dict(feature["geometry"]) if feature["geometry"] else None,
            }
    cache[path] = rows, crs
    return cache[path]


def _validate_geometry(
    kind: str, identifier: str, payload: Mapping[str, Any], failures: list[str]
) -> None:
    geometry = payload.get("geometry")
    if not geometry:
        failures.append(f"{kind} geometry missing: {identifier}")
        return
    value = shape(geometry)
    if value.is_empty or not value.is_valid:
        failures.append(f"{kind} geometry invalid: {identifier}")


def _payload_signature(payload: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {"properties": dict(payload.get("properties") or {}), "geometry": payload.get("geometry")}
    )


def _semantic_payload_signature(payload: Mapping[str, Any]) -> str:
    geometry = dict(payload.get("geometry") or {})
    geometry_type = str(geometry.get("type") or "")
    fields = NODE_CARRIER_FIELDS if "Point" in geometry_type else ROAD_CARRIER_FIELDS
    properties = dict(payload.get("properties") or {})
    normalized_properties = {
        field: (
            _text(properties.get(field))
            if field in IDENTIFIER_FIELDS
            else properties.get(field)
        )
        for field in fields
    }
    return canonical_sha256(
        {
            "properties": normalized_properties,
            "geometry": _semantic_geometry(geometry),
        }
    )


def _semantic_geometry(geometry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": str(geometry.get("type") or ""),
        "coordinates": _xy_coordinates(geometry.get("coordinates")),
    }


def _xy_coordinates(value: Any) -> Any:
    if not isinstance(value, (list, tuple)):
        return value
    if value and all(isinstance(item, (int, float)) for item in value):
        return [float(item) for item in value[:2]]
    return [_xy_coordinates(item) for item in value]


@lru_cache(maxsize=32)
def _canonical_crs(value: Any) -> str:
    authority = CRS.from_user_input(value).to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else CRS.from_user_input(value).to_wkt()


def _io_path(path: str | Path) -> str:
    raw = str(normalize_runtime_path(path).absolute())
    if platform.system() == "Windows" and not raw.startswith("\\\\?\\") and len(raw) >= 248:
        return "\\\\?\\" + raw
    return raw


def _property(properties: Mapping[str, Any], name: str) -> Any:
    for key, value in properties.items():
        if str(key).lower() == name.lower():
            return value
    return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


__all__ = [
    "expand_movement_fallback_closure",
    "fallback_case_to_swsd",
    "fallback_conflicting_groups_to_swsd",
    "materialize_case_roadgraph",
    "select_effective_candidate",
]
