from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from .contracts import T10_MODULE_ID, T10_VERSION


CASE_ID_EMPTY_VALUES = {"", "0", "0.0", "none", "null", "nan", "-1"}
CASE_ID_FIELDS = (
    "case_id",
    "swsd_semantic_junction_id",
    "semantic_junction_id",
    "target_id",
    "mainnodeid",
    "junction_id",
    "main_node_id",
)
NODE_ID_FIELDS = ("node_id", "id")


@dataclass(frozen=True)
class T10CaseSuggestionArtifacts:
    out_dir: Path
    suggestions_json: Path
    suggestions_csv: Path
    summary_json: Path


def suggest_t10_cases(
    *,
    manifest: Mapping[str, Any],
    selector_evidence: Mapping[str, str | Sequence[str]] | None = None,
    include_inventory_if_no_evidence: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    external_inputs = _mapping(manifest.get("external_inputs"))
    nodes_path_text = external_inputs.get("prepared_swsd_nodes")
    if not isinstance(nodes_path_text, str) or not nodes_path_text.strip():
        raise ValueError("manifest.external_inputs.prepared_swsd_nodes is required for case suggestion.")

    groups = _load_swsd_semantic_groups(Path(nodes_path_text).expanduser())
    selector_paths = _selector_paths(selector_evidence or {})
    evidence_by_case = _collect_selector_evidence(selector_paths=selector_paths, groups=groups)
    has_selector_evidence = bool(selector_paths)

    candidates: list[dict[str, Any]] = []
    for case_id, group in sorted(groups.items()):
        evidence_refs = evidence_by_case.get(case_id, [])
        include = bool(evidence_refs) or (include_inventory_if_no_evidence and not has_selector_evidence)
        if not include:
            continue
        candidates.append(
            {
                "case_id": case_id,
                "case_id_semantics": "swsd_semantic_junction_id",
                "candidate_status": "problem_candidate" if evidence_refs else "inventory_only",
                "problem_evidence_count": len(evidence_refs),
                "member_node_ids": group["member_node_ids"],
                "kind_2_values": group["kind_2_values"],
                "center_x": group["center_x"],
                "center_y": group["center_y"],
                "selector_evidence": evidence_refs,
            }
        )

    if limit is not None:
        candidates = candidates[: max(0, limit)]

    return {
        "module_id": T10_MODULE_ID,
        "version": T10_VERSION,
        "produced_at_utc": _now_text(),
        "case_id_semantics": "SWSD semantic junction id; coordinates are derived scope metadata, not the case id.",
        "selector_policy": (
            "Selector evidence can suggest cases, but final T10 case packages still contain external inputs only."
        ),
        "nodes_path": str(Path(nodes_path_text).expanduser()),
        "semantic_junction_count": len(groups),
        "selector_evidence_sources": [
            {"source": source, "path": str(path)} for source, paths in selector_paths.items() for path in paths
        ],
        "candidate_count": len(candidates),
        "problem_candidate_count": sum(1 for item in candidates if item["candidate_status"] == "problem_candidate"),
        "inventory_only_count": sum(1 for item in candidates if item["candidate_status"] == "inventory_only"),
        "candidates": candidates,
    }


def write_t10_case_suggestions(
    *,
    manifest: Mapping[str, Any],
    out_root: str | Path,
    selector_evidence: Mapping[str, str | Sequence[str]] | None = None,
    include_inventory_if_no_evidence: bool = True,
    run_id: str | None = None,
    limit: int | None = None,
) -> T10CaseSuggestionArtifacts:
    effective_run_id = run_id or "t10_case_suggest_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(out_root).expanduser().resolve() / effective_run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = suggest_t10_cases(
        manifest=manifest,
        selector_evidence=selector_evidence,
        include_inventory_if_no_evidence=include_inventory_if_no_evidence,
        limit=limit,
    )
    artifacts = T10CaseSuggestionArtifacts(
        out_dir=out_dir,
        suggestions_json=out_dir / "t10_case_suggestions.json",
        suggestions_csv=out_dir / "t10_case_suggestions.csv",
        summary_json=out_dir / "t10_case_suggestions_summary.json",
    )
    _write_json(artifacts.suggestions_json, payload)
    _write_json(
        artifacts.summary_json,
        {key: value for key, value in payload.items() if key != "candidates"},
    )
    _write_csv(artifacts.suggestions_csv, payload["candidates"])
    return artifacts


