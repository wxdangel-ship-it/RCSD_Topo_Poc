from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


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
    visible: bool
    color: str
    width_or_size: float
    expected_count: int | None = None
    provider: str = "ogr"
    opacity: float = 1.0
    subset: str | None = None


GROUPS = (
    ("00_目标问题复核", True, True),
    ("09_QA_审计", False, False),
    ("08_T06_Step3_最终成果", True, True),
    ("07_T06_Step2_可替换性", False, False),
    ("06_T06_Step1_融合单元", False, False),
    ("05_T05_人工锚定融合", False, False),
    ("04_T01_Segment", True, True),
    ("03_人工锚定关系表", True, False),
    ("02A_RCSD端点人工修订", True, True),
    ("02_T08_预处理过程", False, False),
    ("01_原始数据", True, True),
)


LAYERS = (
    LayerSpec(
        "00_目标问题复核",
        "目标 T01 Segment｜4 条",
        "data/04_t01/segment.gpkg",
        True,
        "#00bcd4",
        3.2,
        4,
        subset='"id" IN (\'3086610_609284657\', \'521458225_600688320\', \'521458225_612028267\', \'609020493_61493884\')',
    ),
    LayerSpec(
        "00_目标问题复核",
        "目标 Step1｜缺锚保留",
        "data/06_t06_step1/t06_swsd_segment_rejected.gpkg",
        True,
        "#ff7f00",
        3.4,
        1,
        subset='"swsd_segment_id" = \'521458225_600688320\'',
    ),
    LayerSpec(
        "00_目标问题复核",
        "目标 Step2｜可替换 3 条",
        "data/07_t06_step2/t06_rcsd_segment_replaceable.gpkg",
        True,
        "#00a651",
        3.8,
        3,
        subset='"swsd_segment_id" IN (\'3086610_609284657\', \'521458225_612028267\', \'609020493_61493884\')',
    ),
    LayerSpec(
        "00_目标问题复核",
        "609020493_61493884｜锚点优先通道 5 段",
        "data/08_t06_step3/t06_frcsd_road.gpkg",
        True,
        "#00e5ff",
        4.6,
        5,
        subset='"id" IN (\'5855295910117380\', \'5855296278768752\', \'5855296278768753\', \'5855295910117379\', \'5855296278768576\')',
    ),
    LayerSpec(
        "00_目标问题复核",
        "3086610_609284657｜归属通道 4 段",
        "data/08_t06_step3/t06_frcsd_road.gpkg",
        True,
        "#ff9800",
        3.4,
        4,
        subset='"id" IN (\'5855295910117399\', \'5855295910117397\', \'5855295910117569\', \'5855296278768716\')',
    ),
    LayerSpec(
        "00_目标问题复核",
        "3086610_609284657｜此前漏替换的两段",
        "data/08_t06_step3/t06_frcsd_road.gpkg",
        True,
        "#e600ff",
        4.0,
        2,
        subset='"id" IN (\'5855296278768589\', \'5855295910117496\')',
    ),
    LayerSpec(
        "00_目标问题复核",
        "目标 Step3｜替换与保留状态",
        "data/08_t06_step3/t06_step3_swsd_frcsd_segment_relation.gpkg",
        True,
        "#ff00ff",
        3.0,
        4,
        subset='"swsd_segment_id" IN (\'3086610_609284657\', \'521458225_600688320\', \'521458225_612028267\', \'609020493_61493884\')',
    ),
    LayerSpec(
        "00_目标问题复核",
        "原多归属 Road｜唯一或无 Segment owner 8 条",
        "data/08_t06_step3/t06_rcsd_road_ownership.gpkg",
        True,
        "#d81b60",
        4.2,
        8,
        subset='"rcsd_road_id" IN (\'5855295910117467\', \'5855296278768493\', \'5855296278768511\', \'5855296278768591\', \'5855296278768608\', \'5855296278768642\', \'5855296278768661\', \'5855296278768702\')',
    ),
    LayerSpec(
        "00_目标问题复核",
        "原始 RCSDRoad｜九条端点修订对象",
        "data/01_raw/RCSDRoad.geojson",
        True,
        "#0055ff",
        2.4,
        9,
        subset='"Id" IN (\'5855295910117379\', \'5855295910117422\', \'5855295910117438\', \'5855295910117456\', \'5855295910117517\', \'5855295910117533\', \'5855295910117534\', \'5855295910117568\', \'5855295910117569\')',
    ),
    LayerSpec("01_原始数据", "SWSD Road｜原始", "data/01_raw/road.geojson", True, "#7f8c8d", 0.55, 163, opacity=0.72),
    LayerSpec("01_原始数据", "SWSD Node｜原始", "data/01_raw/node.geojson", False, "#34495e", 1.7, 143),
    LayerSpec("01_原始数据", "RCSDRoad｜原始", "data/01_raw/RCSDRoad.geojson", True, "#3182bd", 0.45, 469, opacity=0.68),
    LayerSpec("01_原始数据", "RCSDNode｜原始", "data/01_raw/RCSDNode.geojson", False, "#08519c", 1.4, 655),
    LayerSpec("02A_RCSD端点人工修订", "RCSDRoad｜修订后完整工作副本", "data/02a_rcsd_endpoint_override/RCSDRoad_endpoint_override.gpkg", True, "#00acc1", 0.8, 469, opacity=0.78),
    LayerSpec(
        "02A_RCSD端点人工修订",
        "RCSDRoad｜九条修订对象",
        "data/02a_rcsd_endpoint_override/RCSDRoad_endpoint_override.gpkg",
        True,
        "#ff00ff",
        3.2,
        9,
        subset='"Id" IN (\'5855295910117379\', \'5855295910117422\', \'5855295910117438\', \'5855295910117456\', \'5855295910117517\', \'5855295910117533\', \'5855295910117534\', \'5855295910117568\', \'5855295910117569\')',
    ),
    LayerSpec("02_T08_预处理过程", "Tool3 Node｜字段归一", "data/02_t08/p02_nodes_tool3.gpkg", False, "#756bb1", 1.8, 143),
    LayerSpec("02_T08_预处理过程", "Tool6｜异常候选", "data/02_t08/p02_node_error_tool6.gpkg", True, "#ff7f00", 3.2, 3),
    LayerSpec("02_T08_预处理过程", "Tool6后人工补充｜完整 Node", "data/02_t08/p02_nodes_tool3_manual_override.gpkg", False, "#ff00ff", 2.0, 143),
    LayerSpec("02_T08_预处理过程", "Tool6后人工补充｜审计表", "data/02_t08/p02_manual_tool6_override_row.csv", False, "#000000", 1.0, 1, provider="delimitedtext"),
    LayerSpec("02_T08_预处理过程", "Tool4 Road｜修复后", "data/02_t08/p02_roads_tool4.gpkg", False, "#31a354", 0.75, 163),
    LayerSpec("02_T08_预处理过程", "Tool4 Node｜修复后", "data/02_t08/p02_nodes_tool4.gpkg", False, "#238b45", 2.0, 143),
    LayerSpec("02_T08_预处理过程", "Tool4 Node｜修复审计", "data/02_t08/p02_audit_nodes_tool4.gpkg", False, "#e6550d", 2.5, 5),
    LayerSpec("02_T08_预处理过程", "Tool5 Road｜复杂路口后", "data/02_t08/p02_roads_tool5.gpkg", True, "#2ca25f", 0.85, 163),
    LayerSpec("02_T08_预处理过程", "Tool5 Node｜复杂路口后", "data/02_t08/p02_nodes_tool5.gpkg", True, "#006d2c", 2.1, 143),
    LayerSpec("02_T08_预处理过程", "Tool5 Node｜复杂路口审计", "data/02_t08/p02_audit_nodes_tool5.gpkg", False, "#dd1c77", 2.6, 21),
    LayerSpec("03_人工锚定关系表", "人工关系｜原始16条", "data/03_relations/p02_manual_relations_raw.csv", False, "#000000", 1.0, 16, provider="delimitedtext"),
    LayerSpec("03_人工锚定关系表", "人工关系｜转换后12条", "data/03_relations/p02_manual_relations_converted.csv", False, "#000000", 1.0, 12, provider="delimitedtext"),
    LayerSpec("03_人工锚定关系表", "人工关系｜转换审计", "data/03_relations/p02_manual_relation_transform_audit.csv", False, "#000000", 1.0, 16, provider="delimitedtext"),
    LayerSpec("04_T01_Segment", "T01 Road", "data/04_t01/roads.gpkg", False, "#969696", 0.55, 163),
    LayerSpec("04_T01_Segment", "T01 Node", "data/04_t01/nodes.gpkg", False, "#525252", 1.5, 143),
    LayerSpec("04_T01_Segment", "T01 Segment｜109", "data/04_t01/segment.gpkg", True, "#00bcd4", 1.15, 109, opacity=0.90),
    LayerSpec("04_T01_Segment", "T01 未分段道路", "data/04_t01/unsegmented_roads.gpkg", True, "#ff0000", 1.5, 20),
    LayerSpec("05_T05_人工锚定融合", "T05 人工关系成果｜12", "data/05_t05/intersection_match_all.geojson", True, "#9c27b0", 3.0, 12),
    LayerSpec("05_T05_人工锚定融合", "T05 RCSDRoad｜输出", "data/05_t05/rcsdroad_out.gpkg", False, "#2171b5", 0.65, 474),
    LayerSpec("05_T05_人工锚定融合", "T05 RCSDNode｜输出", "data/05_t05/rcsdnode_out.gpkg", False, "#08306b", 1.5, 660),
    LayerSpec("05_T05_人工锚定融合", "T05 RCSDRoad｜拆分", "data/05_t05/rcsdroad_split.gpkg", True, "#fb6a4a", 1.2, 10),
    LayerSpec("05_T05_人工锚定融合", "T05 RCSDNode｜生成", "data/05_t05/rcsdnode_generated.gpkg", True, "#cb181d", 3.0, 5),
    LayerSpec("05_T05_人工锚定融合", "T05 RCSDNode｜分组", "data/05_t05/rcsdnode_grouped.gpkg", False, "#6a51a3", 2.2, 10),
    LayerSpec("05_T05_人工锚定融合", "T05 图可消费审计｜表", "data/05_t05/relation_graph_consumability_audit.csv", False, "#000000", 1.0, 12, provider="delimitedtext"),
    LayerSpec("06_T06_Step1_融合单元", "T06 Step1｜最终融合单元", "data/06_t06_step1/t06_swsd_segment_final_fusion_units.gpkg", True, "#41ab5d", 1.4, 9),
    LayerSpec("06_T06_Step1_融合单元", "T06 Step1｜拒绝 Segment", "data/06_t06_step1/t06_swsd_segment_rejected.gpkg", False, "#bdbdbd", 0.7, 98),
    LayerSpec("07_T06_Step2_可替换性", "T06 Step2｜可替换", "data/07_t06_step2/t06_rcsd_segment_replaceable.gpkg", True, "#00a651", 1.8, 7),
    LayerSpec("07_T06_Step2_可替换性", "T06 Step2｜拒绝", "data/07_t06_step2/t06_rcsd_segment_rejected.gpkg", True, "#d7301f", 1.8, 2),
    LayerSpec("07_T06_Step2_可替换性", "T06 Step2｜替换计划", "data/07_t06_step2/t06_segment_replacement_plan.gpkg", False, "#ff8c00", 1.5, 11),
    LayerSpec("07_T06_Step2_可替换性", "T06 Step2｜失败业务审计", "data/07_t06_step2/t06_rcsd_segment_failure_business_audit.gpkg", False, "#8e44ad", 2.0, 2),
    LayerSpec("07_T06_Step2_可替换性", "T06 Step2｜问题注册表", "data/07_t06_step2/t06_segment_replacement_problem_registry.gpkg", False, "#54278f", 2.0, 2),
    LayerSpec("08_T06_Step3_最终成果", "F-RCSD Road｜最终206", "data/08_t06_step3/t06_frcsd_road.gpkg", True, "#e31a1c", 1.15, 206),
    LayerSpec("08_T06_Step3_最终成果", "F-RCSD Node｜最终243", "data/08_t06_step3/t06_frcsd_node.gpkg", True, "#ffd700", 2.0, 243),
    LayerSpec("08_T06_Step3_最终成果", "T06 Step3｜替换单元", "data/08_t06_step3/t06_step3_replacement_units.gpkg", False, "#ff7f00", 1.5, 7),
    LayerSpec("08_T06_Step3_最终成果", "T06 Step3｜拓扑连通审计", "data/08_t06_step3/t06_step3_topology_connectivity_audit.gpkg", False, "#6a3d9a", 1.2, 346),
    LayerSpec("08_T06_Step3_最终成果", "T06 Step3｜未替换RCSD归因", "data/08_t06_step3/t06_step3_unreplaced_rcsd_attribution.gpkg", False, "#bdbdbd", 0.55, 412, opacity=0.65),
    LayerSpec("08_T06_Step3_最终成果", "T06 Step3｜RCSD Road归属", "data/08_t06_step3/t06_rcsd_road_ownership.gpkg", False, "#1f78b4", 0.65, 474),
    LayerSpec("08_T06_Step3_最终成果", "T06 Step3｜Segment关系", "data/08_t06_step3/t06_step3_swsd_frcsd_segment_relation.gpkg", False, "#33a02c", 0.9, 109),
    LayerSpec("08_T06_Step3_最终成果", "T06 Step3｜新增RCSD道路", "data/08_t06_step3/t06_step3_added_rcsd_roads.gpkg", False, "#00c853", 2.0, 62),
    LayerSpec("08_T06_Step3_最终成果", "T06 Step3｜移除SWSD道路", "data/08_t06_step3/t06_step3_removed_swsd_roads.gpkg", False, "#ff00ff", 2.0, 19),
    LayerSpec("09_QA_审计", "目标 Segment 审计｜表", "data/09_qa/p02_target_segment_audit.csv", False, "#000000", 1.0, 4, provider="delimitedtext"),
)


