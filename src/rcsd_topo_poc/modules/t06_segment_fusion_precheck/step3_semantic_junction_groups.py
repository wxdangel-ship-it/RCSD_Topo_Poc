from __future__ import annotations

import ast
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

from shapely.geometry import MultiPoint

from .io import read_features, write_feature_triplet, write_json
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .schemas import STEP2_SUMMARY, STEP3_SUMMARY, feature
from .step3_topology_connectivity_audit import (
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
    summarize_topology_connectivity_audit,
)


STEP3_SEMANTIC_JUNCTION_GROUPS_STEM = "t06_step3_semantic_junction_groups"
STEP3_SEMANTIC_JUNCTION_GROUP_FIELDS = [
    "semantic_junction_group_id",
    "t05_base_id",
    "swsd_node_ids",
    "rcsd_node_ids",
    "frcsd_node_ids",
    "evidence_source",
    "max_pairwise_distance_m",
    "risk_reason",
    "affected_segment_ids",
    "relation_statuses",
    "source_mixes",
]
SEMANTIC_JUNCTION_GROUP_FIELD = "semantic_junction_group_id"
SEMANTIC_JUNCTION_RISK = "t05_semantic_junction_group_geometry_diverged"
SEMANTIC_JUNCTION_EVIDENCE = "t05_intersection_match_status_0"
SEMANTIC_JUNCTION_TOPOLOGY_ACTION = "semantic_junction_group_verified"
SEMANTIC_JUNCTION_TOPOLOGY_REASON = "junction_incident_semantic_group_diverged"
SEMANTIC_JUNCTION_TOPOLOGY_OWNER = "T06_step3_semantic_junction_groups"
_DOWNGRADABLE_TOPOLOGY_REASONS = {
    "junction_incident_segment_mapped_points_diverged",
    "junction_incident_semantic_mainnode_not_closed",
}


