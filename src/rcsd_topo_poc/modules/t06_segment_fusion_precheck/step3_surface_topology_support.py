from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from shapely.ops import linemerge, substring

from .io import read_features, write_feature_triplet, write_json
from .parsing import normalize_id, unique_preserve_order
from .schemas import (
    STEP2_FAILURE_BUSINESS_AUDIT_STEM,
    STEP2_REPLACEMENT_PLAN_STEM,
    STEP3_FRCSD_NODE_STEM,
    STEP3_FRCSD_ROAD_STEM,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
)
from .step3_relation_node_map import sync_retained_swsd_carrier_mainnodes
from .step3_topology_connectivity_audit import (
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
    build_topology_connectivity_audit_rows,
    summarize_topology_connectivity_audit,
)


SURFACE_TOPOLOGY_AUDIT_STEM = "t06_step3_surface_topology_audit"
SURFACE_TOPOLOGY_SUMMARY = "t06_step3_surface_topology_summary.json"
MAX_EXISTING_CROSS_SOURCE_1V1_DISTANCE_M = 20.0
MAX_T04_PATCH_1V1_DISTANCE_M = 20.0
MAX_RELATION_MAPPED_BOUNDARY_1V1_DISTANCE_M = 20.0
MAX_SURFACE_NEAREST_MULTI_CANDIDATE_DISTANCE_M = 5.0
MIN_SURFACE_NEAREST_MULTI_CANDIDATE_SEPARATION_M = 10.0
SURFACE_NEAREST_MULTI_CANDIDATE_LAYERS = {"t03", "t05"}
MAX_SELECTED_REPLACEMENT_ENDPOINT_DISTANCE_M = 5.0
MAX_SELECTED_REPLACEMENT_ENDPOINT_AMBIGUITY_M = 10.0
MAX_SELECTED_REPLACEMENT_MIDROAD_DISTANCE_M = 5.0
MIN_SELECTED_REPLACEMENT_MIDROAD_ENDPOINT_DISTANCE_M = 1.0
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_CANDIDATES = 2
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_GAP_SPREAD_M = 1.0
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_PROJECTED_DISTANCE_M = 10.0
SELECTED_REPLACEMENT_MIDROAD_SPLIT_REASON = "surface_topology_selected_replacement_midroad"
SURFACE_TOPOLOGY_AUDIT_FIELDS = [
    "audit_layer",
    "audit_status",
    "audit_reason",
    "action",
    "swsd_node_id",
    "swsd_segment_ids",
    "frcsd_node_ids",
    "swsd_patch_ids",
    "surface_patch_ids",
    "surface_layers",
    "surface_candidate_node_ids",
    "t04_reject_reasons",
    "source1_node_count",
    "source2_node_count",
    "max_pairwise_distance_m",
    "closure_mainnodeid",
]


@dataclass(frozen=True)
class SurfaceTopologyInvariantContext:
    surfaces: dict[str, gpd.GeoDataFrame]
    t04_rejects: dict[str, list[dict[str, str]]]
    step2_junc_mappings: dict[tuple[str, str], list[str]]
    step2_dropped_junc_nodes: dict[str, list[str]]


def load_surface_topology_invariant_context(
    *,
    step_root: Path,
    t07_surface_path: str | Path | None,
    t03_surface_path: str | Path | None,
    t04_surface_path: str | Path | None,
    t04_audit_path: str | Path | None,
    t05_surface_path: str | Path | None,
    cache: dict[Any, Any] | None,
) -> SurfaceTopologyInvariantContext:
    step2_source_path = _step2_junc_source_path(step_root)
    signature = tuple(
        _input_signature(path)
        for path in (
            t07_surface_path,
            t03_surface_path,
            t04_surface_path,
            t04_audit_path,
            t05_surface_path,
            step2_source_path,
        )
    )
    cached = getattr(cache, "surface_topology_invariant_context", None)
    if cached is not None and cached[0] == signature:
        return cached[1]
    step2_rows = _read_step2_junc_rows(step2_source_path) if step2_source_path is not None else []
    context = SurfaceTopologyInvariantContext(
        surfaces=_load_surfaces(
            t07_surface_path=t07_surface_path,
            t03_surface_path=t03_surface_path,
            t04_surface_path=t04_surface_path,
            t05_surface_path=t05_surface_path,
        ),
        t04_rejects=_load_t04_rejects(t04_audit_path),
        step2_junc_mappings=_step2_optional_junc_mappings(step2_rows),
        step2_dropped_junc_nodes=_step2_dropped_junc_nodes(step2_rows),
    )
    if cache is not None and hasattr(cache, "__dict__"):
        cache.surface_topology_invariant_context = (signature, context)
    return context


