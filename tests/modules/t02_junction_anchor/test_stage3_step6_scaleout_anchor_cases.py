from __future__ import annotations

import json
from pathlib import Path

import pytest
import geopandas as gpd

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_polygon_solver import (
    _compute_metrics,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    run_t02_virtual_intersection_poc,
)

MANIFEST_PATH = Path(__file__).with_name("data") / "anchor61_manifest.json"


def _load_manifest() -> list[dict[str, object]]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return list(payload["cases"])


def _manifest_entry(case_id: str) -> dict[str, object]:
    for entry in _load_manifest():
        if str(entry["case_id"]) == case_id:
            return entry
    raise AssertionError(f"case_id not found in Anchor61 manifest: {case_id}")


def _case_inputs(case_root: Path) -> dict[str, Path]:
    return {
        "nodes_path": case_root / "nodes.gpkg",
        "roads_path": case_root / "roads.gpkg",
        "drivezone_path": case_root / "drivezone.gpkg",
        "rcsdroad_path": case_root / "rcsdroad.gpkg",
        "rcsdnode_path": case_root / "rcsdnode.gpkg",
    }


def _run_case(
    tmp_path: Path,
    case_id: str,
    *,
    debug: bool = False,
) -> dict[str, object]:
    entry = _manifest_entry(case_id)
    case_root = normalize_runtime_path(str(entry["input_root"]))
    assert case_root.exists(), f"missing Anchor61 case root: {case_root}"

    artifacts = run_t02_virtual_intersection_poc(
        mainnodeid=str(entry["mainnodeid"]),
        out_root=tmp_path / "out",
        debug=debug,
        **_case_inputs(case_root),
    )
    return json.loads(artifacts.status_path.read_text(encoding="utf-8"))


def _step6(doc: dict[str, object]) -> dict[str, object]:
    return (((doc.get("stage3_audit_record") or {}).get("step6")) or {})


def _step4(doc: dict[str, object]) -> dict[str, object]:
    return (((doc.get("stage3_audit_record") or {}).get("step4")) or {})


def _step7(doc: dict[str, object]) -> dict[str, object]:
    return (((doc.get("stage3_audit_record") or {}).get("step7")) or {})


def _exported_geometry_metrics(doc: dict[str, object]):
    output_files = (doc.get("output_files") or {})
    polygon_path = output_files.get("virtual_intersection_polygon")
    assert polygon_path, "missing output_files.virtual_intersection_polygon"
    gdf = gpd.read_file(normalize_runtime_path(str(polygon_path)))
    assert not gdf.empty
    metrics = _compute_metrics(gdf.geometry.iloc[0])
    assert metrics is not None
    return metrics


@pytest.mark.parametrize("case_id", ["584253", "705817"])
def test_kind2_4_extreme_geometry_subcluster_applies_bounded_regularization(
    tmp_path: Path,
    case_id: str,
) -> None:
    status_doc = _run_case(tmp_path, case_id)
    step6 = _step6(status_doc)
    step7 = _step7(status_doc)

    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["business_outcome_class"] == "risk"
    assert status_doc["root_cause_layer"] == "step6"
    assert (
        status_doc["root_cause_type"]
        == "nonstable_center_junction_extreme_geometry_anomaly"
    )
    assert (
        step6.get("geometry_review_reason")
        == "nonstable_center_junction_extreme_geometry_anomaly"
    )
    assert "bounded_regularization_applied" in (step6.get("optimizer_events") or [])
    assert "step6_cluster_canonical_result_selected" in (step7.get("decision_basis") or [])
    assert (step6.get("polygon_compactness") or 0.0) >= 0.35
    assert (step6.get("polygon_bbox_fill_ratio") or 0.0) >= 0.35
    assert (step6.get("polygon_aspect_ratio") or 999.0) <= 2.1


def test_compound_center_weak_protection_remains_stable(tmp_path: Path) -> None:
    status_doc = _run_case(tmp_path, "10970944")
    step6 = _step6(status_doc)
    step7 = _step7(status_doc)

    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["business_outcome_class"] == "risk"
    assert status_doc["root_cause_layer"] == "step6"
    assert status_doc["root_cause_type"] == "stable_compound_center_requires_review"
    assert step6.get("geometry_review_reason") == "stable_compound_center_requires_review"
    assert "bounded_regularization_applied" not in (step6.get("optimizer_events") or [])
    assert "step6_cluster_canonical_result_selected" in (step7.get("decision_basis") or [])


