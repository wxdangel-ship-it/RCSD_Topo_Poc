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
    QgsMarkerSymbol,
    QgsProject,
    QgsRectangle,
    QgsReferencedRectangle,
    QgsRendererCategory,
    QgsVectorLayer,
)

from .qgis_project import (
    LayerSpec,
    _csv_uri,
    _render_preview,
    _sha256,
    _symbolize,
    _transformed_extent,
    _validate_embedded_qgs,
    _write_manifest,
)


GROUPS = (
    ("00_三网显式对比", True, True),
    ("01_稳定中心锚点", True, True),
    ("02_M2扭曲基线", True, True),
    ("03_SWSD父语义", True, False),
    ("04_原始Lane与道路面", True, False),
    ("05_旧Patch Road与匹配审计", True, False),
    ("06_LaneTopo与路口连续性", True, True),
    ("09_几何与拓扑QA", True, True),
)


LAYERS = (
    LayerSpec("00_三网显式对比", "1｜原始SWSD Road（只读投影副本）", "_milestone2/_milestone1/p04_swsd_skeleton.gpkg", "road_sections", True, "#ff8f00", 1.8, 0.80),
    LayerSpec("00_三网显式对比", "2｜原始RCSD Road（只读投影副本）", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "current_rcsd_roads", True, "#0d47a1", 1.5, 0.78),
    LayerSpec("00_三网显式对比", "3｜新生成结果（Directional Road V2）", "p04_directional_roads.gpkg", "directional_roads", True, "#00bcd4", 2.5),
    LayerSpec("09_几何与拓扑QA", "Directional Portal", "p04_directional_road_graph.gpkg", "directional_portals", False, "#212121", 2.2),
    LayerSpec("09_几何与拓扑QA", "Directional Arm", "p04_directional_road_graph.gpkg", "directional_arms", False, "#37474f", 1.2),
    LayerSpec("01_稳定中心锚点", "稳定中心｜Lane/LaneBoundary", "p04_directional_lane_groups.gpkg", "stable_center_anchors", True, "#76ff03", 3.2),
    LayerSpec("01_稳定中心锚点", "方向 LaneGroup｜hard/soft", "p04_directional_lane_groups.gpkg", "lane_group_members", False, "#1565c0", 1.0, 0.70),
    LayerSpec("01_稳定中心锚点", "V2 完整来源分段｜HP/过渡/SD gap", "p04_directional_support_intervals.gpkg", "geometry_segments", True, "#00c853", 3.0),
    LayerSpec("01_稳定中心锚点", "V2 高精几何片段", "p04_directional_support_intervals.gpkg", "geometry_segments", False, "#00c853", 3.0, subset='"interval_state" = \'hp_supported\''),
    LayerSpec("02_M2扭曲基线", "M2 Road｜hp/partial", "_milestone2/p04_road_candidates.gpkg", "road_candidates", True, "#ff6d00", 1.7, 0.72, subset='"support_state" IN (\'hp_supported\', \'partial_hp_supported\')'),
    LayerSpec("02_M2扭曲基线", "M2 拟合站点", "_milestone2/p04_road_support_intervals.gpkg", "fit_stations", False, "#ff1744", 1.2, subset='"station_geometry_source" = \'hp_lane_median\''),
    LayerSpec("03_SWSD父语义", "SWSD Junction", "_milestone2/_milestone1/p04_swsd_skeleton.gpkg", "junctions", False, "#000000", 2.0),
    LayerSpec("04_原始Lane与道路面", "DriveZone_fix｜道路面", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "drivezone_fix", True, "#90caf9", 0.45, 0.18),
    LayerSpec("04_原始Lane与道路面", "DivStripZone_fix｜导流带", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "divstripzone_fix", False, "#ffeb3b", 0.7, 0.42),
    LayerSpec("04_原始Lane与道路面", "Lane｜原始", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "raw_lanes", False, "#1976d2", 0.65, 0.72),
    LayerSpec("04_原始Lane与道路面", "LaneBoundary｜原始", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "raw_lane_boundaries", False, "#616161", 0.45, 0.68),
    LayerSpec("05_旧Patch Road与匹配审计", "Patch Road/LaneGroup｜旧成果", "_milestone2/_milestone1/p04_qgis_comparison.gpkg", "old_patch_roads", True, "#5e35b1", 1.0, 0.68),
    LayerSpec("05_旧Patch Road与匹配审计", "V2—输入 RCSD 多段走廊审计", "p04_directional_current_rcsd_comparison.gpkg", "directional_rcsd_match", False, "#7b1fa2", 2.0, required=False),
    LayerSpec("06_LaneTopo与路口连续性", "Movement｜物理节点共点", "p04_directional_movements.gpkg", "directional_movements", True, "#00c853", 3.0, subset='"junction_relation" = \'same_physical_node\''),
    LayerSpec("06_LaneTopo与路口连续性", "Movement｜复杂语义路口连接", "p04_directional_movements.gpkg", "directional_movements", True, "#ffab00", 3.2, subset='"junction_relation" = \'same_semantic_junction\''),
    LayerSpec("06_LaneTopo与路口连续性", "LaneTopo｜确认投影明细", "p04_directional_movements.gpkg", "movement_evidence_links", False, "#64dd17", 1.2, 0.72, subset='"projection_state" = \'confirmed\''),
    LayerSpec("06_LaneTopo与路口连续性", "LaneTopo复核｜方向未确认", "p04_directional_movements.gpkg", "movement_evidence_links", True, "#ff6d00", 2.5, subset='"reason_codes" = \'input_direction_review_preserved\''),
    LayerSpec("06_LaneTopo与路口连续性", "LaneTopo复核｜语义不连通", "p04_directional_movements.gpkg", "movement_evidence_links", True, "#d50000", 2.8, subset='"reason_codes" = \'input_semantic_unconnected_review_preserved\''),
    LayerSpec("06_LaneTopo与路口连续性", "LaneTopo复核｜方向Road端点冲突", "p04_directional_movements.gpkg", "movement_evidence_links", True, "#aa00ff", 2.8, subset='"reason_codes" = \'directional_semantic_endpoint_conflict\''),
    LayerSpec("06_LaneTopo与路口连续性", "端点协调审计", "p04_directional_movements.gpkg", "endpoint_coordination_audit", False, "#ec407a", 2.0),
    LayerSpec("09_几何与拓扑QA", "拟合站点｜包络越界/SD保留/过渡", "p04_directional_support_intervals.gpkg", "fit_stations", False, "#ff9100", 1.5),
    LayerSpec("09_几何与拓扑QA", "双向证据塌缩｜已降级为纯SWSD", "p04_directional_lane_groups.gpkg", "cross_direction_quality_audit", True, "#d50000", 4.0, subset='"anchor_gate_pass" = 0'),
    LayerSpec("09_几何与拓扑QA", "长SD gap｜仅区间内不声明高精", "p04_directional_support_intervals.gpkg", "support_intervals", True, "#ff6d00", 3.5, subset='"directional_support_state" = \'partial_hp_supported\' AND "interval_state" = \'sd_gap\' AND "interval_length_m" >= "long_sd_gap_review_threshold_m"'),
    LayerSpec("09_几何与拓扑QA", "独立QA｜Road平滑异常", "p04_directional_independent_quality.gpkg", "road_smoothness_audit", True, "#d50000", 3.0, subset='"turn_gate_pass" = 0', required=False),
    LayerSpec("09_几何与拓扑QA", "独立QA｜物理Node断裂", "p04_directional_independent_quality.gpkg", "physical_node_audit", True, "#aa00ff", 3.2, subset='"gap_gate_pass" = 0', required=False),
    LayerSpec("09_几何与拓扑QA", "独立QA｜Movement接头异常", "p04_directional_independent_quality.gpkg", "movement_join_audit", True, "#ff1744", 3.0, subset='"join_gate_pass" = 0', required=False),
    LayerSpec("09_几何与拓扑QA", "独立QA｜双向高精间距异常", "p04_directional_independent_quality.gpkg", "direction_pair_audit", True, "#d50000", 4.5, subset='"direction_pair_gate_pass" = 0', required=False),
    LayerSpec("09_几何与拓扑QA", "几何审计表", "p04_directional_geometry_audit.csv", None, False, "#000000", 1.0, provider="delimitedtext"),
)


