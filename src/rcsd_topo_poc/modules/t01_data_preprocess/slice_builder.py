from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple, Union

import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import (
    TARGET_CRS,
    _resolve_shapefile_crs,
    _transform_geometry,
    read_vector_layer,
    write_geojson,
    write_json,
)


REQUIRED_ROAD_FIELDS = ("id", "snodeid", "enodeid", "direction")
REQUIRED_NODE_FIELDS = ("id",)
DEFAULT_SLICE_RUN_ID_PREFIX = "t01_validation_slices_"
DEFAULT_PROFILE_CONFIG_RELATIVE_PATH = Path("configs") / "t01_data_preprocess" / "slice_profiles.json"


@dataclass(frozen=True)
class SliceNode:
    node_id: str
    x: float
    y: float
    properties: Dict[str, Any]


@dataclass(frozen=True)
class SliceRoad:
    road_id: str
    snodeid: Optional[str]
    enodeid: Optional[str]
    geometry: BaseGeometry
    properties: Dict[str, Any]


@dataclass(frozen=True)
class SliceRoadHeader:
    record_index: int
    road_id: str
    snodeid: Optional[str]
    enodeid: Optional[str]
    properties: Dict[str, Any]


@dataclass(frozen=True)
class SliceProfile:
    profile_id: str
    target_core_node_count: int
    description: str


@dataclass(frozen=True)
class SliceResult:
    profile: SliceProfile
    output_dir: Path
    summary: Dict[str, Any]


def _find_repo_root(start: Path) -> Optional[Path]:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "docs").is_dir():
            return candidate
    return None


def _build_default_run_id(now: Optional[datetime] = None) -> str:
    current = datetime.now() if now is None else now
    return f"{DEFAULT_SLICE_RUN_ID_PREFIX}{current.strftime('%Y%m%d_%H%M%S')}"


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
) -> Tuple[Path, str]:
    resolved_run_id = run_id or _build_default_run_id()
    if out_root is not None:
        return Path(out_root), resolved_run_id

    start = Path.cwd() if cwd is None else cwd
    repo_root = _find_repo_root(start)
    if repo_root is None:
        raise ValueError("Cannot infer default out_root because repo root was not found; please pass --out-root.")
    return repo_root / "outputs" / "_work" / "t01_validation_slices" / resolved_run_id, resolved_run_id


def _resolve_profile_config(path: Optional[Union[str, Path]], *, cwd: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path)

    start = Path.cwd() if cwd is None else cwd
    repo_root = _find_repo_root(start)
    if repo_root is None:
        raise ValueError("Cannot infer default profile config because repo root was not found; please pass --profile-config.")
    return repo_root / DEFAULT_PROFILE_CONFIG_RELATIVE_PATH


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        return stripped
    return value


def _normalize_id(value: Any) -> Optional[str]:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    return str(normalized)


def _sort_key(value: str) -> Tuple[int, Union[int, str]]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _validate_required_fields(
    features: List[Dict[str, Any]],
    required_fields: Tuple[str, ...],
    *,
    layer_label: str,
) -> List[str]:
    issues: List[str] = []
    for index, feature in enumerate(features):
        properties = feature["properties"]
        missing = [field for field in required_fields if field not in properties]
        if missing:
            issues.append(
                f"{layer_label} feature[{index}] missing required fields: {', '.join(sorted(missing))}"
            )
    return issues


def _prepare_nodes(raw_features: List[Dict[str, Any]]) -> Dict[str, SliceNode]:
    nodes: Dict[str, SliceNode] = {}
    for index, feature in enumerate(raw_features):
        geometry = feature["geometry"]
        properties = feature["properties"]
        if geometry.geom_type != "Point":
            raise ValueError(f"node feature[{index}] expected Point but got {geometry.geom_type}")

        node_id = _normalize_id(properties.get("id"))
        if node_id is None:
            raise ValueError(f"node feature[{index}] has null/empty id after normalization")

        nodes[node_id] = SliceNode(
            node_id=node_id,
            x=float(geometry.x),
            y=float(geometry.y),
            properties=dict(properties),
        )
    return nodes


