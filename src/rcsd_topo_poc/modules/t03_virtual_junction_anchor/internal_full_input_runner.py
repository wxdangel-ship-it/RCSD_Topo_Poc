from __future__ import annotations

import json
import shutil
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
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerFeature, read_vector_layer
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.batch_runner import (
    run_t03_step3_legal_space_batch,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import (
    DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_batch_runner import (
    run_t03_step67_batch,
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


def _load_shared_layers(
    *,
    nodes_path: Path,
    roads_path: Path,
    drivezone_path: Path,
    rcsdroad_path: Path,
    rcsdnode_path: Path,
) -> SharedFullInputLayers:
    return SharedFullInputLayers(
        nodes=tuple(read_vector_layer(nodes_path).features),
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
    case_root = internal_root / "case_packages"
    case_progress_root = internal_root / "case_progress"
    step3_out_root = internal_root / "step3_runs"

    if internal_root.exists():
        shutil.rmtree(internal_root)
    case_root.mkdir(parents=True, exist_ok=True)
    case_progress_root.mkdir(parents=True, exist_ok=True)
    step3_out_root.mkdir(parents=True, exist_ok=True)
    resolved_visual_check_dir.mkdir(parents=True, exist_ok=True)

    discovered_case_ids: list[str] = []
    excluded_case_ids = _stable_case_ids(list(DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS))
    selected_case_ids: list[str] = []
    prep_rows: list[dict[str, Any]] = []
    step3_run_root = step3_out_root / f"{run_id}__step3"
    max_workers = max(1, int(workers or 1))

    _write_internal_progress(
        internal_root=internal_root,
        run_root=run_root,
        phase="bootstrap",
        status="running",
        message="Loading shared full-input layers for T03 internal preparation.",
        selected_case_ids=[],
        discovered_case_ids=[],
        excluded_case_ids=excluded_case_ids,
    )

    try:
        shared_layers = _load_shared_layers(
            nodes_path=resolved_nodes_path,
            roads_path=resolved_roads_path,
            drivezone_path=resolved_drivezone_path,
            rcsdroad_path=resolved_rcsdroad_path,
            rcsdnode_path=resolved_rcsdnode_path,
        )
        discovered_case_ids = _discover_candidate_case_ids(shared_layers.nodes)
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
                reason="selected_for_step67_full_input",
                detail="eligible full-input candidate discovered and queued for T03 case-package preparation",
            )
        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase="candidate_selection",
            status="running",
            message="Selected full-input candidates for T03 Step67 internal execution.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
        )

        prep_failures: list[str] = []
        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase="case_package_prepare",
            status="running",
            message="Preparing T03-native case-packages from shared full-input sources.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
        )
        if max_workers == 1:
            for case_id in selected_case_ids:
                try:
                    prepared_row = _prepare_case_package(
                        case_id=case_id,
                        shared_layers=shared_layers,
                        buffer_m=buffer_m,
                        patch_size_m=patch_size_m,
                        resolution_m=resolution_m,
                        case_root=case_root,
                    )
                    prep_rows.append(prepared_row)
                    _write_internal_case_progress(
                        case_progress_root=case_progress_root,
                        case_id=case_id,
                        state="prepared",
                        current_stage="case_package_prepare",
                        reason="case_package_prepared",
                        detail=(
                            "T03-native case-package prepared with "
                            f"{prepared_row['bundle_size_bytes']} bytes"
                        ),
                        selected_counts=prepared_row["selected_counts"],
                    )
                except Exception as exc:
                    prep_failures.append(f"{case_id}: {exc}")
                    _write_internal_case_progress(
                        case_progress_root=case_progress_root,
                        case_id=case_id,
                        state="failed",
                        current_stage="case_package_prepare",
                        reason="case_package_prepare_failed",
                        detail=str(exc),
                    )
        else:
            futures = {}
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="t03-full-input") as executor:
                for case_id in selected_case_ids:
                    futures[
                        executor.submit(
                            _prepare_case_package,
                            case_id=case_id,
                            shared_layers=shared_layers,
                            buffer_m=buffer_m,
                            patch_size_m=patch_size_m,
                            resolution_m=resolution_m,
                            case_root=case_root,
                        )
                    ] = case_id
                for future in as_completed(futures):
                    case_id = futures[future]
                    try:
                        prepared_row = future.result()
                        prep_rows.append(prepared_row)
                        _write_internal_case_progress(
                            case_progress_root=case_progress_root,
                            case_id=case_id,
                            state="prepared",
                            current_stage="case_package_prepare",
                            reason="case_package_prepared",
                            detail=(
                                "T03-native case-package prepared with "
                                f"{prepared_row['bundle_size_bytes']} bytes"
                            ),
                            selected_counts=prepared_row["selected_counts"],
                        )
                    except Exception as exc:
                        prep_failures.append(f"{case_id}: {exc}")
                        _write_internal_case_progress(
                            case_progress_root=case_progress_root,
                            case_id=case_id,
                            state="failed",
                            current_stage="case_package_prepare",
                            reason="case_package_prepare_failed",
                            detail=str(exc),
                        )
        prep_rows.sort(key=lambda row: sort_patch_key(str(row["case_id"])))
        if prep_failures:
            _write_internal_progress(
                internal_root=internal_root,
                run_root=run_root,
                phase="case_package_prepare",
                status="failed",
                message="Failed to prepare one or more T03-native case-packages.",
                selected_case_ids=selected_case_ids,
                discovered_case_ids=discovered_case_ids,
                excluded_case_ids=excluded_case_ids,
                prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
                failures=prep_failures,
            )
            raise ValueError("Failed to prepare T03 full-input case-packages: " + " | ".join(prep_failures))

        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase="step3_batch",
            status="running",
            message="Running frozen T03 Step3 baseline on T03-native case-packages.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
        )
        step3_run_root = run_t03_step3_legal_space_batch(
            case_root=case_root,
            workers=max_workers,
            out_root=step3_out_root,
            run_id=f"{run_id}__step3",
            debug=debug,
        )
        for case_id in selected_case_ids:
            step3_status_path = step3_run_root / "cases" / case_id / "step3_status.json"
            if step3_status_path.is_file():
                step3_status_doc = json.loads(step3_status_path.read_text(encoding="utf-8"))
                _write_internal_case_progress(
                    case_progress_root=case_progress_root,
                    case_id=case_id,
                    state="step3_ready",
                    current_stage="step3_batch",
                    reason=str(step3_status_doc.get("reason") or step3_status_doc.get("step3_state") or "step3_ready"),
                    detail="step3 prerequisite outputs are ready for Step67 batch execution",
                    step3_state=step3_status_doc.get("step3_state"),
                )
            else:
                _write_internal_case_progress(
                    case_progress_root=case_progress_root,
                    case_id=case_id,
                    state="failed",
                    current_stage="step3_batch",
                    reason="step3_output_missing",
                    detail="step3_status.json was not written for the prepared case",
                )

        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase="step67_batch",
            status="running",
            message="Running T03 Step67 batch on top of T03-native case-packages and Step3 outputs.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
            step3_run_root=step3_run_root,
        )
        run_root = run_t03_step67_batch(
            case_root=case_root,
            step3_root=step3_run_root,
            workers=max_workers,
            out_root=resolved_out_root,
            run_id=run_id,
            debug=debug,
            debug_render=debug,
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
            message="T03 Step67 internal full-input execution completed.",
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
            step3_run_root=step3_run_root,
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
                "source_mode": "t03_native_full_input_prepare",
                "discovered_case_ids": discovered_case_ids,
                "default_full_batch_excluded_case_ids": excluded_case_ids,
                "selected_case_ids": list(selected_case_ids),
                "prepared_cases": prep_rows,
                "progress_path": str(internal_root / "internal_full_input_progress.json"),
                "case_progress_root": str(case_progress_root),
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
            prepared_case_ids=[str(row["case_id"]) for row in prep_rows],
            step3_run_root=step3_run_root if step3_run_root.exists() else None,
            failure=str(exc),
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
