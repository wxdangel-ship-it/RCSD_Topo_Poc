from __future__ import annotations

import argparse
import json
from pathlib import Path

from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMapRendererParallelJob,
    QgsMapSettings,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
    Qgis,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create the T12 v10 Segment/Junction QGIS audit project."
    )
    parser.add_argument("--audit-root", required=True, type=Path)
    return parser


def _layer(
    path: Path,
    source_layer: str,
    display_name: str,
    *,
    subset: str = "",
) -> QgsVectorLayer:
    layer = QgsVectorLayer(
        f"{path.resolve()}|layername={source_layer}",
        display_name,
        "ogr",
    )
    if not layer.isValid():
        raise RuntimeError(f"invalid QGIS layer: {display_name} ({path})")
    if subset and not layer.setSubsetString(subset):
        raise RuntimeError(f"invalid subset for {display_name}: {subset}")
    return layer


def _line(layer: QgsVectorLayer, color: str, width: float) -> None:
    layer.setRenderer(
        QgsSingleSymbolRenderer(
            QgsLineSymbol.createSimple(
                {"line_color": color, "line_width": str(width)}
            )
        )
    )


def _marker(
    layer: QgsVectorLayer,
    color: str,
    size: float,
    *,
    outline: str = "255,255,255,255",
    shape: str = "circle",
) -> None:
    layer.setRenderer(
        QgsSingleSymbolRenderer(
            QgsMarkerSymbol.createSimple(
                {
                    "name": shape,
                    "color": color,
                    "size": str(size),
                    "outline_color": outline,
                    "outline_width": "0.5",
                }
            )
        )
    )


def _fill(layer: QgsVectorLayer, color: str, outline: str) -> None:
    layer.setRenderer(
        QgsSingleSymbolRenderer(
            QgsFillSymbol.createSimple(
                {
                    "color": color,
                    "outline_color": outline,
                    "outline_width": "0.25",
                }
            )
        )
    )


def _label(layer: QgsVectorLayer, field: str, color: str) -> None:
    settings = QgsPalLayerSettings()
    settings.fieldName = field
    text_format = QgsTextFormat()
    text_format.setColor(QColor(color))
    text_format.setSize(9)
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1)
    buffer.setColor(QColor(255, 255, 255))
    text_format.setBuffer(buffer)
    settings.setFormat(text_format)
    layer.setLabelsEnabled(True)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))


def _add(project: QgsProject, group, layer: QgsVectorLayer, *, visible: bool = True):
    project.addMapLayer(layer, False)
    node = group.addLayer(layer)
    node.setItemVisibilityChecked(visible)
    return layer


def _render(
    path: Path,
    layers: list[QgsVectorLayer],
    extent_layer: QgsVectorLayer,
    grow_m: float,
) -> None:
    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    extent = extent_layer.extent()
    extent.grow(grow_m)
    settings.setExtent(extent)
    settings.setOutputSize(QSize(1800, 1100))
    settings.setOutputDpi(120)
    settings.setBackgroundColor(QColor(250, 250, 248))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    if not job.renderedImage().save(str(path), "PNG"):
        raise RuntimeError(f"failed to save QGIS render: {path}")