def _load_shapefile_nodes_fast(
    path: Union[str, Path],
    *,
    crs_override: Optional[str] = None,
) -> Dict[str, SliceNode]:
    node_path = Path(path)
    source_crs, _ = _resolve_shapefile_crs(node_path, crs_override)
    transformer = None if source_crs == TARGET_CRS else Transformer.from_crs(source_crs, TARGET_CRS, always_xy=True)

    reader = shapefile.Reader(str(node_path))
    field_names = [field[0] for field in reader.fields[1:]]
    missing = [field for field in REQUIRED_NODE_FIELDS if field not in field_names]
    if missing:
        raise ValueError(f"node layer missing required fields: {', '.join(sorted(missing))}")

    nodes: Dict[str, SliceNode] = {}
    for index, shape_record in enumerate(reader.iterShapeRecords()):
        shape_obj = shape_record.shape
        if shape_obj.shapeTypeName.upper() != "POINT":
            raise ValueError(f"node feature[{index}] expected Point but got {shape_obj.shapeTypeName}")

        properties = dict(zip(field_names, list(shape_record.record)))
        node_id = _normalize_id(properties.get("id"))
        if node_id is None:
            raise ValueError(f"node feature[{index}] has null/empty id after normalization")

        x, y = shape_obj.points[0]
        if transformer is not None:
            x, y = transformer.transform(x, y)

        nodes[node_id] = SliceNode(
            node_id=node_id,
            x=float(x),
            y=float(y),
            properties=properties,
        )
    return nodes


def _prepare_roads(raw_features: List[Dict[str, Any]]) -> List[SliceRoad]:
    roads: List[SliceRoad] = []
    for index, feature in enumerate(raw_features):
        geometry = feature["geometry"]
        properties = feature["properties"]
        if geometry.geom_type not in {"LineString", "MultiLineString"}:
            raise ValueError(f"road feature[{index}] expected LineString/MultiLineString but got {geometry.geom_type}")

        road_id = _normalize_id(properties.get("id"))
        if road_id is None:
            raise ValueError(f"road feature[{index}] has null/empty id after normalization")

        roads.append(
            SliceRoad(
                road_id=road_id,
                snodeid=_normalize_id(properties.get("snodeid")),
                enodeid=_normalize_id(properties.get("enodeid")),
                geometry=geometry,
                properties=dict(properties),
            )
        )
    return roads


def _load_shapefile_road_headers(
    path: Union[str, Path],
    *,
    crs_override: Optional[str] = None,
) -> Tuple[List[SliceRoadHeader], CRS]:
    road_path = Path(path)
    source_crs, _ = _resolve_shapefile_crs(road_path, crs_override)
    reader = shapefile.Reader(str(road_path))
    field_names = [field[0] for field in reader.fields[1:]]
    missing = [field for field in REQUIRED_ROAD_FIELDS if field not in field_names]
    if missing:
        raise ValueError(f"road layer missing required fields: {', '.join(sorted(missing))}")

    headers: List[SliceRoadHeader] = []
    for index, record in enumerate(reader.iterRecords()):
        properties = dict(zip(field_names, list(record)))
        road_id = _normalize_id(properties.get("id"))
        if road_id is None:
            raise ValueError(f"road feature[{index}] has null/empty id after normalization")
        headers.append(
            SliceRoadHeader(
                record_index=index,
                road_id=road_id,
                snodeid=_normalize_id(properties.get("snodeid")),
                enodeid=_normalize_id(properties.get("enodeid")),
                properties=properties,
            )
        )
    return headers, source_crs


