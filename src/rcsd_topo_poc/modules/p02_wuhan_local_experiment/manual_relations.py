from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rcsd_topo_poc.modules.t08_preprocess.vector_io import read_vector, resolve_field_name


MANUAL_RELATION_FIELDS = (
    "case_id",
    "swsd_segment_id",
    "target_id",
    "manual_relation_type",
    "selected_ids",
    "comment",
    "source_manual_table",
    "source_manual_xlsx",
)
JUNCTION_RELATION_TYPES = frozenset({"1v1_rcsd_junction", "1vN_rcsd_junction"})
ROAD_RELATION_TYPES = frozenset({"1v1_rcsd_road", "1vN_rcsd_road"})
ACTIONABLE_RELATION_TYPES = JUNCTION_RELATION_TYPES | ROAD_RELATION_TYPES
AUDIT_FIELDS = (
    "source_row_number",
    "raw_target_id",
    "canonical_target_id",
    "raw_manual_relation_type",
    "raw_selected_ids",
    "transform_status",
    "conflict_reason",
)


@dataclass(frozen=True)
class ManualRelationTransformArtifacts:
    raw_relations: Path
    converted_relations: Path
    audit: Path
    summary: Path


class ManualRelationTransformError(ValueError):
    def __init__(self, message: str, *, summary_path: Path, audit_path: Path) -> None:
        super().__init__(message)
        self.summary_path = summary_path
        self.audit_path = audit_path


