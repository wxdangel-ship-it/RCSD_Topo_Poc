from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    sort_patch_key,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv

from ._runtime_shared import LoadedFeature, normalize_id, read_vector_layer_strict
from .provenance import provenance_doc


T04_NODES_LAYER_NAME = "nodes.gpkg"
T04_NODES_AUDIT_CSV_NAME = "nodes_anchor_update_audit.csv"
T04_NODES_AUDIT_JSON_NAME = "nodes_anchor_update_audit.json"
T04_NODES_ACCEPTED_VALUE = "yes"
T04_NODES_FAILED_VALUE = "fail4"
T04_NODES_ACCEPTED_REASON = "accepted_divmerge_virtual_anchor_surface"
T04_NODES_AUDIT_FIELDNAMES = [
    "case_id",
    "representative_node_id",
    "mainnodeid",
    "previous_is_anchor",
    "new_is_anchor",
    "step7_state",
    "reason",
]


def _properties(feature: Any) -> dict[str, Any]:
    if isinstance(feature, Mapping):
        return dict(feature.get("properties") or {})
    return dict(getattr(feature, "properties", {}) or {})


def _geometry(feature: Any) -> Any:
    if isinstance(feature, Mapping):
        return feature.get("geometry")
    return getattr(feature, "geometry", None)


def _node_id(feature: Any) -> str | None:
    return normalize_id(_properties(feature).get("id"))


def _mainnodeid(feature: Any) -> str | None:
    return normalize_id(_properties(feature).get("mainnodeid"))


def _case_id(case_doc: Mapping[str, Any]) -> str:
    return str(case_doc.get("case_id") or case_doc.get("mainnodeid") or "").strip()


def _case_mainnodeid(case_doc: Mapping[str, Any]) -> str:
    return str(case_doc.get("mainnodeid") or case_doc.get("case_id") or "").strip()


def _artifact_reason(artifact: Any) -> str:
    reject_reasons = tuple(getattr(artifact, "reject_reasons", ()) or ())
    return str(reject_reasons[0]) if reject_reasons else ""


def _failure_status(value: Any) -> tuple[str, str]:
    if isinstance(value, Mapping):
        state = str(value.get("step7_state") or value.get("state") or "formal_result_missing")
        reason = str(value.get("reason") or state)
        return state, reason
    if isinstance(value, (list, tuple)) and value:
        state = str(value[0])
        reason = str(value[1] if len(value) > 1 else value[0])
        return state, reason
    text = str(value or "formal_result_missing")
    return text, text