def _input_signature(path: str | Path | None) -> tuple[str, int, int]:
    if path is None:
        return "", 0, 0
    resolved = Path(path).absolute()
    try:
        stat = resolved.stat()
    except OSError:
        return str(resolved), 0, 0
    return str(resolved), stat.st_size, stat.st_mtime_ns


def _load_surfaces(
    *,
    t07_surface_path: str | Path | None,
    t03_surface_path: str | Path | None,
    t04_surface_path: str | Path | None,
    t05_surface_path: str | Path | None,
) -> dict[str, gpd.GeoDataFrame]:
    result: dict[str, gpd.GeoDataFrame] = {}
    for name, path in {
        "t05": t05_surface_path,
        "t07": t07_surface_path,
        "t04": t04_surface_path,
        "t03": t03_surface_path,
    }.items():
        if path and Path(path).is_file():
            result[name] = gpd.read_file(path)
    return result


def _load_t04_rejects(path: str | Path | None) -> dict[str, list[dict[str, str]]]:
    if not path or not Path(path).is_file():
        return {}
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    rows = gpd.read_file(path)
    for _, row in rows.iterrows():
        target = str(row.get("publish_target") or "")
        reject_reason = str(row.get("reject_reason") or "")
        if not target.startswith("rejected") and not reject_reason:
            continue
        payload = {
            "anchor_id": _safe_id(row.get("anchor_id")),
            "case_id": _safe_id(row.get("case_id")),
            "publish_target": target,
            "reject_reason": reject_reason,
            "reject_reason_detail": str(row.get("reject_reason_detail") or ""),
            "required_rcsd_node_ids": _parse_id_list(row.get("required_rcsd_node_ids")),
            "required_rcsd_node_count": _int_or_none(row.get("required_rcsd_node_count")),
            "hard_must_cover_ok": _bool_or_none(row.get("hard_must_cover_ok")),
            "post_cleanup_forbidden_ok": _bool_or_none(row.get("post_cleanup_forbidden_ok")),
            "post_cleanup_terminal_cut_ok": _bool_or_none(row.get("post_cleanup_terminal_cut_ok")),
            "post_cleanup_lateral_limit_ok": _bool_or_none(row.get("post_cleanup_lateral_limit_ok")),
            "post_cleanup_must_cover_ok": _bool_or_none(row.get("post_cleanup_must_cover_ok")),
            "forbidden_overlap": _bool_or_none(row.get("forbidden_overlap")),
            "cut_violation": _bool_or_none(row.get("cut_violation")),
            "fallback_overexpansion_detected": _bool_or_none(row.get("fallback_overexpansion_detected")),
        }
        for node_id in unique_preserve_order([payload["anchor_id"], payload["case_id"]]):
            if node_id:
                result[node_id].append(payload)
    return dict(result)


def _load_step2_optional_junc_mappings(step_root: Path) -> dict[tuple[str, str], list[str]]:
    return _step2_optional_junc_mappings(_iter_step2_junc_rows(step_root))


