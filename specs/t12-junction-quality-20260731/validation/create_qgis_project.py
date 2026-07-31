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
    Qgis,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create the T12 Junction real-case QGIS audit project."
    )
    parser.add_argument("--run-root", required=True, type=Path)
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


def _label_junction_id(layer: QgsVectorLayer) -> None:
    settings = QgsPalLayerSettings()
    settings.fieldName = "junction_id"
    text_format = QgsTextFormat()
    text_format.setColor(QColor(164, 24, 36))
    text_format.setSize(10)
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1)
    buffer.setColor(QColor(255, 255, 255))
    text_format.setBuffer(buffer)
    settings.setFormat(text_format)
    layer.setLabelsEnabled(True)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))


def _add(
    project: QgsProject,
    group,
    layer: QgsVectorLayer,
    *,
    visible: bool = True,
):
    project.addMapLayer(layer, False)
    node = group.addLayer(layer)
    node.setItemVisibilityChecked(visible)
    return layer


def _render(
    path: Path,
    layers: list[QgsVectorLayer],
    extent_layer: QgsVectorLayer,
) -> None:
    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    extent = extent_layer.extent()
    extent.grow(150)
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
    run_root = args.run_root.resolve()
    inputs = run_root / "t12_junction_original_swsd_frcsd_inputs.gpkg"
    candidates_path = run_root / "t12_frcsd_junction_quality_candidates.gpkg"
    confirmed_path = run_root / "t12_frcsd_confirmed_junction_quality_issues.gpkg"
    evidence_path = run_root / "t12_frcsd_junction_carrier_evidence.gpkg"
    for path in (inputs, candidates_path, confirmed_path, evidence_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    app = QgsApplication([], False)
    app.initQgis()
    try:
        project = QgsProject.instance()
        project.clear()
        project.setTitle("T12 Junction FRCSD Quality Audit")
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        root = project.layerTreeRoot()
        result_group = root.addGroup("01_T12_Junction结果")
        evidence_group = root.addGroup("02_T12_根因证据")
        swsd_group = root.addGroup("03_原始SWSD")
        frcsd_group = root.addGroup("04_原始RCSD_FRCSD")

        confirmed = _layer(
            confirmed_path,
            "t12_frcsd_confirmed_junction_quality_issues",
            "T12_Confirmed_Junction_Point",
        )
        _marker(confirmed, "220,38,38,255", 5.5, shape="diamond")
        _label_junction_id(confirmed)
        _add(project, result_group, confirmed)

        exclusions = _layer(
            candidates_path,
            "t12_frcsd_junction_quality_candidates",
            "T12_Excluded_Junction_Point",
            subset="\"review_status\" = 'excluded_false_positive'",
        )
        _marker(exclusions, "100,116,139,180", 3.4, shape="cross")
        _add(project, result_group, exclusions)

        candidates = _layer(
            candidates_path,
            "t12_frcsd_junction_quality_candidates",
            "T12_All_Junction_Candidates",
        )
        _marker(candidates, "245,158,11,170", 3.0)
        _add(project, result_group, candidates, visible=False)

        support = _layer(
            evidence_path,
            "support_roads",
            "根因_Support_Roads",
        )
        _line(support, "234,88,12,220", 1.2)
        _add(project, evidence_group, support)

        projections = _layer(
            evidence_path,
            "target_projections",
            "根因_Target_Projections",
        )
        _line(projections, "168,85,247,220", 0.8)
        _add(project, evidence_group, projections)

        endpoints = _layer(
            evidence_path,
            "frcsd_endpoints",
            "根因_FRCSD_Endpoints",
        )
        _marker(endpoints, "126,34,206,230", 2.6)
        _add(project, evidence_group, endpoints)

        swsd_roads = _layer(
            inputs,
            "original_swsd_roads",
            "原始_SWSD_Road",
        )
        _line(swsd_roads, "29,112,184,210", 0.9)
        _add(project, swsd_group, swsd_roads)

        swsd_nodes = _layer(
            inputs,
            "original_swsd_nodes",
            "原始_SWSD_Node",
        )
        _marker(swsd_nodes, "37,99,235,190", 1.7)
        _add(project, swsd_group, swsd_nodes, visible=False)

        drivezone = _layer(
            inputs,
            "original_drivezone",
            "原始_SWSD_DriveZone",
        )
        _fill(drivezone, "125,211,252,45", "56,189,248,110")
        _add(project, swsd_group, drivezone)

        frcsd_roads = _layer(
            inputs,
            "original_frcsd_rcsdroad",
            "原始_RCSD_FRCSD_Road",
        )
        _line(frcsd_roads, "55,65,81,230", 1.1)
        _add(project, frcsd_group, frcsd_roads)

        frcsd_nodes = _layer(
            inputs,
            "original_frcsd_rcsdnode",
            "原始_RCSD_FRCSD_Node",
        )
        _marker(frcsd_nodes, "17,24,39,170", 1.5)
        _add(project, frcsd_group, frcsd_nodes, visible=False)

        project_path = run_root / "t12_junction_real_case_audit.qgz"
        if not project.write(str(project_path)):
            raise RuntimeError(f"failed to write QGIS project: {project_path}")

        render_path = run_root / "t12_junction_real_case_audit_overview.png"
        _render(
            render_path,
            [confirmed, exclusions, support, projections, endpoints, swsd_roads, frcsd_roads, drivezone],
            confirmed,
        )

        required = {
            "T12_Confirmed_Junction_Point",
            "T12_Excluded_Junction_Point",
            "根因_Support_Roads",
            "原始_SWSD_Road",
            "原始_SWSD_Node",
            "原始_RCSD_FRCSD_Road",
            "原始_RCSD_FRCSD_Node",
        }
        layers = list(project.mapLayers().values())
        report = {
            "qgis_version": Qgis.QGIS_VERSION,
            "project": str(project_path),
            "render": str(render_path),
            "project_crs": project.crs().authid(),
            "layers": {
                layer.name(): {
                    "valid": layer.isValid(),
                    "feature_count": layer.featureCount(),
                    "crs": layer.crs().authid(),
                    "geometry_type": layer.geometryType(),
                    "source": layer.source(),
                }
                for layer in layers
            },
            "checks": {
                "required_layers_present": required.issubset(
                    {layer.name() for layer in layers}
                ),
                "all_layers_valid": all(layer.isValid() for layer in layers),
                "all_crs_epsg3857": all(
                    layer.crs().authid() == "EPSG:3857" for layer in layers
                ),
                "confirmed_count_is_4": confirmed.featureCount() == 4,
                "excluded_count_is_12": exclusions.featureCount() == 12,
                "original_swsd_and_frcsd_present": all(
                    name in {layer.name() for layer in layers}
                    for name in (
                        "原始_SWSD_Road",
                        "原始_SWSD_Node",
                        "原始_RCSD_FRCSD_Road",
                        "原始_RCSD_FRCSD_Node",
                    )
                ),
            },
            "silent_fix": False,
        }
        report["gate_pass"] = all(report["checks"].values())
        report["fail_reasons"] = [
            name for name, passed in report["checks"].items() if not passed
        ]
        report_path = run_root / "t12_junction_qgis_project_check.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"gate_pass": report["gate_pass"], "project": str(project_path)}))
        return 0 if report["gate_pass"] else 3
    finally:
        app.exitQgis()


if __name__ == "__main__":
    raise SystemExit(main())