def _materialize_selected_shapefile_roads(
    path: Union[str, Path],
    *,
    source_crs: CRS,
    selected_headers: Dict[int, SliceRoadHeader],
) -> List[SliceRoad]:
    if not selected_headers:
        return []

    reader = shapefile.Reader(str(path))
    roads: List[SliceRoad] = []
    for index, shp in enumerate(reader.iterShapes()):
        header = selected_headers.get(index)
        if header is None:
            continue

        geometry = _transform_geometry(shape(shp.__geo_interface__), source_crs)
        if geometry.geom_type not in {"LineString", "MultiLineString"}:
            raise ValueError(f"road feature[{index}] expected LineString/MultiLineString but got {geometry.geom_type}")

        roads.append(
            SliceRoad(
                road_id=header.road_id,
                snodeid=header.snodeid,
                enodeid=header.enodeid,
                geometry=geometry,
                properties=dict(header.properties),
            )
        )
    return roads


def _load_profiles(path: Union[str, Path]) -> List[SliceProfile]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    profiles: List[SliceProfile] = []
    for payload in doc.get("profiles") or []:
        profiles.append(
            SliceProfile(
                profile_id=str(payload["profile_id"]),
                target_core_node_count=int(payload["target_core_node_count"]),
                description=str(payload.get("description") or ""),
            )
        )
    if not profiles:
        raise ValueError(f"No profiles found in '{path}'.")
    return profiles


def _filter_profiles(profiles: List[SliceProfile], selected_profile_ids: Optional[List[str]]) -> List[SliceProfile]:
    if not selected_profile_ids:
        return profiles

    selected = {profile_id.strip() for profile_id in selected_profile_ids if profile_id and profile_id.strip()}
    filtered = [profile for profile in profiles if profile.profile_id in selected]
    missing = sorted(selected - {profile.profile_id for profile in filtered})
    if missing:
        raise ValueError(f"Unknown profile_id(s): {', '.join(missing)}")
    if not filtered:
        raise ValueError("No slice profiles selected.")
    return filtered


def _select_anchor_node_id(nodes: Dict[str, SliceNode]) -> str:
    centroid_x = sum(node.x for node in nodes.values()) / len(nodes)
    centroid_y = sum(node.y for node in nodes.values()) / len(nodes)
    best_node_id = min(
        nodes,
        key=lambda node_id: (
            (nodes[node_id].x - centroid_x) ** 2 + (nodes[node_id].y - centroid_y) ** 2,
            _sort_key(node_id),
        ),
    )
    return best_node_id


def _rank_nodes_by_distance(nodes: Dict[str, SliceNode], anchor_node_id: str) -> List[str]:
    anchor = nodes[anchor_node_id]
    ranked = sorted(
        nodes,
        key=lambda node_id: (
            (nodes[node_id].x - anchor.x) ** 2 + (nodes[node_id].y - anchor.y) ** 2,
            _sort_key(node_id),
        ),
    )
    return ranked


def _node_feature(node: SliceNode) -> Dict[str, Any]:
    return {"geometry": Point(node.x, node.y), "properties": dict(node.properties)}


def _road_feature(road: SliceRoad) -> Dict[str, Any]:
    return {"geometry": road.geometry, "properties": dict(road.properties)}


