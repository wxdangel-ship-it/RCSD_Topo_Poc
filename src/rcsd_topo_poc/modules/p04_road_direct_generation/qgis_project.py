from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.PyQt.QtCore import QSize, QUrl
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMapRendererParallelJob,
    QgsMapSettings,
    QgsMarkerSymbol,
    QgsProject,
    QgsRectangle,
    QgsReferencedRectangle,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsWkbTypes,
)


@dataclass(frozen=True)
class LayerSpec:
    group: str
    name: str
    relative_path: str
    layer_name: str | None
    visible: bool
    color: str
    width_or_size: float
    opacity: float = 1.0
    subset: str | None = None
    provider: str = "ogr"
    required: bool = True


GROUPS = (
    ("00_本轮目标结果", True, True),
    ("01_SWSD语义骨架", True, True),
    ("02_Lane证据明细", False, False),
    ("03_原始Vector", True, False),
    ("04_当前RCSD与旧Road", True, True),
    ("09_QA与冲突", False, False),
)


LAYERS = (
    LayerSpec("00_本轮目标结果", "Lane assignment｜accepted", "p04_lane_decisions.gpkg", "lane_decisions", True, "#00a651", 1.7, subset='"decision" = \'accepted\''),
    LayerSpec("00_本轮目标结果", "Lane assignment｜review", "p04_lane_decisions.gpkg", "lane_decisions", True, "#ff9800", 2.2, subset='"decision" = \'review_required\''),
    LayerSpec("00_本轮目标结果", "Lane assignment｜insufficient", "p04_lane_decisions.gpkg", "lane_decisions", True, "#9e9e9e", 1.8, subset='"decision" = \'insufficient_evidence\''),
    LayerSpec("00_本轮目标结果", "宽度异常｜narrow", "p04_lane_decisions.gpkg", "lane_decisions", True, "#d500f9", 3.0, subset='"width_state" = \'narrow_candidate\''),
    LayerSpec("00_本轮目标结果", "宽度异常｜wide_or_gap", "p04_lane_decisions.gpkg", "lane_decisions", True, "#ff1744", 2.8, subset='"width_state" = \'wide_or_boundary_gap\''),
    LayerSpec("01_SWSD语义骨架", "SWSD RoadSection｜571", "p04_swsd_skeleton.gpkg", "road_sections", True, "#212121", 1.2, 0.75),
    LayerSpec("01_SWSD语义骨架", "SWSD Junction", "p04_swsd_skeleton.gpkg", "junctions", False, "#000000", 2.0),
    LayerSpec("01_SWSD语义骨架", "T01 Segment｜scope", "p04_swsd_skeleton.gpkg", "t01_segments", False, "#00bcd4", 2.0, required=False),
    LayerSpec("02_Lane证据明细", "Owner candidate｜rank1", "p04_evidence_assignment.gpkg", "lane_owner_candidates", False, "#7b1fa2", 1.5, subset='"candidate_rank" = 1'),
    LayerSpec("02_Lane证据明细", "Boundary 采样｜含缺失状态", "p04_evidence_assignment.gpkg", "lane_boundary_samples", False, "#43a047", 1.3),
    LayerSpec("03_原始Vector", "DriveZone_fix｜道路面", "p04_qgis_comparison.gpkg", "drivezone_fix", True, "#90caf9", 0.45, 0.18),
    LayerSpec("03_原始Vector", "DivStripZone_fix｜路面导流带", "p04_qgis_comparison.gpkg", "divstripzone_fix", True, "#ffeb3b", 0.7, 0.42),
    LayerSpec("03_原始Vector", "Lane｜原始", "p04_qgis_comparison.gpkg", "raw_lanes", False, "#1976d2", 0.65, 0.72),
    LayerSpec("03_原始Vector", "LaneBoundary｜原始", "p04_qgis_comparison.gpkg", "raw_lane_boundaries", False, "#616161", 0.45, 0.68),
    LayerSpec("03_原始Vector", "DriveZone｜raw", "p04_qgis_comparison.gpkg", "drivezone_raw", False, "#64b5f6", 0.35, 0.15),
    LayerSpec("03_原始Vector", "DivStripZone｜raw", "p04_qgis_comparison.gpkg", "divstripzone_raw", False, "#fdd835", 0.55, 0.35),
    LayerSpec("04_当前RCSD与旧Road", "Patch Road/LaneGroup｜旧成果", "p04_qgis_comparison.gpkg", "old_patch_roads", True, "#5e35b1", 1.0, 0.75),
    LayerSpec("04_当前RCSD与旧Road", "当前 RCSD Road｜只读对照", "p04_qgis_comparison.gpkg", "current_rcsd_roads", False, "#1565c0", 0.8, 0.60, required=False),
    LayerSpec("04_当前RCSD与旧Road", "旧 Road｜混合多个 SWSD owner", "p04_current_road_comparison.gpkg", "old_patch_roads", True, "#e91e63", 3.0, subset='"comparison_state" = \'mixed_swsd_owner\''),
    LayerSpec("09_QA与冲突", "LaneTopo｜跨 Road 节点一致", "p04_lane_topo_readiness.gpkg", "lane_topo_links", False, "#00c853", 1.6, subset='"lane_topo_state" = \'cross_owner_directed_node_supported\''),
    LayerSpec("09_QA与冲突", "LaneTopo｜跨 Road 语义冲突", "p04_lane_topo_readiness.gpkg", "lane_topo_links", True, "#d50000", 2.8, subset='"lane_topo_state" = \'cross_owner_semantic_unconnected_review\''),
    LayerSpec("09_QA与冲突", "冲突与资料不足｜表", "p04_conflicts.csv", None, False, "#000000", 1.0, provider="delimitedtext"),
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
    project_path = root / "p04_milestone1_comparison.qgz"
    preview_path = root / "p04_milestone1_comparison_preview.png"
    manifest_path = root / "p04_qgis_layer_manifest.csv"
    qa_path = root / "p04_qgis_project_qa.json"
    project = QgsProject.instance()
    project.clear()
    project.setFileName(str(project_path))
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    project.setTitle("P04 Road 直出第一里程碑｜原始 Vector、当前 Road 与 Lane Assignment 对比")
    project.setCustomVariables(
        {
            "p04_run_id": summary["run_id"],
            "p04_status": summary["terminal_status"],
            "p04_scope": "SWSD skeleton -> evidence pool -> Lane-Boundary width -> Lane assignment",
            "p04_policy": "SWSD defines structure; Vector provides high-precision evidence; current Road is comparison only",
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
        if spec.provider == "delimitedtext":
            source = _csv_uri(path)
        else:
            source = str(path) + (f"|layername={spec.layer_name}" if spec.layer_name else "")
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
                "geometry_type": QgsWkbTypes.displayString(layer.wkbType()),
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
        project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(combined_extent, project.crs()))
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
    invalid_layers = sorted(layer.name() for layer in read_project.mapLayers().values() if not layer.isValid())
    if invalid_layers:
        errors.append("invalid readback layers: " + ", ".join(invalid_layers))
    missing_sources: list[str] = []
    for layer in read_project.mapLayers().values():
        relative_path = str(layer.customProperty("p04/relative_path", ""))
        if relative_path and not (root / relative_path).is_file():
            missing_sources.append(relative_path)
    if missing_sources:
        errors.append("missing readback sources: " + ", ".join(sorted(set(missing_sources))))
    xml_ok, absolute_count = _validate_embedded_qgs(project_path)
    if not xml_ok:
        errors.append("embedded QGS XML parse failed")
    if absolute_count:
        errors.append(f"absolute datasource references found: {absolute_count}")
    group_names = [child.name() for child in read_project.layerTreeRoot().children() if hasattr(child, "name")]
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
        "missing_readback_sources": sorted(set(missing_sources)),
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


def _csv_uri(path: Path) -> str:
    url = QUrl.fromLocalFile(str(path)).toString()
    return f"{url}?type=csv&delimiter=,&detectTypes=yes&geomType=none&subsetIndex=no&watchFile=no"


def _symbolize(layer: QgsVectorLayer, color: str, width_or_size: float, opacity: float) -> None:
    geometry_type = layer.geometryType()
    if geometry_type == QgsWkbTypes.PointGeometry:
        symbol = QgsMarkerSymbol.createSimple(
            {"name": "circle", "color": color, "size": str(width_or_size), "outline_color": "#ffffff"}
        )
    elif geometry_type == QgsWkbTypes.LineGeometry:
        symbol = QgsLineSymbol.createSimple(
            {"line_color": color, "line_width": str(width_or_size), "capstyle": "round", "joinstyle": "round"}
        )
    elif geometry_type == QgsWkbTypes.PolygonGeometry:
        symbol = QgsFillSymbol.createSimple(
            {
                "color": color,
                "outline_color": color,
                "outline_width": str(max(width_or_size / 2.0, 0.2)),
                "style": "solid",
            }
        )
    else:
        return
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.setOpacity(opacity)


def _transformed_extent(layer: QgsVectorLayer, project: QgsProject) -> QgsRectangle | None:
    if layer.geometryType() == QgsWkbTypes.NullGeometry or layer.featureCount() == 0:
        return None
    extent = layer.extent()
    if extent.isNull():
        return None
    if layer.crs() != project.crs():
        transform = QgsCoordinateTransform(layer.crs(), project.crs(), project.transformContext())
        extent = transform.transformBoundingBox(extent)
    return extent


def _render_preview(project: QgsProject, extent: QgsRectangle, output_path: Path) -> bool:
    settings = QgsMapSettings()
    settings.setDestinationCrs(project.crs())
    settings.setLayers(project.layerTreeRoot().checkedLayers())
    preview_extent = QgsRectangle(extent)
    preview_extent.scale(1.06)
    settings.setExtent(preview_extent)
    settings.setOutputSize(QSize(2000, 1400))
    settings.setOutputDpi(120)
    settings.setBackgroundColor(QColor("#f7f7f7"))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    return bool(job.renderedImage().save(str(output_path), "PNG"))


def _write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = tuple(rows[0]) if rows else ()
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(rows)


def _validate_embedded_qgs(project_path: Path) -> tuple[bool, int]:
    if not project_path.is_file():
        return False, 0
    with zipfile.ZipFile(project_path) as archive:
        qgs_names = [name for name in archive.namelist() if name.lower().endswith(".qgs")]
        if len(qgs_names) != 1:
            return False, 0
        xml_root = ET.fromstring(archive.read(qgs_names[0]))
    datasource_values = [
        (element.text or "").strip()
        for element in xml_root.iter("datasource")
        if (element.text or "").strip()
    ]
    absolute_count = sum(
        value.startswith(("/mnt/", "file:///", "file://"))
        or bool(re.match(r"^[A-Za-z]:[/\\]", value))
        for value in datasource_values
    )
    return True, absolute_count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["build"]