def _resolve_representative_feature(
    features: list[Any],
    *,
    case_id: str,
    mainnodeid: str,
) -> Any | None:
    candidates: list[tuple[int, int, Any]] = []
    for order, feature in enumerate(features):
        node_id = _node_id(feature)
        feature_mainnodeid = _mainnodeid(feature)
        if node_id is None:
            continue
        if node_id == mainnodeid:
            candidates.append((0, order, feature))
        elif node_id == case_id:
            candidates.append((1, order, feature))
        elif feature_mainnodeid == mainnodeid and node_id == feature_mainnodeid:
            candidates.append((2, order, feature))
        elif feature_mainnodeid is None and node_id == mainnodeid:
            candidates.append((3, order, feature))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def _selected_case_docs(selected_cases: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for case_doc in selected_cases:
        case_id = _case_id(case_doc)
        mainnodeid = _case_mainnodeid(case_doc)
        if not case_id:
            continue
        docs.append({"case_id": case_id, "mainnodeid": mainnodeid or case_id})
    return sorted(docs, key=lambda item: sort_patch_key(item["case_id"]))


def load_case_package_node_features(case_specs: Iterable[Any]) -> list[LoadedFeature]:
    features: list[LoadedFeature] = []
    for spec in sorted(case_specs, key=lambda item: sort_patch_key(str(item.case_id))):
        input_paths = getattr(spec, "input_paths", None)
        if not isinstance(input_paths, Mapping) or not input_paths.get("nodes_path"):
            continue
        layer = read_vector_layer_strict(
            input_paths["nodes_path"],
            allow_null_geometry=False,
        )
        features.extend(layer.features)
    return features


def selected_cases_from_specs(case_specs: Iterable[Any]) -> list[dict[str, str]]:
    return [
        {
            "case_id": str(spec.case_id),
            "mainnodeid": str(getattr(spec, "mainnodeid", spec.case_id)),
        }
        for spec in sorted(case_specs, key=lambda item: sort_patch_key(str(item.case_id)))
    ]


def _empty_nodes_outputs(*, run_root: Path, input_dataset_id: str | None = None) -> dict[str, Any]:
    nodes_path = run_root / T04_NODES_LAYER_NAME
    audit_csv_path = run_root / T04_NODES_AUDIT_CSV_NAME
    audit_json_path = run_root / T04_NODES_AUDIT_JSON_NAME
    write_csv(audit_csv_path, [], T04_NODES_AUDIT_FIELDNAMES)
    write_json(
        audit_json_path,
        {
            **provenance_doc(input_dataset_id=input_dataset_id),
            "total_update_count": 0,
            "updated_to_yes_count": 0,
            "updated_to_fail4_count": 0,
            "rows": [],
        },
    )
    return {
        "nodes_path": str(nodes_path),
        "nodes_anchor_update_audit_csv_path": str(audit_csv_path),
        "nodes_anchor_update_audit_json_path": str(audit_json_path),
        "nodes_total_update_count": 0,
        "nodes_updated_to_yes_count": 0,
        "nodes_updated_to_fail4_count": 0,
        "nodes_updated_feature_count": 0,
        "nodes_consistency_passed": True,
        "nodes_missing_case_ids": [],
        "nodes_mismatch_case_ids": [],
    }


def write_t04_nodes_outputs(
    *,
    run_root: Path,
    source_node_features: Iterable[Any],
    selected_cases: Iterable[Mapping[str, Any]],
    artifacts: Iterable[Any],
    failure_status_by_case: Mapping[str, Any] | None = None,
    input_dataset_id: str | None = None,
) -> dict[str, Any]:
    features = list(source_node_features)
    cases = _selected_case_docs(selected_cases)
    artifact_by_case = {str(item.case_id): item for item in artifacts}
    failure_status_by_case = {} if failure_status_by_case is None else dict(failure_status_by_case)

    updates_by_node_id: dict[str, str] = {}
    audit_rows: list[dict[str, Any]] = []
    missing_case_ids: list[str] = []
    expected_value_by_case: dict[str, str] = {}

    for case_doc in cases:
        case_id = case_doc["case_id"]
        mainnodeid = case_doc["mainnodeid"]
        artifact = artifact_by_case.get(case_id)
        if artifact is not None:
            step7_state = str(getattr(artifact, "final_state", ""))
            if step7_state not in {"accepted", "rejected"}:
                raise ValueError(f"unexpected T04 Step7 final_state for case_id={case_id}: {step7_state!r}")
            reason = T04_NODES_ACCEPTED_REASON if step7_state == "accepted" else _artifact_reason(artifact)
        else:
            step7_state, reason = _failure_status(failure_status_by_case.get(case_id))

        new_is_anchor = T04_NODES_ACCEPTED_VALUE if step7_state == "accepted" else T04_NODES_FAILED_VALUE
        representative = _resolve_representative_feature(features, case_id=case_id, mainnodeid=mainnodeid)
        if representative is None:
            missing_case_ids.append(case_id)
            continue
        representative_node_id = _node_id(representative) or case_id
        previous_is_anchor = _properties(representative).get("is_anchor")
        updates_by_node_id[representative_node_id] = new_is_anchor
        expected_value_by_case[case_id] = new_is_anchor
        audit_rows.append(
            {
                "case_id": case_id,
                "representative_node_id": representative_node_id,
                "mainnodeid": mainnodeid,
                "previous_is_anchor": previous_is_anchor,
                "new_is_anchor": new_is_anchor,
                "step7_state": step7_state,
                "reason": reason or step7_state,
            }
        )

    if missing_case_ids:
        raise ValueError(f"missing representative node for T04 case(s): {', '.join(missing_case_ids)}")

    updated_feature_node_ids: set[str] = set()
    output_features: list[dict[str, Any]] = []
    for feature in features:
        properties = _properties(feature)
        node_id = normalize_id(properties.get("id"))
        if node_id is not None and node_id in updates_by_node_id:
            properties["is_anchor"] = updates_by_node_id[node_id]
            updated_feature_node_ids.add(node_id)
        output_features.append({"properties": properties, "geometry": _geometry(feature)})

    mismatch_case_ids = sorted(
        row["case_id"]
        for row in audit_rows
        if row["representative_node_id"] not in updated_feature_node_ids
        or row["new_is_anchor"] != expected_value_by_case.get(row["case_id"])
    )
    nodes_consistency_passed = not mismatch_case_ids and len(audit_rows) == len(cases)

    nodes_path = run_root / T04_NODES_LAYER_NAME
    audit_csv_path = run_root / T04_NODES_AUDIT_CSV_NAME
    audit_json_path = run_root / T04_NODES_AUDIT_JSON_NAME
    write_vector(nodes_path, output_features, crs_text="EPSG:3857")
    write_csv(audit_csv_path, audit_rows, T04_NODES_AUDIT_FIELDNAMES)
    audit_payload = {
        **provenance_doc(input_dataset_id=input_dataset_id),
        "total_update_count": len(audit_rows),
        "updated_to_yes_count": sum(1 for row in audit_rows if row["new_is_anchor"] == T04_NODES_ACCEPTED_VALUE),
        "updated_to_fail4_count": sum(1 for row in audit_rows if row["new_is_anchor"] == T04_NODES_FAILED_VALUE),
        "rows": audit_rows,
    }
    write_json(audit_json_path, audit_payload)

    return {
        "nodes_path": str(nodes_path),
        "nodes_anchor_update_audit_csv_path": str(audit_csv_path),
        "nodes_anchor_update_audit_json_path": str(audit_json_path),
        "nodes_total_update_count": len(audit_rows),
        "nodes_updated_to_yes_count": audit_payload["updated_to_yes_count"],
        "nodes_updated_to_fail4_count": audit_payload["updated_to_fail4_count"],
        "nodes_updated_feature_count": len(updated_feature_node_ids),
        "nodes_consistency_passed": nodes_consistency_passed,
        "nodes_missing_case_ids": [],
        "nodes_mismatch_case_ids": mismatch_case_ids,
    }


def write_t04_nodes_outputs_for_case_packages(
    *,
    run_root: Path,
    case_specs: Iterable[Any],
    artifacts: Iterable[Any],
    failed_case_ids: Iterable[str],
    input_dataset_id: str | None = None,
) -> dict[str, Any]:
    specs = list(case_specs)
    artifacts = list(artifacts)
    if not specs or (
        not artifacts
        and not any(
            isinstance(getattr(spec, "input_paths", None), Mapping)
            and getattr(spec, "input_paths", {}).get("nodes_path")
            for spec in specs
        )
    ):
        return _empty_nodes_outputs(
            run_root=run_root,
            input_dataset_id=input_dataset_id,
        )
    failure_status_by_case = {
        str(case_id): {"step7_state": "runtime_failed", "reason": "runtime_failed"}
        for case_id in failed_case_ids
    }
    return write_t04_nodes_outputs(
        run_root=run_root,
        source_node_features=load_case_package_node_features(specs),
        selected_cases=selected_cases_from_specs(specs),
        artifacts=artifacts,
        failure_status_by_case=failure_status_by_case,
        input_dataset_id=input_dataset_id,
    )


def augment_step7_consistency_report(
    *,
    consistency_report_path: Path,
    nodes_outputs: Mapping[str, Any],
) -> dict[str, Any]:
    report = json.loads(consistency_report_path.read_text(encoding="utf-8"))
    previous_passed = bool(report.get("passed"))
    nodes_passed = bool(nodes_outputs.get("nodes_consistency_passed"))
    report.update(
        {
            "nodes_path": nodes_outputs.get("nodes_path"),
            "nodes_anchor_update_audit_csv_path": nodes_outputs.get("nodes_anchor_update_audit_csv_path"),
            "nodes_anchor_update_audit_json_path": nodes_outputs.get("nodes_anchor_update_audit_json_path"),
            "nodes_total_update_count": nodes_outputs.get("nodes_total_update_count"),
            "nodes_updated_to_yes_count": nodes_outputs.get("nodes_updated_to_yes_count"),
            "nodes_updated_to_fail4_count": nodes_outputs.get("nodes_updated_to_fail4_count"),
            "nodes_updated_feature_count": nodes_outputs.get("nodes_updated_feature_count"),
            "nodes_consistency_passed": nodes_passed,
            "nodes_missing_case_ids": list(nodes_outputs.get("nodes_missing_case_ids") or []),
            "nodes_mismatch_case_ids": list(nodes_outputs.get("nodes_mismatch_case_ids") or []),
            "passed": previous_passed and nodes_passed,
        }
    )
    write_json(consistency_report_path, report)
    return report


__all__ = [
    "T04_NODES_AUDIT_CSV_NAME",
    "T04_NODES_AUDIT_JSON_NAME",
    "T04_NODES_FAILED_VALUE",
    "T04_NODES_LAYER_NAME",
    "augment_step7_consistency_report",
    "load_case_package_node_features",
    "selected_cases_from_specs",
    "write_t04_nodes_outputs",
    "write_t04_nodes_outputs_for_case_packages",
]
