from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from qgis.core import QgsApplication, QgsGeometry, QgsVectorLayer


ALLOWED_SPACE_OVERLAY_RISK_RATIO = 0.90
PREFERRED_RAW_DRIVEZONE_RATIO = 0.95
OPERATIONAL_ALLOWED_BUFFER_M = 0.60
OPERATIONAL_ESCAPE_AREA_TOLERANCE_M2 = 0.0001


def _load_overlay_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("qgis_overlay_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load overlay gate: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _accepted_case_ids(review_index: Path) -> list[str]:
    with review_index.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            str(row["case_id"])
            for row in csv.DictReader(handle)
            if row.get("step7_state") == "accepted"
        ]


def _run_overlay(
    *,
    overlay_module: Any,
    map_path: Path,
    reference_path: Path,
    minimum_ratio: float,
) -> dict[str, Any]:
    return overlay_module.run(
        SimpleNamespace(
            map_gpkg=str(map_path),
            road=str(reference_path),
            layers="",
            skip_layers="",
            min_layer_ratio=minimum_ratio,
            min_overall_ratio=minimum_ratio,
            require_nonempty=True,
        )
    )


def _geometry_gate(map_path: Path) -> dict[str, Any]:
    layer = QgsVectorLayer(str(map_path), "step7_final_polygon", "ogr")
    if not layer.isValid():
        return {
            "gate_pass": False,
            "fail_reasons": ["output_layer_invalid"],
            "feature_count": 0,
            "invalid_geometry_count": 0,
            "crs": "",
        }
    feature_count = 0
    invalid_geometry_count = 0
    for feature in layer.getFeatures():
        geometry = feature.geometry()
        if geometry is None or geometry.isEmpty():
            continue
        feature_count += 1
        if not geometry.isGeosValid():
            invalid_geometry_count += 1
    fail_reasons: list[str] = []
    if feature_count == 0:
        fail_reasons.append("output_geometry_empty")
    if invalid_geometry_count:
        fail_reasons.append("output_geometry_invalid")
    crs = layer.crs().authid()
    if crs != "EPSG:3857":
        fail_reasons.append("output_crs_not_epsg3857")
    return {
        "gate_pass": not fail_reasons,
        "fail_reasons": fail_reasons,
        "feature_count": feature_count,
        "invalid_geometry_count": invalid_geometry_count,
        "crs": crs,
    }


def _operational_allowed_gate(
    map_path: Path,
    allowed_path: Path,
) -> dict[str, Any]:
    map_layer = QgsVectorLayer(str(map_path), "step7_final_polygon", "ogr")
    allowed_layer = QgsVectorLayer(str(allowed_path), "step3_allowed_space", "ogr")
    fail_reasons: list[str] = []
    if not map_layer.isValid():
        fail_reasons.append("output_layer_invalid")
    if not allowed_layer.isValid():
        fail_reasons.append("allowed_space_layer_invalid")
    if fail_reasons:
        return {
            "gate_pass": False,
            "fail_reasons": fail_reasons,
            "buffer_m": OPERATIONAL_ALLOWED_BUFFER_M,
            "escape_area_tolerance_m2": OPERATIONAL_ESCAPE_AREA_TOLERANCE_M2,
            "escape_area_m2": None,
        }

    map_geometry = QgsGeometry.unaryUnion(
        [feature.geometry() for feature in map_layer.getFeatures()]
    )
    allowed_geometry = QgsGeometry.unaryUnion(
        [feature.geometry() for feature in allowed_layer.getFeatures()]
    )
    operational_allowed_geometry = allowed_geometry.buffer(
        OPERATIONAL_ALLOWED_BUFFER_M,
        16,
    )
    escape_geometry = map_geometry.difference(operational_allowed_geometry)
    escape_area_m2 = 0.0 if escape_geometry.isEmpty() else escape_geometry.area()
    if escape_area_m2 > OPERATIONAL_ESCAPE_AREA_TOLERANCE_M2:
        fail_reasons.append("output_escaped_operational_allowed_space")
    return {
        "gate_pass": not fail_reasons,
        "fail_reasons": fail_reasons,
        "buffer_m": OPERATIONAL_ALLOWED_BUFFER_M,
        "escape_area_tolerance_m2": OPERATIONAL_ESCAPE_AREA_TOLERANCE_M2,
        "escape_area_m2": escape_area_m2,
    }