def _step2_optional_junc_mappings(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        segment_id = _safe_id(row.get("swsd_segment_id"))
        if not segment_id:
            continue
        swsd_nodes = _parse_id_list(row.get("optional_junc_nodes"))
        rcsd_nodes = _parse_id_list(row.get("optional_junc_rcsd_nodes"))
        raw_rcsd_nodes = _parse_id_list(row.get("rcsd_junc_nodes"))
        if len(rcsd_nodes) != len(swsd_nodes) and len(raw_rcsd_nodes) == len(swsd_nodes):
            rcsd_nodes = raw_rcsd_nodes
        for swsd_node_id, rcsd_node_id in zip(swsd_nodes, rcsd_nodes):
            if not swsd_node_id or not rcsd_node_id:
                continue
            key = (segment_id, swsd_node_id)
            result[key] = unique_preserve_order([*result[key], rcsd_node_id])
    return dict(result)


def _load_step2_dropped_junc_nodes(step_root: Path) -> dict[str, list[str]]:
    return _step2_dropped_junc_nodes(_iter_step2_junc_rows(step_root))


def _step2_dropped_junc_nodes(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        segment_id = _safe_id(row.get("swsd_segment_id"))
        if not segment_id:
            continue
        dropped_nodes = _parse_id_list(row.get("dropped_junc_nodes"))
        if dropped_nodes:
            result[segment_id] = unique_preserve_order([*result[segment_id], *dropped_nodes])
    return dict(result)


def _iter_step2_junc_rows(step_root: Path) -> list[dict[str, Any]]:
    path = _step2_junc_source_path(step_root)
    return _read_step2_junc_rows(path) if path is not None else []


def _step2_junc_source_path(step_root: Path) -> Path | None:
    for step2_root in _step2_junc_roots(step_root):
        for stem in (STEP2_REPLACEMENT_PLAN_STEM, STEP2_FAILURE_BUSINESS_AUDIT_STEM):
            for suffix in (".gpkg", ".csv"):
                path = step2_root / f"{stem}{suffix}"
                if path.is_file():
                    return path
    return None


def _step2_junc_roots(step_root: Path) -> list[Path]:
    roots = [step_root.parent / "step2_extract_rcsd_segments"]
    summary_path = step_root / "t06_step3_summary.json"
    if summary_path.is_file():
        try:
            input_paths = json.loads(summary_path.read_text(encoding="utf-8")).get("input_paths") or {}
        except json.JSONDecodeError:
            input_paths = {}
        step2_replaceable = input_paths.get("step2_replaceable_path")
        if step2_replaceable:
            path = Path(step2_replaceable)
            if not path.is_absolute():
                path = Path.cwd() / path
            roots.append(path.parent)
    result: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        result.append(root)
    return result


def _read_step2_junc_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".gpkg":
        return [dict(row) for _, row in gpd.read_file(path).iterrows()]
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _road_features_by_id(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.is_file():
        return {}
    return _road_features_by_id_from_features(read_features(path))


def _road_features_by_id_from_features(roads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for road in roads:
        road_id = _safe_id((road.get("properties") or {}).get("id"))
        if road_id:
            result[road_id].append(road)
    return dict(result)


def _relation_props_by_segment(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in read_features(path):
        props = dict(row.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if segment_id:
            result[segment_id] = props
    return result


def _swsd_patch_ids_by_node(swsd_roads: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for road in swsd_roads:
        props = dict(road.get("properties") or {})
        patch_ids = set(_patch_ids(props.get("patch_id") or props.get("patchid")))
        for node_id in [_safe_id(props.get("snodeid")), _safe_id(props.get("enodeid"))]:
            if node_id:
                result[node_id].update(patch_ids)
    return dict(result)


def _node_info(feature_item: dict[str, Any] | None, node_id: str, source_field_name: str) -> dict[str, Any]:
    props = dict((feature_item or {}).get("properties") or {})
    return {
        "id": node_id,
        "source": _safe_id(props.get(source_field_name)),
        "mainnodeid": _safe_id(props.get("mainnodeid")),
        "point": (feature_item or {}).get("geometry"),
    }


def _surface_hits(point: Any, surfaces: dict[str, gpd.GeoDataFrame]) -> list[dict[str, Any]]:
    if not isinstance(point, Point):
        return []
    hits: list[dict[str, Any]] = []
    for layer, rows in surfaces.items():
        try:
            candidates = rows.iloc[list(rows.sindex.query(point.buffer(0.01), predicate="intersects"))]
        except Exception:
            candidates = rows
        for _, row in candidates.iterrows():
            geometry = row.geometry
            if geometry is None or geometry.is_empty:
                continue
            if not geometry.intersects(point) and geometry.distance(point) > 1.0:
                continue
            hits.append(
                {
                    "layer": layer,
                    "id": _safe_id(
                        row.get("surface_id")
                        or row.get("id")
                        or row.get("anchor_id")
                        or row.get("mainnodeid")
                        or row.get("case_id")
                    ),
                    "patch_ids": _patch_ids(row.get("patch_id") or row.get("patchid")),
                    "candidate_node_ids": _surface_candidate_node_ids(layer, row),
                    "target_id": _safe_id(row.get("target_id")),
                    "representative_node_id": _safe_id(row.get("representative_node_id")),
                    "mainnodeid": _safe_id(row.get("mainnodeid")),
                    "anchor_id": _safe_id(row.get("anchor_id")),
                    "case_id": _safe_id(row.get("case_id")),
                    "final_state": str(row.get("final_state") or ""),
                    "relation_state": str(row.get("relation_state") or ""),
                }
            )
    return hits


def _surface_candidate_node_ids(layer: str, row: Any) -> list[str]:
    if layer != "t07":
        return []
    return unique_preserve_order(
        candidate_id
        for value in (
            row.get("base_id_candidate"),
            row.get("source_rcsdintersection_id"),
            row.get("matched_rcsdintersection_ids"),
            row.get("id"),
        )
        for candidate_id in _parse_id_list(value)
    )


def _closure_mainnodeid(source1_node: dict[str, Any], source2_nodes: list[dict[str, Any]]) -> str:
    mainnodeid = _safe_id(source1_node.get("mainnodeid"))
    if mainnodeid and mainnodeid != "0":
        return mainnodeid
    return _source2_default_mainnodeid(source2_nodes)


def _has_effective_mainnode(node: dict[str, Any]) -> bool:
    mainnodeid = _safe_id(node.get("mainnodeid"))
    return bool(mainnodeid and mainnodeid != "0")


def _can_resolve_closure_mainnode(source1_node: dict[str, Any], source2_nodes: list[dict[str, Any]]) -> bool:
    return _has_effective_mainnode(source1_node) or bool(_source2_default_mainnodeid(source2_nodes))


def _source2_default_mainnodeid(source2_nodes: list[dict[str, Any]]) -> str:
    mainnodeids = unique_preserve_order(
        mainnodeid
        for node in source2_nodes
        for mainnodeid in [_safe_id(node.get("mainnodeid"))]
        if mainnodeid and mainnodeid != "0"
    )
    return mainnodeids[0] if len(mainnodeids) == 1 else ""


def _fieldnames_from_gpkg(path: Path) -> list[str]:
    gdf = gpd.read_file(path, rows=0)
    return [column for column in gdf.columns if column != "geometry"]


def _feature_id(feature_item: dict[str, Any]) -> str:
    try:
        return normalize_id((feature_item.get("properties") or {}).get("id"))
    except Exception:
        return _safe_id((feature_item.get("properties") or {}).get("id"))


def _parse_id_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [_safe_id(item) for item in value if _safe_id(item)]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [_safe_id(item) for item in parsed if _safe_id(item)]
    return [_safe_id(item) for item in text.replace("[", "").replace("]", "").replace('"', "").split(",") if _safe_id(item)]


def _patch_ids(value: Any) -> list[str]:
    return [item for item in _parse_id_list(value) if item not in {"0", "None", "nan"}]


def _safe_id(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        if value != value:
            return ""
    except Exception:
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, "") or value != value:
            return None
        return float(value)
    except Exception:
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value in (None, "") or value != value:
            return None
        return int(float(value))
    except Exception:
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _distance_within(value: Any, threshold: float) -> bool:
    distance = _float_or_none(value)
    return distance is not None and distance <= threshold


def _points_geometry(points: list[Point]) -> Point | MultiPoint | None:
    if not points:
        return None
    if len(points) == 1:
        return points[0]
    return MultiPoint(points)
