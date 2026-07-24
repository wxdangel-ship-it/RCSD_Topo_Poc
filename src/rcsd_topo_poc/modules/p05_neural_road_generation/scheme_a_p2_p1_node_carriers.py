from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import canonical_sha256
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_dataset import (
    candidate_matches_label,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_execution import (
    NODE_CARRIER_FIELDS,
    _property,
    _read_vector,
    _semantic_payload_signature,
    _text,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_models import (
    SCHEME_A_P2_P1_DATASET_SCHEMA,
)


T01_NODE = "T01_NODE"
PROPOSAL_NODE = "PROPOSAL_NODE"
OMIT = "OMIT"


@dataclass
class _Option:
    case_key: str
    node_id: str
    carrier_kind: str
    payload_signature: str
    output_payloads: list[dict[str, Any]]
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    lineage_kinds: set[str] = field(default_factory=set)

    @property
    def group_id(self) -> str:
        return f"P2P1:NODE:{self.case_key}:{self.node_id}"

    @property
    def candidate_id(self) -> str:
        return "p2p1n:" + canonical_sha256(
            {
                "case_key": self.case_key,
                "node_id": self.node_id,
                "carrier_kind": self.carrier_kind,
                "payload_signature": self.payload_signature,
            }
        )[:24]


def build_endpoint_node_carriers(
    *,
    pto_candidate_path: Path,
    p1_lineage_path: Path,
    segment_candidates: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    segment_labels: Mapping[tuple[str, str], Mapping[str, Any]],
    case_folds: Mapping[str, int],
    expected_missing_nodes: Sequence[tuple[str, str]] = (),
) -> dict[str, Any]:
    vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]] = {}
    possible_nodes, possible_sources, compatibility_edges = _possible_endpoint_nodes(
        segment_candidates, vector_cache
    )
    lineage = _load_lineage(p1_lineage_path)
    options = _collect_options(
        pto_candidate_path, possible_nodes, lineage, vector_cache
    )
    candidate_rows, payload_rows, group_rows = _freeze_candidates(
        options, possible_sources, case_folds
    )
    candidate_signature = canonical_sha256(
        [
            {
                "group_id": row["group_id"],
                "candidate_id": row["candidate_id"],
                "candidate_target": row["candidate_target"],
            }
            for row in candidate_rows
        ]
    )
    required, segment_requirements = _truth_endpoint_requirements(
        segment_candidates, segment_labels, vector_cache
    )
    label_rows, missing, conflicts = _join_labels(
        options,
        required,
        lineage,
        case_folds,
        vector_cache,
        frozenset(expected_missing_nodes),
    )
    conflict_nodes = {
        (str(row["case_key"]), str(row["node_id"])) for row in conflicts
    }
    conflict_units = {
        (case_key, _junction_unit_id(case_key, node_id, lineage, vector_cache))
        for case_key, node_id in conflict_nodes
    }
    junction_fallback_segment_keys = sorted(
        {
            (case_key, str(row["segment_id"]))
            for case_key, rows in segment_requirements.items()
            for row in rows
            if (
                case_key,
                _junction_unit_id(
                    case_key, str(row["node_id"]), lineage, vector_cache
                ),
            )
            in conflict_units
        }
    )
    return {
        "features": candidate_rows,
        "payloads": payload_rows,
        "groups": group_rows,
        "labels": label_rows,
        "compatibility_edges": compatibility_edges,
        "candidate_signature": candidate_signature,
        "possible_endpoint_count": sum(len(values) for values in possible_nodes.values()),
        "required_endpoint_count": sum(len(values) for values in required.values()),
        "candidate_count": len(candidate_rows),
        "group_count": len(group_rows),
        "missing": missing,
        "shared_payload_conflicts": conflicts,
        "junction_fallback_segment_keys": junction_fallback_segment_keys,
        "segment_requirement_count": len(segment_requirements),
        "passed": not missing and not conflicts and len(label_rows) == len(group_rows),
    }