def transform_manual_relations(
    *,
    raw_relation_path: str | Path,
    final_swsd_nodes_path: str | Path,
    rcsdnode_path: str | Path,
    rcsdroad_path: str | Path,
    out_dir: str | Path,
) -> ManualRelationTransformArtifacts:
    source_path = Path(raw_relation_path).expanduser().resolve()
    output_root = Path(out_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    raw_output = output_root / "p02_manual_relations_raw.csv"
    converted_output = output_root / "p02_manual_relations_converted.csv"
    audit_output = output_root / "p02_manual_relation_transform_audit.csv"
    summary_output = output_root / "p02_manual_relation_transform_summary.json"

    raw_rows = _read_manual_rows(source_path)
    _write_csv(raw_output, raw_rows, MANUAL_RELATION_FIELDS)

    swsd_nodes = read_vector(final_swsd_nodes_path, target_epsg=None)
    rcsd_nodes = read_vector(rcsdnode_path, target_epsg=None)
    rcsd_roads = read_vector(rcsdroad_path, target_epsg=None)
    swsd_id_field = resolve_field_name(swsd_nodes.features, ["id"], "final SWSD Nodes")
    swsd_mainnode_field = resolve_field_name(swsd_nodes.features, ["mainnodeid"], "final SWSD Nodes")
    rcsdnode_id_field = resolve_field_name(rcsd_nodes.features, ["id"], "RCSDNode")
    rcsdnode_mainnode_field = resolve_field_name(rcsd_nodes.features, ["mainnodeid"], "RCSDNode")
    rcsdroad_id_field = resolve_field_name(rcsd_roads.features, ["id"], "RCSDRoad")

    canonical_target_by_id = {
        _required_id(feature.properties.get(swsd_id_field), "SWSD node id"): (
            _valid_mainnode_id(feature.properties.get(swsd_mainnode_field))
            or _required_id(feature.properties.get(swsd_id_field), "SWSD node id")
        )
        for feature in swsd_nodes.features
    }
    rcsdnode_ids = _semantic_node_ids(
        rcsd_nodes.features,
        id_field=rcsdnode_id_field,
        mainnode_field=rcsdnode_mainnode_field,
    )
    rcsdroad_ids = {
        _required_id(feature.properties.get(rcsdroad_id_field), "RCSDRoad id")
        for feature in rcsd_roads.features
    }

    audit_rows: list[dict[str, str]] = []
    prepared_rows: list[dict[str, Any]] = []
    missing_target_count = 0
    invalid_selected_id_count = 0
    for row_number, row in enumerate(raw_rows, start=2):
        target_id = _normalize_id(row.get("target_id"))
        relation_type = _text(row.get("manual_relation_type"))
        selected_ids = _selected_ids(row.get("selected_ids"))
        canonical_target = canonical_target_by_id.get(target_id or "")
        reasons: list[str] = []
        if canonical_target is None:
            missing_target_count += 1
            reasons.append("missing_target")
        if relation_type not in ACTIONABLE_RELATION_TYPES:
            reasons.append(f"unsupported_manual_relation_type:{relation_type or 'empty'}")
        expected_count = 1 if relation_type.startswith("1v1_") else 2
        if relation_type in ACTIONABLE_RELATION_TYPES and len(selected_ids) < expected_count:
            reasons.append(f"selected_id_count_below_{expected_count}")
        selected_universe = rcsdnode_ids if relation_type in JUNCTION_RELATION_TYPES else rcsdroad_ids
        missing_selected = [value for value in selected_ids if value not in selected_universe]
        if missing_selected:
            invalid_selected_id_count += len(missing_selected)
            reasons.append("missing_selected_ids:" + "|".join(missing_selected))
        prepared_rows.append(
            {
                "source_row_number": row_number,
                "raw": row,
                "raw_target_id": target_id or "",
                "canonical_target_id": canonical_target or "",
                "manual_relation_type": relation_type,
                "selected_ids": "|".join(selected_ids),
                "blocking_reasons": reasons,
            }
        )

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in prepared_rows:
        if item["canonical_target_id"]:
            groups[item["canonical_target_id"]].append(item)
    group_transform_by_target: dict[str, dict[str, Any]] = {}
    for target_id, items in groups.items():
        relation_classes = {
            "junction" if item["manual_relation_type"] in JUNCTION_RELATION_TYPES else "road"
            for item in items
            if item["manual_relation_type"] in ACTIONABLE_RELATION_TYPES
        }
        if len(relation_classes) > 1:
            relation_text = ";".join(
                f"{item['manual_relation_type']}:{item['selected_ids']}" for item in items
            )
            for item in items:
                item["blocking_reasons"].append(
                    f"canonical_target_mixed_object_class:{target_id}:{relation_text}"
                )
            continue
        selected_union: list[str] = []
        for item in items:
            for selected_id in _selected_ids(item["selected_ids"]):
                if selected_id not in selected_union:
                    selected_union.append(selected_id)
        relation_class = next(iter(relation_classes), "")
        converted_relation_type = (
            f"1v{'1' if len(selected_union) == 1 else 'N'}_rcsd_{relation_class}"
            if relation_class and selected_union
            else ""
        )
        signatures = {(item["manual_relation_type"], item["selected_ids"]) for item in items}
        group_transform_by_target[target_id] = {
            "manual_relation_type": converted_relation_type,
            "selected_ids": "|".join(selected_union),
            "exact_duplicate": len(signatures) == 1,
            "merged_to_1vn": len(items) > 1 and len(selected_union) > 1,
            "source_target_ids": [item["raw_target_id"] for item in items],
        }

    converted_rows: list[dict[str, str]] = []
    emitted_targets: set[str] = set()
    deduplicated_count = 0
    conflict_count = 0
    merged_to_1vn_targets: set[str] = set()
    for item in prepared_rows:
        reasons = item["blocking_reasons"]
        canonical_target = item["canonical_target_id"]
        if reasons:
            status = "missing_target" if "missing_target" in reasons else "conflict"
            if status == "conflict":
                conflict_count += 1
        elif group_transform_by_target[canonical_target]["merged_to_1vn"]:
            status = "merged_to_1vN"
            merged_to_1vn_targets.add(canonical_target)
        elif canonical_target in emitted_targets:
            status = "deduplicated"
            deduplicated_count += 1
        else:
            status = "remapped" if item["raw_target_id"] != canonical_target else "unchanged"
        if not reasons and canonical_target not in emitted_targets:
            group_transform = group_transform_by_target[canonical_target]
            emitted_targets.add(canonical_target)
            converted = {field: _text(item["raw"].get(field)) for field in MANUAL_RELATION_FIELDS}
            converted["target_id"] = canonical_target
            converted["manual_relation_type"] = group_transform["manual_relation_type"]
            converted["selected_ids"] = group_transform["selected_ids"]
            if len(group_transform["source_target_ids"]) > 1:
                lineage = "canonicalized_from=" + "|".join(group_transform["source_target_ids"])
                converted["comment"] = "; ".join(value for value in (converted["comment"], lineage) if value)
            converted_rows.append(converted)
        audit_rows.append(
            {
                "source_row_number": str(item["source_row_number"]),
                "raw_target_id": item["raw_target_id"],
                "canonical_target_id": canonical_target,
                "raw_manual_relation_type": item["manual_relation_type"],
                "raw_selected_ids": item["selected_ids"],
                "transform_status": status,
                "conflict_reason": ";".join(reasons),
            }
        )

    _write_csv(audit_output, audit_rows, AUDIT_FIELDS)
    blocking_row_count = sum(bool(item["blocking_reasons"]) for item in prepared_rows)
    passed = blocking_row_count == 0
    summary = {
        "passed": passed,
        "raw_relation_count": len(raw_rows),
        "converted_relation_count": len(converted_rows) if passed else 0,
        "deduplicated_relation_count": deduplicated_count,
        "merged_to_1vn_group_count": len(merged_to_1vn_targets),
        "blocking_row_count": blocking_row_count,
        "conflict_count": conflict_count,
        "missing_target_count": missing_target_count,
        "invalid_selected_id_count": invalid_selected_id_count,
        "relation_type_counts": _counts(row["manual_relation_type"] for row in raw_rows),
        "input_paths": {
            "raw_relation_path": str(source_path),
            "final_swsd_nodes_path": str(Path(final_swsd_nodes_path).expanduser().resolve()),
            "rcsdnode_path": str(Path(rcsdnode_path).expanduser().resolve()),
            "rcsdroad_path": str(Path(rcsdroad_path).expanduser().resolve()),
        },
        "output_paths": {
            "raw_relations": str(raw_output),
            "converted_relations": str(converted_output) if passed else None,
            "audit": str(audit_output),
            "summary": str(summary_output),
        },
    }
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if not passed:
        raise ManualRelationTransformError(
            f"blocking manual relation transform issues: {blocking_row_count}",
            summary_path=summary_output,
            audit_path=audit_output,
        )
    _write_csv(converted_output, converted_rows, MANUAL_RELATION_FIELDS)
    return ManualRelationTransformArtifacts(
        raw_relations=raw_output,
        converted_relations=converted_output,
        audit=audit_output,
        summary=summary_output,
    )


def _read_manual_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_fields = [field for field in MANUAL_RELATION_FIELDS if field not in (reader.fieldnames or [])]
        if missing_fields:
            raise ValueError("manual relation CSV missing fields: " + ", ".join(missing_fields))
        return [{field: _text(row.get(field)) for field in MANUAL_RELATION_FIELDS} for row in reader]


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: Iterable[str]) -> None:
    field_names = list(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_names)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in field_names})


