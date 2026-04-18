from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_vector
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import load_case_specs
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import build_step1_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step2_template import classify_step2_template
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import build_step3_case_result


def node_feature(
    node_id: str,
    x: float,
    y: float,
    *,
    mainnodeid: str | None = None,
    kind_2: int = 4,
    has_evd: str = "yes",
    is_anchor: str = "no",
) -> dict:
    return {
        "properties": {
            "id": node_id,
            "mainnodeid": mainnodeid or node_id,
            "has_evd": has_evd,
            "is_anchor": is_anchor,
            "kind_2": kind_2,
            "grade_2": 1,
        },
        "geometry": Point(x, y),
    }


def road_feature(
    road_id: str,
    snodeid: str,
    enodeid: str,
    coords: list[tuple[float, float]],
    *,
    direction: int = 2,
) -> dict:
    return {
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
        },
        "geometry": LineString(coords),
    }


def write_case_package(
    case_root: Path,
    case_id: str,
    *,
    kind_2: int = 4,
    roads: list[dict] | None = None,
    extra_nodes: list[dict] | None = None,
    rcsd_roads: list[dict] | None = None,
    rcsd_nodes: list[dict] | None = None,
    has_evd: str = "yes",
    is_anchor: str = "no",
    drivezone_geometry=None,
    drivezone_geometries: list | None = None,
) -> None:
    case_root.mkdir(parents=True, exist_ok=True)
    base_node = node_feature(case_id, 0.0, 0.0, mainnodeid=case_id, kind_2=kind_2, has_evd=has_evd, is_anchor=is_anchor)
    write_vector(case_root / "nodes.gpkg", [base_node, *(extra_nodes or [])])
    write_vector(case_root / "roads.gpkg", roads or [])
    write_vector(case_root / "rcsdroad.gpkg", rcsd_roads or [])
    write_vector(case_root / "rcsdnode.gpkg", rcsd_nodes or [])
    write_vector(
        case_root / "drivezone.gpkg",
        [
            {
                "properties": {"id": f"dz_{idx}"},
                "geometry": geometry,
            }
            for idx, geometry in enumerate(drivezone_geometries or [drivezone_geometry or box(-60.0, -60.0, 120.0, 60.0)])
        ],
    )
    manifest = {
        "bundle_version": 1,
        "mainnodeid": case_id,
        "epsg": 3857,
        "file_list": [
            "manifest.json",
            "size_report.json",
            "drivezone.gpkg",
            "nodes.gpkg",
            "roads.gpkg",
            "rcsdroad.gpkg",
            "rcsdnode.gpkg",
        ],
        "decoded_output": {"vector_crs": "EPSG:3857"},
    }
    size_report = {"within_limit": True, "limit_bytes": 307200}
    (case_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (case_root / "size_report.json").write_text(json.dumps(size_report, ensure_ascii=False, indent=2), encoding="utf-8")


def run_case_bundle(suite_root: Path, case_id: str) -> tuple[object, object, object]:
    specs, _ = load_case_specs(case_root=suite_root, case_ids=[case_id])
    context = build_step1_context(specs[0])
    template_result = classify_step2_template(context)
    case_result = build_step3_case_result(context, template_result)
    return context, template_result, case_result
