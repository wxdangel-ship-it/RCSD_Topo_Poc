from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsLineSymbol,
    QgsProject,
    QgsRectangle,
    QgsReferencedRectangle,
    QgsRendererCategory,
    QgsVectorLayer,
)

from .qgis_project import (
    LayerSpec,
    _render_preview,
    _sha256,
    _symbolize,
    _transformed_extent,
    _validate_embedded_qgs,
    _write_manifest,
)


GROUPS = (
    ("00_四网显式对比", True, True),
    ("01_V3高精骨架来源", True, True),
    ("02_物理走廊与中心证据", True, True),
    ("03_LaneTopo与RoadGraph", True, True),
    ("04_原始基础资料", True, False),
    ("09_独立质量审计", True, True),
)


COMPARISON_ROLES = {
    "1｜原始SWSD Road": "original_swsd",
    "2｜原始RCSD Road": "original_rcsd",
    "3｜冻结Directional V2（638 Road）": "frozen_directional_v2",
    "4｜High-Precision Road V3": "generated_high_precision_v3",
}


def build(package_root: str | Path) -> dict[str, Any]:
    root = Path(package_root).expanduser().resolve()
    summary = json.loads((root / "p04_hp_v3_summary.json").read_text(encoding="utf-8"))
    layers = _layers(root, summary)
    gpkg_sources = sorted(
        {
            (root / spec.relative_path).resolve()
            for spec in layers
            if spec.relative_path.lower().endswith(".gpkg")
            and (root / spec.relative_path).is_file()
        }
    )
    source_modes = {path: stat.S_IMODE(path.stat().st_mode) for path in gpkg_sources}
    source_hashes = {path: _sha256(path) for path in gpkg_sources}
    for path, mode in source_modes.items():
        path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    app = QgsApplication([], False)
    app.initQgis()
    try:
        qa = _build_with_qgis(root, summary, layers)
    finally:
        QgsProject.instance().clear()
        app.exitQgis()
        for path, mode in source_modes.items():
            path.chmod(mode)
    changes = sorted(
        str(path)
        for path, before in source_hashes.items()
        if _sha256(path) != before
    )
    qa["qgis_source_read_only_guard"] = True
    qa["source_hash_changes"] = changes
    qa["source_hashes_unchanged"] = not changes
    if changes:
        qa["errors"].append("QGIS source hashes changed: " + ", ".join(changes))
        qa["status"] = "failed"
    (root / "p04_hp_v3_qgis_project_qa.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return qa


def _layers(
    root: Path,
    summary: dict[str, Any],
) -> tuple[LayerSpec, ...]:
    frozen_root = Path(summary["frozen_v2"]["root"]).resolve()
    frozen_rel = Path(os.path.relpath(frozen_root, root)).as_posix()
    return (
        LayerSpec("00_四网显式对比", "1｜原始SWSD Road", "_milestone2/_milestone1/p04_swsd_skeleton.gpkg", "road_sections", True, "#ff8f00", 1.8, 0.80),
        LayerSpec("00_四网显式对比", "2｜原始RCSD Road", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "current_rcsd_roads", True, "#0d47a1", 1.5, 0.76),
        LayerSpec("00_四网显式对比", "3｜冻结Directional V2（638 Road）", f"{frozen_rel}/p04_directional_roads.gpkg", "directional_roads", True, "#ab47bc", 1.8, 0.75),
        LayerSpec("00_四网显式对比", "4｜High-Precision Road V3", "p04_hp_v3_roads.gpkg", "high_precision_roads", True, "#00c853", 2.8, 1.0),
        LayerSpec("01_V3高精骨架来源", "V3 完整来源分段｜观测/约束/SD", "p04_hp_v3_geometry_sources.gpkg", "geometry_segments", True, "#00c853", 3.2),
        LayerSpec("01_V3高精骨架来源", "中心观测点｜仅直接Lane证据", "p04_hp_v3_corridors.gpkg", "center_observations", False, "#76ff03", 2.0),
        LayerSpec("01_V3高精骨架来源", "拟合站点｜来源明细", "p04_hp_v3_geometry_sources.gpkg", "fit_stations", False, "#ff9100", 1.5),
        LayerSpec("02_物理走廊与中心证据", "物理走廊决策｜split/shared/fallback", "p04_hp_v3_corridors.gpkg", "physical_corridor_decisions", True, "#26a69a", 2.0),
        LayerSpec("02_物理走廊与中心证据", "稳定中心基准", "p04_hp_v3_corridors.gpkg", "center_anchors", True, "#64dd17", 3.0),
        LayerSpec("02_物理走廊与中心证据", "LaneGroup成员｜hard/review", "p04_hp_v3_corridors.gpkg", "lane_group_members", False, "#1976d2", 0.9, 0.62),
        LayerSpec("03_LaneTopo与RoadGraph", "Road Movement｜物理节点", "p04_hp_v3_movements.gpkg", "high_precision_movements", True, "#00c853", 3.0, subset='"junction_relation" = \'same_physical_node\''),
        LayerSpec("03_LaneTopo与RoadGraph", "Road Movement｜语义路口", "p04_hp_v3_movements.gpkg", "high_precision_movements", True, "#ffab00", 3.0, subset='"junction_relation" = \'same_semantic_junction\''),
        LayerSpec("03_LaneTopo与RoadGraph", "LaneTopo｜confirmed", "p04_hp_v3_movements.gpkg", "movement_evidence_links", False, "#64dd17", 1.2, 0.72, subset='"projection_state" = \'confirmed\''),
        LayerSpec("03_LaneTopo与RoadGraph", "LaneTopo｜review", "p04_hp_v3_movements.gpkg", "movement_evidence_links", True, "#d50000", 2.4, subset='"projection_state" = \'review\''),
        LayerSpec("03_LaneTopo与RoadGraph", "Road Portal", "p04_hp_v3_road_graph.gpkg", "high_precision_portals", False, "#212121", 2.0),
        LayerSpec("03_LaneTopo与RoadGraph", "Road Arm", "p04_hp_v3_road_graph.gpkg", "high_precision_arms", False, "#37474f", 1.2),
        LayerSpec("04_原始基础资料", "DriveZone_fix｜道路面", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "drivezone_fix", True, "#90caf9", 0.45, 0.18),
        LayerSpec("04_原始基础资料", "DivStripZone_fix｜导流带", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "divstripzone_fix", False, "#ffeb3b", 0.7, 0.42),
        LayerSpec("04_原始基础资料", "Lane｜原始", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "raw_lanes", False, "#1976d2", 0.65, 0.72),
        LayerSpec("04_原始基础资料", "LaneBoundary｜原始", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "raw_lane_boundaries", False, "#616161", 0.45, 0.68),
        LayerSpec("04_原始基础资料", "旧Patch Road/LaneGroup", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "old_patch_roads", False, "#5e35b1", 1.0, 0.68),
        LayerSpec("09_独立质量审计", "QA｜Road平滑异常", "p04_hp_v3_independent_quality.gpkg", "road_smoothness_audit", True, "#d50000", 3.0, subset='"turn_gate_pass" = 0'),
        LayerSpec("09_独立质量审计", "QA｜物理Node断裂", "p04_hp_v3_independent_quality.gpkg", "physical_node_audit", True, "#aa00ff", 3.2, subset='"gap_gate_pass" = 0'),
        LayerSpec("09_独立质量审计", "QA｜Movement接头异常", "p04_hp_v3_independent_quality.gpkg", "movement_join_audit", True, "#ff1744", 3.0, subset='"join_gate_pass" = 0'),
        LayerSpec("09_独立质量审计", "QA｜来源分段异常", "p04_hp_v3_independent_quality.gpkg", "geometry_source_audit", True, "#ff1744", 3.0, subset='"partition_pass" = 0 OR "declaration_pass" = 0 OR "unbacked_observed_segment_count" > 0'),
        LayerSpec("09_独立质量审计", "QA｜物理走廊拆分异常", "p04_hp_v3_independent_quality.gpkg", "corridor_split_audit", True, "#d50000", 4.0, subset='"split_gate_pass" = 0'),
    )


def _build_with_qgis(
    root: Path,
    summary: dict[str, Any],
    layers: tuple[LayerSpec, ...],
) -> dict[str, Any]:
    project_path = root / "p04_hp_v3_four_network_comparison.qgz"
    preview_path = root / "p04_hp_v3_four_network_preview.png"
    manifest_path = root / "p04_hp_v3_qgis_layer_manifest.csv"
    qa_path = root / "p04_hp_v3_qgis_project_qa.json"
    project = QgsProject.instance()
    project.clear()
    project.setFileName(str(project_path))
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    project.setCrs(QgsCoordinateReferenceSystem(summary["analysis_crs"]))
    project.setTitle("P04 四网对比｜SWSD / RCSD / 冻结V2 / 高精骨架V3")
    project.setCustomVariables(
        {
            "p04_run_id": summary["run_id"],
            "p04_status": summary["terminal_status"],
            "p04_pipeline_version": "p04_high_precision_road_v3",
            "p04_geometry_policy": "SWSD semantic ownership; HP observed or constrained geometry; explicit SWSD fallback",
            "p04_frozen_v2": summary["frozen_v2"]["run_id"],
            "p04_comparison_order": "1 original_swsd; 2 original_rcsd; 3 frozen_v2; 4 generated_v3",
        }
    )
    tree = project.layerTreeRoot()
    groups: dict[str, Any] = {}
    for name, checked, expanded in GROUPS:
        group = tree.addGroup(name)
        group.setItemVisibilityChecked(checked)
        group.setExpanded(expanded)
        groups[name] = group

    errors: list[str] = []
    manifest_rows: list[dict[str, Any]] = []
    combined_extent = QgsRectangle()
    has_extent = False
    for index, spec in enumerate(layers, start=1):
        path = root / spec.relative_path
        if not path.is_file():
            if spec.required:
                errors.append(f"missing source: {spec.relative_path}")
            continue
        source = str(path) + (f"|layername={spec.layer_name}" if spec.layer_name else "")
        layer = QgsVectorLayer(source, spec.name, spec.provider)
        if not layer.isValid():
            if spec.required:
                errors.append(f"invalid layer: {spec.name}")
            continue
        source_crs = layer.crs()
        if not source_crs.isValid():
            errors.append(f"invalid source CRS: {spec.name}")
        layer.setCustomProperty("p04/group", spec.group)
        layer.setCustomProperty("p04/relative_path", spec.relative_path)
        layer.setCustomProperty("p04/layer_name", spec.layer_name or "")
        layer.setCustomProperty("p04/stage_order", index)
        role = COMPARISON_ROLES.get(spec.name, "")
        if role:
            layer.setCustomProperty("p04/comparison_role", role)
        if spec.subset and not layer.setSubsetString(spec.subset):
            errors.append(f"subset rejected: {spec.name}")
        if source_crs.isValid() and not layer.crs().isValid():
            layer.setCrs(source_crs)
            layer.setCustomProperty("p04/crs_metadata_restored_after_subset", True)
        if spec.name == "4｜High-Precision Road V3":
            _symbolize_v3_roads(layer)
        elif spec.name == "3｜冻结Directional V2（638 Road）":
            _symbolize_v2_roads(layer)
        elif spec.name == "V3 完整来源分段｜观测/约束/SD":
            _symbolize_sources(layer)
        elif spec.name == "物理走廊决策｜split/shared/fallback":
            _symbolize_corridor_decisions(layer)
        else:
            _symbolize(layer, spec.color, spec.width_or_size, spec.opacity)
        project.addMapLayer(layer, False)
        node = groups[spec.group].addLayer(layer)
        node.setItemVisibilityChecked(spec.visible)
        extent = _transformed_extent(layer, project)
        if extent is not None:
            if has_extent:
                combined_extent.combineExtentWith(extent)
            else:
                combined_extent = QgsRectangle(extent)
                has_extent = True
        manifest_rows.append(
            {
                "group": spec.group,
                "layer_name": spec.name,
                "relative_path": spec.relative_path,
                "gpkg_layer": spec.layer_name,
                "provider": spec.provider,
                "feature_count": layer.featureCount(),
                "crs": layer.crs().authid() or layer.crs().toWkt(),
                "visible_by_default": spec.visible,
                "subset": spec.subset,
                "comparison_role": role,
                "source_sha256": _sha256(path),
            }
        )
    if has_extent:
        combined_extent.scale(1.04)
        project.viewSettings().setDefaultViewExtent(
            QgsReferencedRectangle(combined_extent, project.crs())
        )
    else:
        errors.append("no spatial extent available")
    _write_manifest(manifest_path, manifest_rows)
    write_ok = project.write(str(project_path))
    if not write_ok:
        errors.append("QGIS project write failed")
    render_ok = _render_preview(project, combined_extent, preview_path) if has_extent else False
    if not render_ok:
        errors.append("preview render failed")

    read_project = QgsProject()
    read_ok = read_project.read(str(project_path)) if project_path.is_file() else False
    if not read_ok:
        errors.append("QGIS project readback failed")
    invalid = sorted(
        layer.name() for layer in read_project.mapLayers().values() if not layer.isValid()
    )
    if invalid:
        errors.append("invalid readback layers: " + ", ".join(invalid))
    crs_mismatches = sorted(
        f"{layer.name()}:{layer.crs().authid() or '<empty>'}"
        for layer in read_project.mapLayers().values()
        if layer.isValid()
        and layer.isSpatial()
        and layer.crs().authid() != read_project.crs().authid()
    )
    if crs_mismatches:
        errors.append("spatial readback CRS mismatch: " + ", ".join(crs_mismatches))
    missing_sources = sorted(
        {
            str(layer.customProperty("p04/relative_path", ""))
            for layer in read_project.mapLayers().values()
            if str(layer.customProperty("p04/relative_path", ""))
            and not (root / str(layer.customProperty("p04/relative_path", ""))).is_file()
        }
    )
    if missing_sources:
        errors.append("missing readback sources: " + ", ".join(missing_sources))
    xml_ok, absolute_count = _validate_embedded_qgs(project_path)
    if not xml_ok:
        errors.append("embedded QGS XML parse failed")
    if absolute_count:
        errors.append(f"absolute datasource references found: {absolute_count}")
    group_names = [
        child.name()
        for child in read_project.layerTreeRoot().children()
        if hasattr(child, "name")
    ]
    missing_groups = [name for name, _, _ in GROUPS if name not in group_names]
    if missing_groups:
        errors.append("missing groups: " + ", ".join(missing_groups))
    comparison_roles = sorted(
        str(layer.customProperty("p04/comparison_role", ""))
        for layer in read_project.mapLayers().values()
        if str(layer.customProperty("p04/comparison_role", ""))
    )
    if comparison_roles != sorted(COMPARISON_ROLES.values()):
        errors.append("four-network comparison roles incomplete")
    qa = {
        "status": "passed" if not errors else "failed",
        "run_id": summary["run_id"],
        "qgis_version": Qgis.QGIS_VERSION,
        "project_path": str(project_path),
        "project_crs": read_project.crs().authid() if read_ok else None,
        "file_path_storage": "relative",
        "layer_count_configured": len(layers),
        "layer_count_loaded": len(read_project.mapLayers()) if read_ok else 0,
        "comparison_roles": comparison_roles,
        "group_names": group_names,
        "project_write_ok": write_ok,
        "project_readback_ok": read_ok,
        "embedded_qgs_xml_parse_ok": xml_ok,
        "invalid_readback_layers": invalid,
        "spatial_readback_crs_mismatches": crs_mismatches,
        "missing_readback_sources": missing_sources,
        "absolute_datasource_reference_count": absolute_count,
        "preview_render_ok": render_ok,
        "manifest_row_count": len(manifest_rows),
        "errors": errors,
        "outputs": {
            "project": str(project_path),
            "preview": str(preview_path),
            "layer_manifest": str(manifest_path),
            "qa": str(qa_path),
        },
    }
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    read_project.clear()
    QgsApplication.processEvents()
    return qa


def _categories(
    field: str,
    values: tuple[tuple[str, str, str, float, float, str], ...],
) -> QgsCategorizedSymbolRenderer:
    categories: list[QgsRendererCategory] = []
    for value, label, color, width, opacity, style in values:
        symbol = QgsLineSymbol.createSimple(
            {
                "line_color": color,
                "line_width": str(width),
                "line_style": style,
                "capstyle": "round",
                "joinstyle": "round",
            }
        )
        symbol.setOpacity(opacity)
        categories.append(QgsRendererCategory(value, symbol, label))
    return QgsCategorizedSymbolRenderer(field, categories)


def _symbolize_v3_roads(layer: QgsVectorLayer) -> None:
    layer.setRenderer(
        _categories(
            "support_state",
            (
                ("hp_supported", "完全高精证据", "#00c853", 3.2, 1.0, "solid"),
                ("partial_hp_supported", "部分高精证据", "#00b8d4", 2.8, 1.0, "solid"),
                ("sd_only", "无高精证据｜SWSD fallback", "#78909c", 1.8, 0.72, "dash"),
                ("conflict_retained", "高精与语义冲突保留", "#d50000", 3.2, 1.0, "dash"),
            ),
        )
    )


def _symbolize_v2_roads(layer: QgsVectorLayer) -> None:
    layer.setRenderer(
        _categories(
            "travel_side",
            (
                ("forward", "V2 forward", "#ab47bc", 2.0, 0.78, "solid"),
                ("reverse", "V2 reverse", "#ec407a", 2.0, 0.78, "solid"),
                ("sd_parent", "V2 sd_parent", "#8d6e63", 1.3, 0.62, "dash"),
            ),
        )
    )


def _symbolize_sources(layer: QgsVectorLayer) -> None:
    layer.setRenderer(
        _categories(
            "geometry_source",
            (
                ("hp_observed", "直接高精观测", "#00c853", 3.4, 1.0, "solid"),
                ("hp_constrained_interpolation", "受约束高精补全", "#ffab00", 2.8, 0.95, "dash"),
                ("swsd_fallback", "SWSD fallback", "#78909c", 2.0, 0.72, "dash"),
            ),
        )
    )


def _symbolize_corridor_decisions(layer: QgsVectorLayer) -> None:
    layer.setRenderer(
        _categories(
            "decision",
            (
                ("split", "物理双走廊证据成立", "#00c853", 3.0, 0.9, "solid"),
                ("shared", "共享物理Road", "#00b8d4", 2.4, 0.8, "solid"),
                ("fallback", "无高精走廊证据", "#78909c", 1.8, 0.65, "dash"),
            ),
        )
    )


__all__ = ["build"]