def _semantic_node_ids(features: Iterable[Any], *, id_field: str, mainnode_field: str) -> set[str]:
    result: set[str] = set()
    for feature in features:
        node_id = _normalize_id(feature.properties.get(id_field))
        mainnode_id = _valid_mainnode_id(feature.properties.get(mainnode_field))
        if node_id:
            result.add(node_id)
        if mainnode_id:
            result.add(mainnode_id)
    return result


def _selected_ids(value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in _text(value).split("|"):
        normalized = _normalize_id(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _valid_mainnode_id(value: Any) -> str | None:
    normalized = _normalize_id(value)
    return None if normalized in {None, "0"} else normalized


def _required_id(value: Any, label: str) -> str:
    normalized = _normalize_id(value)
    if normalized is None:
        raise ValueError(f"missing {label}")
    return normalized


def _normalize_id(value: Any) -> str | None:
    text = _text(value)
    if not text or text.upper() in {"NULL", "NONE", "NAN"}:
        return None
    signless = text[1:] if text[:1] in {"+", "-"} else text
    if signless.isdigit():
        return str(int(text))
    integer_part, separator, fractional_part = signless.partition(".")
    if (
        separator
        and integer_part.isdigit()
        and fractional_part
        and set(fractional_part) == {"0"}
    ):
        signed_integer = f"{text[:1]}{integer_part}" if text[:1] in {"+", "-"} else integer_part
        return str(int(signed_integer))
    return text


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


__all__ = [
    "MANUAL_RELATION_FIELDS",
    "ManualRelationTransformArtifacts",
    "ManualRelationTransformError",
    "transform_manual_relations",
]
