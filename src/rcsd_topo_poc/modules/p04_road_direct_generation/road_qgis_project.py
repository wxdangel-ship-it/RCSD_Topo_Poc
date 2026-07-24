from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsRectangle,
    QgsReferencedRectangle,
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
    ("00_本轮RoadGraph", True, True),
    ("01_高精支持与SD缺口", True, True),
    ("02_SWSD语义骨架", True, False),
    ("03_LaneEvidenceSegment", False, False),
    ("04_道路面与原始Vector", True, False),
    ("05_旧Road与当前RCSD对照", True, False),
    ("09_QA与拒绝拟合", True, True),
)


LAYERS = (
    LayerSpec("00_本轮RoadGraph", "Road｜hp_supported", "p04_road_candidates.gpkg", "road_candidates", True, "#00a651", 2.2, subset='"support_state" = \'hp_supported\''),
    LayerSpec("00_本轮RoadGraph", "Road｜partial_hp_supported", "p04_road_candidates.gpkg", "road_candidates", True, "#ff9800", 2.0, subset='"support_state" = \'partial_hp_supported\''),
    LayerSpec("00_本轮RoadGraph", "Road｜sd_only", "p04_road_candidates.gpkg", "road_candidates", True, "#607d8b", 1.5, 0.75, subset='"support_state" = \'sd_only\''),
    LayerSpec("00_本轮RoadGraph", "Road｜conflict_retained", "p04_road_candidates.gpkg", "road_candidates", True, "#d50000", 3.0, subset='"support_state" = \'conflict_retained\''),
    LayerSpec("01_高精支持与SD缺口", "几何片段｜hp_fitted", "p04_road_support_intervals.gpkg", "candidate_geometry_segments", True, "#00c853", 3.0, subset='"geometry_source" = \'hp_fitted\''),
    LayerSpec("01_高精支持与SD缺口", "几何片段｜swsd_retained", "p04_road_support_intervals.gpkg", "candidate_geometry_segments", True, "#78909c", 1.4, 0.75, subset='"geometry_source" = \'swsd_retained\''),
    LayerSpec("01_高精支持与SD缺口", "拟合站点｜hp_lane_median", "p04_road_support_intervals.gpkg", "fit_stations", False, "#00e676", 1.2, subset='"station_geometry_source" = \'hp_lane_median\''),
    LayerSpec("02_SWSD语义骨架", "SWSD RoadSection｜原始参考", "_milestone1/p04_swsd_skeleton.gpkg", "road_sections", True, "#212121", 0.8, 0.70),
    LayerSpec("02_SWSD语义骨架", "SWSD Junction", "_milestone1/p04_swsd_skeleton.gpkg", "junctions", False, "#000000", 2.0),
    LayerSpec("02_SWSD语义骨架", "SWSD Arms", "_milestone1/p04_swsd_skeleton.gpkg", "arms", False, "#455a64", 0.7),
    LayerSpec("03_LaneEvidenceSegment", "LaneEvidenceSegment｜全部", "p04_lane_evidence_segments.gpkg", "lane_segments", False, "#1565c0", 1.2, 0.70),
    LayerSpec("03_LaneEvidenceSegment", "Lane 样点｜无局部 SWSD fit", "p04_lane_evidence_segments.gpkg", "lane_samples", True, "#e040fb", 2.0, subset='"assignment_state" = \'no_local_swsd_fit\''),
    LayerSpec("04_道路面与原始Vector", "DriveZone_fix｜道路面", "_milestone1/p04_qgis_comparison.gpkg", "drivezone_fix", True, "#90caf9", 0.45, 0.18),
    LayerSpec("04_道路面与原始Vector", "DivStripZone_fix｜导流带", "_milestone1/p04_qgis_comparison.gpkg", "divstripzone_fix", True, "#ffeb3b", 0.7, 0.42),
    LayerSpec("04_道路面与原始Vector", "Lane｜原始", "_milestone1/p04_qgis_comparison.gpkg", "raw_lanes", False, "#1976d2", 0.65, 0.72),
    LayerSpec("04_道路面与原始Vector", "LaneBoundary｜原始", "_milestone1/p04_qgis_comparison.gpkg", "raw_lane_boundaries", False, "#616161", 0.45, 0.68),
    LayerSpec("05_旧Road与当前RCSD对照", "Patch Road/LaneGroup｜旧成果", "_milestone1/p04_qgis_comparison.gpkg", "old_patch_roads", True, "#5e35b1", 1.0, 0.70),
    LayerSpec("05_旧Road与当前RCSD对照", "当前 RCSD Road｜只读对照", "_milestone1/p04_qgis_comparison.gpkg", "current_rcsd_roads", False, "#1565c0", 0.9, 0.60, required=False),
    LayerSpec("09_QA与拒绝拟合", "Road｜non-simple 拟合拒绝", "p04_road_candidates.gpkg", "road_candidates", True, "#d50000", 4.0, subset='"geometry_fit_state" = \'fit_rejected_non_simple_swsd_retained\''),
    LayerSpec("09_QA与拒绝拟合", "拟合站点｜拒绝候选", "p04_road_support_intervals.gpkg", "fit_stations", False, "#ff1744", 2.2, subset='"station_geometry_source" = \'swsd_fit_rejected_non_simple\''),
    LayerSpec("09_QA与拒绝拟合", "LaneTopo｜方向复核", "_milestone1/p04_lane_topo_readiness.gpkg", "lane_topo_links", True, "#ff6d00", 2.4, subset='"lane_topo_state" = \'cross_owner_shared_node_review\''),
    LayerSpec("09_QA与拒绝拟合", "LaneTopo｜语义节点异常", "_milestone1/p04_lane_topo_readiness.gpkg", "lane_topo_links", True, "#d50000", 3.0, subset='"lane_topo_state" = \'cross_owner_semantic_unconnected_review\''),
    LayerSpec("09_QA与拒绝拟合", "输入质量明细｜表", "p04_input_quality_flags.csv", None, False, "#000000", 1.0, provider="delimitedtext"),
    LayerSpec("09_QA与拒绝拟合", "Road geometry QA｜表", "p04_road_geometry_qa.csv", None, False, "#000000", 1.0, provider="delimitedtext"),
)