def _write_profile_slice(
    *,
    profile: SliceProfile,
    nodes: Dict[str, SliceNode],
    core_node_ids: set[str],
    selected_roads: List[SliceRoad],
    selected_node_ids: List[str],
    out_dir: Path,
    run_id: str,
    anchor_node_id: str,
    source_road_path: Union[str, Path],
    source_node_path: Union[str, Path],
    closure_added_node_count: int,
    orphan_ref_count: int,
) -> SliceResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    selected_road_ids = sorted([road.road_id for road in selected_roads], key=_sort_key)

    roads_path = out_dir / "roads.geojson"
    nodes_path = out_dir / "nodes.geojson"
    summary_path = out_dir / "slice_summary.json"

    write_geojson(nodes_path, [_node_feature(nodes[node_id]) for node_id in selected_node_ids])
    write_geojson(roads_path, [_road_feature(road) for road in sorted(selected_roads, key=lambda road: _sort_key(road.road_id))])

    anchor_node = nodes[anchor_node_id]
    minx = min(nodes[node_id].x for node_id in selected_node_ids)
    miny = min(nodes[node_id].y for node_id in selected_node_ids)
    maxx = max(nodes[node_id].x for node_id in selected_node_ids)
    maxy = max(nodes[node_id].y for node_id in selected_node_ids)

    summary = {
        "run_id": run_id,
        "profile_id": profile.profile_id,
        "description": profile.description,
        "source_road_path": str(Path(source_road_path)),
        "source_node_path": str(Path(source_node_path)),
        "anchor_node_id": anchor_node_id,
        "anchor_point_3857": {"x": anchor_node.x, "y": anchor_node.y},
        "target_core_node_count": profile.target_core_node_count,
        "core_node_count": len(core_node_ids),
        "output_node_count": len(selected_node_ids),
        "output_road_count": len(selected_roads),
        "closure_added_node_count": closure_added_node_count,
        "orphan_ref_count": orphan_ref_count,
        "selected_node_ids_preview": selected_node_ids[:20],
        "selected_road_ids_preview": selected_road_ids[:20],
        "bounds_3857": {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy},
        "output_files": [roads_path.name, nodes_path.name, summary_path.name],
    }
    write_json(summary_path, summary)
    return SliceResult(profile=profile, output_dir=out_dir, summary=summary)


def _build_profile_slice(
    *,
    profile: SliceProfile,
    ranked_node_ids: List[str],
    nodes: Dict[str, SliceNode],
    roads: List[SliceRoad],
    out_dir: Path,
    run_id: str,
    anchor_node_id: str,
    source_road_path: Union[str, Path],
    source_node_path: Union[str, Path],
) -> SliceResult:
    target_count = min(profile.target_core_node_count, len(ranked_node_ids))
    core_node_ids = set(ranked_node_ids[:target_count])
    output_node_ids = set(core_node_ids)
    selected_roads: List[SliceRoad] = []
    orphan_ref_count = 0
    closure_added_node_count = 0

    for road in roads:
        touches_core = road.snodeid in core_node_ids or road.enodeid in core_node_ids
        if not touches_core:
            continue

        selected_roads.append(road)
        for endpoint_node_id in (road.snodeid, road.enodeid):
            if endpoint_node_id is None:
                orphan_ref_count += 1
                continue
            if endpoint_node_id in nodes:
                if endpoint_node_id not in output_node_ids:
                    output_node_ids.add(endpoint_node_id)
                    closure_added_node_count += 1
            else:
                orphan_ref_count += 1

    return _write_profile_slice(
        profile=profile,
        nodes=nodes,
        core_node_ids=core_node_ids,
        selected_roads=selected_roads,
        selected_node_ids=sorted(output_node_ids, key=_sort_key),
        out_dir=out_dir,
        run_id=run_id,
        anchor_node_id=anchor_node_id,
        source_road_path=source_road_path,
        source_node_path=source_node_path,
        closure_added_node_count=closure_added_node_count,
        orphan_ref_count=orphan_ref_count,
    )


