from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    read_vector,
    resolve_field_name,
    write_gpkg,
)


TARGET_ID = "609020493"
TARGET_GRADE = 2
TARGET_KIND_BEFORE = 4
TARGET_KIND_AFTER_TOOL4 = 2048
TOOL6_ERROR_TYPE = "错误交叉路口_T型路口"


@dataclass(frozen=True)
class ManualTJunctionOverrideArtifacts:
    nodes: Path
    tool6_csv: Path
    manual_row_csv: Path
    audit: Path


def apply_wuhan_t_junction_override(
    *,
    nodes_path: str | Path,
    roads_path: str | Path,
    tool6_csv_path: str | Path,
    out_dir: str | Path,
) -> ManualTJunctionOverrideArtifacts:
    nodes_input = Path(nodes_path).expanduser().resolve()
    roads_input = Path(roads_path).expanduser().resolve()
    tool6_input = Path(tool6_csv_path).expanduser().resolve()
    output_root = Path(out_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    nodes_output = output_root / "p02_nodes_tool3_manual_override.gpkg"
    tool6_output = output_root / "p02_node_error_tool6_with_manual_override.csv"
    manual_row_output = output_root / "p02_manual_tool6_override_row.csv"
    audit_output = output_root / "p02_manual_t_junction_override_audit.json"
    for path in (nodes_output, tool6_output, manual_row_output, audit_output):
        if path.exists():
            raise FileExistsError(f"manual T-junction override output already exists: {path}")

    nodes = read_vector(nodes_input, target_epsg=None)
    roads = read_vector(roads_input, target_epsg=3857)
    node_id_field = resolve_field_name(nodes.features, ["id"], "SWSD Nodes")
    mainnode_field = resolve_field_name(nodes.features, ["mainnodeid"], "SWSD Nodes")
    grade_field = resolve_field_name(nodes.features, ["grade"], "SWSD Nodes")
    grade_2_field = resolve_field_name(nodes.features, ["grade_2"], "SWSD Nodes")
    kind_2_field = resolve_field_name(nodes.features, ["kind_2"], "SWSD Nodes")
    road_id_field = resolve_field_name(roads.features, ["id"], "SWSD Roads")
    snode_field = resolve_field_name(roads.features, ["snodeid"], "SWSD Roads")
    enode_field = resolve_field_name(roads.features, ["enodeid"], "SWSD Roads")
    direction_field = resolve_field_name(roads.features, ["direction"], "SWSD Roads")

    semantic_node_ids = {
        _text(feature.properties.get(node_id_field))
        for feature in nodes.features
        if (_valid_mainnode(feature.properties.get(mainnode_field)) or _text(feature.properties.get(node_id_field)))
        == TARGET_ID
    }
    if TARGET_ID not in semantic_node_ids:
        raise ValueError(f"target semantic mainnode missing: {TARGET_ID}")

    output_features: list[dict[str, Any]] = []
    target_before: dict[str, Any] | None = None
    target_after: dict[str, Any] | None = None
    target_match_count = 0
    for feature in nodes.features:
        properties = dict(feature.properties)
        if _text(properties.get(node_id_field)) == TARGET_ID:
            target_match_count += 1
            target_before = {
                "grade": properties.get(grade_field),
                "grade_2": properties.get(grade_2_field),
                "kind_2": properties.get(kind_2_field),
                "mainnodeid": properties.get(mainnode_field),
            }
            if int(properties.get(grade_field) or 0) != 1 or int(properties.get(grade_2_field) or 0) != 1:
                raise ValueError(f"unexpected target grade before override: {target_before}")
            if int(properties.get(kind_2_field) or 0) != TARGET_KIND_BEFORE:
                raise ValueError(f"unexpected target kind_2 before Tool4: {target_before}")
            properties[grade_field] = TARGET_GRADE
            properties[grade_2_field] = TARGET_GRADE
            target_after = {
                "grade": properties.get(grade_field),
                "grade_2": properties.get(grade_2_field),
                "kind_2": properties.get(kind_2_field),
                "mainnodeid": properties.get(mainnode_field),
            }
        output_features.append({"properties": properties, "geometry": feature.geometry})
    if target_match_count != 1 or target_before is None or target_after is None:
        raise ValueError(f"expected one target node, got {target_match_count}: {TARGET_ID}")

    in_degree = 0
    out_degree = 0
    related_road_ids: list[str] = []
    for feature in roads.features:
        properties = feature.properties
        snode_id = _text(properties.get(snode_field))
        enode_id = _text(properties.get(enode_field))
        snode_in_group = snode_id in semantic_node_ids
        enode_in_group = enode_id in semantic_node_ids
        if not snode_in_group and not enode_in_group:
            continue
        related_road_ids.append(_text(properties.get(road_id_field)))
        direction = int(properties.get(direction_field) or 0)
        if snode_in_group and enode_in_group:
            in_degree += 1
            out_degree += 1
        elif direction in {0, 1}:
            in_degree += 1
            out_degree += 1
        elif direction == 2:
            out_degree += int(snode_in_group)
            in_degree += int(enode_in_group)
        elif direction == 3:
            in_degree += int(snode_in_group)
            out_degree += int(enode_in_group)
        else:
            raise ValueError(f"unsupported road direction: {direction}")

    with tool6_input.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        tool6_rows = list(reader)
    if any(_text(row.get("semantic_node_id")) == TARGET_ID for row in tool6_rows):
        raise ValueError(f"Tool6 already contains target; refuse duplicate manual override: {TARGET_ID}")

    manual_audit = {
        "manual_override": True,
        "source": "user_confirmed_2026-07-14",
        "reason": "Tool6 missing main_auxiliary_road_t_junction_pattern",
        "classification": "temporary_experiment_override_not_tool6_strong_rule",
        "semantic_node_ids": sorted(semantic_node_ids, key=int),
        "incident_road_ids": sorted(related_road_ids, key=int),
        "observed_in_degree": in_degree,
        "observed_out_degree": out_degree,
        "requested_grade": TARGET_GRADE,
        "tool4_expected_kind_2": TARGET_KIND_AFTER_TOOL4,
    }
    manual_row = {
        "error_id": f"manual_cross_t_{TARGET_ID}:{TARGET_ID}",
        "error_group_id": f"manual_cross_t_{TARGET_ID}",
        "error_type": TOOL6_ERROR_TYPE,
        "semantic_node_id": TARGET_ID,
        "source_node_id": TARGET_ID,
        "role": "manual_cross_t",
        "kind_2": _text(target_before["kind_2"]),
        "in_degree": str(in_degree),
        "out_degree": str(out_degree),
        "paired_semantic_node_id": "",
        "related_node_ids": ",".join(sorted(semantic_node_ids, key=int)),
        "related_road_ids": ",".join(sorted(related_road_ids, key=int)),
        "reason": "user_confirmed_main_auxiliary_road_t_junction_tool6_missing_pattern",
        "audit_json": json.dumps(manual_audit, ensure_ascii=False, separators=(",", ":")),
        "是否修复": "1",
    }
    missing_fields = [field for field in manual_row if field not in fieldnames]
    if missing_fields:
        raise ValueError(f"Tool6 CSV schema missing fields: {missing_fields}")

    write_gpkg(
        nodes_output,
        output_features,
        crs_text=nodes.output_crs.to_string(),
        empty_fields=nodes.field_names,
        geometry_type="Point",
    )
    with tool6_output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(tool6_rows + [manual_row])
    with manual_row_output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(manual_row)

    written = read_vector(nodes_output, target_epsg=None)
    audit = {
        "status": "passed",
        "policy": "copy_on_write_manual_override_after_tool6_before_tool4",
        "target_id": TARGET_ID,
        "before": target_before,
        "after_manual_grade_override": target_after,
        "expected_after_tool4": {
            "grade": TARGET_GRADE,
            "grade_2": TARGET_GRADE,
            "kind_2": TARGET_KIND_AFTER_TOOL4,
        },
        "semantic_node_ids": sorted(semantic_node_ids, key=int),
        "related_road_ids": sorted(related_road_ids, key=int),
        "in_degree": in_degree,
        "out_degree": out_degree,
        "tool6_auto_candidate_count": len(tool6_rows),
        "tool6_augmented_candidate_count": len(tool6_rows) + 1,
        "checks": {
            "input_node_count": len(nodes.features),
            "output_node_count": len(written.features),
            "target_match_count": target_match_count,
            "input_geometry_unchanged": all(
                before.geometry.equals_exact(after.geometry, 0.0)
                for before, after in zip(nodes.features, written.features)
            ),
            "crosslid_used": False,
            "nodelid_used": False,
            "geometry_inference_used": False,
        },
        "paths": {
            "nodes_input": str(nodes_input),
            "roads_input": str(roads_input),
            "tool6_csv_input": str(tool6_input),
            "nodes_output": str(nodes_output),
            "tool6_csv_output": str(tool6_output),
        },
        "hashes": {
            "nodes_input_sha256": _sha256(nodes_input),
            "nodes_output_sha256": _sha256(nodes_output),
            "tool6_csv_input_sha256": _sha256(tool6_input),
            "tool6_csv_output_sha256": _sha256(tool6_output),
        },
    }
    audit_output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return ManualTJunctionOverrideArtifacts(
        nodes=nodes_output,
        tool6_csv=tool6_output,
        manual_row_csv=manual_row_output,
        audit=audit_output,
    )


def _valid_mainnode(value: Any) -> str | None:
    text = _text(value)
    return None if text in {"", "0", "NULL", "None"} else text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


__all__ = ["ManualTJunctionOverrideArtifacts", "apply_wuhan_t_junction_override"]
