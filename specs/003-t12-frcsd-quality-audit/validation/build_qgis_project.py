#!/usr/bin/env python3
"""Build a review-ready QGIS project for one T12 acceptance run."""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsPalLayerSettings,
    QgsProject,
    QgsReferencedRectangle,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
    Qgis,
)


def _layer(source: str, name: str) -> QgsVectorLayer:
    layer = QgsVectorLayer(source, name, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"invalid QGIS layer: {name} ({source})")
    return layer


def _style(layer: QgsVectorLayer, color: str, width: float, opacity: float) -> None:
    symbol = layer.renderer().symbol()
    if symbol is None:
        return
    symbol.setColor(QColor(color))
    symbol.setOpacity(opacity)
    if QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.LineGeometry:
        symbol.setWidth(width)
    elif QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PointGeometry:
        symbol.setSize(width * 1.8)


def _label(layer: QgsVectorLayer, field_name: str) -> None:
    if layer.fields().indexOf(field_name) < 0:
        return
    settings = QgsPalLayerSettings()
    settings.enabled = True
    settings.fieldName = field_name
    text_format = QgsTextFormat()
    text_format.setSize(8)
    text_format.setColor(QColor("#7f0000"))
    settings.setFormat(text_format)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--segment", required=True, type=Path)
    parser.add_argument("--swsd-roads", required=True, type=Path)
    parser.add_argument("--frcsd-roads", required=True, type=Path)
    parser.add_argument("--drivezone", required=True, type=Path)
    parser.add_argument("--rcsd-intersection", required=True, type=Path)
    parser.add_argument("--out-project", required=True, type=Path)
    parser.add_argument("--out-manifest", required=True, type=Path)
    args = parser.parse_args()

    app = QgsApplication([], False)
    app.initQgis()
    try:
        run_root = args.run_root.resolve()
        candidates = run_root / "t12_frcsd_quality_candidates.gpkg"
        confirmed = run_root / "t12_frcsd_confirmed_quality_issues.gpkg"
        evidence = run_root / "t12_frcsd_carrier_evidence.gpkg"
        required = [
            candidates,
            confirmed,
            evidence,
            args.segment,
            args.swsd_roads,
            args.frcsd_roads,
            args.drivezone,
            args.rcsd_intersection,
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(f"missing project inputs: {missing}")

        project = QgsProject.instance()
        project.clear()
        project.setTitle("T12 1026960 原始1V1 FRCSD质量审计")
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        project.setFilePathStorage(Qgis.FilePathType.Absolute)
        project.setCustomVariables(
            {
                "t12_run_root": str(run_root),
                "t12_business_note": (
                    "candidate不是正式问题；仅confirmed层是复核后质量问题；"
                    "DriveZone仅作证据，不作修复或强判定规则"
                ),
            }
        )

        root = project.layerTreeRoot()
        result_group = root.addGroup("01_T12复核结果")
        evidence_group = root.addGroup("02_T12路径证据")
        context_group = root.addGroup("03_原始上下文")

        layer_specs = [
            (
                result_group,
                f"{confirmed}|layername=t12_frcsd_confirmed_quality_issues",
                "T12_Confirmed_10_正式质量问题",
                "#d7191c",
                1.4,
                1.0,
                True,
                "candidate_id",
            ),
            (
                result_group,
                f"{candidates}|layername=t12_frcsd_quality_candidates",
                "T12_Candidates_35_含复核状态",
                "#fdae61",
                0.8,
                0.9,
                True,
                "candidate_id",
            ),
            (
                evidence_group,
                f"{evidence}|layername=anchor_portals",
                "Anchor_Portals",
                "#984ea3",
                1.2,
                0.9,
                False,
                "",
            ),
            (
                evidence_group,
                f"{evidence}|layername=swsd_required_carriers",
                "SWSD_Required_Carriers",
                "#377eb8",
                0.9,
                0.9,
                False,
                "",
            ),
            (
                evidence_group,
                f"{evidence}|layername=frcsd_carrier_paths",
                "FRCSD_Carrier_Paths",
                "#4daf4a",
                1.0,
                0.9,
                False,
                "",
            ),
            (
                context_group,
                str(args.segment.resolve()),
                "SWSD_Segments",
                "#2166ac",
                0.35,
                0.45,
                False,
                "",
            ),
            (
                context_group,
                str(args.swsd_roads.resolve()),
                "SWSD_Roads",
                "#67a9cf",
                0.25,
                0.35,
                False,
                "",
            ),
            (
                context_group,
                str(args.frcsd_roads.resolve()),
                "Original_1V1_FRCSD_Roads",
                "#1b7837",
                0.35,
                0.55,
                True,
                "",
            ),
            (
                context_group,
                str(args.drivezone.resolve()),
                "DriveZone_Evidence_Only",
                "#ffffbf",
                0.25,
                0.22,
                True,
                "",
            ),
            (
                context_group,
                str(args.rcsd_intersection.resolve()),
                "RCSDIntersection_Truth",
                "#762a83",
                0.4,
                0.25,
                True,
                "",
            ),
        ]
        audit_rows = []
        combined_extent = None
        for group, source, name, color, width, opacity, visible, label in layer_specs:
            layer = _layer(source, name)
            _style(layer, color, width, opacity)
            if label:
                _label(layer, label)
            project.addMapLayer(layer, False)
            node = group.addLayer(layer)
            node.setItemVisibilityChecked(visible)
            if name.startswith("T12_Confirmed") or name.startswith("T12_Candidates"):
                extent = layer.extent()
                if combined_extent is None:
                    combined_extent = extent
                else:
                    combined_extent.combineExtentWith(extent)
            audit_rows.append(
                {
                    "name": name,
                    "source": layer.source(),
                    "crs": layer.crs().authid(),
                    "feature_count": layer.featureCount(),
                    "geometry_type": QgsWkbTypes.displayString(layer.wkbType()),
                    "valid": layer.isValid(),
                    "visible_by_default": visible,
                }
            )

        if combined_extent is not None and not combined_extent.isEmpty():
            combined_extent.scale(1.15)
            try:
                project.viewSettings().setDefaultViewExtent(
                    QgsReferencedRectangle(combined_extent, project.crs())
                )
            except AttributeError:
                pass

        out_project = args.out_project.resolve()
        out_project.parent.mkdir(parents=True, exist_ok=True)
        if not project.write(str(out_project)):
            raise RuntimeError(f"failed to write QGIS project: {out_project}")

        verification = QgsProject()
        if not verification.read(str(out_project)):
            raise RuntimeError(f"failed to reopen QGIS project: {out_project}")
        invalid_reopened = [
            layer.name() for layer in verification.mapLayers().values() if not layer.isValid()
        ]
        manifest = {
            "project": str(out_project),
            "project_crs": project.crs().authid(),
            "layer_count": len(audit_rows),
            "layers": audit_rows,
            "reopen_valid": not invalid_reopened,
            "invalid_reopened_layers": invalid_reopened,
            "silent_fix": False,
            "drivezone_policy": "evidence_only",
        }
        out_manifest = args.out_manifest.resolve()
        out_manifest.parent.mkdir(parents=True, exist_ok=True)
        out_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        verification.clear()
        project.clear()
        del verification, layer, node
        gc.collect()
        return 0
    finally:
        QgsProject.instance().clear()
        app.exitQgis()


if __name__ == "__main__":
    raise SystemExit(main())