def _build_profile_slice_from_shapefile_headers(
    *,
    profile: SliceProfile,
    ranked_node_ids: List[str],
    nodes: Dict[str, SliceNode],
    road_headers: List[SliceRoadHeader],
    road_path: Union[str, Path],
    road_source_crs: CRS,
    out_dir: Path,
    run_id: str,
    anchor_node_id: str,
    source_road_path: Union[str, Path],
    source_node_path: Union[str, Path],
) -> SliceResult:
    target_count = min(profile.target_core_node_count, len(ranked_node_ids))
    core_node_ids = set(ranked_node_ids[:target_count])
    output_node_ids = set(core_node_ids)
    selected_headers: Dict[int, SliceRoadHeader] = {}
    orphan_ref_count = 0
    closure_added_node_count = 0

    for header in road_headers:
        touches_core = header.snodeid in core_node_ids or header.enodeid in core_node_ids
        if not touches_core:
            continue

        selected_headers[header.record_index] = header
        for endpoint_node_id in (header.snodeid, header.enodeid):
            if endpoint_node_id is None:
                orphan_ref_count += 1
                continue
            if endpoint_node_id in nodes:
                if endpoint_node_id not in output_node_ids:
                    output_node_ids.add(endpoint_node_id)
                    closure_added_node_count += 1
            else:
                orphan_ref_count += 1

    print(
        f"[slice] materializing road geometries for profile {profile.profile_id}: selected_roads={len(selected_headers)} ...",
        flush=True,
    )
    selected_roads = _materialize_selected_shapefile_roads(
        road_path,
        source_crs=road_source_crs,
        selected_headers=selected_headers,
    )
    return _write_profile_slice(
        profile=profile,
        nodes=nodes,
        core_node_ids=core_node_ids,
        selected_roads=selected_roads,
        selected_node_ids=sorted(output_node_ids, key=_sort_key),
        out_dir=out_dir,
        run_id=run_id,
        anchor_node_id=anchor_node_id,
        source_road_path=source_road_path,
        source_node_path=source_node_path,
        closure_added_node_count=closure_added_node_count,
        orphan_ref_count=orphan_ref_count,
    )


