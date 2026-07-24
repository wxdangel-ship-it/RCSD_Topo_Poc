from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import QgsApplication, QgsProject, QgsWkbTypes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independent P04 M2 QGIS project readback.")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--expected-layer-count", type=int, default=24)
    parser.add_argument("--expected-group-count", type=int, default=7)
    parser.add_argument("--strict-exit", action="store_true")
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, object]:
    project_path = args.project.expanduser().resolve()
    project = QgsProject()
    read_ok = project.read(str(project_path))
    project_crs = project.crs().authid() if read_ok else ""
    layers: list[dict[str, object]] = []
    errors: list[str] = []
    if not read_ok:
        errors.append("project_read_failed")
    for layer in sorted(project.mapLayers().values(), key=lambda item: item.name()):
        valid = bool(layer.isValid())
        declared_count = int(layer.featureCount()) if valid else -1
        iterated_count = sum(1 for _ in layer.getFeatures()) if valid else -1
        if not valid:
            errors.append(f"invalid_layer:{layer.name()}")
        if declared_count >= 0 and declared_count != iterated_count:
            errors.append(
                f"feature_count_mismatch:{layer.name()}:{declared_count}!={iterated_count}"
            )
        layer_crs = layer.crs().authid()
        if valid and layer.isSpatial() and layer_crs != project_crs:
            errors.append(
                f"spatial_crs_mismatch:{layer.name()}:{layer_crs or '<empty>'}!={project_crs}"
            )
        layers.append(
            {
                "name": layer.name(),
                "valid": valid,
                "declared_feature_count": declared_count,
                "iterated_feature_count": iterated_count,
                "geometry_type": QgsWkbTypes.displayString(layer.wkbType()),
                "crs": layer_crs,
                "subset": layer.subsetString(),
                "source": layer.source(),
            }
        )
    groups = [
        child.name() for child in project.layerTreeRoot().children() if hasattr(child, "name")
    ]
    if len(layers) != args.expected_layer_count:
        errors.append(f"layer_count:{len(layers)}!={args.expected_layer_count}")
    if len(groups) != args.expected_group_count:
        errors.append(f"group_count:{len(groups)}!={args.expected_group_count}")
    result = {
        "project": str(project_path),
        "project_read_ok": read_ok,
        "project_crs": project_crs,
        "layer_count": len(layers),
        "group_count": len(groups),
        "groups": groups,
        "layers": layers,
        "all_layers_valid": all(bool(layer["valid"]) for layer in layers),
        "all_feature_counts_iterated": all(
            layer["declared_feature_count"] == layer["iterated_feature_count"]
            for layer in layers
        ),
        "all_spatial_crs_match_project": all(
            not layer["valid"]
            or layer["geometry_type"] == "NoGeometry"
            or layer["crs"] == project_crs
            for layer in layers
        ),
        "gate_pass": not errors,
        "errors": errors,
    }
    project.clear()
    return result


def main() -> int:
    args = parse_args()
    app = QgsApplication([], False)
    app.initQgis()
    try:
        result = run(args)
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 0 if result["gate_pass"] or not args.strict_exit else 3
    finally:
        app.exitQgis()


if __name__ == "__main__":
    raise SystemExit(main())