def _audit_dataset(
    *,
    overlay_module: Any,
    name: str,
    run_root: Path,
    input_root: Path,
) -> dict[str, Any]:
    review_index = run_root / "t03_review_index.csv"
    step3_root = run_root.parent / "step3"
    if not step3_root.is_dir() and run_root.name.endswith("_final"):
        step3_root = run_root.with_name(
            f"{run_root.name.removesuffix('_final')}_step3"
        )
    rows: list[dict[str, Any]] = []
    for case_id in _accepted_case_ids(review_index):
        map_path = run_root / "cases" / case_id / "step7_final_polygon.gpkg"
        allowed_path = step3_root / "cases" / case_id / "step3_allowed_space.gpkg"
        raw_drivezone_path = input_root / case_id / "drivezone.gpkg"
        try:
            allowed_result = _run_overlay(
                overlay_module=overlay_module,
                map_path=map_path,
                reference_path=allowed_path,
                minimum_ratio=0.0,
            )
        except Exception as exc:  # pragma: no cover - validation evidence path
            rows.append(
                {
                    "case_id": case_id,
                    "state": "error",
                    "allowed_space_ratio": None,
                    "raw_drivezone_ratio": None,
                    "below_preferred_ratio": True,
                    "fail_reasons": [f"{type(exc).__name__}: {exc}"],
                    "map_gpkg": str(map_path),
                    "allowed_space": str(allowed_path),
                    "raw_drivezone": str(raw_drivezone_path),
                }
            )
            continue

        raw_result: dict[str, Any] | None = None
        raw_audit_state = "measured"
        raw_audit_reasons: list[str] = []
        try:
            raw_result = _run_overlay(
                overlay_module=overlay_module,
                map_path=map_path,
                reference_path=raw_drivezone_path,
                minimum_ratio=0.0,
            )
        except Exception as exc:  # raw reference can be intentionally empty
            raw_audit_state = "not_applicable"
            raw_audit_reasons = [f"{type(exc).__name__}: {exc}"]
        raw_ratio = (
            raw_result["overall"]["in_road_ratio"] if raw_result is not None else None
        )
        geometry_gate = _geometry_gate(map_path)
        operational_allowed_gate = _operational_allowed_gate(map_path, allowed_path)
        allowed_ratio = allowed_result["overall"]["in_road_ratio"]
        hard_fail_reasons = list(geometry_gate["fail_reasons"])
        hard_fail_reasons.extend(operational_allowed_gate["fail_reasons"])
        rows.append(
            {
                "case_id": case_id,
                "state": "pass" if not hard_fail_reasons else "fail",
                "allowed_space_ratio": allowed_ratio,
                "below_allowed_space_overlay_risk_ratio": (
                    allowed_ratio is None
                    or allowed_ratio < ALLOWED_SPACE_OVERLAY_RISK_RATIO
                ),
                "raw_drivezone_ratio": raw_ratio,
                "below_preferred_ratio": (
                    raw_ratio is not None
                    and raw_ratio < PREFERRED_RAW_DRIVEZONE_RATIO
                ),
                "raw_drivezone_audit_state": raw_audit_state,
                "raw_drivezone_audit_reasons": raw_audit_reasons,
                "fail_reasons": hard_fail_reasons,
                "geometry_gate": geometry_gate,
                "operational_allowed_gate": operational_allowed_gate,
                "layers": allowed_result["layers"],
                "map_gpkg": str(map_path),
                "allowed_space": str(allowed_path),
                "raw_drivezone": str(raw_drivezone_path),
            }
        )
    return {
        "dataset": name,
        "run_root": str(run_root),
        "input_root": str(input_root),
        "accepted_case_count": len(rows),
        "hard_gate_pass_count": sum(row["state"] == "pass" for row in rows),
        "hard_gate_fail_count": sum(row["state"] == "fail" for row in rows),
        "execution_error_count": sum(row["state"] == "error" for row in rows),
        "below_preferred_ratio_count": sum(
            bool(row["below_preferred_ratio"]) for row in rows
        ),
        "below_allowed_space_overlay_risk_ratio_count": sum(
            bool(row.get("below_allowed_space_overlay_risk_ratio", True))
            for row in rows
        ),
        "minimum_allowed_space_ratio": min(
            (
                float(row["allowed_space_ratio"])
                for row in rows
                if row["allowed_space_ratio"] is not None
            ),
            default=None,
        ),
        "minimum_raw_drivezone_ratio": min(
            (
                float(row["raw_drivezone_ratio"])
                for row in rows
                if row["raw_drivezone_ratio"] is not None
            ),
            default=None,
        ),
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="T03 accepted surface full QGIS Road-surface overlay audit"
    )
    parser.add_argument("--overlay-tool", required=True, type=Path)
    parser.add_argument(
        "--dataset",
        action="append",
        nargs=3,
        metavar=("NAME", "RUN_ROOT", "INPUT_ROOT"),
        required=True,
    )
    parser.add_argument("--out-json", required=True, type=Path)
    args = parser.parse_args()

    overlay_module = _load_overlay_module(args.overlay_tool)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        datasets = [
            _audit_dataset(
                overlay_module=overlay_module,
                name=name,
                run_root=Path(run_root),
                input_root=Path(input_root),
            )
            for name, run_root, input_root in args.dataset
        ]
    finally:
        app.exitQgis()

    output = {
        "schema_version": "2026-08-01.t03-qgis-overlay-audit.v4",
        "thresholds": {
            "hard_gate": "nonempty_valid_epsg3857_within_step3_allowed_plus_operational_0_6m_tolerance",
            "operational_allowed_buffer_m": OPERATIONAL_ALLOWED_BUFFER_M,
            "operational_escape_area_tolerance_m2": OPERATIONAL_ESCAPE_AREA_TOLERANCE_M2,
            "allowed_space_overlay_risk_ratio": ALLOWED_SPACE_OVERLAY_RISK_RATIO,
            "preferred_raw_drivezone_ratio": PREFERRED_RAW_DRIVEZONE_RATIO,
            "overlay_ratio_role": "audit_only_after_confirmed_2m_access_gate",
        },
        "datasets": datasets,
        "overall": {
            "accepted_case_count": sum(
                item["accepted_case_count"] for item in datasets
            ),
            "hard_gate_fail_count": sum(
                item["hard_gate_fail_count"] for item in datasets
            ),
            "execution_error_count": sum(
                item["execution_error_count"] for item in datasets
            ),
            "below_preferred_ratio_count": sum(
                item["below_preferred_ratio_count"] for item in datasets
            ),
            "below_allowed_space_overlay_risk_ratio_count": sum(
                item["below_allowed_space_overlay_risk_ratio_count"]
                for item in datasets
            ),
        },
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return int(
        output["overall"]["hard_gate_fail_count"] > 0
        or output["overall"]["execution_error_count"] > 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