def _load_swsd_semantic_groups(nodes_path: Path) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for record in _read_records(nodes_path):
        props = record["properties"]
        node_id = _normalize_id(_field_value(props, "id"))
        if not node_id:
            continue
        mainnodeid = _normalize_id(_field_value(props, "mainnodeid"))
        case_id = mainnodeid if _is_valid_case_id(mainnodeid) else node_id
        group = groups.setdefault(
            case_id,
            {
                "member_node_ids": [],
                "kind_2_values": [],
                "geometries": [],
                "center_x": None,
                "center_y": None,
            },
        )
        group["member_node_ids"].append(node_id)
        kind_2 = _normalize_id(_field_value(props, "kind_2"))
        if kind_2 and kind_2 not in group["kind_2_values"]:
            group["kind_2_values"].append(kind_2)
        if record["geometry"] is not None and not record["geometry"].is_empty:
            group["geometries"].append(record["geometry"])
    for group in groups.values():
        group["member_node_ids"] = sorted(set(group["member_node_ids"]), key=_sort_key)
        group["kind_2_values"] = sorted(set(group["kind_2_values"]), key=_sort_key)
        centroids = [geometry.centroid for geometry in group.pop("geometries")]
        if centroids:
            group["center_x"] = sum(point.x for point in centroids) / len(centroids)
            group["center_y"] = sum(point.y for point in centroids) / len(centroids)
    return groups


def _collect_selector_evidence(
    *,
    selector_paths: Mapping[str, tuple[Path, ...]],
    groups: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    case_by_node: dict[str, str] = {}
    for case_id, group in groups.items():
        case_by_node[case_id] = case_id
        for node_id in group["member_node_ids"]:
            case_by_node[str(node_id)] = case_id

    evidence_by_case: dict[str, list[dict[str, Any]]] = {}
    for source, paths in selector_paths.items():
        for path in paths:
            for row_index, record in enumerate(_read_records(path), start=1):
                props = record["properties"]
                match = _match_case_id(props, groups.keys(), case_by_node)
                if match is None:
                    continue
                case_id, matched_field, matched_value = match
                evidence_by_case.setdefault(case_id, []).append(
                    {
                        "source": source,
                        "source_path": str(path),
                        "row_index": row_index,
                        "matched_field": matched_field,
                        "matched_value": matched_value,
                        "evidence_type": _first_text(
                            props,
                            ("error_type", "reject_reason", "relation_reason", "failure_reason", "status", "reason"),
                        ),
                    }
                )
    return evidence_by_case


def _match_case_id(
    props: Mapping[str, Any],
    case_ids: Iterable[str],
    case_by_node: Mapping[str, str],
) -> tuple[str, str, str] | None:
    case_id_set = set(case_ids)
    for field in CASE_ID_FIELDS:
        value = _normalize_id(_field_value(props, field))
        if value and value in case_id_set:
            return value, field, value
    for field in NODE_ID_FIELDS:
        value = _normalize_id(_field_value(props, field))
        if value and value in case_by_node:
            return case_by_node[value], field, value
    return None


def _read_records(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as fp:
            return [{"properties": dict(row), "geometry": None} for row in csv.DictReader(fp)]
    if suffix in {".json", ".geojson"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _records_from_json_payload(payload)
    return _records_from_vector(path)


def _records_from_json_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping) and payload.get("type") == "FeatureCollection":
        return [
            {"properties": dict(feature.get("properties") or {}), "geometry": _shape_or_none(feature.get("geometry"))}
            for feature in payload.get("features") or []
        ]
    if isinstance(payload, Mapping) and isinstance(payload.get("rows"), list):
        return [{"properties": dict(row), "geometry": None} for row in payload["rows"] if isinstance(row, Mapping)]
    if isinstance(payload, list):
        return [{"properties": dict(row), "geometry": None} for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        return [{"properties": dict(payload), "geometry": None}]
    return []


def _records_from_vector(path: Path) -> list[dict[str, Any]]:
    import fiona

    records: list[dict[str, Any]] = []
    with fiona.open(path) as source:
        for feature in source:
            records.append(
                {
                    "properties": dict(feature.get("properties") or {}),
                    "geometry": _shape_or_none(feature.get("geometry")),
                }
            )
    return records


def _shape_or_none(geometry: Any) -> BaseGeometry | None:
    if not geometry:
        return None
    try:
        return shape(geometry)
    except Exception:
        return None


def _selector_paths(selector_evidence: Mapping[str, str | Sequence[str]]) -> dict[str, tuple[Path, ...]]:
    result: dict[str, tuple[Path, ...]] = {}
    for source, value in selector_evidence.items():
        if isinstance(value, str):
            result[source] = (Path(value).expanduser(),)
        else:
            result[source] = tuple(Path(item).expanduser() for item in value)
    return result


def _field_value(props: Mapping[str, Any], field_name: str) -> Any:
    expected = field_name.lower()
    for key, value in props.items():
        if str(key).lower() == expected:
            return value
    return None


def _first_text(props: Mapping[str, Any], fields: Iterable[str]) -> str:
    for field in fields:
        value = _normalize_id(_field_value(props, field))
        if value:
            return value
    return ""


def _normalize_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"none", "null", "nan"}:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return str(int(number))
    return text


def _is_valid_case_id(value: str) -> bool:
    return value.strip().lower() not in CASE_ID_EMPTY_VALUES


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, candidates: list[dict[str, Any]]) -> None:
    fields = ("case_id", "candidate_status", "problem_evidence_count", "member_node_ids", "kind_2_values", "center_x", "center_y")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({field: _csv_value(candidate.get(field)) for field in fields})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _sort_key(value: Any) -> tuple[int, Any]:
    text = str(value)
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