def build(package_root: str | Path) -> dict[str, Any]:
    root_path = Path(package_root).expanduser().resolve()
    package_manifest_path = root_path / "p02_qgis_package_manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    run_id = str(package_manifest["run_id"])
    project_path = root_path / "p02_wuhan_local_analysis.qgz"
    preview_path = root_path / "p02_wuhan_local_analysis_preview.png"
    manifest_csv_path = root_path / "p02_qgis_layer_manifest.csv"
    qa_path = root_path / "p02_qgis_project_qa.json"

    project = QgsProject.instance()
    project.clear()
    project.setFileName(str(project_path))
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    project.setTitle("P02 武汉局部实验｜原始数据与端到端成果分析")
    project.setCustomVariables(
        {
            "p02_module": "p02_wuhan_local_experiment",
            "p02_run_id": run_id,
            "p02_status": "validated_current_wuhan_result",
            "p02_stage_order": "Tool1 -> endpoint override -> Tool3 -> Tool6 -> manual T-junction -> Tool4 -> Tool5 -> T01 -> T05 -> T06",
            "p02_manual_override": "609020493 grade=2; Tool4 kind_2=2048",
            "p02_input_policy": "full input; no clip; nine confirmed SNodeId/ENodeId overrides only",
            "p02_replacement_policy": "formal anchors > ordered relative position > geometry distance; RCSD Road unique ordinary Segment owner",
        }
    )

    tree_root = project.layerTreeRoot()
    group_nodes: dict[str, Any] = {}
    for group_name, checked, expanded in GROUPS:
        group = tree_root.addGroup(group_name)
        group.setItemVisibilityChecked(checked)
        group.setExpanded(expanded)
        group_nodes[group_name] = group

    manifest_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    combined_extent = QgsRectangle()
    has_extent = False
    for index, spec in enumerate(LAYERS, start=1):
        source_path = root_path / spec.relative_path
        if not source_path.is_file():
            errors.append(f"missing source: {spec.relative_path}")
            continue
        source = _csv_uri(source_path) if spec.provider == "delimitedtext" else str(source_path)
        layer = QgsVectorLayer(source, spec.name, spec.provider)
        if not layer.isValid():
            errors.append(f"invalid layer: {spec.name} -> {spec.relative_path}")
            continue
        layer.setCustomProperty("p02/group", spec.group)
        layer.setCustomProperty("p02/relative_path", spec.relative_path)
        layer.setCustomProperty("p02/stage_order", index)
        if spec.subset and not layer.setSubsetString(spec.subset):
            errors.append(f"subset rejected: {spec.name} -> {spec.subset}")
        if spec.provider != "delimitedtext":
            _symbolize(layer, spec.color, spec.width_or_size, spec.opacity)
        project.addMapLayer(layer, False)
        tree_layer = group_nodes[spec.group].addLayer(layer)
        tree_layer.setItemVisibilityChecked(spec.visible)

        feature_count = layer.featureCount()
        if spec.expected_count is not None and feature_count != spec.expected_count:
            errors.append(
                f"feature count mismatch: {spec.name} expected={spec.expected_count} actual={feature_count}"
            )
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
                "provider": spec.provider,
                "geometry_type": QgsWkbTypes.displayString(layer.wkbType()),
                "feature_count": feature_count,
                "crs": layer.crs().authid() or layer.crs().toWkt(),
                "visible_by_default": spec.visible,
                "source_sha256": _sha256(source_path),
            }
        )

    if not has_extent:
        errors.append("no spatial extent available")
    else:
        combined_extent.scale(1.06)
        project.viewSettings().setDefaultViewExtent(
            QgsReferencedRectangle(combined_extent, project.crs())
        )
    _write_layer_manifest(manifest_csv_path, manifest_rows)

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
    invalid_readback_layers = sorted(
        layer.name() for layer in read_project.mapLayers().values() if not layer.isValid()
    )
    if invalid_readback_layers:
        errors.append("invalid readback layers: " + ", ".join(invalid_readback_layers))
    missing_readback_sources: list[str] = []
    for layer in read_project.mapLayers().values():
        relative_path = str(layer.customProperty("p02/relative_path", ""))
        if relative_path and not (root_path / relative_path).is_file():
            missing_readback_sources.append(relative_path)
    if missing_readback_sources:
        errors.append("missing readback sources: " + ", ".join(sorted(missing_readback_sources)))

    xml_parse_ok, absolute_datasource_reference_count = _validate_embedded_qgs(project_path)
    if not xml_parse_ok:
        errors.append("embedded QGS XML parse failed")
    if absolute_datasource_reference_count:
        errors.append(
            f"absolute datasource references found: {absolute_datasource_reference_count}"
        )
    group_names = [
        child.name() for child in read_project.layerTreeRoot().children() if hasattr(child, "name")
    ]
    missing_groups = [name for name, _, _ in GROUPS if name not in group_names]
    if missing_groups:
        errors.append("missing groups: " + ", ".join(missing_groups))

    qa = {
        "status": "passed_with_known_limitation" if not errors else "failed",
        "run_id": run_id,
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
        "embedded_qgs_xml_parse_ok": xml_parse_ok,
        "invalid_readback_layers": invalid_readback_layers,
        "missing_readback_sources": missing_readback_sources,
        "absolute_datasource_reference_count": absolute_datasource_reference_count,
        "preview_render_ok": render_ok,
        "manifest_row_count": len(manifest_rows),
        "errors": errors,
        "known_limitations": {
            "road_surface_overlay_gate": {
                "status": "not_run_unavailable",
                "reason": "road surface polygon data is unavailable; no coverage ratio is fabricated",
            },
            "t03_t04_t07": {
                "status": "not_run_unavailable",
                "reason": "road surface, diversion belt and RCSDIntersection are unavailable",
            },
        },
        "outputs": {
            "project": str(project_path),
            "preview": str(preview_path),
            "layer_manifest": str(manifest_csv_path),
            "qa": str(qa_path),
        },
    }
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    return qa


def cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and verify the P02 Wuhan QGIS project.")
    parser.add_argument("--package-root", required=True, type=Path)
    args = parser.parse_args(argv)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        qa = build(args.package_root)
        print(json.dumps(qa, ensure_ascii=False, indent=2))
        return 0 if qa["status"] != "failed" else 1
    finally:
        QgsProject.instance().clear()
        app.exitQgis()


def _csv_uri(path: Path) -> str:
    url = QUrl.fromLocalFile(str(path)).toString()
    return f"{url}?type=csv&delimiter=,&detectTypes=yes&geomType=none&subsetIndex=no&watchFile=no"


def _symbolize(layer: QgsVectorLayer, color: str, width_or_size: float, opacity: float) -> None:
    geometry_type = layer.geometryType()
    if geometry_type == QgsWkbTypes.PointGeometry:
        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": color,
                "size": str(width_or_size),
                "outline_color": "#ffffff",
                "outline_width": "0.25",
            }
        )
    elif geometry_type == QgsWkbTypes.LineGeometry:
        symbol = QgsLineSymbol.createSimple(
            {
                "line_color": color,
                "line_width": str(width_or_size),
                "capstyle": "round",
                "joinstyle": "round",
            }
        )
    elif geometry_type == QgsWkbTypes.PolygonGeometry:
        symbol = QgsFillSymbol.createSimple(
            {
                "color": color,
                "outline_color": color,
                "outline_width": str(max(width_or_size / 2, 0.25)),
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
        transform = QgsCoordinateTransform(
            layer.crs(),
            project.crs(),
            project.transformContext(),
        )
        extent = transform.transformBoundingBox(extent)
    return extent


def _render_preview(project: QgsProject, extent: QgsRectangle, output_path: Path) -> bool:
    settings = QgsMapSettings()
    settings.setDestinationCrs(project.crs())
    settings.setLayers(project.layerTreeRoot().checkedLayers())
    preview_extent = QgsRectangle(extent)
    preview_extent.scale(1.08)
    settings.setExtent(preview_extent)
    settings.setOutputSize(QSize(1800, 1200))
    settings.setOutputDpi(120)
    settings.setBackgroundColor(QColor("#f7f7f7"))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    return bool(job.renderedImage().save(str(output_path), "PNG"))


def _write_layer_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = tuple(rows[0]) if rows else (
        "group",
        "layer_name",
        "relative_path",
        "provider",
        "geometry_type",
        "feature_count",
        "crs",
        "visible_by_default",
        "source_sha256",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _validate_embedded_qgs(project_path: Path) -> tuple[bool, int]:
    if not project_path.is_file():
        return False, 0
    with zipfile.ZipFile(project_path) as archive:
        qgs_names = [name for name in archive.namelist() if name.lower().endswith(".qgs")]
        if len(qgs_names) != 1:
            return False, 0
        xml_bytes = archive.read(qgs_names[0])
    xml_root = ET.fromstring(xml_bytes)
    datasource_values = [
        (element.text or "").strip()
        for element in xml_root.iter("datasource")
        if (element.text or "").strip()
    ]
    absolute_count = sum(
        value.startswith(("/mnt/", "file:///", "file://"))
        or bool(re.match(r"^[A-Za-z]:[/\\\\]", value))
        for value in datasource_values
    )
    return True, absolute_count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["build", "cli"]