@pytest.mark.parametrize("case_id", ["584253", "705817"])
def test_regularized_geometry_is_written_to_export_and_render(
    tmp_path: Path,
    case_id: str,
) -> None:
    status_doc = _run_case(tmp_path, case_id, debug=True)
    step6 = _step6(status_doc)
    metrics = _exported_geometry_metrics(status_doc)
    rendered_map_png = (status_doc.get("output_files") or {}).get("rendered_map_png")

    assert "bounded_regularization_applied" in (step6.get("optimizer_events") or [])
    assert metrics.aspect_ratio == pytest.approx(
        step6.get("polygon_aspect_ratio"),
        abs=1e-9,
    )
    assert metrics.compactness == pytest.approx(
        step6.get("polygon_compactness"),
        abs=1e-9,
    )
    assert metrics.bbox_fill_ratio == pytest.approx(
        step6.get("polygon_bbox_fill_ratio"),
        abs=1e-9,
    )
    assert rendered_map_png, "debug run should publish rendered_map_png"
    assert normalize_runtime_path(str(rendered_map_png)).is_file()


@pytest.mark.parametrize(
    ("case_id", "acceptance_class", "business_outcome_class", "root_cause_layer", "root_cause_type"),
    [
        (
            "698330",
            "review_required",
            "risk",
            "step6",
            "stable_single_sided_mouth_geometry_requires_review",
        ),
        (
            "706389",
            "review_required",
            "risk",
            "step6",
            "stable_single_sided_mouth_geometry_requires_review",
        ),
        (
            "520394575",
            "rejected",
            "failure",
            "frozen-constraints conflict",
            "rc_outside_drivezone",
        ),
        (
            "861032",
            "accepted",
            "success",
            "step3",
            "stable",
        ),
    ],
)
def test_external_protection_cases_do_not_regress(
    tmp_path: Path,
    case_id: str,
    acceptance_class: str,
    business_outcome_class: str,
    root_cause_layer: str,
    root_cause_type: str,
) -> None:
    status_doc = _run_case(tmp_path, case_id)
    step6 = _step6(status_doc)

    assert status_doc["acceptance_class"] == acceptance_class
    assert status_doc["business_outcome_class"] == business_outcome_class
    assert status_doc["root_cause_layer"] == root_cause_layer
    assert status_doc["root_cause_type"] == root_cause_type
    assert "bounded_regularization_applied" not in (step6.get("optimizer_events") or [])

    if case_id == "520394575":
        assert status_doc["official_review_eligible"] is False
        assert status_doc["failure_bucket"] == "frozen-constraints conflict"


@pytest.mark.parametrize(
    ("case_id", "acceptance_class", "business_outcome_class", "root_cause_layer", "root_cause_type"),
    [
        (
            "500860756",
            "review_required",
            "risk",
            "step4",
            "stable_with_incomplete_t_mouth_rc_context",
        ),
        (
            "61529208",
            "accepted",
            "success",
            "step3",
            "stable",
        ),
        (
            "707476",
            "accepted",
            "success",
            "step3",
            "stable",
        ),
        (
            "769081",
            "rejected",
            "failure",
            "step5",
            "foreign_outside_drivezone_soft_excluded",
        ),
        (
            "954218",
            "rejected",
            "failure",
            "step5",
            "foreign_outside_drivezone_soft_excluded",
        ),
    ],
)
def test_a_cluster_tailcap_regression(
    tmp_path: Path,
    case_id: str,
    acceptance_class: str,
    business_outcome_class: str,
    root_cause_layer: str,
    root_cause_type: str,
) -> None:
    status_doc = _run_case(tmp_path, case_id)
    step4 = _step4(status_doc)
    step6 = _step6(status_doc)

    assert status_doc["acceptance_class"] == acceptance_class
    assert status_doc["business_outcome_class"] == business_outcome_class
    assert status_doc["root_cause_layer"] == root_cause_layer
    assert status_doc["root_cause_type"] == root_cause_type
    assert "surplus_trunk_tail_trim_applied" in (step6.get("optimizer_events") or [])
    assert "surplus_trunk_tail_residual_released" in (step6.get("optimizer_events") or [])
    assert step6.get("geometry_review_reason") is None
    assert (step6.get("foreign_overlap_metric_m") or 0.0) <= 2.0

    if case_id == "500860756":
        assert len(step4.get("uncovered_selected_endpoint_node_ids") or []) == 2
    if case_id in {"769081", "954218"}:
        assert status_doc["acceptance_reason"] == "foreign_outside_drivezone_soft_excluded"


def test_793460_expression_mismatch_case_remains_stable(tmp_path: Path) -> None:
    status_doc = _run_case(tmp_path, "793460")
    step6 = _step6(status_doc)

    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["business_outcome_class"] == "failure"
    assert status_doc["root_cause_layer"] == "step5"
    assert status_doc["root_cause_type"] == "foreign_outside_drivezone_soft_excluded"
    assert step6.get("geometry_review_reason") == "outside_rc_gap_requires_review"
    assert "surplus_trunk_tail_trim_applied" not in (step6.get("optimizer_events") or [])
