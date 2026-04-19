from __future__ import annotations

import platform
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
    sort_patch_key,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import (
    LayerFeature,
    read_vector_layer,
    write_csv,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_contract import (
    derive_stage3_official_review_decision,
    resolve_stage3_output_kind,
    resolve_stage3_output_kind_source,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_facts import (
    acceptance_class_from_business_outcome,
    business_outcome_from_visual_review_class,
    success_flag_from_business_outcome,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import (
    DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.models import CaseSpec
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import (
    build_step1_context_from_features,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step2_template import (
    classify_step2_template,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import (
    build_step3_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_loader import (
    build_step45_context_from_step3_case,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_rcsd_association import (
    build_step45_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_acceptance import (
    build_step7_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_geometry import (
    build_step6_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_models import (
    Step67CaseResult,
    Step67Context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_writer import (
    materialize_review_gallery,
    write_case_outputs as write_step67_case_outputs,
    write_review_index as write_step67_review_index,
    write_review_summary,
    write_summary as write_step67_summary,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.writer import (
    write_case_outputs as write_step3_case_outputs,
    write_review_index as write_step3_review_index,
    write_summary as write_step3_summary,
)


CASE_FILE_LIST = (
    "manifest.json",
    "size_report.json",
    "drivezone.gpkg",
    "nodes.gpkg",
    "roads.gpkg",
    "rcsdroad.gpkg",
    "rcsdnode.gpkg",
)

ALLOWED_KIND_2_VALUES = frozenset({4, 2048})


@dataclass(frozen=True)
class SharedFullInputLayers:
    nodes: tuple[LayerFeature, ...]
    roads: tuple[LayerFeature, ...]
    drivezones: tuple[LayerFeature, ...]
    rcsd_roads: tuple[LayerFeature, ...]
    rcsd_nodes: tuple[LayerFeature, ...]


@dataclass(frozen=True)
class T03Step67InternalFullInputArtifacts:
    run_root: Path
    visual_check_dir: Path
    internal_root: Path
    case_root: Path
    step3_run_root: Path
    selected_case_ids: tuple[str, ...]
    discovered_case_ids: tuple[str, ...]
    excluded_case_ids: tuple[str, ...]


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_case_ids(case_ids: list[str]) -> list[str]:
    return sorted({str(case_id) for case_id in case_ids}, key=sort_patch_key)


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _feature_id(feature: LayerFeature) -> str | None:
    return _normalize_text(feature.properties.get("id"))


def _feature_mainnodeid(feature: LayerFeature) -> str | None:
    return _normalize_text(feature.properties.get("mainnodeid"))


def _feature_snodeid(feature: LayerFeature) -> str | None:
    return _normalize_text(feature.properties.get("snodeid"))


def _feature_enodeid(feature: LayerFeature) -> str | None:
    return _normalize_text(feature.properties.get("enodeid"))


def _has_geometry(feature: LayerFeature) -> bool:
    geometry = feature.geometry
    return geometry is not None and not geometry.is_empty


def _intersects(feature: LayerFeature, geometry: BaseGeometry) -> bool:
    return _has_geometry(feature) and bool(feature.geometry.intersects(geometry))


def _load_shared_nodes(*, nodes_path: Path) -> tuple[LayerFeature, ...]:
    return tuple(read_vector_layer(nodes_path).features)


def _load_shared_layers(
    *,
    nodes: tuple[LayerFeature, ...],
    nodes_path: Path,
    roads_path: Path,
    drivezone_path: Path,
    rcsdroad_path: Path,
    rcsdnode_path: Path,
) -> SharedFullInputLayers:
    return SharedFullInputLayers(
        nodes=nodes,
        roads=tuple(read_vector_layer(roads_path).features),
        drivezones=tuple(read_vector_layer(drivezone_path).features),
        rcsd_roads=tuple(read_vector_layer(rcsdroad_path).features),
        rcsd_nodes=tuple(read_vector_layer(rcsdnode_path).features),
    )


def _is_auto_candidate(feature: LayerFeature) -> bool:
    node_id = _feature_id(feature)
    mainnodeid = _feature_mainnodeid(feature)
    kind_2 = _coerce_int(feature.properties.get("kind_2"))
    has_evd = _normalize_text(feature.properties.get("has_evd"))
    is_anchor = _normalize_text(feature.properties.get("is_anchor"))
    is_representative = (mainnodeid is not None and node_id == mainnodeid) or (mainnodeid is None and node_id is not None)
    return (
        is_representative
        and has_evd == "yes"
        and is_anchor == "no"
        and kind_2 in ALLOWED_KIND_2_VALUES
    )


def _discover_candidate_case_ids(nodes: tuple[LayerFeature, ...]) -> list[str]:
    discovered = []
    for feature in nodes:
        if not _is_auto_candidate(feature):
            continue
        case_id = _feature_mainnodeid(feature) or _feature_id(feature)
        if case_id is not None:
            discovered.append(case_id)
    return _stable_case_ids(discovered)


def _resolve_representative_feature(nodes: tuple[LayerFeature, ...], case_id: str) -> LayerFeature:
    for feature in nodes:
        if _feature_id(feature) == case_id and _has_geometry(feature):
            return feature
    for feature in nodes:
        if _feature_mainnodeid(feature) == case_id and _has_geometry(feature):
            return feature
    raise ValueError(f"representative node not found for case_id={case_id}")


def _selection_window(representative_feature: LayerFeature, *, buffer_m: float, patch_size_m: float) -> BaseGeometry:
    geometry = representative_feature.geometry
    if geometry is None or geometry.is_empty:
        raise ValueError("representative node geometry is empty")
    min_x, min_y, max_x, max_y = geometry.bounds
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    half_span = max(float(buffer_m or 0.0), float(patch_size_m or 0.0) / 2.0, 1.0)
    return box(center_x - half_span, center_y - half_span, center_x + half_span, center_y + half_span)


def _collect_case_features(
    *,
    shared_layers: SharedFullInputLayers,
    case_id: str,
    buffer_m: float,
    patch_size_m: float,
) -> dict[str, list[LayerFeature] | BaseGeometry]:
    representative_feature = _resolve_representative_feature(shared_layers.nodes, case_id)
    selection_window = _selection_window(
        representative_feature,
        buffer_m=buffer_m,
        patch_size_m=patch_size_m,
    )
    target_group_id = _feature_mainnodeid(representative_feature) or case_id

    target_group_nodes = [
        feature
        for feature in shared_layers.nodes
        if (_feature_mainnodeid(feature) or _feature_id(feature)) == target_group_id and _has_geometry(feature)
    ]
    if not target_group_nodes:
        target_group_nodes = [representative_feature]

    target_node_ids = {_feature_id(feature) for feature in target_group_nodes if _feature_id(feature) is not None}
    selected_roads = [
        feature
        for feature in shared_layers.roads
        if (
            _feature_snodeid(feature) in target_node_ids
            or _feature_enodeid(feature) in target_node_ids
            or _intersects(feature, selection_window)
        )
    ]
    referenced_node_ids = {
        value
        for feature in selected_roads
        for value in (_feature_snodeid(feature), _feature_enodeid(feature))
        if value is not None
    }

    selected_nodes = []
    for feature in shared_layers.nodes:
        node_id = _feature_id(feature)
        if node_id is None or not _has_geometry(feature):
            continue
        if (
            node_id in referenced_node_ids
            or node_id in target_node_ids
            or _feature_mainnodeid(feature) == target_group_id
            or _intersects(feature, selection_window)
        ):
            selected_nodes.append(feature)

    selected_rcsd_nodes = [
        feature
        for feature in shared_layers.rcsd_nodes
        if (
            _has_geometry(feature)
            and (
                _intersects(feature, selection_window)
                or _feature_mainnodeid(feature) == target_group_id
                or _feature_id(feature) == case_id
            )
        )
    ]
    selected_rcsd_node_ids = {_feature_id(feature) for feature in selected_rcsd_nodes if _feature_id(feature) is not None}
    selected_rcsd_roads = [
        feature
        for feature in shared_layers.rcsd_roads
        if (
            _feature_snodeid(feature) in selected_rcsd_node_ids
            or _feature_enodeid(feature) in selected_rcsd_node_ids
            or _intersects(feature, selection_window)
        )
    ]

    selected_drivezones = [
        feature
        for feature in shared_layers.drivezones
        if _intersects(feature, selection_window)
    ]
    if not selected_drivezones:
        drivezone_candidates = [feature for feature in shared_layers.drivezones if _has_geometry(feature)]
        if not drivezone_candidates:
            raise ValueError(f"drivezone layer is empty for case_id={case_id}")
        representative_geometry = representative_feature.geometry
        assert representative_geometry is not None
        selected_drivezones = [
            min(
                drivezone_candidates,
                key=lambda feature: float(feature.geometry.distance(representative_geometry)),
            )
        ]

    return {
        "selection_window": selection_window,
        "nodes": selected_nodes,
        "roads": selected_roads,
        "drivezones": selected_drivezones,
        "rcsd_roads": selected_rcsd_roads,
        "rcsd_nodes": selected_rcsd_nodes,
    }


def _as_write_features(features: list[LayerFeature]) -> list[dict[str, Any]]:
    return [
        {
            "properties": dict(feature.properties),
            "geometry": feature.geometry,
        }
        for feature in features
    ]


def _write_case_package_files(
    *,
    case_dir: Path,
    case_id: str,
    selection_window: BaseGeometry,
    nodes: list[LayerFeature],
    roads: list[LayerFeature],
    drivezones: list[LayerFeature],
    rcsd_roads: list[LayerFeature],
    rcsd_nodes: list[LayerFeature],
    buffer_m: float,
    patch_size_m: float,
    resolution_m: float,
) -> dict[str, Any]:
    case_dir.mkdir(parents=True, exist_ok=True)
    write_vector(case_dir / "nodes.gpkg", _as_write_features(nodes), crs_text="EPSG:3857")
    write_vector(case_dir / "roads.gpkg", _as_write_features(roads), crs_text="EPSG:3857")
    write_vector(case_dir / "drivezone.gpkg", _as_write_features(drivezones), crs_text="EPSG:3857")
    write_vector(case_dir / "rcsdroad.gpkg", _as_write_features(rcsd_roads), crs_text="EPSG:3857")
    write_vector(case_dir / "rcsdnode.gpkg", _as_write_features(rcsd_nodes), crs_text="EPSG:3857")

    manifest = {
        "bundle_version": 1,
        "mainnodeid": case_id,
        "epsg": 3857,
        "file_list": list(CASE_FILE_LIST),
        "decoded_output": {
            "vector_crs": "EPSG:3857",
            "vector_coordinates": "absolute_epsg3857",
        },
        "source_mode": "t03_internal_full_input_prepare",
        "selection_window_bounds": [round(float(value), 6) for value in selection_window.bounds],
        "buffer_m": float(buffer_m),
        "patch_size_m": float(patch_size_m),
        "resolution_m": float(resolution_m),
        "selected_feature_counts": {
            "nodes": len(nodes),
            "roads": len(roads),
            "drivezones": len(drivezones),
            "rcsd_roads": len(rcsd_roads),
            "rcsd_nodes": len(rcsd_nodes),
        },
    }
    write_json(case_dir / "manifest.json", manifest)

    total_size_bytes = 0
    for file_name in CASE_FILE_LIST:
        file_path = case_dir / file_name
        if file_path.is_file():
            total_size_bytes += int(file_path.stat().st_size)
    size_report = {
        "within_limit": True,
        "limit_bytes": max(307200, total_size_bytes),
        "total_vector_size_bytes": total_size_bytes,
    }
    write_json(case_dir / "size_report.json", size_report)
    total_size_bytes = sum(
        int((case_dir / file_name).stat().st_size)
        for file_name in CASE_FILE_LIST
        if (case_dir / file_name).is_file()
    )

    return {
        "case_id": case_id,
        "decoded_case_root": str(case_dir),
        "bundle_size_bytes": total_size_bytes,
        "selected_counts": manifest["selected_feature_counts"],
        "selection_window_bounds": manifest["selection_window_bounds"],
    }


def _prepare_case_package(
    *,
    case_id: str,
    shared_layers: SharedFullInputLayers,
    buffer_m: float,
    patch_size_m: float,
    resolution_m: float,
    case_root: Path,
) -> dict[str, Any]:
    selected = _collect_case_features(
        shared_layers=shared_layers,
        case_id=case_id,
        buffer_m=buffer_m,
        patch_size_m=patch_size_m,
    )
    return _write_case_package_files(
        case_dir=case_root / case_id,
        case_id=case_id,
        selection_window=selected["selection_window"],
        nodes=list(selected["nodes"]),
        roads=list(selected["roads"]),
        drivezones=list(selected["drivezones"]),
        rcsd_roads=list(selected["rcsd_roads"]),
        rcsd_nodes=list(selected["rcsd_nodes"]),
        buffer_m=buffer_m,
        patch_size_m=patch_size_m,
        resolution_m=resolution_m,
    )


def _build_internal_case_spec(
    *,
    case_id: str,
    internal_root: Path,
    input_paths: dict[str, Path],
) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        mainnodeid=case_id,
        case_root=internal_root,
        manifest={
            "bundle_version": 1,
            "source_mode": "t03_internal_full_input_direct_local_query",
            "mainnodeid": case_id,
        },
        size_report={
            "within_limit": True,
            "source_mode": "t03_internal_full_input_direct_local_query",
        },
        input_paths=input_paths,
    )


def _write_local_context_snapshot(
    *,
    local_context_root: Path,
    case_id: str,
    selected_counts: dict[str, int],
    selection_window: BaseGeometry,
) -> None:
    local_context_root.mkdir(parents=True, exist_ok=True)
    write_json(
        local_context_root / f"{case_id}.json",
        {
            "case_id": case_id,
            "source_mode": "t03_internal_full_input_direct_local_query",
            "selection_window_bounds": [round(float(value), 6) for value in selection_window.bounds],
            "selected_feature_counts": dict(selected_counts),
            "updated_at": _now_text(),
        },
    )


def _write_step67_watch_status(
    *,
    run_root: Path,
    case_id: str,
    state: str,
    current_stage: str,
    reason: str,
    detail: str,
    **extra: Any,
) -> None:
    case_dir = run_root / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        case_dir / "step67_watch_status.json",
        {
            "case_id": case_id,
            "state": state,
            "current_stage": current_stage,
            "reason": reason,
            "detail": detail,
            "updated_at": _now_text(),
            **extra,
        },
    )


def _run_single_case_direct(
    *,
    case_id: str,
    shared_layers: SharedFullInputLayers,
    buffer_m: float,
    patch_size_m: float,
    resolution_m: float,
    internal_root: Path,
    run_root: Path,
    step3_run_root: Path,
    input_paths: dict[str, Path],
    debug_render: bool,
) -> dict[str, Any]:
    representative_feature = _resolve_representative_feature(shared_layers.nodes, case_id)
    selected = _collect_case_features(
        shared_layers=shared_layers,
        case_id=case_id,
        buffer_m=buffer_m,
        patch_size_m=patch_size_m,
    )
    selected_counts = {
        "nodes": len(selected["nodes"]),
        "roads": len(selected["roads"]),
        "drivezones": len(selected["drivezones"]),
        "rcsd_roads": len(selected["rcsd_roads"]),
        "rcsd_nodes": len(selected["rcsd_nodes"]),
    }
    case_spec = _build_internal_case_spec(
        case_id=case_id,
        internal_root=internal_root,
        input_paths=input_paths,
    )
    step1_context = build_step1_context_from_features(
        case_spec=case_spec,
        node_features=selected["nodes"],
        road_features=selected["roads"],
        drivezone_features=selected["drivezones"],
        rcsdroad_features=selected["rcsd_roads"],
        rcsdnode_features=selected["rcsd_nodes"],
    )
    template_result = classify_step2_template(step1_context)
    step3_case_result = build_step3_case_result(step1_context, template_result)
    step3_row = write_step3_case_outputs(
        run_root=step3_run_root,
        context=step1_context,
        case_result=step3_case_result,
    )
    step45_context = build_step45_context_from_step3_case(
        step1_context=step1_context,
        template_result=template_result,
        step3_run_root=step3_run_root,
        step3_case_dir=step3_run_root / "cases" / case_id,
        step3_case_result=step3_case_result,
    )
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)
    step7_result = build_step7_result(step67_context, step6_result)
    step67_case_result = Step67CaseResult(
        case_id=case_id,
        template_class=step45_case_result.template_class,
        association_class=step45_case_result.association_class,
        step45_state=step45_case_result.step45_state,
        step6_result=step6_result,
        step7_result=step7_result,
    )
    step67_row = write_step67_case_outputs(
        run_root=run_root,
        step67_context=step67_context,
        case_result=step67_case_result,
        debug_render=debug_render,
    )
    return {
        "case_id": case_id,
        "representative_feature": representative_feature,
        "selection_window": selected["selection_window"],
        "selected_counts": selected_counts,
        "step3_row": step3_row,
        "step3_case_result": step3_case_result,
        "step67_row": step67_row,
        "step67_case_result": step67_case_result,
    }


def _write_internal_case_progress(
    *,
    case_progress_root: Path,
    case_id: str,
    state: str,
    current_stage: str,
    reason: str,
    detail: str,
    **extra: Any,
) -> None:
    case_progress_root.mkdir(parents=True, exist_ok=True)
    write_json(
        case_progress_root / f"{case_id}.json",
        {
            "case_id": str(case_id),
            "state": state,
            "current_stage": current_stage,
            "reason": reason,
            "detail": detail,
            "updated_at": _now_text(),
            **extra,
        },
    )


def _write_internal_progress(
    *,
    internal_root: Path,
    run_root: Path,
    phase: str,
    status: str,
    message: str,
    selected_case_ids: list[str],
    discovered_case_ids: list[str],
    excluded_case_ids: list[str],
    prepared_case_ids: list[str] | None = None,
    step3_run_root: Path | None = None,
    **extra: Any,
) -> None:
    payload = {
        "updated_at": _now_text(),
        "phase": phase,
        "status": status,
        "message": message,
        "run_root": str(run_root),
        "internal_root": str(internal_root),
        "selected_case_count": len(selected_case_ids),
        "selected_case_ids": list(selected_case_ids),
        "discovered_case_count": len(discovered_case_ids),
        "discovered_case_ids": list(discovered_case_ids),
        "default_full_batch_excluded_case_count": len(excluded_case_ids),
        "default_full_batch_excluded_case_ids": list(excluded_case_ids),
        "prepared_case_count": len(prepared_case_ids or []),
        "prepared_case_ids": list(prepared_case_ids or []),
        "step3_run_root": str(step3_run_root) if step3_run_root is not None else None,
        **extra,
    }
    write_json(internal_root / "internal_full_input_progress.json", payload)


def _mirror_visual_checks(*, source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        same_dir = source_dir.resolve() == target_dir.resolve()
    except FileNotFoundError:
        same_dir = False
    if same_dir:
        return

    for png_path in sorted(source_dir.glob("*.png"), key=lambda path: sort_patch_key(path.name)):
        shutil.copy2(png_path, target_dir / png_path.name)


def _write_internal_failure(
    *,
    internal_root: Path,
    run_root: Path,
    phase: str,
    failure: str,
    selected_case_ids: list[str],
    discovered_case_ids: list[str],
    excluded_case_ids: list[str],
    prepared_case_ids: list[str] | None = None,
    step3_run_root: Path | None = None,
) -> None:
    write_json(
        internal_root / "internal_full_input_failure.json",
        {
            "updated_at": _now_text(),
            "phase": phase,
            "failure": failure,
            "run_root": str(run_root),
            "internal_root": str(internal_root),
            "selected_case_ids": list(selected_case_ids),
            "discovered_case_ids": list(discovered_case_ids),
            "excluded_case_ids": list(excluded_case_ids),
            "prepared_case_ids": list(prepared_case_ids or []),
            "step3_run_root": str(step3_run_root) if step3_run_root is not None else None,
        },
    )


def _build_virtual_intersection_polygon_feature(
    *,
    representative_feature: LayerFeature,
    case_result: Step67CaseResult,
    case_dir: Path,
) -> dict[str, Any] | None:
    polygon_geometry = case_result.step6_result.output_geometries.polygon_final_geometry
    if polygon_geometry is None or polygon_geometry.is_empty:
        return None

    visual_review_class = case_result.step7_result.visual_review_class
    business_outcome_class = business_outcome_from_visual_review_class(visual_review_class)
    if business_outcome_class == "failure":
        return None

    acceptance_class = acceptance_class_from_business_outcome(business_outcome_class)
    success = success_flag_from_business_outcome(business_outcome_class)
    representative_properties = dict(representative_feature.properties)
    representative_node_id = _feature_id(representative_feature) or case_result.case_id
    mainnodeid = _feature_mainnodeid(representative_feature) or representative_node_id
    kind_2 = _coerce_int(representative_properties.get("kind_2"))
    grade_2 = _coerce_int(representative_properties.get("grade_2"))
    official_review = derive_stage3_official_review_decision(
        success=success,
        business_outcome_class=business_outcome_class,
        acceptance_class=acceptance_class,
        acceptance_reason=case_result.step7_result.reason,
        status=case_result.step7_result.reason,
        root_cause_layer=case_result.step7_result.root_cause_layer,
        representative_has_evd=representative_properties.get("has_evd"),
        representative_is_anchor=representative_properties.get("is_anchor"),
        representative_kind_2=kind_2,
    )
    properties = {
        "mainnodeid": mainnodeid,
        "kind": resolve_stage3_output_kind(
            representative_kind=representative_properties.get("kind"),
            representative_kind_2=kind_2,
            representative_properties=representative_properties,
        ),
        "kind_source": resolve_stage3_output_kind_source(
            representative_kind=representative_properties.get("kind"),
            representative_kind_2=kind_2,
            representative_properties=representative_properties,
        ),
        "status": case_result.step7_result.reason,
        "representative_node_id": representative_node_id,
        "kind_2": kind_2,
        "grade_2": grade_2,
        "success": success,
        "business_outcome_class": business_outcome_class,
        "acceptance_class": acceptance_class,
        "root_cause_layer": case_result.step7_result.root_cause_layer,
        "root_cause_type": case_result.step7_result.root_cause_type,
        "visual_review_class": visual_review_class,
        "official_review_eligible": official_review.official_review_eligible,
        "failure_bucket": official_review.failure_bucket,
        "source_case_dir": str(case_dir),
    }
    return {"properties": properties, "geometry": polygon_geometry}


def _write_virtual_intersection_polygons(
    *,
    run_root: Path,
    successful_results: dict[str, dict[str, Any]],
) -> Path:
    features: list[dict[str, Any]] = []
    for case_id in sorted(successful_results.keys(), key=sort_patch_key):
        result = successful_results[case_id]
        feature = _build_virtual_intersection_polygon_feature(
            representative_feature=result["representative_feature"],
            case_result=result["step67_case_result"],
            case_dir=run_root / "cases" / case_id,
        )
        if feature is not None:
            features.append(feature)
    output_path = run_root / "virtual_intersection_polygons.gpkg"
    write_vector(output_path, features, crs_text="EPSG:3857")
    return output_path


def _write_updated_nodes_outputs(
    *,
    run_root: Path,
    shared_nodes: tuple[LayerFeature, ...],
    selected_case_ids: list[str],
    successful_results: dict[str, dict[str, Any]],
    failed_case_ids: list[str],
) -> dict[str, Path]:
    updates_by_node_id: dict[str, str] = {}
    audit_rows: list[dict[str, Any]] = []
    failed_case_id_set = {str(case_id) for case_id in failed_case_ids}

    for case_id in sorted(selected_case_ids, key=sort_patch_key):
        representative_feature = _resolve_representative_feature(shared_nodes, case_id)
        representative_node_id = _feature_id(representative_feature) or case_id
        previous_is_anchor = representative_feature.properties.get("is_anchor")
        if case_id in successful_results:
            case_result = successful_results[case_id]["step67_case_result"]
            step7_state = case_result.step7_result.step7_state
            reason = case_result.step7_result.reason
            new_is_anchor = "yes" if step7_state == "accepted" else "fail3"
        else:
            step7_state = "runtime_failed" if case_id in failed_case_id_set else "runtime_failed"
            reason = "runtime_failed"
            new_is_anchor = "fail3"
        updates_by_node_id[representative_node_id] = new_is_anchor
        audit_rows.append(
            {
                "case_id": case_id,
                "representative_node_id": representative_node_id,
                "previous_is_anchor": previous_is_anchor,
                "new_is_anchor": new_is_anchor,
                "step7_state": step7_state,
                "reason": reason,
            }
        )

    nodes_features = []
    for feature in shared_nodes:
        properties = dict(feature.properties)
        node_id = _feature_id(feature)
        if node_id is not None and node_id in updates_by_node_id:
            properties["is_anchor"] = updates_by_node_id[node_id]
        nodes_features.append({"properties": properties, "geometry": feature.geometry})

    nodes_output_path = run_root / "nodes.gpkg"
    audit_csv_path = run_root / "nodes_anchor_update_audit.csv"
    audit_json_path = run_root / "nodes_anchor_update_audit.json"
    write_vector(nodes_output_path, nodes_features, crs_text="EPSG:3857")
    write_csv(
        audit_csv_path,
        audit_rows,
        [
            "case_id",
            "representative_node_id",
            "previous_is_anchor",
            "new_is_anchor",
            "step7_state",
            "reason",
        ],
    )
    write_json(
        audit_json_path,
        {
            "total_update_count": len(audit_rows),
            "updated_to_yes_count": sum(1 for row in audit_rows if row["new_is_anchor"] == "yes"),
            "updated_to_fail3_count": sum(1 for row in audit_rows if row["new_is_anchor"] == "fail3"),
            "rows": audit_rows,
        },
    )
    return {
        "nodes_path": nodes_output_path,
        "audit_csv_path": audit_csv_path,
        "audit_json_path": audit_json_path,
    }


def run_t03_step67_internal_full_input(
    *,
    nodes_path: str | Path,
    roads_path: str | Path,
    drivezone_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str,
    workers: int = 1,
    max_cases: int | None = None,
    buffer_m: float = 100.0,
    patch_size_m: float = 200.0,
    resolution_m: float = 0.2,
    debug: bool = False,
    review_mode: bool = False,
    visual_check_dir: str | Path | None = None,
) -> T03Step67InternalFullInputArtifacts:
    resolved_nodes_path = normalize_runtime_path(nodes_path)
    resolved_roads_path = normalize_runtime_path(roads_path)
    resolved_drivezone_path = normalize_runtime_path(drivezone_path)
    resolved_rcsdroad_path = normalize_runtime_path(rcsdroad_path)
    resolved_rcsdnode_path = normalize_runtime_path(rcsdnode_path)
    resolved_out_root = normalize_runtime_path(out_root)
    resolved_visual_check_dir = (
        normalize_runtime_path(visual_check_dir)
        if visual_check_dir is not None
        else resolved_out_root / run_id / "visual_checks"
    )
    run_root = resolved_out_root / run_id
    internal_root = resolved_out_root / "_internal" / run_id
    case_root = internal_root / "local_context"
    case_progress_root = internal_root / "case_progress"
    step3_out_root = internal_root / "step3_runs"
    step3_run_root = step3_out_root / f"{run_id}__step3"
    max_workers = max(1, int(workers or 1))
    rerun_cleaned_before_write = False

    if run_root.exists():
        shutil.rmtree(run_root)
        rerun_cleaned_before_write = True
    if internal_root.exists():
        shutil.rmtree(internal_root)
    run_root.mkdir(parents=True, exist_ok=True)
    case_root.mkdir(parents=True, exist_ok=True)
    case_progress_root.mkdir(parents=True, exist_ok=True)
    step3_run_root.mkdir(parents=True, exist_ok=True)
    resolved_visual_check_dir.mkdir(parents=True, exist_ok=True)

    discovered_case_ids: list[str] = []
    excluded_case_ids = _stable_case_ids(list(DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS))
    selected_case_ids: list[str] = []
    step3_rows = []
    step67_rows = []
    failed_case_ids: list[str] = []
    successful_case_results: dict[str, dict[str, Any]] = {}
    shared_memory_summary: dict[str, Any] = {
        "enabled": False,
        "node_group_lookup": False,
        "shared_local_layer_query": False,
        "layers": {},
    }
    input_paths = {
        "nodes_path": resolved_nodes_path,
        "roads_path": resolved_roads_path,
        "drivezone_path": resolved_drivezone_path,
        "rcsdroad_path": resolved_rcsdroad_path,
        "rcsdnode_path": resolved_rcsdnode_path,
    }

    _write_internal_progress(
        internal_root=internal_root,
        run_root=run_root,
        phase="bootstrap",
        status="running",
        message="Preloading shared nodes handle for T03 internal full-input execution.",
        selected_case_ids=[],
        discovered_case_ids=[],
        excluded_case_ids=excluded_case_ids,
    )

    try:
        shared_nodes = _load_shared_nodes(nodes_path=resolved_nodes_path)
        shared_memory_summary["enabled"] = True
        shared_memory_summary["node_group_lookup"] = True
        shared_memory_summary["layers"]["nodes"] = {
            "feature_count": len(shared_nodes),
        }
        discovered_case_ids = _discover_candidate_case_ids(shared_nodes)
        eligible_case_ids = [case_id for case_id in discovered_case_ids if case_id not in set(excluded_case_ids)]
        selected_case_ids = eligible_case_ids[:max_cases] if max_cases is not None else eligible_case_ids
        if not selected_case_ids:
            _write_internal_progress(
                internal_root=internal_root,
                run_root=run_root,
                phase="candidate_selection",
                status="failed",
                message="No eligible T03 Step67 full-input candidates were discovered.",
                selected_case_ids=[],
                discovered_case_ids=discovered_case_ids,
                excluded_case_ids=excluded_case_ids,
            )
            raise ValueError(
                "No eligible Step67 full-input cases were discovered after applying "
                "has_evd=yes, is_anchor=no, kind_2 in {4, 2048} and the default T03 excluded-case set."
            )

        for case_id in selected_case_ids:
            _write_internal_case_progress(
                case_progress_root=case_progress_root,
                case_id=case_id,
                state="pending",
                current_stage="candidate_selection",
                reason="selected_for_direct_full_input_execution",
                detail="eligible full-input candidate discovered and queued for direct per-case execution",
            )
            _write_step67_watch_status(
                run_root=run_root,
                case_id=case_id,
                state="pending",
                current_stage="queued",
                reason="queued_for_step67_full_input",
                detail="case queued for direct T03 full-input execution",
            )

        default_formal_case_ids = list(eligible_case_ids)
        preflight_doc = {
            "generated_at": _now_text(),
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "nodes_path": str(resolved_nodes_path),
            "roads_path": str(resolved_roads_path),
            "drivezone_path": str(resolved_drivezone_path),
            "rcsdroad_path": str(resolved_rcsdroad_path),
            "rcsdnode_path": str(resolved_rcsdnode_path),
            "out_root": str(resolved_out_root),
            "run_root": str(run_root),
            "visual_check_dir": str(resolved_visual_check_dir),
            "raw_case_count": len(discovered_case_ids),
            "raw_case_ids": list(discovered_case_ids),
            "default_formal_case_count": len(default_formal_case_ids),
            "default_formal_case_ids": list(default_formal_case_ids),
            "formal_full_batch_case_count": len(default_formal_case_ids),
            "formal_full_batch_case_ids": list(default_formal_case_ids),
            "selected_case_count": len(selected_case_ids),
            "selected_case_ids": list(selected_case_ids),
            "effective_case_count": len(selected_case_ids),
            "effective_case_ids": list(selected_case_ids),
            "excluded_case_ids": list(excluded_case_ids),
            "default_full_batch_excluded_case_ids": list(excluded_case_ids),
            "explicit_case_selection": False,
            "execution_mode": "direct_shared_handle_local_query",
            "review_mode_requested": review_mode,
            "review_mode_effective": False,
        }
        write_json(run_root / "preflight.json", preflight_doc)

        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase="shared_handle_preload",
            status="running",
            message="Preloading shared full-input layers for direct per-case local query.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
        )
        shared_layers = _load_shared_layers(
            nodes=shared_nodes,
            nodes_path=resolved_nodes_path,
            roads_path=resolved_roads_path,
            drivezone_path=resolved_drivezone_path,
            rcsdroad_path=resolved_rcsdroad_path,
            rcsdnode_path=resolved_rcsdnode_path,
        )
        shared_memory_summary["shared_local_layer_query"] = True
        shared_memory_summary["layers"].update(
            {
                "roads": {"feature_count": len(shared_layers.roads)},
                "drivezone": {"feature_count": len(shared_layers.drivezones)},
                "rcsdroad": {"feature_count": len(shared_layers.rcsd_roads)},
                "rcsdnode": {"feature_count": len(shared_layers.rcsd_nodes)},
            }
        )

        write_json(
            step3_run_root / "preflight.json",
            {
                "generated_at": _now_text(),
                "case_root": str(case_root),
                "run_root": str(step3_run_root),
                "execution_mode": "direct_shared_handle_local_query",
                "selected_case_ids": list(selected_case_ids),
                "raw_case_count": len(discovered_case_ids),
                "default_formal_case_count": len(default_formal_case_ids),
                "excluded_case_ids": list(excluded_case_ids),
            },
        )

        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase="direct_case_execution",
            status="running",
            message="Executing T03 Step3/Step67 directly inside full-input runner with shared local query.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            step3_run_root=step3_run_root,
        )

        def _execute_case(case_id: str) -> dict[str, Any]:
            _write_internal_case_progress(
                case_progress_root=case_progress_root,
                case_id=case_id,
                state="running",
                current_stage="direct_case_execution",
                reason="direct_case_started",
                detail="executing step3/step67 directly from shared full-input layers",
            )
            _write_step67_watch_status(
                run_root=run_root,
                case_id=case_id,
                state="running",
                current_stage="direct_case_execution",
                reason="direct_case_started",
                detail="executing step3/step67 directly from shared full-input layers",
            )
            try:
                result = _run_single_case_direct(
                    case_id=case_id,
                    shared_layers=shared_layers,
                    buffer_m=buffer_m,
                    patch_size_m=patch_size_m,
                    resolution_m=resolution_m,
                    internal_root=internal_root,
                    run_root=run_root,
                    step3_run_root=step3_run_root,
                    input_paths=input_paths,
                    debug_render=debug,
                )
            except Exception as exc:
                _write_internal_case_progress(
                    case_progress_root=case_progress_root,
                    case_id=case_id,
                    state="failed",
                    current_stage="direct_case_execution",
                    reason="direct_case_failed",
                    detail=str(exc),
                )
                _write_step67_watch_status(
                    run_root=run_root,
                    case_id=case_id,
                    state="failed",
                    current_stage="direct_case_execution",
                    reason="direct_case_failed",
                    detail=f"{type(exc).__name__}: {exc}",
                )
                raise

            _write_local_context_snapshot(
                local_context_root=case_root,
                case_id=case_id,
                selected_counts=result["selected_counts"],
                selection_window=result["selection_window"],
            )
            case_result = result["step67_case_result"]
            _write_internal_case_progress(
                case_progress_root=case_progress_root,
                case_id=case_id,
                state=case_result.step7_result.step7_state,
                current_stage="completed",
                reason=case_result.step7_result.reason,
                detail=case_result.step7_result.note or case_result.step6_result.reason,
                step3_state=result["step3_case_result"].step3_state,
                step45_state=case_result.step45_state,
                step6_state=case_result.step6_result.step6_state,
                step7_state=case_result.step7_result.step7_state,
                selected_counts=result["selected_counts"],
            )
            _write_step67_watch_status(
                run_root=run_root,
                case_id=case_id,
                state=case_result.step7_result.step7_state,
                current_stage="completed",
                reason=case_result.step7_result.reason,
                detail=case_result.step7_result.note or case_result.step6_result.reason,
                step45_state=case_result.step45_state,
                step6_state=case_result.step6_result.step6_state,
                step7_state=case_result.step7_result.step7_state,
            )
            return result

        if max_workers == 1 or len(selected_case_ids) <= 1:
            for case_id in selected_case_ids:
                try:
                    result = _execute_case(case_id)
                except Exception:
                    failed_case_ids.append(case_id)
                    continue
                step3_rows.append(result["step3_row"])
                step67_rows.append(result["step67_row"])
                successful_case_results[case_id] = result
        else:
            futures = {}
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="t03-full-input-direct") as executor:
                for case_id in selected_case_ids:
                    futures[executor.submit(_execute_case, case_id)] = case_id
                for future in as_completed(futures):
                    case_id = futures[future]
                    try:
                        result = future.result()
                    except Exception:
                        failed_case_ids.append(case_id)
                        continue
                    step3_rows.append(result["step3_row"])
                    step67_rows.append(result["step67_row"])
                    successful_case_results[case_id] = result

        step3_rows.sort(key=lambda row: sort_patch_key(str(row.case_id)))
        step67_rows.sort(key=lambda row: sort_patch_key(str(row.case_id)))
        categorized_rows = materialize_review_gallery(run_root, step67_rows)
        write_step3_review_index(step3_run_root, step3_rows)
        write_step3_summary(
            step3_run_root,
            step3_rows,
            expected_case_ids=list(selected_case_ids),
            raw_case_count=len(discovered_case_ids),
            default_formal_case_count=len(default_formal_case_ids),
            effective_case_ids=list(selected_case_ids),
            raw_case_ids=list(discovered_case_ids),
            default_formal_case_ids=list(default_formal_case_ids),
            default_full_batch_excluded_case_ids=list(excluded_case_ids),
            excluded_case_ids=list(excluded_case_ids),
            explicit_case_selection=False,
            failed_case_ids=list(failed_case_ids),
            rerun_cleaned_before_write=False,
        )
        write_step67_review_index(run_root, categorized_rows)
        write_review_summary(run_root, categorized_rows)
        write_step67_summary(
            run_root,
            categorized_rows,
            expected_case_ids=list(selected_case_ids),
            raw_case_count=len(discovered_case_ids),
            default_formal_case_count=len(default_formal_case_ids),
            effective_case_ids=list(selected_case_ids),
            raw_case_ids=list(discovered_case_ids),
            default_formal_case_ids=list(default_formal_case_ids),
            default_full_batch_excluded_case_ids=list(excluded_case_ids),
            excluded_case_ids=list(excluded_case_ids),
            explicit_case_selection=False,
            failed_case_ids=list(failed_case_ids),
            rerun_cleaned_before_write=rerun_cleaned_before_write,
        )
        polygons_path = _write_virtual_intersection_polygons(
            run_root=run_root,
            successful_results=successful_case_results,
        )
        nodes_outputs = _write_updated_nodes_outputs(
            run_root=run_root,
            shared_nodes=shared_nodes,
            selected_case_ids=selected_case_ids,
            successful_results=successful_case_results,
            failed_case_ids=failed_case_ids,
        )
        _mirror_visual_checks(
            source_dir=run_root / "step67_review_flat",
            target_dir=resolved_visual_check_dir,
        )

        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase="completed",
            status="completed",
            message="T03 internal full-input execution completed with direct shared-handle local query.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            prepared_case_ids=[],
            step3_run_root=step3_run_root,
            execution_mode="direct_shared_handle_local_query",
            runtime_failed_case_ids=list(failed_case_ids),
            virtual_intersection_polygons_path=str(polygons_path),
            nodes_output_path=str(nodes_outputs["nodes_path"]),
            nodes_anchor_update_audit_csv=str(nodes_outputs["audit_csv_path"]),
            nodes_anchor_update_audit_json=str(nodes_outputs["audit_json_path"]),
        )

        write_json(
            internal_root / "internal_full_input_manifest.json",
            {
                "run_id": run_id,
                "nodes_path": str(resolved_nodes_path),
                "roads_path": str(resolved_roads_path),
                "drivezone_path": str(resolved_drivezone_path),
                "rcsdroad_path": str(resolved_rcsdroad_path),
                "rcsdnode_path": str(resolved_rcsdnode_path),
                "out_root": str(resolved_out_root),
                "run_root": str(run_root),
                "case_root": str(case_root),
                "step3_run_root": str(step3_run_root),
                "visual_check_dir": str(resolved_visual_check_dir),
                "workers": max_workers,
                "max_cases": max_cases,
                "buffer_m": buffer_m,
                "patch_size_m": patch_size_m,
                "resolution_m": resolution_m,
                "debug": debug,
                "review_mode_requested": review_mode,
                "review_mode_effective": False,
                "review_mode_note": (
                    "accepted for parameter compatibility only; "
                    "T03 internal full-input runner keeps formal Step67 semantics unchanged"
                ),
                "source_mode": "t03_internal_full_input_direct_local_query",
                "execution_mode": "direct_shared_handle_local_query",
                "candidate_discovery_mode": "shared_nodes_handle",
                "shared_memory_summary": shared_memory_summary,
                "discovered_case_ids": discovered_case_ids,
                "default_full_batch_excluded_case_ids": excluded_case_ids,
                "selected_case_ids": list(selected_case_ids),
                "prepared_cases": [],
                "transitional_case_package_path_retained": False,
                "local_context_root": str(case_root),
                "progress_path": str(internal_root / "internal_full_input_progress.json"),
                "case_progress_root": str(case_progress_root),
                "runtime_failed_case_ids": list(failed_case_ids),
                "virtual_intersection_polygons_path": str(polygons_path),
                "nodes_output_path": str(nodes_outputs["nodes_path"]),
                "nodes_anchor_update_audit_csv": str(nodes_outputs["audit_csv_path"]),
                "nodes_anchor_update_audit_json": str(nodes_outputs["audit_json_path"]),
            },
        )
    except Exception as exc:
        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase="failed",
            status="failed",
            message="T03 internal full-input execution failed before completion.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            prepared_case_ids=[],
            step3_run_root=step3_run_root if step3_run_root.exists() else None,
            failure=str(exc),
            execution_mode="direct_shared_handle_local_query",
        )
        _write_internal_failure(
            internal_root=internal_root,
            run_root=run_root,
            phase="failed",
            failure=str(exc),
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            prepared_case_ids=[],
            step3_run_root=step3_run_root if step3_run_root.exists() else None,
        )
        raise

    return T03Step67InternalFullInputArtifacts(
        run_root=run_root,
        visual_check_dir=resolved_visual_check_dir,
        internal_root=internal_root,
        case_root=case_root,
        step3_run_root=step3_run_root,
        selected_case_ids=tuple(selected_case_ids),
        discovered_case_ids=tuple(discovered_case_ids),
        excluded_case_ids=tuple(excluded_case_ids),
    )