def _possible_endpoint_nodes(
    segment_candidates: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]],
) -> tuple[
    dict[str, set[str]],
    dict[tuple[str, str], set[str]],
    list[dict[str, Any]],
]:
    result: dict[str, set[str]] = defaultdict(set)
    sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    for rows in segment_candidates.values():
        for candidate in rows:
            for endpoint, carrier_kind in _candidate_endpoints(candidate, vector_cache):
                case_key = str(candidate["case_key"])
                result[case_key].add(endpoint)
                sources[(case_key, endpoint)].add(carrier_kind)
                edge_key = (
                    str(candidate["group_id"]),
                    str(candidate["candidate_id"]),
                    endpoint,
                )
                edges[edge_key] = {
                    "schema_version": "p05-scheme-a-p2-p1-compatibility-edge-v1",
                    "case_key": case_key,
                    "segment_group_id": str(candidate["group_id"]),
                    "segment_object_id": str(candidate["object_id"]),
                    "segment_candidate_id": str(candidate["candidate_id"]),
                    "segment_candidate_target": str(candidate["candidate_target"]),
                    "node_group_id": f"P2P1:NODE:{case_key}:{endpoint}",
                    "node_id": endpoint,
                    "required_node_target": carrier_kind,
                    "feature_uses_truth": False,
                }
    return (
        dict(result),
        dict(sources),
        [edges[key] for key in sorted(edges)],
    )


def _candidate_endpoints(
    candidate: Mapping[str, Any],
    vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]],
) -> list[tuple[str, str]]:
    target = str(candidate.get("candidate_target") or "")
    if target == "REVIEW_FALLBACK" or not candidate.get("target_payload"):
        return []
    preferred_prefix = "t01_" if target == "KEEP_SWSD" else "proposal_" if target == "USE_RCSD" else ""
    result: list[tuple[str, str]] = []
    for road_id in candidate.get("target_payload") or []:
        provenance = [
            item
            for item in candidate.get("payload_artifact_by_id") or []
            if str(item[0]) == str(road_id)
            and (not preferred_prefix or str(item[1]).startswith(preferred_prefix))
        ]
        if not provenance:
            provenance = [
                (road_id, item[0], item[1], item[2])
                for item in candidate.get("payload_artifacts") or []
                if not preferred_prefix or str(item[0]).startswith(preferred_prefix)
            ]
        matches: list[tuple[dict[str, Any], str]] = []
        for _, role, path, *_ in provenance:
            payloads, _ = _read_vector(str(path), vector_cache)
            if str(road_id) in payloads:
                matches.append((payloads[str(road_id)], str(role)))
        semantic = {_semantic_payload_signature(payload) for payload, _ in matches}
        if len(semantic) > 1:
            raise ValueError(
                f"Segment candidate Road payload is ambiguous: {candidate['candidate_id']}/{road_id}"
            )
        if not matches:
            raise ValueError(
                f"Segment candidate Road payload is missing: {candidate['candidate_id']}/{road_id}"
            )
        payload, role = matches[0]
        properties = payload.get("properties") or {}
        start = _text(_property(properties, "snodeid"))
        end = _text(_property(properties, "enodeid"))
        if not start or not end:
            raise ValueError(f"Segment candidate Road endpoint is missing: {road_id}")
        kind = T01_NODE if role.startswith("t01_") else PROPOSAL_NODE
        result.extend(((start, kind), (end, kind)))
    return result


def _collect_options(
    path: Path,
    possible_nodes: Mapping[str, set[str]],
    lineage: Mapping[str, Mapping[str, str]],
    vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]],
) -> dict[tuple[str, str], list[_Option]]:
    by_key: dict[tuple[str, str, str, str], _Option] = {}
    group_scope = {
        (case_key, node_id) for case_key, values in possible_nodes.items() for node_id in values
    }
    for row in _read_jsonl(path):
        if row.get("stage") != "FINAL_NODE":
            continue
        case_key = f"{row['family']}:{row['business_id']}"
        for payload in row.get("output_payloads") or []:
            node_id = _identifier(payload.get("id"))
            if (case_key, node_id) not in group_scope:
                continue
            signature = _node_payload_signature(payload)
            kinds = _source_carrier_kinds(row, payload)
            for carrier_kind in kinds:
                key = (case_key, node_id, carrier_kind, signature)
                option = by_key.setdefault(
                    key,
                    _Option(
                        case_key=case_key,
                        node_id=node_id,
                        carrier_kind=carrier_kind,
                        payload_signature=signature,
                        output_payloads=[dict(payload)],
                    ),
                )
                option.lineage_kinds.add(str(row.get("lineage_kind") or "UNKNOWN"))
                for source in row.get("sources") or []:
                    source_key = canonical_sha256(source)
                    option.sources[source_key] = dict(source)
    for case_key, node_ids in sorted(possible_nodes.items()):
        for role, carrier_kind in (
            ("t01_nodes", T01_NODE),
            ("proposal_nodes", PROPOSAL_NODE),
        ):
            path_value = lineage.get(case_key, {}).get(role)
            if not path_value:
                continue
            payloads, _ = _read_vector(path_value, vector_cache)
            for node_id in sorted(node_ids):
                payload = payloads.get(node_id)
                if payload is None:
                    continue
                signature = _node_payload_signature(payload)
                key = (case_key, node_id, carrier_kind, signature)
                option = by_key.setdefault(
                    key,
                    _Option(
                        case_key=case_key,
                        node_id=node_id,
                        carrier_kind=carrier_kind,
                        payload_signature=signature,
                        output_payloads=[dict(payload)],
                    ),
                )
                option.lineage_kinds.add("P1_TRUTH_FREE_LINEAGE")
                source = {
                    "artifact_path": path_value,
                    "role": role,
                    "source_kind": "P1_TRUTH_FREE_LINEAGE",
                }
                option.sources[canonical_sha256(source)] = source
    groups: dict[tuple[str, str], list[_Option]] = defaultdict(list)
    for option in by_key.values():
        groups[(option.case_key, option.node_id)].append(option)
    for case_key, node_id in sorted(group_scope):
        groups[(case_key, node_id)].append(
            _Option(
                case_key=case_key,
                node_id=node_id,
                carrier_kind=OMIT,
                payload_signature="OMIT",
                output_payloads=[],
            )
        )
    return {
        key: sorted(values, key=lambda item: item.candidate_id)
        for key, values in groups.items()
    }


