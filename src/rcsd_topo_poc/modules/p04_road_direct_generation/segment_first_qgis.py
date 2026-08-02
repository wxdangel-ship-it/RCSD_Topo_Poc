from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import fiona
from pyproj import CRS

from .segment_first_progress import (
    advance_progress,
    begin_progress_stage,
    finish_progress_stage,
)


@dataclass(frozen=True)
class QgisProjectResult:
    project_path: Path
    layer_count: int
    readback_pass: bool
    missing_layers: tuple[str, ...]


def build_qgis_project(output_dir: Path, *, run_id: str) -> QgisProjectResult:
    specs = [
        ("01A_当前结果", "结果 Road", "p04_segment_first_rcsd.gpkg", "Road", True),
        ("01A_当前结果", "结果 Node", "p04_segment_first_rcsd.gpkg", "Node", False),
        ("01A_当前结果", "结果 RoadNextRoad", "p04_segment_first_rcsd.gpkg", "RoadNextRoad", False),
        ("01A_当前结果", "结果 built Road", "p04_segment_first_comparison.gpkg", "new_built_roads", False),
        ("01A_当前结果", "结果 retained Road", "p04_segment_first_comparison.gpkg", "new_retained_roads", False),
        ("01B_原始SWSD", "SWSD Road", "p04_segment_first_comparison.gpkg", "original_swsd_roads", True),
        ("01B_原始SWSD", "SWSD Node", "p04_segment_first_comparison.gpkg", "original_swsd_nodes", False),
        ("01C_原始完整RCSD", "完整 RCSD Road", "p04_segment_first_comparison.gpkg", "original_rcsd_roads", True),
        ("01C_原始完整RCSD", "完整 RCSD Node", "p04_segment_first_comparison.gpkg", "original_rcsd_nodes", False),
        ("01D_Patch级RC", "Patch Road", "p04_segment_first_comparison.gpkg", "original_patch_roads", True),
        ("01_历史基线", "冻结 V3 Road", "p04_segment_first_comparison.gpkg", "frozen_v3_roads", False),
        ("02_Patch高精证据", "Patch Road 居中走廊", "p04_segment_first_comparison.gpkg", "patch_road_centers", False),
        ("02_Patch高精证据", "原始 Lane", "p04_segment_first_comparison.gpkg", "patch_lanes", False),
        ("02_Patch高精证据", "LaneBoundary", "p04_segment_first_comparison.gpkg", "patch_boundaries", False),
        ("02_Patch高精证据", "DriveZone", "p04_segment_first_comparison.gpkg", "drivezones", False),
        ("03A_路口面审计", "P04 JunctionUnit（最终使用）", "p04_segment_first_audit.gpkg", "junction_units", True),
        ("03A_路口面审计", "P04 Road端点选用路口面", "p04_segment_first_audit.gpkg", "junction_endpoint_surfaces", True),
        ("03A_路口面审计", "T07 人工确认路口面", "p04_segment_first_comparison.gpkg", "t07_accepted_surfaces", True),
        ("03A_路口面审计", "Patch 原始 Intersection", "p04_segment_first_comparison.gpkg", "patch_intersections", False),
        ("03A_路口面审计", "T03 accepted 路口面", "p04_segment_first_comparison.gpkg", "t03_accepted_surfaces", False),
        ("03A_路口面审计", "T04 accepted 分合流面", "p04_segment_first_comparison.gpkg", "t04_accepted_surfaces", False),
        ("03_Segment与Junction", "Segment Build Unit", "p04_segment_first_audit.gpkg", "segment_build_units", False),
        ("03_Segment与Junction", "SWSD完整Segment参考轴", "p04_segment_first_audit.gpkg", "segment_reference_axis_audit", False),
        ("03_Segment与Junction", "SWSD方向Road路径合同", "p04_segment_first_audit.gpkg", "swsd_segment_directional_paths", False),
        ("03_Segment与Junction", "Segment Access", "p04_segment_first_audit.gpkg", "segment_accesses", False),
        ("03_Segment与Junction", "Segment Access Realization", "p04_segment_first_audit.gpkg", "segment_access_realization", False),
        ("03_Segment与Junction", "SWSD路口方向合同", "p04_segment_first_audit.gpkg", "swsd_topology_contract", False),
        ("03_Segment与Junction", "SWSD路口Movement合同", "p04_segment_first_audit.gpkg", "swsd_junction_movement_contract", False),
        ("03_Segment与Junction", "SWSD完整路口结构", "p04_segment_first_audit.gpkg", "swsd_junction_structure", False),
        ("03_Segment与Junction", "方向主干链验收", "p04_segment_first_comparison.gpkg", "target_realization", False),
        ("03_Segment与Junction", "DirectBuild硬目标", "p04_segment_first_comparison.gpkg", "target_direct_build_required", False),
        ("06_质量审计", "Patch资料不足", "p04_segment_first_comparison.gpkg", "target_patch_data_insufficient", True),
        ("06_质量审计", "RealityChange线索", "p04_segment_first_comparison.gpkg", "target_reality_change_clues", True),
        ("04_Carrier与几何", "Road Carrier Plan", "p04_segment_first_audit.gpkg", "road_carriers", False),
        ("04_Carrier与几何", "路口门户审计", "p04_segment_first_audit.gpkg", "junction_internal_carriers", False),
        ("04_Carrier与几何", "Geometry Source", "p04_segment_first_audit.gpkg", "road_geometry_sources", False),
        ("04_Carrier与几何", "Endpoint Coordination", "p04_segment_first_audit.gpkg", "endpoint_coordination", False),
        ("04_Carrier与几何", "Node Connection Evidence", "p04_segment_first_audit.gpkg", "node_connection_evidence", False),
        ("04_Carrier与几何", "Road Geometry Quality", "p04_segment_first_audit.gpkg", "road_geometry_quality", False),
        ("04_Carrier与几何", "Movement Split Audit", "p04_segment_first_audit.gpkg", "movement_split_audit", False),
        ("04_Carrier与几何", "Road证据边界切分", "p04_segment_first_audit.gpkg", "road_lineage_split_audit", False),
        ("04_Carrier与几何", "冗余 retained Road 抑制", "p04_segment_first_audit.gpkg", "redundant_retained_suppressions", False),
        ("04_Carrier与几何", "Built Road Continuity", "p04_segment_first_audit.gpkg", "built_road_continuity", False),
        ("05_LaneTopo与关系", "LaneTopo Projection", "p04_segment_first_audit.gpkg", "lane_topo_projection", False),
        ("05_LaneTopo与关系", "Road-Lane Relation", "p04_segment_first_relations.gpkg", "road_lane_relation", False),
        ("06_质量审计", "Soft Review", "p04_segment_first_audit.gpkg", "soft_review_features", False),
        ("06_质量审计", "Segment Fallback Trigger", "p04_segment_first_audit.gpkg", "segment_fallback_triggers", False),
        ("06_质量审计", "LaneTopo Connection Exclusion", "p04_segment_first_audit.gpkg", "lane_topo_connection_exclusions", False),
        ("06_质量审计", "Geometry Fallback Trigger", "p04_segment_first_audit.gpkg", "geometry_fallback_triggers", False),
        ("06_质量审计", "Access Fallback Trigger", "p04_segment_first_audit.gpkg", "access_fallback_triggers", False),
        ("06_质量审计", "Continuity Fallback Trigger", "p04_segment_first_audit.gpkg", "continuity_fallback_triggers", False),
        ("06_质量审计", "SWSD拓扑回退触发", "p04_segment_first_audit.gpkg", "swsd_topology_fallback_triggers", False),
        ("06_质量审计", "Junction Carrier Suppression", "p04_segment_first_audit.gpkg", "junction_carrier_suppressions", False),
        ("06_质量审计", "Independent Quality", "p04_segment_first_independent_quality.gpkg", "quality_metrics", False),
        ("06_质量审计", "Hard Gate Violations", "p04_segment_first_independent_quality.gpkg", "hard_gate_violations", True),
    ]
    optional_names = {
        "冻结 V3 Road",
        "方向主干链验收",
        "DirectBuild硬目标",
        "Patch资料不足",
        "RealityChange线索",
        "Movement Split Audit",
        "Road证据边界切分",
        "Built Road Continuity",
        "Soft Review",
        "Segment Fallback Trigger",
        "路口门户审计",
        "P04 JunctionUnit（最终使用）",
        "P04 Road端点选用路口面",
        "T07 人工确认路口面",
        "Patch 原始 Intersection",
        "T03 accepted 路口面",
        "T04 accepted 分合流面",
        "冗余 retained Road 抑制",
        "LaneTopo Connection Exclusion",
        "Geometry Fallback Trigger",
        "Access Fallback Trigger",
        "Continuity Fallback Trigger",
        "SWSD拓扑回退触发",
        "Junction Carrier Suppression",
        "Hard Gate Violations",
    }
    available = []
    missing = []
    begin_progress_stage(
        "qgis_layer_discovery",
        len(specs),
        detail="QGIS comparison layer inventory",
    )
    for spec_index, (group, name, filename, layer, visible) in enumerate(specs):
        path = output_dir / filename
        if path.is_file() and layer in fiona.listlayers(path):
            with fiona.open(path, layer=layer) as source:
                geometry_type = source.schema.get("geometry", "Unknown")
                layer_crs = (
                    CRS.from_wkt(source.crs_wkt)
                    if source.crs_wkt
                    else None
                )
            available.append(
                (
                    group,
                    name,
                    filename,
                    layer,
                    visible,
                    geometry_type,
                    layer_crs,
                )
            )
        elif name not in optional_names:
            missing.append(name)
        advance_progress(
            "qgis_layer_discovery",
            completed=spec_index + 1,
            last_unit=name,
            counters={
                "available_layers": len(available),
                "missing_required_layers": len(missing),
            },
        )
    finish_progress_stage(
        "qgis_layer_discovery",
        counters={
            "available_layers": len(available),
            "missing_required_layers": len(missing),
        },
    )
    root = ET.Element("qgis", {"projectname": run_id, "version": "3.34.0"})
    project_crs = next(
        (item[6] for item in available if item[6] is not None),
        None,
    )
    if project_crs is not None:
        _append_project_crs_settings(root, project_crs)
    tree_root = ET.SubElement(root, "layer-tree-group", {"name": "", "checked": "Qt::Checked", "expanded": "1"})
    project_layers = ET.SubElement(root, "projectlayers")
    groups: dict[str, ET.Element] = {}
    begin_progress_stage(
        "qgis_project_layers",
        len(available),
        detail="QGIS XML layer materialization",
        counters={"missing_required_layers": len(missing)},
    )
    for ordinal, (
        group,
        name,
        filename,
        layer,
        visible,
        geometry_type,
        layer_crs,
    ) in enumerate(available):
        if group not in groups:
            groups[group] = ET.SubElement(
                tree_root,
                "layer-tree-group",
                {"name": group, "checked": "Qt::Checked", "expanded": "1"},
            )
        group_element = groups[group]
        layer_id = f"p04_segment_first_{ordinal}_{layer}"
        ET.SubElement(
            group_element,
            "layer-tree-layer",
            {"id": layer_id, "name": name, "checked": "Qt::Checked" if visible else "Qt::Unchecked", "expanded": "1"},
        )
        qgis_geometry = _qgis_geometry_type(geometry_type)
        maplayer = ET.SubElement(
            project_layers,
            "maplayer",
            {"type": "vector", "geometry": qgis_geometry, "simplifyDrawingHints": "1"},
        )
        ET.SubElement(maplayer, "id").text = layer_id
        ET.SubElement(maplayer, "layername").text = name
        if layer_crs is not None:
            _append_qgis_crs(maplayer, "srs", layer_crs)
        ET.SubElement(maplayer, "datasource").text = f"./{filename}|layername={layer}"
        ET.SubElement(maplayer, "provider", {"encoding": "UTF-8"}).text = "ogr"
        if name == "方向主干链验收":
            _append_target_realization_renderer(maplayer)
        elif name == "SWSD完整Segment参考轴":
            _append_reference_axis_renderer(maplayer)
        elif name == "SWSD路口方向合同":
            _append_swsd_topology_renderer(maplayer)
        elif name == "SWSD路口Movement合同":
            _append_swsd_topology_renderer(
                maplayer,
                attribute="movement_topology_preserved",
                pass_label="PASS：SWSD路口Movement完整保留",
                fail_label="FAIL：SWSD路口Movement缺失或新增",
            )
        elif name == "Endpoint Coordination":
            _append_endpoint_surface_renderer(maplayer)
        else:
            _append_single_symbol_renderer(
                maplayer,
                qgis_geometry,
                *_layer_style(name),
            )
        advance_progress(
            "qgis_project_layers",
            completed=ordinal + 1,
            last_unit=name,
            counters={"materialized_layers": ordinal + 1},
        )
    ET.SubElement(root, "homePath", {"path": "."})
    qgs_path = output_dir / "p04_segment_first_comparison.qgs"
    ET.ElementTree(root).write(qgs_path, encoding="utf-8", xml_declaration=True)
    qgz_path = output_dir / "p04_segment_first_comparison.qgz"
    with zipfile.ZipFile(qgz_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(qgs_path, arcname=qgs_path.name)
    readback = _readback(qgz_path, len(available))
    finish_progress_stage(
        "qgis_project_layers",
        counters={
            "materialized_layers": len(available),
            "readback_pass": str(readback and not missing).lower(),
        },
    )
    return QgisProjectResult(qgz_path, len(available), readback and not missing, tuple(missing))


def _qgis_geometry_type(value: str) -> str:
    lowered = str(value).lower()
    if "point" in lowered:
        return "Point"
    if "polygon" in lowered:
        return "Polygon"
    if "line" in lowered:
        return "Line"
    return "Unknown"


def _append_qgis_crs(
    parent: ET.Element,
    tag: str,
    crs: CRS,
) -> None:
    container = ET.SubElement(parent, tag)
    spatial = ET.SubElement(
        container,
        "spatialrefsys",
        {"nativeFormat": "Wkt"},
    )
    authority = crs.to_authority()
    authid = (
        f"{authority[0]}:{authority[1]}"
        if authority is not None
        else ""
    )
    srid = authority[1] if authority is not None else "0"
    values = {
        "wkt": crs.to_wkt(),
        "proj4": crs.to_proj4(),
        "srsid": srid,
        "srid": srid,
        "authid": authid,
        "description": crs.name,
        "projectionacronym": "",
        "ellipsoidacronym": "",
        "geographicflag": str(crs.is_geographic).lower(),
    }
    for name, value in values.items():
        ET.SubElement(spatial, name).text = str(value)


def _append_project_crs_settings(
    root: ET.Element,
    crs: CRS,
) -> None:
    _append_qgis_crs(root, "projectCrs", crs)
    properties = ET.SubElement(root, "properties")
    spatial = ET.SubElement(properties, "SpatialRefSys")
    ET.SubElement(
        spatial,
        "ProjectionsEnabled",
        {"type": "int"},
    ).text = "1"


def _layer_style(name: str) -> tuple[str, float, float, str]:
    styles = {
        "结果 Road": ("0,168,107,255", 1.00, 0.95, "solid"),
        "结果 built Road": ("0,168,107,255", 0.90, 0.95, "solid"),
        "结果 retained Road": ("67,97,238,255", 0.70, 0.85, "solid"),
        "结果 Node": ("0,121,78,255", 2.0, 0.95, "solid"),
        "结果 RoadNextRoad": ("14,116,144,255", 0.45, 0.75, "dash"),
        "SWSD Road": ("245,158,11,255", 0.75, 0.80, "dash"),
        "SWSD Node": ("245,158,11,255", 1.7, 0.90, "solid"),
        "完整 RCSD Road": ("217,70,239,255", 0.65, 0.75, "solid"),
        "完整 RCSD Node": ("217,70,239,255", 1.6, 0.90, "solid"),
        "Patch Road": ("8,145,178,255", 0.40, 0.70, "solid"),
        "冻结 V3 Road": ("124,58,237,255", 0.45, 0.55, "dash"),
        "Patch Road 居中走廊": ("8,145,178,255", 0.35, 0.75, "solid"),
        "原始 Lane": ("100,116,139,255", 0.18, 0.45, "solid"),
        "LaneBoundary": ("71,85,105,255", 0.15, 0.35, "dash"),
        "DriveZone": ("203,213,225,255", 0.20, 0.35, "solid"),
        "P04 JunctionUnit（最终使用）": ("239,68,68,255", 0.70, 0.30, "solid"),
        "P04 Road端点选用路口面": ("126,34,206,255", 0.80, 0.22, "solid"),
        "T07 人工确认路口面": ("147,51,234,255", 0.60, 0.24, "solid"),
        "Patch 原始 Intersection": ("14,165,233,255", 0.45, 0.18, "solid"),
        "T03 accepted 路口面": ("245,158,11,255", 0.55, 0.20, "solid"),
        "T04 accepted 分合流面": ("236,72,153,255", 0.55, 0.20, "solid"),
        "冗余 retained Road 抑制": ("220,38,38,255", 1.6, 0.90, "dash"),
        "Soft Review": ("220,38,38,255", 2.4, 0.95, "solid"),
        "Segment Fallback Trigger": ("239,68,68,255", 2.0, 0.90, "solid"),
        "Geometry Fallback Trigger": ("234,88,12,255", 2.0, 0.90, "solid"),
        "Access Fallback Trigger": ("202,138,4,255", 2.0, 0.90, "solid"),
        "Continuity Fallback Trigger": ("190,24,93,255", 2.0, 0.90, "solid"),
        "SWSD拓扑回退触发": ("220,38,38,255", 2.2, 0.95, "solid"),
        "Movement Split Audit": ("147,51,234,255", 1.8, 0.90, "solid"),
        "Road证据边界切分": ("124,58,237,255", 2.0, 0.95, "solid"),
        "路口门户审计": ("5,150,105,255", 2.0, 0.90, "solid"),
        "方向主干链验收": ("30,64,175,255", 1.2, 0.85, "solid"),
        "LaneTopo Connection Exclusion": ("225,29,72,255", 1.8, 0.90, "dash"),
        "Built Road Continuity": ("6,182,212,255", 1.8, 0.90, "solid"),
    }
    return styles.get(name, ("100,116,139,255", 0.35, 0.65, "solid"))


def _append_single_symbol_renderer(
    maplayer: ET.Element,
    geometry_type: str,
    color: str,
    width_or_size: float,
    opacity: float,
    line_style: str,
) -> None:
    renderer = ET.SubElement(
        maplayer,
        "renderer-v2",
        {
            "type": "singleSymbol",
            "symbollevels": "0",
            "forceraster": "0",
            "enableorderby": "0",
            "referencescale": "-1",
        },
    )
    symbols = ET.SubElement(renderer, "symbols")
    symbol_type = (
        "marker"
        if geometry_type == "Point"
        else "fill"
        if geometry_type == "Polygon"
        else "line"
    )
    symbol = ET.SubElement(
        symbols,
        "symbol",
        {"name": "0", "type": symbol_type, "alpha": "1", "clip_to_extent": "1"},
    )
    if symbol_type == "marker":
        symbol_layer = ET.SubElement(
            symbol,
            "layer",
            {"class": "SimpleMarker", "enabled": "1", "locked": "0", "pass": "0"},
        )
        options = {
            "name": "circle",
            "color": color,
            "outline_color": "255,255,255,255",
            "size": str(width_or_size),
            "size_unit": "MM",
        }
    elif symbol_type == "fill":
        symbol_layer = ET.SubElement(
            symbol,
            "layer",
            {"class": "SimpleFill", "enabled": "1", "locked": "0", "pass": "0"},
        )
        options = {
            "color": color,
            "outline_color": color,
            "outline_style": "solid",
            "outline_width": "0.15",
            "outline_width_unit": "MM",
            "style": "solid",
        }
    else:
        symbol_layer = ET.SubElement(
            symbol,
            "layer",
            {"class": "SimpleLine", "enabled": "1", "locked": "0", "pass": "0"},
        )
        options = {
            "line_color": color,
            "line_style": line_style,
            "line_width": str(width_or_size),
            "line_width_unit": "MM",
            "capstyle": "round",
            "joinstyle": "round",
        }
    option_map = ET.SubElement(symbol_layer, "Option", {"type": "Map"})
    for key, value in options.items():
        ET.SubElement(
            option_map,
            "Option",
            {"name": key, "value": value, "type": "QString"},
        )
    ET.SubElement(maplayer, "layerOpacity").text = str(opacity)


def _append_target_realization_renderer(maplayer: ET.Element) -> None:
    renderer = ET.SubElement(
        maplayer,
        "renderer-v2",
        {
            "type": "categorizedSymbol",
            "attr": "publish_disposition",
            "symbollevels": "0",
            "forceraster": "0",
            "enableorderby": "0",
            "referencescale": "-1",
        },
    )
    categories = ET.SubElement(renderer, "categories")
    for value, label, symbol_id in (
        ("hp_published", "PASS：高精方向主干已发布", "0"),
        ("conflict_retained", "FAIL：高精证据硬冲突", "1"),
        (
            "swsd_retained_partial_evidence",
            "FAIL：部分高精证据未闭合",
            "2",
        ),
        (
            "swsd_retained_data_insufficient",
            "例外：Patch资料不足，完整保留",
            "3",
        ),
        (
            "swsd_retained_reality_change_pending",
            "例外：RealityChange待二次标准化",
            "4",
        ),
    ):
        ET.SubElement(
            categories,
            "category",
            {
                "value": value,
                "label": label,
                "symbol": symbol_id,
                "render": "true",
            },
        )
    symbols = ET.SubElement(renderer, "symbols")
    for symbol_id, color, width, line_style in (
        ("0", "22,163,74,255", "1.2", "solid"),
        ("1", "220,38,38,255", "1.8", "dash"),
        ("2", "234,88,12,255", "1.8", "dash"),
        ("3", "100,116,139,255", "1.6", "dash"),
        ("4", "147,51,234,255", "1.8", "dash"),
    ):
        symbol = ET.SubElement(
            symbols,
            "symbol",
            {
                "name": symbol_id,
                "type": "line",
                "alpha": "1",
                "clip_to_extent": "1",
            },
        )
        symbol_layer = ET.SubElement(
            symbol,
            "layer",
            {
                "class": "SimpleLine",
                "enabled": "1",
                "locked": "0",
                "pass": "0",
            },
        )
        option_map = ET.SubElement(symbol_layer, "Option", {"type": "Map"})
        for key, value in {
            "line_color": color,
            "line_style": line_style,
            "line_width": width,
            "line_width_unit": "MM",
            "capstyle": "round",
            "joinstyle": "round",
        }.items():
            ET.SubElement(
                option_map,
                "Option",
                {"name": key, "value": value, "type": "QString"},
            )
    ET.SubElement(maplayer, "layerOpacity").text = "0.9"


def _append_endpoint_surface_renderer(maplayer: ET.Element) -> None:
    renderer = ET.SubElement(
        maplayer,
        "renderer-v2",
        {
            "type": "categorizedSymbol",
            "attr": "junction_surface_strict_inside",
            "symbollevels": "0",
            "forceraster": "0",
            "enableorderby": "0",
            "referencescale": "-1",
        },
    )
    categories = ET.SubElement(renderer, "categories")
    for value, label, symbol_id in (
        ("1", "PASS：Road端点已进入路口面", "0"),
        ("0", "FAIL：Road端点未进入路口面", "1"),
        ("", "不适用：retained或无高精路口面", "2"),
    ):
        ET.SubElement(
            categories,
            "category",
            {
                "value": value,
                "label": label,
                "symbol": symbol_id,
                "render": "true",
            },
        )
    symbols = ET.SubElement(renderer, "symbols")
    for symbol_id, color, size in (
        ("0", "22,163,74,255", "1.8"),
        ("1", "220,38,38,255", "3.0"),
        ("2", "100,116,139,255", "1.2"),
    ):
        symbol = ET.SubElement(
            symbols,
            "symbol",
            {
                "name": symbol_id,
                "type": "marker",
                "alpha": "1",
                "clip_to_extent": "1",
            },
        )
        layer = ET.SubElement(
            symbol,
            "layer",
            {
                "class": "SimpleMarker",
                "enabled": "1",
                "locked": "0",
                "pass": "0",
            },
        )
        option_map = ET.SubElement(layer, "Option", {"type": "Map"})
        for key, value in {
            "name": "circle",
            "color": color,
            "outline_color": "255,255,255,255",
            "size": size,
            "size_unit": "MM",
        }.items():
            ET.SubElement(
                option_map,
                "Option",
                {"name": key, "value": value, "type": "QString"},
            )
    ET.SubElement(maplayer, "layerOpacity").text = "0.95"


def _append_swsd_topology_renderer(
    maplayer: ET.Element,
    *,
    attribute: str = "topology_preserved",
    pass_label: str = "PASS：SWSD进出方向完整保留",
    fail_label: str = "FAIL：SWSD进出方向缺失或新增",
) -> None:
    renderer = ET.SubElement(
        maplayer,
        "renderer-v2",
        {
            "type": "categorizedSymbol",
            "attr": attribute,
            "symbollevels": "0",
            "forceraster": "0",
            "enableorderby": "0",
            "referencescale": "-1",
        },
    )
    categories = ET.SubElement(renderer, "categories")
    for value, label, symbol_id in (
        ("1", pass_label, "0"),
        ("0", fail_label, "1"),
    ):
        ET.SubElement(
            categories,
            "category",
            {
                "value": value,
                "label": label,
                "symbol": symbol_id,
                "render": "true",
            },
        )
    symbols = ET.SubElement(renderer, "symbols")
    for symbol_id, color, size in (
        ("0", "22,163,74,255", "1.6"),
        ("1", "220,38,38,255", "2.6"),
    ):
        symbol = ET.SubElement(
            symbols,
            "symbol",
            {
                "name": symbol_id,
                "type": "marker",
                "alpha": "1",
                "clip_to_extent": "1",
            },
        )
        symbol_layer = ET.SubElement(
            symbol,
            "layer",
            {
                "class": "SimpleMarker",
                "enabled": "1",
                "locked": "0",
                "pass": "0",
            },
        )
        option_map = ET.SubElement(
            symbol_layer,
            "Option",
            {"type": "Map"},
        )
        for key, value in {
            "name": "circle",
            "color": color,
            "outline_color": "255,255,255,255",
            "size": size,
            "size_unit": "MM",
        }.items():
            ET.SubElement(
                option_map,
                "Option",
                {"name": key, "value": value, "type": "QString"},
            )
    ET.SubElement(maplayer, "layerOpacity").text = "0.9"


def _append_reference_axis_renderer(maplayer: ET.Element) -> None:
    renderer = ET.SubElement(
        maplayer,
        "renderer-v2",
        {
            "type": "categorizedSymbol",
            "attr": "reference_source",
            "symbollevels": "0",
            "forceraster": "0",
            "enableorderby": "0",
            "referencescale": "-1",
        },
    )
    categories = ET.SubElement(renderer, "categories")
    for value, label, symbol_id in (
        (
            "swsd_endpoint_topology_chain",
            "exact Node连续：允许牵引高精证据",
            "0",
        ),
        (
            "swsd_endpoint_mainnode_topology_chain",
            "ordinary mainnode连续：仅语义审计",
            "1",
        ),
        ("", "SWSD端点路径未解析", "2"),
    ):
        ET.SubElement(
            categories,
            "category",
            {
                "value": value,
                "label": label,
                "symbol": symbol_id,
                "render": "true",
            },
        )
    symbols = ET.SubElement(renderer, "symbols")
    for symbol_id, color, width, line_style in (
        ("0", "245,158,11,255", "1.0", "solid"),
        ("1", "147,51,234,255", "1.2", "dash"),
        ("2", "220,38,38,255", "1.4", "dot"),
    ):
        symbol = ET.SubElement(
            symbols,
            "symbol",
            {
                "name": symbol_id,
                "type": "line",
                "alpha": "1",
                "clip_to_extent": "1",
            },
        )
        symbol_layer = ET.SubElement(
            symbol,
            "layer",
            {
                "class": "SimpleLine",
                "enabled": "1",
                "locked": "0",
                "pass": "0",
            },
        )
        option_map = ET.SubElement(symbol_layer, "Option", {"type": "Map"})
        for key, value in {
            "line_color": color,
            "line_style": line_style,
            "line_width": width,
            "line_width_unit": "MM",
            "capstyle": "round",
            "joinstyle": "round",
        }.items():
            ET.SubElement(
                option_map,
                "Option",
                {"name": key, "value": value, "type": "QString"},
            )
    ET.SubElement(maplayer, "layerOpacity").text = "0.9"


def _readback(path: Path, expected_layers: int) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            qgs = next(name for name in names if name.endswith(".qgs"))
            root = ET.fromstring(archive.read(qgs))
        return len(root.findall("./projectlayers/maplayer")) == expected_layers
    except (OSError, ValueError, StopIteration, ET.ParseError, zipfile.BadZipFile):
        return False


__all__ = ["QgisProjectResult", "build_qgis_project"]
