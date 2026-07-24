from __future__ import annotations

import xml.etree.ElementTree as ET
from pyproj import CRS

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_qgis import (
    _append_project_crs_settings,
    _append_qgis_crs,
    _append_reference_axis_renderer,
    _append_swsd_topology_renderer,
    _append_target_realization_renderer,
)


def test_target_realization_qgis_renderer_distinguishes_pass_and_fail() -> None:
    maplayer = ET.Element("maplayer")

    _append_target_realization_renderer(maplayer)

    renderer = maplayer.find("renderer-v2")
    assert renderer is not None
    assert renderer.attrib["type"] == "categorizedSymbol"
    assert renderer.attrib["attr"] == "publish_disposition"
    categories = renderer.findall("./categories/category")
    assert {(item.attrib["value"], item.attrib["symbol"]) for item in categories} == {
        ("hp_published", "0"),
        ("conflict_retained", "1"),
        ("swsd_retained_partial_evidence", "2"),
        ("swsd_retained_data_insufficient", "3"),
        ("swsd_retained_reality_change_pending", "4"),
    }
    colors = {
        option.attrib["value"]
        for option in renderer.findall(
            "./symbols/symbol/layer/Option/Option[@name='line_color']"
        )
    }
    assert colors == {
        "22,163,74,255",
        "220,38,38,255",
        "234,88,12,255",
        "100,116,139,255",
        "147,51,234,255",
    }


def test_reference_axis_renderer_distinguishes_guidance_and_audit() -> None:
    maplayer = ET.Element("maplayer")

    _append_reference_axis_renderer(maplayer)

    renderer = maplayer.find("renderer-v2")
    assert renderer is not None
    assert renderer.attrib["type"] == "categorizedSymbol"
    assert renderer.attrib["attr"] == "reference_source"
    categories = renderer.findall("./categories/category")
    assert {
        (item.attrib["value"], item.attrib["symbol"])
        for item in categories
    } == {
        ("swsd_endpoint_topology_chain", "0"),
        ("swsd_endpoint_mainnode_topology_chain", "1"),
        ("", "2"),
    }
    colors = {
        option.attrib["value"]
        for option in renderer.findall(
            "./symbols/symbol/layer/Option/Option[@name='line_color']"
        )
    }
    assert colors == {
        "245,158,11,255",
        "147,51,234,255",
        "220,38,38,255",
    }


def test_swsd_topology_renderer_distinguishes_preserved_and_failed() -> None:
    maplayer = ET.Element("maplayer")

    _append_swsd_topology_renderer(maplayer)

    renderer = maplayer.find("renderer-v2")
    assert renderer is not None
    assert renderer.attrib["type"] == "categorizedSymbol"
    assert renderer.attrib["attr"] == "topology_preserved"
    categories = renderer.findall("./categories/category")
    assert {
        (item.attrib["value"], item.attrib["symbol"])
        for item in categories
    } == {
        ("1", "0"),
        ("0", "1"),
    }
    colors = {
        option.attrib["value"]
        for option in renderer.findall(
            "./symbols/symbol/layer/Option/Option[@name='color']"
        )
    }
    assert colors == {"22,163,74,255", "220,38,38,255"}


def test_qgis_crs_serialization_preserves_projected_authid() -> None:
    root = ET.Element("qgis")

    _append_qgis_crs(root, "projectCrs", CRS.from_epsg(32650))

    spatial = root.find("./projectCrs/spatialrefsys")
    assert spatial is not None
    assert spatial.findtext("authid") == "EPSG:32650"
    assert spatial.findtext("srsid") == "32650"
    assert spatial.findtext("srid") == "32650"
    assert "+proj=utm" in spatial.findtext("proj4", "")
    assert spatial.findtext("geographicflag") == "false"
    assert "WGS 84 / UTM zone 50N" in spatial.findtext("wkt", "")


def test_project_crs_settings_enable_qgis_projection_loading() -> None:
    root = ET.Element("qgis")

    _append_project_crs_settings(root, CRS.from_epsg(32650))

    assert root.findtext(
        "./properties/SpatialRefSys/ProjectionsEnabled"
    ) == "1"