def _source_carrier_kinds(
    row: Mapping[str, Any], payload: Mapping[str, Any]
) -> set[str]:
    roles = {str(source.get("role") or "") for source in row.get("sources") or []}
    source_kinds = {
        str(source.get("source_kind") or "") for source in row.get("sources") or []
    }
    payload_role = str(payload.get("source_role") or "")
    result: set[str] = set()
    if (
        "prepared_swsd_nodes" in roles
        or "BASE_IDENTITY" in source_kinds
        or "prepared_swsd" in payload_role
    ):
        result.add(T01_NODE)
    if (
        "t06_frcsd_node" in roles
        or "STRATEGY_REPLAY" in source_kinds
        or "t06_frcsd" in payload_role
    ):
        result.add(PROPOSAL_NODE)
    if not result:
        result.add(PROPOSAL_NODE)
    return result


def _freeze_candidates(
    options: Mapping[tuple[str, str], Sequence[_Option]],
    possible_sources: Mapping[tuple[str, str], set[str]],
    case_folds: Mapping[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    features: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    for (case_key, node_id), rows in sorted(options.items()):
        kinds = {row.carrier_kind for row in rows}
        mainnodes = {
            _identifier((payload.get("properties") or {}).get("mainnodeid"))
            for row in rows
            for payload in row.output_payloads
            if (payload.get("properties") or {}).get("mainnodeid") not in (None, "", 0, 0.0)
        }
        junction_key = (
            f"{case_key}:MAINNODE:{','.join(sorted(mainnodes))}"
            if mainnodes
            else f"{case_key}:NODE:{node_id}"
        )
        group_id = rows[0].group_id
        groups.append(
            {
                "case_key": case_key,
                "object_type": "NODE",
                "object_id": node_id,
                "group_id": group_id,
                "junction_key": junction_key,
                "candidate_count": len(rows),
                "fold": case_folds[case_key],
            }
        )
        for option in rows:
            source_values = list(option.sources.values())
            payload = option.output_payloads[0] if option.output_payloads else {}
            properties = payload.get("properties") or {}
            geometry_type = str((payload.get("geometry") or {}).get("type") or "NONE")
            node_lid_count = len(
                [value for value in str(properties.get("node_lid") or "").split(",") if value]
            )
            candidate_tokens = {
                f"CARRIER:{option.carrier_kind}",
                f"GEOMETRY:{geometry_type}",
                f"SOURCE_COUNT:{_count_bin(len(source_values))}",
                *(f"SOURCE_KIND:{source.get('source_kind') or 'UNKNOWN'}" for source in source_values),
                *(f"SOURCE_ROLE:{source.get('role') or 'UNKNOWN'}" for source in source_values),
                *(f"LINEAGE:{value}" for value in option.lineage_kinds),
            }
            object_tokens = {
                "OBJECT:NODE",
                f"OPTION_COUNT:{_count_bin(len(rows))}",
                f"HAS_T01_OPTION:{T01_NODE in kinds}",
                f"HAS_PROPOSAL_OPTION:{PROPOSAL_NODE in kinds}",
                f"POSSIBLE_SOURCE_COUNT:{_count_bin(len(possible_sources.get((case_key, node_id), set())))}",
            }
            context_tokens = {
                f"CONTEXT_OPTION:{value}" for value in kinds
            } | {
                f"CONTEXT_POSSIBLE_SOURCE:{value}"
                for value in possible_sources.get((case_key, node_id), set())
            }
            numeric = [
                float(bool(option.output_payloads)),
                math.log1p(len(source_values)),
                math.log1p(len(properties)),
                math.log1p(node_lid_count),
                math.log1p(len(rows)),
                float(T01_NODE in kinds),
                float(PROPOSAL_NODE in kinds),
                float(option.carrier_kind == OMIT),
            ]
            features.append(
                {
                    "schema_version": SCHEME_A_P2_P1_DATASET_SCHEMA,
                    "case_key": case_key,
                    "object_type": "NODE",
                    "object_id": node_id,
                    "group_id": group_id,
                    "candidate_id": option.candidate_id,
                    "candidate_target": option.carrier_kind,
                    "object_tokens": sorted(object_tokens),
                    "candidate_tokens": sorted(candidate_tokens),
                    "context_tokens": sorted(context_tokens),
                    "numeric_features": numeric,
                    "hard_unsafe": False,
                    "fold": case_folds[case_key],
                    "feature_uses_truth": False,
                    "absolute_coordinate_feature_count": 0,
                }
            )
            payloads.append(
                {
                    "case_key": case_key,
                    "object_type": "NODE",
                    "object_id": node_id,
                    "group_id": group_id,
                    "junction_key": junction_key,
                    "candidate_id": option.candidate_id,
                    "candidate_target": option.carrier_kind,
                    "canonical_payload_sha256": option.payload_signature,
                    "output_object_ids": [node_id] if option.output_payloads else [],
                    "output_payloads": option.output_payloads,
                    "sources": source_values,
                    "carrier_kind": option.carrier_kind,
                }
            )
    return features, payloads, groups


def _truth_endpoint_requirements(
    segment_candidates: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    segment_labels: Mapping[tuple[str, str], Mapping[str, Any]],
    vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]],
) -> tuple[dict[str, dict[str, set[str]]], dict[str, list[dict[str, Any]]]]:
    required: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    segment_requirements: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key, label in sorted(segment_labels.items()):
        rows = list(segment_candidates[key])
        matches = [row for row in rows if candidate_matches_label(row, label)]
        if len(matches) != 1:
            raise ValueError(f"Segment truth candidate is not unique while joining Node label: {key}")
        candidate = matches[0]
        if not bool(label["available"]) or candidate.get("candidate_target") == "REVIEW_FALLBACK":
            safe = [row for row in rows if row.get("candidate_target") == "KEEP_SWSD" and row.get("target_payload")]
            if len(safe) != 1:
                raise ValueError(f"Segment has no unique SWSD fallback for Node label: {key}")
            candidate = safe[0]
        endpoints = _candidate_endpoints(candidate, vector_cache)
        for node_id, carrier_kind in endpoints:
            required[str(label["case_key"])][node_id].add(carrier_kind)
            segment_requirements[str(label["case_key"])].append(
                {
                    "segment_id": str(label["object_id"]),
                    "node_id": node_id,
                    "carrier_kind": carrier_kind,
                }
            )
    return {key: dict(value) for key, value in required.items()}, dict(segment_requirements)