def main() -> int:
    args = _parser().parse_args()
    audit_root = args.audit_root.resolve()
    segment_root = audit_root
    junction_inputs = audit_root / "t12_junction_original_swsd_frcsd_inputs.gpkg"
    segment_inputs = audit_root / "t12_segment_original_swsd_frcsd_inputs.gpkg"
    junction_candidates_path = (
        audit_root / "t12_frcsd_junction_quality_candidates.gpkg"
    )
    junction_confirmed_path = (
        audit_root / "t12_frcsd_confirmed_junction_quality_issues.gpkg"
    )
    junction_evidence_path = (
        audit_root / "t12_frcsd_junction_carrier_evidence.gpkg"
    )
    segment_candidates_path = segment_root / "t12_frcsd_quality_candidates.gpkg"
    segment_confirmed_path = (
        segment_root / "t12_frcsd_confirmed_quality_issues.gpkg"
    )
    segment_evidence_path = segment_root / "t12_frcsd_carrier_evidence.gpkg"
    for path in (
        junction_inputs,
        segment_inputs,
        junction_candidates_path,
        junction_confirmed_path,
        junction_evidence_path,
        segment_candidates_path,
        segment_confirmed_path,
        segment_evidence_path,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    app = QgsApplication([], False)
    app.initQgis()
    try:
        project = QgsProject.instance()
        project.clear()
        project.setTitle("T12 v10 Segment and Junction Quality Audit")
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        root = project.layerTreeRoot()
        junction_result_group = root.addGroup("01_T12_Junction结果")
        segment_result_group = root.addGroup("02_T12_Segment结果")
        junction_evidence_group = root.addGroup("03_Junction根因证据")
        segment_evidence_group = root.addGroup("04_Segment根因证据")
        junction_swsd_group = root.addGroup("05_Junction原始SWSD")
        junction_frcsd_group = root.addGroup("06_Junction原始RCSD_FRCSD")
        segment_swsd_group = root.addGroup("07_Segment原始SWSD")
        segment_frcsd_group = root.addGroup("08_Segment原始RCSD_FRCSD")

        junction_confirmed = _layer(
            junction_confirmed_path,
            "t12_frcsd_confirmed_junction_quality_issues",
            "T12_Junction_Confirmed_J01_J02",
        )
        _marker(junction_confirmed, "220,38,38,255", 5.5, shape="diamond")
        _label(junction_confirmed, "junction_id", "164,24,36")
        _add(project, junction_result_group, junction_confirmed)

        junction_excluded = _layer(
            junction_candidates_path,
            "t12_frcsd_junction_quality_candidates",
            "T12_Junction_Excluded",
            subset='"result_status" = \'excluded\'',
        )
        _marker(junction_excluded, "100,116,139,180", 3.4, shape="cross")
        _add(project, junction_result_group, junction_excluded)

        junction_all = _layer(
            junction_candidates_path,
            "t12_frcsd_junction_quality_candidates",
            "T12_Junction_All_Candidates",
        )
        _marker(junction_all, "245,158,11,170", 3.0)
        _add(project, junction_result_group, junction_all, visible=False)

        segment_confirmed = _layer(
            segment_confirmed_path,
            "t12_frcsd_confirmed_quality_issues",
            "T12_Segment_Confirmed_S01_S03",
        )
        _line(segment_confirmed, "220,38,38,255", 1.8)
        _label(segment_confirmed, "segment_id", "164,24,36")
        _add(project, segment_result_group, segment_confirmed)

        segment_excluded = _layer(
            segment_candidates_path,
            "t12_frcsd_quality_candidates",
            "T12_Segment_Excluded",
            subset='"result_status" = \'excluded\'',
        )
        _line(segment_excluded, "100,116,139,160", 0.7)
        _add(project, segment_result_group, segment_excluded, visible=False)

        support = _layer(
            junction_evidence_path,
            "support_roads",
            "Junction根因_Support_Roads",
        )
        _line(support, "234,88,12,220", 1.2)
        _add(project, junction_evidence_group, support)

        projections = _layer(
            junction_evidence_path,
            "target_projections",
            "Junction根因_Target_Projections",
        )
        _line(projections, "168,85,247,220", 0.8)
        _add(project, junction_evidence_group, projections)

        endpoints = _layer(
            junction_evidence_path,
            "frcsd_endpoints",
            "Junction根因_FRCSD_Endpoints",
        )
        _marker(endpoints, "126,34,206,230", 2.6)
        _add(project, junction_evidence_group, endpoints)

        segment_paths = _layer(
            segment_evidence_path,
            "frcsd_carrier_paths",
            "Segment根因_FRCSD_Carrier_Paths",
        )
        _line(segment_paths, "234,88,12,210", 1.1)
        _add(project, segment_evidence_group, segment_paths)

        segment_portals = _layer(
            segment_evidence_path,
            "anchor_portals",
            "Segment根因_Anchor_Portals",
        )
        _marker(segment_portals, "126,34,206,200", 2.0)
        _add(project, segment_evidence_group, segment_portals, visible=False)

        junction_swsd_roads = _layer(
            junction_inputs,
            "original_swsd_roads",
            "Junction原始_SWSD_Road",
        )
        _line(junction_swsd_roads, "29,112,184,210", 0.9)
        _add(project, junction_swsd_group, junction_swsd_roads)

        junction_swsd_nodes = _layer(
            junction_inputs,
            "original_swsd_nodes",
            "Junction原始_SWSD_Node",
        )
        _marker(junction_swsd_nodes, "37,99,235,190", 1.7)
        _add(project, junction_swsd_group, junction_swsd_nodes, visible=False)

        junction_drivezone = _layer(
            junction_inputs,
            "original_drivezone",
            "Junction原始_SWSD_DriveZone",
        )
        _fill(junction_drivezone, "125,211,252,45", "56,189,248,110")
        _add(project, junction_swsd_group, junction_drivezone)

        junction_frcsd_roads = _layer(
            junction_inputs,
            "original_frcsd_rcsdroad",
            "Junction原始_RCSD_FRCSD_Road",
        )
        _line(junction_frcsd_roads, "55,65,81,230", 1.1)
        _add(project, junction_frcsd_group, junction_frcsd_roads)

        junction_frcsd_nodes = _layer(
            junction_inputs,
            "original_frcsd_rcsdnode",
            "Junction原始_RCSD_FRCSD_Node",
        )
        _marker(junction_frcsd_nodes, "17,24,39,170", 1.5)
        _add(project, junction_frcsd_group, junction_frcsd_nodes, visible=False)

        original_segment = _layer(
            segment_inputs,
            "original_segment",
            "Segment原始_SWSD_Segment",
        )
        _line(original_segment, "29,112,184,190", 0.7)
        _add(project, segment_swsd_group, original_segment, visible=False)

        segment_swsd_roads = _layer(
            segment_inputs,
            "original_swsd_roads",
            "Segment原始_SWSD_Road",
        )
        _line(segment_swsd_roads, "29,112,184,210", 0.8)
        _add(project, segment_swsd_group, segment_swsd_roads)

        segment_swsd_nodes = _layer(
            segment_inputs,
            "original_swsd_nodes",
            "Segment原始_SWSD_Node",
        )
        _marker(segment_swsd_nodes, "37,99,235,180", 1.4)
        _add(project, segment_swsd_group, segment_swsd_nodes, visible=False)

        segment_drivezone = _layer(
            segment_inputs,
            "original_drivezone",
            "Segment原始_SWSD_DriveZone",
        )
        _fill(segment_drivezone, "125,211,252,35", "56,189,248,90")
        _add(project, segment_swsd_group, segment_drivezone, visible=False)

        segment_frcsd_roads = _layer(
            segment_inputs,
            "original_frcsd_rcsdroad",
            "Segment原始_RCSD_FRCSD_Road",
        )
        _line(segment_frcsd_roads, "55,65,81,220", 0.9)
        _add(project, segment_frcsd_group, segment_frcsd_roads)

        segment_frcsd_nodes = _layer(
            segment_inputs,
            "original_frcsd_rcsdnode",
            "Segment原始_RCSD_FRCSD_Node",
        )
        _marker(segment_frcsd_nodes, "17,24,39,160", 1.3)
        _add(project, segment_frcsd_group, segment_frcsd_nodes, visible=False)

        segment_intersections = _layer(
            segment_inputs,
            "original_rcsd_intersection",
            "Segment原始_RCSDIntersection",
        )
        _fill(segment_intersections, "251,146,60,30", "234,88,12,100")
        _add(project, segment_frcsd_group, segment_intersections, visible=False)

        project_path = audit_root / "t12_v10_segment_junction_audit.qgz"
        if not project.write(str(project_path)):
            raise RuntimeError(f"failed to write QGIS project: {project_path}")

        junction_render = audit_root / "t12_v10_junction_audit_overview.png"
        _render(
            junction_render,
            [
                junction_confirmed,
                junction_excluded,
                support,
                projections,
                endpoints,
                junction_swsd_roads,
                junction_frcsd_roads,
                junction_drivezone,
            ],
            junction_confirmed,
            150,
        )
        segment_render = audit_root / "t12_v10_segment_audit_overview.png"
        _render(
            segment_render,
            [
                segment_confirmed,
                segment_paths,
                segment_swsd_roads,
                segment_frcsd_roads,
            ],
            segment_confirmed,
            300,
        )

        required = {
            "T12_Junction_Confirmed_J01_J02",
            "T12_Segment_Confirmed_S01_S03",
            "Junction原始_SWSD_Road",
            "Junction原始_SWSD_Node",
            "Junction原始_RCSD_FRCSD_Road",
            "Junction原始_RCSD_FRCSD_Node",
            "Segment原始_SWSD_Road",
            "Segment原始_SWSD_Node",
            "Segment原始_RCSD_FRCSD_Road",
            "Segment原始_RCSD_FRCSD_Node",
        }
        layers = list(project.mapLayers().values())
        layer_names = {layer.name() for layer in layers}
        checks = {
            "required_layers_present": required.issubset(layer_names),
            "all_layers_valid": all(layer.isValid() for layer in layers),
            "all_crs_epsg3857": all(
                layer.crs().authid() == "EPSG:3857" for layer in layers
            ),
            "junction_confirmed_count_is_4": junction_confirmed.featureCount()
            == 4,
            "junction_excluded_count_is_12": junction_excluded.featureCount()
            == 12,
            "segment_confirmed_count_is_10": segment_confirmed.featureCount()
            == 10,
            "junction_geometry_is_point": junction_confirmed.geometryType()
            == QgsWkbTypes.PointGeometry,
            "segment_geometry_is_line_family": segment_confirmed.geometryType()
            == QgsWkbTypes.LineGeometry,
            "original_swsd_and_frcsd_present": all(
                token in layer_names
                for token in (
                    "Junction原始_SWSD_Road",
                    "Junction原始_RCSD_FRCSD_Road",
                    "Segment原始_SWSD_Road",
                    "Segment原始_RCSD_FRCSD_Road",
                )
            ),
        }
        report = {
            "qgis_version": Qgis.QGIS_VERSION,
            "project": str(project_path),
            "renders": [str(junction_render), str(segment_render)],
            "project_crs": project.crs().authid(),
            "layers": {
                layer.name(): {
                    "valid": layer.isValid(),
                    "feature_count": layer.featureCount(),
                    "crs": layer.crs().authid(),
                    "geometry_type": layer.geometryType(),
                    "wkb_type": QgsWkbTypes.displayString(layer.wkbType()),
                    "source": layer.source(),
                }
                for layer in layers
            },
            "checks": checks,
            "silent_fix": False,
        }
        report["gate_pass"] = all(checks.values())
        report["fail_reasons"] = [
            name for name, passed in checks.items() if not passed
        ]
        report_path = audit_root / "t12_v10_qgis_project_check.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "gate_pass": report["gate_pass"],
                    "project": str(project_path),
                },
                ensure_ascii=False,
            )
        )
        return 0 if report["gate_pass"] else 3
    finally:
        app.exitQgis()


if __name__ == "__main__":
    raise SystemExit(main())