def build_semantic_junction_groups(
    *,
    step2_replaceable_path: str | Path,
    frcsd_nodes: list[dict[str, Any]],
    segment_relation_rows: list[dict[str, Any]],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    relation_path = discover_intersection_match_path(step2_replaceable_path)
    if relation_path is None:
        return [], {"semantic_junction_group_count": 0, "semantic_junction_group_reason": "missing_t05_relation_path"}
    relations_by_base = _t05_relations_by_base(relation_path)
    if not relations_by_base:
        return [], {"semantic_junction_group_count": 0, "semantic_junction_group_reason": "no_valid_t05_relation"}

    node_index = _NodeIndex(frcsd_nodes, source_field_name, swsd_source_value, rcsd_source_value)
    affected = _affected_segments_by_swsd_node(segment_relation_rows)
    rows: list[dict[str, Any]] = []
    assigned_node_count = 0
    for base_id, swsd_node_ids in sorted(relations_by_base.items(), key=lambda item: _id_sort_key(item[0])):
        swsd_nodes = node_index.swsd_nodes(swsd_node_ids)
        rcsd_nodes = node_index.rcsd_nodes_for_base(base_id)
        if not swsd_nodes or not rcsd_nodes:
            continue
        group_id = f"SJG:{base_id}"
        all_nodes = unique_preserve_order([*swsd_nodes, *rcsd_nodes])
        for node_id in all_nodes:
            assigned_node_count += node_index.assign_group(node_id, group_id)
        affected_segment_ids = unique_preserve_order(
            segment_id for swsd_node_id in swsd_node_ids for segment_id in affected.get(swsd_node_id, [])
        )
        relation_statuses, source_mixes = _relation_context(segment_relation_rows, affected_segment_ids)
        rows.append(
            feature(
                {
                    "semantic_junction_group_id": group_id,
                    "t05_base_id": base_id,
                    "swsd_node_ids": swsd_nodes,
                    "rcsd_node_ids": rcsd_nodes,
                    "frcsd_node_ids": all_nodes,
                    "evidence_source": SEMANTIC_JUNCTION_EVIDENCE,
                    "max_pairwise_distance_m": _max_pairwise_distance(node_index.points(all_nodes)),
                    "risk_reason": SEMANTIC_JUNCTION_RISK,
                    "affected_segment_ids": affected_segment_ids,
                    "relation_statuses": relation_statuses,
                    "source_mixes": source_mixes,
                },
                _multipoint(node_index.points(all_nodes)),
            )
        )
    return rows, {
        "semantic_junction_group_count": len(rows),
        "semantic_junction_group_node_count": assigned_node_count,
        "semantic_junction_group_t05_relation_path": str(relation_path),
    }


def downgrade_semantic_junction_topology_rows(
    rows: list[dict[str, Any]],
    semantic_group_rows: list[dict[str, Any]],
) -> dict[str, int]:
    group_by_swsd_node: dict[str, str] = {}
    nodes_by_group: dict[str, set[str]] = {}
    for row in semantic_group_rows:
        props = row.get("properties") or {}
        group_id = str(props.get("semantic_junction_group_id") or "")
        if group_id:
            nodes_by_group[group_id] = set(_ids(props.get("frcsd_node_ids")))
        for node_id in _ids(props.get("swsd_node_ids")):
            if group_id:
                group_by_swsd_node[node_id] = group_id

    downgraded = 0
    for row in rows:
        props = row.get("properties") or {}
        if props.get("audit_layer") != "segment_junction_connectivity":
            continue
        if props.get("audit_status") != "fail":
            continue
        if str(props.get("audit_reason") or "") not in _DOWNGRADABLE_TOPOLOGY_REASONS:
            continue
        swsd_node_id = str(props.get("swsd_node_id") or "")
        group_id = group_by_swsd_node.get(swsd_node_id)
        if not group_id:
            continue
        row_node_ids = set(_ids(props.get("frcsd_node_ids")))
        if row_node_ids and not row_node_ids.issubset(nodes_by_group.get(group_id, set())):
            continue
        props["audit_status"] = "warn"
        props["audit_reason"] = SEMANTIC_JUNCTION_TOPOLOGY_REASON
        props["recommended_owner"] = SEMANTIC_JUNCTION_TOPOLOGY_OWNER
        props["action"] = SEMANTIC_JUNCTION_TOPOLOGY_ACTION
        props["action_reason"] = f"{SEMANTIC_JUNCTION_GROUP_FIELD}={group_id}"
        downgraded += 1
    return {"semantic_junction_topology_fail_downgraded_count": downgraded}


def discover_intersection_match_path(step2_replaceable_path: str | Path) -> Path | None:
    step2_root = Path(step2_replaceable_path).resolve().parent
    summary_path = step2_root / STEP2_SUMMARY
    if not summary_path.is_file():
        return None
    value = (json.loads(summary_path.read_text(encoding="utf-8")).get("input_paths") or {}).get("intersection_match_path")
    if not value:
        return None
    path = Path(value)
    candidates = [path] if path.is_absolute() else [Path.cwd() / path, summary_path.parent / path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def valid_t05_relation_targets(path: str | Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for base_id, target_ids in _t05_relations_by_base(Path(path)).items():
        for target_id in target_ids:
            result[target_id] = base_id
    return result


def refresh_semantic_junction_topology_audit(
    *,
    step_root: str | Path,
    summary_path: str | Path | None = None,
) -> dict[str, int]:
    root = Path(step_root)
    group_path = root / f"{STEP3_SEMANTIC_JUNCTION_GROUPS_STEM}.gpkg"
    topology_path = root / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.gpkg"
    if not group_path.is_file() or not topology_path.is_file():
        return {"semantic_junction_topology_fail_downgraded_count": 0}
    semantic_group_rows = read_features(group_path)
    topology_rows = read_features(topology_path)
    downgrade_stats = downgrade_semantic_junction_topology_rows(topology_rows, semantic_group_rows)
    summary_stats = {
        **summarize_topology_connectivity_audit(topology_rows),
        **downgrade_stats,
    }
    if downgrade_stats.get("semantic_junction_topology_fail_downgraded_count", 0) <= 0:
        _merge_summary_stats(summary_path or root / STEP3_SUMMARY, summary_stats)
        return downgrade_stats
    write_feature_triplet(
        step_root=root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        features=topology_rows,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    )
    _merge_summary_stats(summary_path or root / STEP3_SUMMARY, summary_stats)
    return downgrade_stats


def _t05_relations_by_base(path: Path) -> dict[str, list[str]]:
    by_base: dict[str, list[str]] = defaultdict(list)
    for props in _relation_properties(path):
        status = props.get("status")
        if str(status if status is not None else "") not in {"0", "0.0"}:
            continue
        target_id = _safe_id(props.get("target_id"))
        base_id = _safe_id(props.get("base_id"))
        if not target_id or not base_id or base_id == "0":
            continue
        by_base[base_id] = unique_preserve_order([*by_base[base_id], target_id])
    return dict(by_base)


def _relation_properties(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".geojson", ".json"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features") if isinstance(payload, dict) else None
        if isinstance(features, list):
            return [dict((feature.get("properties") or {})) for feature in features if isinstance(feature, dict)]
    return [dict(row.get("properties") or {}) for row in read_features(path, crs_override="EPSG:4326")]


def _affected_segments_by_swsd_node(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        props = row.get("properties") or {}
        segment_id = str(props.get("swsd_segment_id") or "")
        if not segment_id:
            continue
        nodes = unique_preserve_order(
            [
                *_ids(props.get("swsd_pair_nodes")),
                *_ids(props.get("swsd_junc_nodes")),
                *_node_map_swsd_nodes(props.get("swsd_to_frcsd_node_map")),
            ]
        )
        for node_id in nodes:
            result[node_id] = unique_preserve_order([*result[node_id], segment_id])
    return dict(result)


def _relation_context(rows: list[dict[str, Any]], segment_ids: list[str]) -> tuple[list[str], list[str]]:
    wanted = set(segment_ids)
    statuses: list[str] = []
    sources: list[str] = []
    for row in rows:
        props = row.get("properties") or {}
        if str(props.get("swsd_segment_id") or "") not in wanted:
            continue
        statuses.append(str(props.get("relation_status") or ""))
        sources.append(str(props.get("source_mix") or ""))
    return unique_preserve_order(statuses), unique_preserve_order(sources)


def _node_map_swsd_nodes(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return result
    if not isinstance(value, list):
        return result
    for item in value:
        if isinstance(item, dict):
            node_id = _safe_id(item.get("swsd_node_id"))
            if node_id:
                result.append(node_id)
    return unique_preserve_order(result)


class _NodeIndex:
    def __init__(self, nodes: list[dict[str, Any]], source_field_name: str, swsd_source_value: int, rcsd_source_value: int) -> None:
        self._nodes_by_id: dict[str, dict[str, Any]] = {}
        self._swsd_by_id: dict[str, list[str]] = defaultdict(list)
        self._rcsd_by_semantic_id: dict[str, list[str]] = defaultdict(list)
        self._points_by_id: dict[str, Any] = {}
        for node in nodes:
            props = node.get("properties") or {}
            node_id = _safe_id(props.get("id"))
            if not node_id:
                continue
            self._nodes_by_id[node_id] = node
            if node.get("geometry") is not None:
                self._points_by_id[node_id] = node.get("geometry")
            source = str(props.get(source_field_name) or "")
            if source == str(swsd_source_value):
                self._swsd_by_id[node_id].append(node_id)
            elif source == str(rcsd_source_value):
                for semantic_id in unique_preserve_order([node_id, _safe_id(props.get("mainnodeid"))]):
                    if semantic_id and semantic_id != "0":
                        self._rcsd_by_semantic_id[semantic_id].append(node_id)

    def swsd_nodes(self, swsd_node_ids: list[str]) -> list[str]:
        return unique_preserve_order(node_id for swsd_id in swsd_node_ids for node_id in self._swsd_by_id.get(swsd_id, []))

    def rcsd_nodes_for_base(self, base_id: str) -> list[str]:
        return unique_preserve_order(self._rcsd_by_semantic_id.get(base_id, []))

    def assign_group(self, node_id: str, group_id: str) -> int:
        node = self._nodes_by_id.get(node_id)
        if node is None:
            return 0
        props = node.setdefault("properties", {})
        existing = _ids(props.get(SEMANTIC_JUNCTION_GROUP_FIELD))
        if group_id in existing:
            return 0
        group_ids = unique_preserve_order([*existing, group_id])
        props[SEMANTIC_JUNCTION_GROUP_FIELD] = group_ids[0] if len(group_ids) == 1 else "|".join(group_ids)
        return 1

    def points(self, node_ids: list[str]) -> list[Any]:
        return [self._points_by_id[node_id] for node_id in node_ids if node_id in self._points_by_id]


def _multipoint(points: list[Any]) -> Any:
    if not points:
        return None
    if len(points) == 1:
        return points[0]
    return MultiPoint(points)


def _max_pairwise_distance(points: list[Any]) -> float | None:
    if len(points) < 2:
        return None
    return round(max(float(a.distance(b)) for a, b in combinations(points, 2)), 3)


def _ids(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = ast.literal_eval(text)
                except Exception:
                    parsed = None
                if isinstance(parsed, list):
                    return [_safe_id(item) for item in parsed if _safe_id(item)]
            if "|" in value:
                return [item for item in value.split("|") if item]
        return []


def _safe_id(value: Any) -> str:
    if value in (None, "", "None"):
        return ""
    try:
        if value != value:
            return ""
    except Exception:
        pass
    try:
        return normalize_id(value)
    except ParseError:
        return str(value)


def _id_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except Exception:
        return (1, str(value))


def _merge_summary_stats(summary_path: str | Path, stats: dict[str, int]) -> None:
    path = Path(summary_path)
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(stats)
    write_json(path, payload)
