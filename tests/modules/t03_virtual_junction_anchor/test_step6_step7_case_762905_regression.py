from __future__ import annotations

from pathlib import Path

import fiona
import pytest
from shapely.geometry import shape

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import (
    load_association_case_specs,
    load_association_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import load_case_specs
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import FinalizationContext
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_outputs import (
    write_case_outputs as write_step3_case_outputs,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import build_step1_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step2_template import classify_step2_template
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import build_step3_case_result
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import (
    build_association_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_geometry import build_step6_result
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step7_acceptance import build_step7_result


REAL_T03_ROOT = Path("/mnt/e/TestData/POC_Data/T03")


def _write_step3_for_case(case_root: Path, step3_root: Path, case_id: str) -> None:
    specs, _ = load_case_specs(case_root=case_root, case_ids=[case_id], exclude_case_ids=[])
    context = build_step1_context(specs[0])
    template_result = classify_step2_template(context)
    case_result = build_step3_case_result(context, template_result)
    write_step3_case_outputs(run_root=step3_root, context=context, case_result=case_result)


def _rcsd_node_covered(case_root: Path, case_id: str, node_id: str, polygon) -> bool:
    with fiona.open(case_root / case_id / "rcsdnode.gpkg") as src:
        for feature in src:
            properties = dict(feature["properties"])
            if str(properties.get("id")) != node_id:
                continue
            return bool(polygon is not None and polygon.buffer(1.0).contains(shape(feature["geometry"])))
    raise AssertionError(f"missing RCSDNode {node_id}")


def test_real_case_762905_single_sided_strong_rcsdnode_is_kept_inside_final_polygon(tmp_path: Path) -> None:
    case_id = "762905"
    if not (REAL_T03_ROOT / case_id).is_dir():
        pytest.skip(f"missing decoded T03 case: {REAL_T03_ROOT / case_id}")

    step3_root = tmp_path / "step3"
    _write_step3_for_case(REAL_T03_ROOT, step3_root, case_id)
    specs, _ = load_association_case_specs(
        case_root=REAL_T03_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=step3_root)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)
    polygon = step6_result.output_geometries.polygon_final_geometry

    assert association_case_result.association_class == "A"
    assert association_case_result.extra_status_fields["t_mouth_strong_related_rcsdnode_ids"] == [
        "5384380731228487",
        "5384380731228527",
    ]
    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert step6_result.extra_status_fields["local_required_rcsdnode_ids"] == [
        "5384380731228487",
        "5384380731228527",
    ]
    assert _rcsd_node_covered(REAL_T03_ROOT, case_id, "5384380731228487", polygon)
    assert _rcsd_node_covered(REAL_T03_ROOT, case_id, "5384380731228505", polygon)