def _load_lineage(path: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = defaultdict(dict)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            role = str(row["role"])
            if role in {"t01_nodes", "proposal_nodes"}:
                result[str(row["case_key"])][role] = str(row["path"])
    return dict(result)


def _join_labels(
    options: Mapping[tuple[str, str], Sequence[_Option]],
    required: Mapping[str, Mapping[str, set[str]]],
    lineage: Mapping[str, Mapping[str, str]],
    case_folds: Mapping[str, int],
    vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]],
    expected_missing_nodes: frozenset[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    labels: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    node_layers: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for case_key, roles in lineage.items():
        for role, path in roles.items():
            node_layers[(case_key, role)] = _read_vector(path, vector_cache)[0]
    for (case_key, node_id), rows in sorted(options.items()):
        required_kinds = set(required.get(case_key, {}).get(node_id, set()))
        expected_missing = False
        if not required_kinds:
            matches = [row for row in rows if row.carrier_kind == OMIT]
            target = OMIT
        else:
            signatures: dict[str, str] = {}
            for carrier_kind in required_kinds:
                role = "t01_nodes" if carrier_kind == T01_NODE else "proposal_nodes"
                payload = node_layers.get((case_key, role), {}).get(node_id)
                if payload is None:
                    if (case_key, node_id) in expected_missing_nodes:
                        expected_missing = True
                    else:
                        missing.append(
                            {
                                "case_key": case_key,
                                "node_id": node_id,
                                "carrier_kind": carrier_kind,
                                "reason": "source_node_payload_missing",
                            }
                        )
                    continue
                signatures[carrier_kind] = _node_payload_signature(payload)
            if expected_missing:
                matches = [row for row in rows if row.carrier_kind == OMIT]
                target = OMIT
            elif len(set(signatures.values())) > 1:
                conflicts.append(
                    {
                        "case_key": case_key,
                        "node_id": node_id,
                        "required_kinds": sorted(required_kinds),
                        "reason": "shared_node_payload_conflict_requires_junction_fallback",
                    }
                )
                matches = []
                target = "JUNCTION_FALLBACK"
            elif signatures:
                target_signature = next(iter(signatures.values()))
                target = T01_NODE if T01_NODE in required_kinds else PROPOSAL_NODE
                matches = [
                    row
                    for row in rows
                    if row.carrier_kind == target and row.payload_signature == target_signature
                ]
                if not matches and target == T01_NODE and PROPOSAL_NODE in required_kinds:
                    matches = [
                        row
                        for row in rows
                        if row.carrier_kind == PROPOSAL_NODE
                        and row.payload_signature == target_signature
                    ]
                    target = PROPOSAL_NODE
            else:
                matches = []
                target = "MISSING"
        if len(matches) != 1:
            if target == "JUNCTION_FALLBACK":
                continue
            missing.append(
                {
                    "case_key": case_key,
                    "node_id": node_id,
                    "carrier_kind": target,
                    "match_count": len(matches),
                    "reason": "conditioned_node_candidate_not_unique",
                }
            )
            continue
        truth = matches[0]
        labels.append(
            {
                "schema_version": SCHEME_A_P2_P1_DATASET_SCHEMA,
                "case_key": case_key,
                "object_type": "NODE",
                "object_id": node_id,
                "group_id": truth.group_id,
                "junction_key": next(
                    str(row["junction_key"])
                    for row in _freeze_candidates({(case_key, node_id): rows}, {}, case_folds)[2]
                ),
                "truth_candidate_id": truth.candidate_id,
                "carrier_target": target,
                "available": not expected_missing,
                "anomaly_target": expected_missing,
                "label_weight": 0.3 if expected_missing or not required_kinds else 1.0,
                "weight_role": "CONTEXT" if expected_missing or not required_kinds else "TARGET",
                "mask_reason": "expected_roadgraph_endpoint_missing" if expected_missing else "",
                "fold": case_folds[case_key],
                "label_only": True,
            }
        )
    return labels, missing, conflicts


def _identifier(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _junction_unit_id(
    case_key: str,
    node_id: str,
    lineage: Mapping[str, Mapping[str, str]],
    vector_cache: dict[str, tuple[dict[str, dict[str, Any]], str]],
) -> str:
    for role in ("t01_nodes", "proposal_nodes"):
        path = lineage.get(case_key, {}).get(role)
        if not path:
            continue
        payload = _read_vector(path, vector_cache)[0].get(node_id)
        if payload is None:
            continue
        mainnode = _property(payload.get("properties") or {}, "mainnodeid")
        if mainnode not in (None, "", 0, 0.0):
            return _identifier(mainnode)
    return node_id


def _node_payload_signature(payload: Mapping[str, Any]) -> str:
    properties = payload.get("properties") or {}
    normalized_properties = {
        field: _normalize_scalar(_property(properties, field))
        for field in NODE_CARRIER_FIELDS
    }
    geometry = payload.get("geometry") or {}
    return canonical_sha256(
        {
            "properties": normalized_properties,
            "geometry": {
                "type": str(geometry.get("type") or ""),
                "coordinates": _normalize_coordinates(geometry.get("coordinates")),
            },
        }
    )


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _normalize_coordinates(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_normalize_coordinates(item) for item in value]
    return float(value) if isinstance(value, (int, float)) else value


def _count_bin(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 4:
        return "2_4"
    if value <= 8:
        return "5_8"
    if value <= 16:
        return "9_16"
    return "17_PLUS"


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = [
    "OMIT",
    "PROPOSAL_NODE",
    "T01_NODE",
    "build_endpoint_node_carriers",
]
