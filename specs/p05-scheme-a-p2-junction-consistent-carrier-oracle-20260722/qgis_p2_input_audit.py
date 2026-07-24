from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from qgis.core import QgsApplication, QgsVectorLayer, QgsWkbTypes


ROLE_GEOMETRY_FAMILY = {
    "t01_nodes": "Point",
    "proposal_nodes": "Point",
    "t01_roads": "Line",
    "proposal_roads": "Line",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    app = QgsApplication([], False)
    app.initQgis()
    try:
        rows = _audit_layers(args.lineage)
    finally:
        app.exitQgis()

    fail_reasons: list[str] = []
    if len(rows) != 204:
        fail_reasons.append(f"expected_204_layers_got_{len(rows)}")
    if any(not row["layer_valid"] for row in rows):
        fail_reasons.append("invalid_vector_layer")
    if any(row["crs"] != "EPSG:3857" for row in rows):
        fail_reasons.append("crs_mismatch")
    if any(not row["geometry_family_pass"] for row in rows):
        fail_reasons.append("geometry_family_mismatch")
    if any(row["empty_geometry_count"] for row in rows):
        fail_reasons.append("empty_geometry")
    if any(row["invalid_geometry_count"] for row in rows):
        fail_reasons.append("invalid_geometry")

    report = {
        "schema_version": "p05-scheme-a-p2-gis-audit-v1",
        "runtime": {
            "qgis": "3.40.14-Bratislava",
            "python": "3.12.12",
            "gdal": "3.12.1",
            "proj": "9.7.1",
        },
        "scope": {
            "case_count": len({row["case_key"] for row in rows}),
            "layer_count": len(rows),
            "role_counts": dict(
                sorted(Counter(row["role"] for row in rows).items())
            ),
        },
        "summary": {
            "feature_count": sum(row["feature_count"] for row in rows),
            "invalid_layer_count": sum(not row["layer_valid"] for row in rows),
            "crs_mismatch_count": sum(
                row["crs"] != "EPSG:3857" for row in rows
            ),
            "geometry_family_mismatch_count": sum(
                not row["geometry_family_pass"] for row in rows
            ),
            "empty_geometry_count": sum(row["empty_geometry_count"] for row in rows),
            "invalid_geometry_count": sum(
                row["invalid_geometry_count"] for row in rows
            ),
        },
        "overlay_gate": {
            "status": "NOT_APPLICABLE",
            "reason": (
                "P2-P0 emits a logical RoadGraph over existing Road/Node payloads "
                "and does not emit a new vector geometry layer or road-polygon reference."
            ),
        },
        "gate_pass": not fail_reasons,
        "fail_reasons": fail_reasons,
        "layers": rows,
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "scope",
                    "summary",
                    "overlay_gate",
                    "gate_pass",
                    "fail_reasons",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["gate_pass"] else 1


def _audit_layers(lineage_path: Path) -> list[dict[str, object]]:
    with lineage_path.open(encoding="utf-8-sig", newline="") as source:
        lineage = [
            row
            for row in csv.DictReader(source)
            if row["role"] in ROLE_GEOMETRY_FAMILY
        ]
    rows: list[dict[str, object]] = []
    for item in lineage:
        layer = QgsVectorLayer(item["path"], item["role"], "ogr")
        valid = layer.isValid()
        crs = layer.crs().authid() if valid else ""
        actual_family = (
            QgsWkbTypes.geometryDisplayString(
                QgsWkbTypes.geometryType(layer.wkbType())
            )
            if valid
            else ""
        )
        feature_count = empty_count = invalid_count = 0
        if valid:
            for feature in layer.getFeatures():
                feature_count += 1
                geometry = feature.geometry()
                if geometry is None or geometry.isNull() or geometry.isEmpty():
                    empty_count += 1
                elif not geometry.isGeosValid():
                    invalid_count += 1
        expected_family = ROLE_GEOMETRY_FAMILY[item["role"]]
        rows.append(
            {
                "case_key": item["case_key"],
                "role": item["role"],
                "path": item["path"],
                "source_sha256": item["sha256"],
                "layer_valid": valid,
                "crs": crs,
                "expected_geometry_family": expected_family,
                "actual_geometry_family": actual_family,
                "feature_count": feature_count,
                "empty_geometry_count": empty_count,
                "invalid_geometry_count": invalid_count,
                "geometry_family_pass": actual_family == expected_family,
            }
        )
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
