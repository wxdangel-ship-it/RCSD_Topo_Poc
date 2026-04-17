from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_vector
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import load_case_specs
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step1_context import build_step1_context
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step2_template import classify_step2_template
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step3_engine import build_step3_case_result


def _write_case_package(
    case_root: Path,
    case_id: str,
    *,
    kind_2: int = 4,
    roads: list[dict] | None = None,
    extra_nodes: list[dict] | None = None,
    has_evd: str = "yes",
    is_anchor: str = "no",
) -> None:
    case_root.mkdir(parents=True, exist_ok=True)
    write_vector(
        case_root / "nodes.gpkg",
        [
            {
                "properties": {
                    "id": case_id,
                    "mainnodeid": case_id,
                    "has_evd": has_evd,
                    "is_anchor": is_anchor,
                    "kind_2": kind_2,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            }
        ],
    )
    if extra_nodes:
        node_features = [
            {
                "properties": {
                    "id": case_id,
                    "mainnodeid": case_id,
                    "has_evd": has_evd,
                    "is_anchor": is_anchor,
                    "kind_2": kind_2,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            },
            *extra_nodes,
        ]
        write_vector(case_root / "nodes.gpkg", node_features)
    write_vector(case_root / "roads.gpkg", roads or [])
    write_vector(case_root / "rcsdroad.gpkg", [])
    write_vector(case_root / "rcsdnode.gpkg", [])
    write_vector(case_root / "drivezone.gpkg", [{"properties": {"id": "dz"}, "geometry": Polygon([(-60.0, -60.0), (120.0, -60.0), (120.0, 60.0), (-60.0, 60.0)])}])
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


def _run_case(case_root: Path) -> object:
    specs, _ = load_case_specs(case_root=case_root)
    context = build_step1_context(specs[0])
    template_result = classify_step2_template(context)
    return build_step3_case_result(context, template_result)


@pytest.mark.parametrize(
    "case_id,kind_2,roads,expected_state,expected_reason_prefix,expected_root_layer,expected_visual_prefix",
    [
        (
            "100001",
            4,
            [],
            "established",
            "step3_established",
            None,
            "V1",
        ),
        (
            "200001",
            4,
            [],
            "review",
            "rule_b_node_fallback",
            "step3",
            "V2",
        ),
        (
            "300001",
            999,
            [],
            "not_established",
            "unsupported_kind_2:999",
            "step2",
            "V5",
        ),
    ],
)
def test_step3_state_mapping(
    tmp_path: Path,
    case_id: str,
    kind_2: int,
    roads: list[dict],
    expected_state: str,
    expected_reason_prefix: str,
    expected_root_layer: str | None,
    expected_visual_prefix: str,
) -> None:
    suite_root = tmp_path / "suite"
    case_root = suite_root / case_id
    road_features = roads
    if case_id == "200001":
        road_features = []
        _write_case_package(
            case_root,
            case_id,
            kind_2=kind_2,
            roads=road_features,
            extra_nodes=[
                {
                    "properties": {
                        "id": "foreign_1",
                        "mainnodeid": "foreign_1",
                        "has_evd": "yes",
                        "is_anchor": "no",
                        "kind_2": 4,
                        "grade_2": 1,
                    },
                    "geometry": Point(100.0, 100.0),
                }
            ],
        )
    else:
        _write_case_package(case_root, case_id, kind_2=kind_2, roads=road_features)

    result = _run_case(suite_root)

    assert result.step3_state == expected_state
    assert result.step3_established is (expected_state == "established")
    assert result.reason.startswith(expected_reason_prefix)
    assert result.root_cause_layer == expected_root_layer
    assert str(result.visual_review_class).startswith(expected_visual_prefix)

    if expected_state == "review":
        assert "rule_b_node_fallback" in result.audit_doc["review_signals"]
        assert result.audit_doc["rules"]["D"]["passed"] is True
    elif expected_state == "established":
        assert result.audit_doc["review_signals"] == []
        assert result.audit_doc["rules"]["D"]["passed"] is True
    else:
        assert result.audit_doc["rules"]["D"]["passed"] is False
        assert result.audit_doc["must_cover_result"]["missing_node_ids"] == [case_id]