def build(package_root: str | Path) -> dict[str, Any]:
    root = Path(package_root).expanduser().resolve()
    summary = json.loads((root / "p04_run_summary.json").read_text(encoding="utf-8"))
    app = QgsApplication([], False)
    app.initQgis()
    try:
        return _build_with_qgis(root, summary)
    finally:
        QgsProject.instance().clear()
        app.exitQgis()


def _build_with_qgis(root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    project_path = root / "p04_milestone2_comparison.qgz"
    preview_path = root / "p04_milestone2_comparison_preview.png"
    manifest_path = root / "p04_qgis_layer_manifest.csv"
    qa_path = root / "p04_qgis_project_qa.json"
    project = QgsProject.instance()
    project.clear()
    project.setFileName(str(project_path))
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    project.setCrs(QgsCoordinateReferenceSystem(summary["analysis_crs"]))
    project.setTitle("P04 Road 直出第二里程碑｜四态 Road、支持区间与当前成果对比")
    project.setCustomVariables(
        {
            "p04_run_id": summary["run_id"],
            "p04_status": summary["terminal_status"],
            "p04_scope": "LaneEvidenceSegment -> Road support intervals -> four-state Road geometry",
            "p04_policy": "input QA is separate; rejected non-simple fit retains SWSD explicitly",
            "p04_analysis_crs": summary["analysis_crs"],
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
        layer.setCustomProperty("p04/group", spec.group)
        layer.setCustomProperty("p04/relative_path", spec.relative_path)
        layer.setCustomProperty("p04/layer_name", spec.layer_name or "")
        layer.setCustomProperty("p04/stage_order", index)
        if spec.subset and not layer.setSubsetString(spec.subset):
            errors.append(f"subset rejected: {spec.name}")
        if spec.provider != "delimitedtext":
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
        "layer_count_expected": len(LAYERS),
        "layer_count_loaded": len(read_project.mapLayers()) if read_ok else 0,
        "group_count_expected": len(GROUPS),
        "group_names": group_names,
        "project_write_ok": write_ok,
        "project_readback_ok": read_ok,
        "embedded_qgs_xml_parse_ok": xml_ok,
        "invalid_readback_layers": invalid_layers,
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


__all__ = ["build"]
