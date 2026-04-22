from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
    sort_patch_key,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step2_local_context import _load_layer
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import (
    _parse_nodes,
    _parse_rc_nodes,
    _parse_roads,
    _resolve_group,
)

from .case_models import T04CaseBundle, T04CaseSpec


REQUIRED_CASE_FILES = (
    "manifest.json",
    "size_report.json",
    "drivezone.gpkg",
    "divstripzone.gpkg",
    "nodes.gpkg",
    "roads.gpkg",
    "rcsdroad.gpkg",
    "rcsdnode.gpkg",
)


def _stable_case_sort_key(value: str) -> tuple[int, int | str]:
    return sort_patch_key(value)


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _validate_manifest(case_root: Path, manifest: dict[str, Any], size_report: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    manifest_file_list = {str(item) for item in manifest.get("file_list") or []}
    actual_files = {path.name for path in case_root.iterdir() if path.is_file()}
    required_files = set(REQUIRED_CASE_FILES)
    missing_required = sorted(required_files - actual_files)
    if missing_required:
        issues.append(f"missing_required_files={','.join(missing_required)}")
    missing_from_manifest = sorted(required_files - manifest_file_list)
    if missing_from_manifest:
        issues.append(f"manifest_missing_files={','.join(missing_from_manifest)}")
    if int(manifest.get("bundle_version") or 0) != 1:
        issues.append(f"bundle_version={manifest.get('bundle_version')!r}")
    if int(manifest.get("epsg") or 0) != 3857:
        issues.append(f"manifest_epsg={manifest.get('epsg')!r}")
    decoded_output = manifest.get("decoded_output") or {}
    if str(decoded_output.get("vector_crs") or "") != "EPSG:3857":
        issues.append(f"decoded_vector_crs={decoded_output.get('vector_crs')!r}")
    if bool(size_report.get("within_limit")) is not True:
        issues.append(f"within_limit={size_report.get('within_limit')!r}")
    return issues


def load_case_specs(
    *,
    case_root: str | Path,
    case_ids: list[str] | None = None,
    max_cases: int | None = None,
) -> tuple[list[T04CaseSpec], dict[str, Any]]:
    resolved_case_root = normalize_runtime_path(case_root)
    if not resolved_case_root.is_dir():
        raise ValueError(f"case root does not exist: {resolved_case_root}")

    selected_case_ids = {str(case_id) for case_id in case_ids or []}
    raw_case_dirs = [
        path
        for path in resolved_case_root.iterdir()
        if path.is_dir() and path.name not in {"out", "renders"}
    ]
    sorted_case_dirs = sorted(raw_case_dirs, key=lambda path: _stable_case_sort_key(path.name))

    specs: list[T04CaseSpec] = []
    preflight_rows: list[dict[str, Any]] = []
    for case_dir in sorted_case_dirs:
        case_id = str(case_dir.name)
        if selected_case_ids and case_id not in selected_case_ids:
            continue
        manifest = _read_json(case_dir / "manifest.json")
        size_report = _read_json(case_dir / "size_report.json")
        issues = _validate_manifest(case_dir, manifest, size_report)
        preflight_rows.append(
            {
                "case_id": case_id,
                "case_root": str(case_dir),
                "issues": issues,
            }
        )
        if issues:
            raise ValueError(f"invalid case-package for case_id={case_id}: {issues}")
        specs.append(
            T04CaseSpec(
                case_id=case_id,
                mainnodeid=str(manifest.get("mainnodeid") or case_id),
                case_root=case_dir,
                manifest=manifest,
                size_report=size_report,
                input_paths={
                    "manifest_path": case_dir / "manifest.json",
                    "size_report_path": case_dir / "size_report.json",
                    "drivezone_path": case_dir / "drivezone.gpkg",
                    "divstripzone_path": case_dir / "divstripzone.gpkg",
                    "nodes_path": case_dir / "nodes.gpkg",
                    "roads_path": case_dir / "roads.gpkg",
                    "rcsdroad_path": case_dir / "rcsdroad.gpkg",
                    "rcsdnode_path": case_dir / "rcsdnode.gpkg",
                },
            )
        )
        if max_cases is not None and len(specs) >= max_cases:
            break

    preflight_doc = {
        "case_root": str(resolved_case_root),
        "raw_case_count": len(sorted_case_dirs),
        "raw_case_ids": [path.name for path in sorted_case_dirs],
        "selected_case_count": len(specs),
        "selected_case_ids": [spec.case_id for spec in specs],
        "missing_case_ids": [],
        "failed_case_ids": [],
        "rows": preflight_rows,
    }
    return specs, preflight_doc


def load_case_bundle(case_spec: T04CaseSpec) -> T04CaseBundle:
    nodes_layer_data = _load_layer(case_spec.input_paths["nodes_path"], layer_name=None, crs_override=None, allow_null_geometry=False)
    roads_layer_data = _load_layer(case_spec.input_paths["roads_path"], layer_name=None, crs_override=None, allow_null_geometry=False)
    drivezone_layer_data = _load_layer(case_spec.input_paths["drivezone_path"], layer_name=None, crs_override=None, allow_null_geometry=False)
    divstrip_layer_data = _load_layer(case_spec.input_paths["divstripzone_path"], layer_name=None, crs_override=None, allow_null_geometry=False)
    rcsdroad_layer_data = _load_layer(case_spec.input_paths["rcsdroad_path"], layer_name=None, crs_override=None, allow_null_geometry=False)
    rcsdnode_layer_data = _load_layer(case_spec.input_paths["rcsdnode_path"], layer_name=None, crs_override=None, allow_null_geometry=False)

    nodes = tuple(_parse_nodes(nodes_layer_data, require_anchor_fields=True))
    roads = tuple(_parse_roads(roads_layer_data, label="Road"))
    rcsd_roads = tuple(_parse_roads(rcsdroad_layer_data, label="RCSDRoad"))
    rcsd_nodes = tuple(_parse_rc_nodes(rcsdnode_layer_data))
    representative_node, group_nodes = _resolve_group(mainnodeid=case_spec.mainnodeid, nodes=list(nodes))

    return T04CaseBundle(
        case_spec=case_spec,
        nodes=nodes,
        roads=roads,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        drivezone_features=tuple(drivezone_layer_data.features),
        divstrip_features=tuple(divstrip_layer_data.features),
        representative_node=representative_node,
        group_nodes=tuple(group_nodes),
    )