COMPARISON_ROLES = {
    "1｜原始SWSD Road（只读投影副本）": "original_swsd",
    "2｜原始RCSD Road（只读投影副本）": "original_rcsd",
    "3｜新生成结果（Directional Road V2）": "generated_directional_v2",
}


def build(package_root: str | Path) -> dict[str, Any]:
    root = Path(package_root).expanduser().resolve()
    summary = json.loads(
        (root / "p04_directional_v2_summary.json").read_text(encoding="utf-8")
    )
    gpkg_sources = sorted(
        {
            root / spec.relative_path
            for spec in LAYERS
            if spec.provider != "delimitedtext"
            and spec.relative_path.lower().endswith(".gpkg")
            and (root / spec.relative_path).is_file()
        }
    )
    source_modes = {path: stat.S_IMODE(path.stat().st_mode) for path in gpkg_sources}
    source_hashes_before = {path: _sha256(path) for path in gpkg_sources}
    for path, mode in source_modes.items():
        path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    app = QgsApplication([], False)
    app.initQgis()
    try:
        qa = _build_with_qgis(root, summary)
    finally:
        QgsProject.instance().clear()
        app.exitQgis()
        for path, mode in source_modes.items():
            path.chmod(mode)
    source_hash_changes = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path, before in source_hashes_before.items()
        if _sha256(path) != before
    )
    qa["qgis_source_read_only_guard"] = True
    qa["source_hash_changes"] = source_hash_changes
    qa["source_hashes_unchanged"] = not source_hash_changes
    if source_hash_changes:
        qa["errors"].append(
            "QGIS source hashes changed: " + ", ".join(source_hash_changes)
        )
        qa["status"] = "failed"
    (root / "p04_directional_qgis_project_qa.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return qa


def _build_with_qgis(root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    project_path = root / "p04_directional_v2_comparison.qgz"
    preview_path = root / "p04_directional_v2_comparison_preview.png"
    manifest_path = root / "p04_directional_qgis_layer_manifest.csv"
    qa_path = root / "p04_directional_qgis_project_qa.json"
    project = QgsProject.instance()
    project.clear()
    project.setFileName(str(project_path))
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    project.setCrs(QgsCoordinateReferenceSystem(summary["analysis_crs"]))
    project.setTitle("P04 三网显式对比｜原始SWSD / 原始RCSD / Directional Road V2")
    project.setCustomVariables(
        {
            "p04_run_id": summary["run_id"],
            "p04_status": summary["terminal_status"],
            "p04_pipeline_version": "p04_directional_road_v2",
            "p04_policy": "evidence-only directional fit; SWSD gap retained; LaneTopo movement; coordinated portals",
            "p04_analysis_crs": summary["analysis_crs"],
            "p04_comparison_order": "1 original_swsd; 2 original_rcsd; 3 generated_directional_v2",
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
    for index, spec in enumerate(LAYERS, start=1):
        path = root / spec.relative_path
        if not path.is_file():
            if spec.required:
                errors.append(f"missing source: {spec.relative_path}")
            continue
        source = _csv_uri(path) if spec.provider == "delimitedtext" else str(path) + (
            f"|layername={spec.layer_name}" if spec.layer_name else ""
        )
        layer = QgsVectorLayer(source, spec.name, spec.provider)
        if not layer.isValid():
            if spec.required:
                errors.append(f"invalid layer: {spec.name}")
            continue
        source_crs = layer.crs()
        crs_metadata_restored = False
        if spec.provider != "delimitedtext" and not source_crs.isValid():
            errors.append(f"invalid source CRS: {spec.name}")
        layer.setCustomProperty("p04/group", spec.group)
        layer.setCustomProperty("p04/relative_path", spec.relative_path)
        layer.setCustomProperty("p04/layer_name", spec.layer_name or "")
        layer.setCustomProperty("p04/stage_order", index)
        comparison_role = COMPARISON_ROLES.get(spec.name, "")
        if comparison_role:
            layer.setCustomProperty("p04/comparison_role", comparison_role)
        if spec.subset and not layer.setSubsetString(spec.subset):
            errors.append(f"subset rejected: {spec.name}")
        if (
            spec.provider != "delimitedtext"
            and source_crs.isValid()
            and not layer.crs().isValid()
        ):
            # QGIS/OGR can temporarily drop provider CRS metadata after a subset is
            # applied. Restore only the already validated source CRS and record it.
            layer.setCrs(source_crs)
            layer.setCustomProperty("p04/crs_metadata_restored_after_subset", True)
            crs_metadata_restored = True
        if spec.provider != "delimitedtext":
            if spec.name == "3｜新生成结果（Directional Road V2）":
                _symbolize_directional_roads(layer)
            elif spec.name == "稳定中心｜Lane/LaneBoundary":
                _symbolize_stable_center_anchors(layer)
            elif spec.name == "方向 LaneGroup｜hard/soft":
                _symbolize_lane_group_members(layer)
            elif spec.name == "拟合站点｜包络越界/SD保留/过渡":
                _symbolize_fit_station_qa(layer)
            elif spec.name == "V2 完整来源分段｜HP/过渡/SD gap":
                _symbolize_geometry_segments(layer)
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
                "comparison_role": comparison_role,
                "crs_metadata_restored_after_subset": crs_metadata_restored,
                "source_sha256": _sha256(path),
            }
        )
    if not has_extent:
        errors.append("no spatial extent available")
    else:
        combined_extent.scale(1.04)
        project.viewSettings().setDefaultViewExtent(
            QgsReferencedRectangle(combined_extent, project.crs())
        )
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
    invalid_layers = sorted(
        layer.name() for layer in read_project.mapLayers().values() if not layer.isValid()
    )
    if invalid_layers:
        errors.append("invalid readback layers: " + ", ".join(invalid_layers))
    spatial_crs_mismatches = sorted(
        f"{layer.name()}:{layer.crs().authid() or '<empty>'}"
        for layer in read_project.mapLayers().values()
        if layer.isValid()
        and layer.isSpatial()
        and layer.crs().authid() != read_project.crs().authid()
    )
    if spatial_crs_mismatches:
        errors.append("spatial readback CRS mismatch: " + ", ".join(spatial_crs_mismatches))
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
        child.name() for child in read_project.layerTreeRoot().children() if hasattr(child, "name")
    ]
    missing_groups = [name for name, _, _ in GROUPS if name not in group_names]
    if missing_groups:
        errors.append("missing groups: " + ", ".join(missing_groups))
    qa = {
        "status": "passed" if not errors else "failed",
        "run_id": summary["run_id"],
        "qgis_version": Qgis.QGIS_VERSION,
        "project_path": str(project_path),
        "project_crs": read_project.crs().authid() if read_ok else None,
        "file_path_storage": "relative",
        "layer_count_configured": len(LAYERS),
        "layer_count_loaded": len(read_project.mapLayers()) if read_ok else 0,
        "group_count_expected": len(GROUPS),
        "group_names": group_names,
        "project_write_ok": write_ok,
        "project_readback_ok": read_ok,
        "embedded_qgs_xml_parse_ok": xml_ok,
        "invalid_readback_layers": invalid_layers,
        "spatial_readback_crs_mismatches": spatial_crs_mismatches,
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


def _symbolize_lane_group_members(layer: QgsVectorLayer) -> None:
    categories: list[QgsRendererCategory] = []
    for value, label, color, width, opacity in (
        ("hard_member", "usable hard member", "#1565c0", 1.0, 0.70),
        ("soft_review", "review / insufficient", "#9e9e9e", 0.8, 0.50),
        ("topology_only_review", "collapse review; LaneTopo lineage only", "#d50000", 1.4, 0.80),
    ):
        symbol = QgsLineSymbol.createSimple(
            {
                "line_color": color,
                "line_width": str(width),
                "capstyle": "round",
                "joinstyle": "round",
            }
        )
        symbol.setOpacity(opacity)
        categories.append(QgsRendererCategory(value, symbol, label))
    layer.setRenderer(QgsCategorizedSymbolRenderer("geometry_role", categories))


def _symbolize_directional_roads(layer: QgsVectorLayer) -> None:
    categories: list[QgsRendererCategory] = []
    for value, label, color, width, opacity in (
        ("forward", "forward single-direction Road", "#00bcd4", 2.5, 1.0),
        ("reverse", "reverse single-direction Road", "#e91e63", 2.5, 1.0),
        ("sd_parent", "pure sd parent", "#78909c", 1.3, 0.65),
    ):
        symbol = QgsLineSymbol.createSimple(
            {
                "line_color": color,
                "line_width": str(width),
                "capstyle": "round",
                "joinstyle": "round",
            }
        )
        symbol.setOpacity(opacity)
        categories.append(QgsRendererCategory(value, symbol, label))
    layer.setRenderer(QgsCategorizedSymbolRenderer("travel_side", categories))


def _symbolize_geometry_segments(layer: QgsVectorLayer) -> None:
    categories: list[QgsRendererCategory] = []
    for value, label, color, width, opacity, style in (
        ("hp_supported", "high precision supported", "#00c853", 3.2, 1.0, "solid"),
        ("transition", "audited HP to SWSD transition", "#ffab00", 2.6, 0.95, "dash"),
        ("sd_gap", "SWSD retained gap; no HP claim", "#78909c", 2.0, 0.72, "dash"),
    ):
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
    layer.setRenderer(QgsCategorizedSymbolRenderer("interval_state", categories))


def _symbolize_stable_center_anchors(layer: QgsVectorLayer) -> None:
    categories: list[QgsRendererCategory] = []
    for value, label, color in (
        ("lane", "stable center Lane", "#76ff03"),
        ("lane_boundary", "shared center LaneBoundary", "#ffea00"),
    ):
        symbol = QgsLineSymbol.createSimple(
            {
                "line_color": color,
                "line_width": "3.2",
                "capstyle": "round",
                "joinstyle": "round",
            }
        )
        categories.append(QgsRendererCategory(value, symbol, label))
    layer.setRenderer(QgsCategorizedSymbolRenderer("anchor_kind", categories))


def _symbolize_fit_station_qa(layer: QgsVectorLayer) -> None:
    categories: list[QgsRendererCategory] = []
    for value, label, color, size in (
        ("violation", "LaneGroup envelope violation", "#d50000", 3.0),
        ("sd_gap_retained", "unsupported gap retained on SWSD", "#78909c", 1.5),
        ("hp_transition", "audited HP to SWSD transition", "#ff9100", 1.8),
    ):
        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": color,
                "size": str(size),
                "outline_color": "#ffffff",
            }
        )
        categories.append(QgsRendererCategory(value, symbol, label))
    expression = (
        "CASE WHEN \"envelope_violation\" = 1 THEN 'violation' "
        "WHEN \"station_geometry_source\" = "
        "'swsd_gap_retained' THEN 'sd_gap_retained' "
        "WHEN \"station_geometry_source\" = "
        "'directional_transition_supported' THEN 'hp_transition' "
        "ELSE 'other' END"
    )
    layer.setRenderer(QgsCategorizedSymbolRenderer(expression, categories))


__all__ = ["build"]