def build_validation_slices(
    *,
    road_path: Union[str, Path],
    node_path: Union[str, Path],
    profile_config_path: Union[str, Path],
    out_root: Union[str, Path],
    selected_profile_ids: Optional[List[str]] = None,
    run_id: Optional[str] = None,
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
) -> List[SliceResult]:
    build_started_at = perf_counter()
    node_path_obj = Path(node_path)
    if node_path_obj.suffix.lower() == ".shp":
        print("[slice] loading node layer (fast shapefile path)...", flush=True)
        nodes = _load_shapefile_nodes_fast(node_path, crs_override=node_crs)
    else:
        print("[slice] loading node layer...", flush=True)
        node_layer_result = read_vector_layer(node_path, layer_name=node_layer, crs_override=node_crs)
        raw_node_features = [
            {"properties": feature.properties, "geometry": feature.geometry} for feature in node_layer_result.features
        ]
        validation_issues = _validate_required_fields(raw_node_features, REQUIRED_NODE_FIELDS, layer_label="node")
        if validation_issues:
            raise ValueError("; ".join(validation_issues))

        nodes = _prepare_nodes(raw_node_features)
        if not nodes:
            raise ValueError("No valid node features were loaded for slice building.")

    profiles = _filter_profiles(_load_profiles(profile_config_path), selected_profile_ids)
    anchor_node_id = _select_anchor_node_id(nodes)
    ranked_node_ids = _rank_nodes_by_distance(nodes, anchor_node_id)

    resolved_run_id = Path(out_root).name if run_id is None else run_id
    results: List[SliceResult] = []
    source_road_count = 0
    road_path_obj = Path(road_path)

    if road_path_obj.suffix.lower() == ".shp":
        print("[slice] loading road headers...", flush=True)
        road_headers, road_source_crs = _load_shapefile_road_headers(road_path, crs_override=road_crs)
        source_road_count = len(road_headers)
        print(
            f"[slice] source loaded: nodes={len(nodes)}, roads={source_road_count}, anchor_node_id={anchor_node_id}, profiles={','.join(profile.profile_id for profile in profiles)}",
            flush=True,
        )
        for profile in profiles:
            profile_started_at = perf_counter()
            print(
                f"[slice] building profile {profile.profile_id} with target_core_node_count={profile.target_core_node_count} ...",
                flush=True,
            )
            result = _build_profile_slice_from_shapefile_headers(
                profile=profile,
                ranked_node_ids=ranked_node_ids,
                nodes=nodes,
                road_headers=road_headers,
                road_path=road_path,
                road_source_crs=road_source_crs,
                out_dir=Path(out_root) / profile.profile_id,
                run_id=resolved_run_id,
                anchor_node_id=anchor_node_id,
                source_road_path=road_path,
                source_node_path=node_path,
            )
            results.append(result)
            print(
                f"[slice] profile {profile.profile_id} done in {perf_counter() - profile_started_at:.1f}s: output_nodes={result.summary['output_node_count']}, output_roads={result.summary['output_road_count']}",
                flush=True,
            )
    else:
        print("[slice] loading road layer...", flush=True)
        road_layer_result = read_vector_layer(road_path, layer_name=road_layer, crs_override=road_crs)
        raw_road_features = [
            {"properties": feature.properties, "geometry": feature.geometry} for feature in road_layer_result.features
        ]
        validation_issues = _validate_required_fields(raw_road_features, REQUIRED_ROAD_FIELDS, layer_label="road")
        if validation_issues:
            raise ValueError("; ".join(validation_issues))
        roads = _prepare_roads(raw_road_features)
        source_road_count = len(roads)
        print(
            f"[slice] source loaded: nodes={len(nodes)}, roads={source_road_count}, anchor_node_id={anchor_node_id}, profiles={','.join(profile.profile_id for profile in profiles)}",
            flush=True,
        )
        for profile in profiles:
            profile_started_at = perf_counter()
            print(
                f"[slice] building profile {profile.profile_id} with target_core_node_count={profile.target_core_node_count} ...",
                flush=True,
            )
            result = _build_profile_slice(
                profile=profile,
                ranked_node_ids=ranked_node_ids,
                nodes=nodes,
                roads=roads,
                out_dir=Path(out_root) / profile.profile_id,
                run_id=resolved_run_id,
                anchor_node_id=anchor_node_id,
                source_road_path=road_path,
                source_node_path=node_path,
            )
            results.append(result)
            print(
                f"[slice] profile {profile.profile_id} done in {perf_counter() - profile_started_at:.1f}s: output_nodes={result.summary['output_node_count']}, output_roads={result.summary['output_road_count']}",
                flush=True,
            )

    manifest = {
        "run_id": resolved_run_id,
        "out_root": str(Path(out_root).resolve()),
        "profile_config_path": str(Path(profile_config_path)),
        "source_road_path": str(Path(road_path)),
        "source_node_path": str(Path(node_path)),
        "source_road_count": source_road_count,
        "source_node_count": len(nodes),
        "anchor_node_id": anchor_node_id,
        "profiles": [result.summary for result in results],
    }
    write_json(Path(out_root) / "slice_manifest.json", manifest)
    print(f"[slice] all profiles done in {perf_counter() - build_started_at:.1f}s", flush=True)
    return results


def run_slice_builder_cli(args: argparse.Namespace) -> int:
    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=args.out_root, run_id=args.run_id)
    profile_config_path = _resolve_profile_config(args.profile_config)
    results = build_validation_slices(
        road_path=args.road_path,
        road_layer=args.road_layer,
        road_crs=args.road_crs,
        node_path=args.node_path,
        node_layer=args.node_layer,
        node_crs=args.node_crs,
        profile_config_path=profile_config_path,
        out_root=resolved_out_root,
        selected_profile_ids=args.profile_id,
        run_id=resolved_run_id,
    )

    payload = {
        "run_id": resolved_run_id,
        "out_root": str(resolved_out_root.resolve()),
        "profile_config_path": str(profile_config_path.resolve()),
        "profiles": [
            {
                "profile_id": result.profile.profile_id,
                "output_dir": str(result.output_dir.resolve()),
                "output_node_count": result.summary["output_node_count"],
                "output_road_count": result.summary["output_road_count"],
            }
            for result in results
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
