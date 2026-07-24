from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_models import (
    HierarchicalTrainingExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_dataset import (
    load_dataset_p1_hierarchical_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p9_models import (
    SchemeAP2P3P9Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


_P7_DECISION = "P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO"
_P8_DECISION = (
    "P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_CLUE_SOURCE_BLOCKED"
)
_P5_DECISION = "P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO"
_P5_DATASET_DECISION = "P05_SCHEME_A_P2_P3_P5_DATASET_GO"
_MISSING = "<MISSING>"
_UNKNOWN = "<UNKNOWN>"


@dataclass(frozen=True)
class SourceFoldTransform:
    fields: tuple[str, ...]
    field_kinds: tuple[str, ...]
    categorical_values: tuple[tuple[str, ...], ...]
    feature_names: tuple[str, ...]
    train_case_keys: tuple[str, ...]
    signature: str

    @property
    def fact_dimension(self) -> int:
        return len(self.feature_names)

    @property
    def pooled_dimension(self) -> int:
        return self.fact_dimension * 2


@dataclass(frozen=True)
class EncodedSourceRow:
    group_id: str
    case_key: str
    source_applicable: bool
    values: tuple[float, ...]


def load_p9_inputs(
    config: SchemeAP2P3P9Config,
) -> tuple[
    list[HierarchicalTrainingExample],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
]:
    loader_config = replace(
        config.engine_config,
        base_config=replace(
            config.engine_config.base_config,
            expected_evidence_dim=202,
        ),
    )
    examples, metadata = load_dataset_p1_hierarchical_examples(
        loader_config
    )
    p7_root = normalize_runtime_path(config.p7_run_root).resolve(strict=True)
    p8_root = normalize_runtime_path(config.p8_run_root).resolve(strict=True)
    p5_root = normalize_runtime_path(config.p5_run_root).resolve(strict=True)
    p5_dataset_root = normalize_runtime_path(
        config.engine_config.base_config.dataset_run_root
    ).resolve(strict=True)
    p5_manifest_path = p5_root / "scheme_a_p2_p3_p5_manifest.json"
    p5_dataset_manifest_path = (
        p5_dataset_root / "scheme_a_p2_p3_p5_dataset_manifest.json"
    )
    p7_manifest_path = p7_root / "scheme_a_p2_p3_p7_manifest.json"
    p8_manifest_path = p8_root / "scheme_a_p2_p3_p8_manifest.json"
    p5_manifest = _read_json(p5_manifest_path)
    p5_dataset_manifest = _read_json(p5_dataset_manifest_path)
    p7_manifest = _read_json(p7_manifest_path)
    p8_manifest = _read_json(p8_manifest_path)
    if p5_manifest.get("decision") != _P5_DECISION:
        raise ValueError("P5 decision differs from the P9 frozen input")
    if p5_dataset_manifest.get("decision") != _P5_DATASET_DECISION:
        raise ValueError("P5 scope-first dataset decision differs")
    if not str(
        (p5_dataset_manifest.get("lineage") or {}).get("p4_manifest_sha256")
        or ""
    ):
        raise ValueError("P5 scope-first dataset lacks P4 lineage")
    if p7_manifest.get("decision") != _P7_DECISION:
        raise ValueError("P7 decision differs from the P9 frozen input")
    if p8_manifest.get("decision") != _P8_DECISION:
        raise ValueError("P8 decision differs from the P9 frozen input")
    p7_outputs = dict(p7_manifest.get("outputs") or {})
    p8_outputs = dict(p8_manifest.get("outputs") or {})
    representation_path = _verified_output(
        p7_outputs, "representations", config.strict_hashes
    )
    feature_contract_path = _verified_output(
        p7_outputs, "feature_contract", config.strict_hashes
    )
    applicability_path = _verified_output(
        p8_outputs, "segment_applicability", config.strict_hashes
    )
    field_contract_path = _verified_output(
        p8_outputs, "field_contract", config.strict_hashes
    )
    feature_contract = _read_json(feature_contract_path)
    field_contract = _read_json(field_contract_path)
    fields = tuple(field_contract.get("promotion_candidate_fields") or ())
    if (
        int(feature_contract.get("feature_count") or 0)
        != config.expected_feature_count
        or len(fields) != config.expected_promotion_field_count
    ):
        raise ValueError("P7/P8 feature contract differs from P9")
    forbidden_counts = (
        "truth_feature_count",
        "identifier_feature_count",
        "absolute_coordinate_feature_count",
        "movement_feature_count",
    )
    if any(int(feature_contract.get(key) or 0) for key in forbidden_counts):
        raise ValueError("P7 representation contains a forbidden feature")
    if any(int(field_contract.get(key) or 0) for key in forbidden_counts):
        raise ValueError("P8 source contract contains a forbidden feature")
    if any(
        int(field_contract.get(key) or 0)
        for key in (
            "free_text_feature_count",
            "path_feature_count",
            "review_feature_count",
            "t05_t06_feature_count",
        )
    ):
        raise ValueError("P8 source contract contains a prohibited field role")

    representations: dict[str, tuple[float, ...]] = {}
    for row in _read_jsonl(representation_path):
        group_id = str(row["group_id"])
        values = tuple(float(value) for value in row["features"])
        if len(values) != config.expected_feature_count:
            raise ValueError(f"P7 representation dimension differs: {group_id}")
        if (
            row.get("feature_uses_truth")
            or row.get("feature_uses_identifier")
            or int(row.get("absolute_coordinate_feature_count") or 0)
            or int(row.get("movement_feature_count") or 0)
        ):
            raise ValueError(f"forbidden P7 representation marker: {group_id}")
        if group_id in representations:
            raise ValueError(f"duplicate P7 representation: {group_id}")
        representations[group_id] = values
    example_ids = {example.group.group_id for example in examples}
    if set(representations) != example_ids:
        raise ValueError("P7 representation and eligible P9 scope differ")
    control_examples = [
        replace(
            example,
            evidence_features=representations[example.group.group_id],
        )
        for example in examples
    ]

    source_rows = list(_read_jsonl(applicability_path))
    source_by_id: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        group_id = str(row["group_id"])
        if group_id in source_by_id:
            raise ValueError(f"duplicate P8 applicability row: {group_id}")
        if bool(row["source_applicable"]) != bool(row.get("source_facts")):
            raise ValueError(f"P8 applicability/fact mismatch: {group_id}")
        if int(row["source_count"]) != len(row.get("source_facts") or []):
            raise ValueError(f"P8 source count mismatch: {group_id}")
        source_by_id[group_id] = row
    if set(source_by_id) != example_ids:
        raise ValueError("P8 applicability and eligible P9 scope differ")
    applicable_count = sum(
        bool(row["source_applicable"]) for row in source_rows
    )
    if applicable_count != config.expected_source_applicable_count:
        raise ValueError("P8 source-applicable denominator differs")
    if len(source_rows) - applicable_count != (
        config.expected_source_not_applicable_count
    ):
        raise ValueError("P8 no-source denominator differs")
    if (
        len(examples) != config.expected_eligible_count
        or len({example.group.case_key for example in examples})
        != config.expected_case_count
    ):
        raise ValueError("P9 eligible Case/Segment denominator differs")

    lineage = {
        "p5_manifest_sha256": sha256_file(p5_manifest_path),
        "p5_dataset_manifest_sha256": sha256_file(
            p5_dataset_manifest_path
        ),
        "p4_manifest_sha256": str(
            p5_dataset_manifest["lineage"]["p4_manifest_sha256"]
        ),
        "p7_manifest_sha256": sha256_file(p7_manifest_path),
        "p7_representation_sha256": sha256_file(representation_path),
        "p7_feature_contract_sha256": sha256_file(feature_contract_path),
        "p8_manifest_sha256": sha256_file(p8_manifest_path),
        "p8_applicability_sha256": sha256_file(applicability_path),
        "p8_field_contract_sha256": sha256_file(field_contract_path),
        "dataset_p1_training_signature": metadata["lineage"][
            "dataset_p1_training_signature"
        ],
    }
    lineage["p9_input_signature"] = canonical_sha256(lineage)
    return control_examples, {
        **metadata,
        "p9_lineage": lineage,
        "p7_feature_contract": feature_contract,
        "p8_field_contract": field_contract,
    }, source_rows, field_contract


def build_source_fold_transform(
    rows: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str],
    train_case_keys: Sequence[str],
) -> SourceFoldTransform:
    train_cases = set(train_case_keys)
    if not train_cases:
        raise ValueError("source transform has no training Cases")
    ordered_fields = tuple(str(field) for field in fields)
    kinds = tuple(_field_kind(field) for field in ordered_fields)
    facts = [
        fact
        for row in rows
        if str(row["case_key"]) in train_cases
        for fact in row.get("source_facts") or []
    ]
    categorical_values: list[tuple[str, ...]] = []
    feature_names: list[str] = []
    for field, kind in zip(ordered_fields, kinds, strict=True):
        if kind == "count":
            categorical_values.append(())
            feature_names.extend((f"{field}:present", f"{field}:log1p"))
        elif kind == "boolean":
            values = ("MISSING", "FALSE", "TRUE")
            categorical_values.append(values)
            feature_names.extend(f"{field}:{value}" for value in values)
        else:
            observed = sorted(
                {
                    _normalize_categorical(field, fact[field])
                    for fact in facts
                    if field in fact and fact[field] is not None
                }
            )
            values = (_MISSING, _UNKNOWN, *observed)
            categorical_values.append(values)
            feature_names.extend(f"{field}:{value}" for value in values)
    payload = {
        "fields": ordered_fields,
        "field_kinds": kinds,
        "categorical_values": categorical_values,
        "feature_names": feature_names,
        "train_case_keys": sorted(train_cases),
    }
    return SourceFoldTransform(
        fields=ordered_fields,
        field_kinds=kinds,
        categorical_values=tuple(categorical_values),
        feature_names=tuple(feature_names),
        train_case_keys=tuple(sorted(train_cases)),
        signature=canonical_sha256(payload),
    )


def encode_source_rows(
    rows: Sequence[Mapping[str, Any]],
    transform: SourceFoldTransform,
) -> list[EncodedSourceRow]:
    result: list[EncodedSourceRow] = []
    for row in rows:
        applicable = bool(row["source_applicable"])
        facts = list(row.get("source_facts") or [])
        if not applicable:
            values = (0.0,) * transform.pooled_dimension
        else:
            encoded_facts = [
                _encode_fact(fact, transform) for fact in facts
            ]
            values = tuple(
                sum(fact[index] for fact in encoded_facts)
                / len(encoded_facts)
                for index in range(transform.fact_dimension)
            ) + tuple(
                max(fact[index] for fact in encoded_facts)
                for index in range(transform.fact_dimension)
            )
        result.append(
            EncodedSourceRow(
                group_id=str(row["group_id"]),
                case_key=str(row["case_key"]),
                source_applicable=applicable,
                values=values,
            )
        )
    return result


def _encode_fact(
    fact: Mapping[str, Any],
    transform: SourceFoldTransform,
) -> tuple[float, ...]:
    values: list[float] = []
    for field, kind, categories in zip(
        transform.fields,
        transform.field_kinds,
        transform.categorical_values,
        strict=True,
    ):
        raw = fact.get(field)
        if kind == "count":
            present = field in fact and raw is not None
            numeric = max(0.0, float(raw)) if present else 0.0
            values.extend((float(present), math.log1p(numeric)))
        elif kind == "boolean":
            token = (
                "MISSING"
                if field not in fact or raw is None
                else ("TRUE" if bool(raw) else "FALSE")
            )
            values.extend(float(token == category) for category in categories)
        else:
            if field not in fact or raw is None:
                token = _MISSING
            else:
                normalized = _normalize_categorical(field, raw)
                token = normalized if normalized in categories else _UNKNOWN
            values.extend(float(token == category) for category in categories)
    if len(values) != transform.fact_dimension:
        raise ValueError("encoded source fact dimension differs")
    return tuple(values)


def _field_kind(field: str) -> str:
    if field.endswith("_count"):
        return "count"
    boolean_suffixes = (
        "_ok",
        "_present",
        "_performed",
        "_detected",
        "_localized",
        "_suggested",
        "_suppressed_by_no_surface_reference",
    )
    if field.endswith(boolean_suffixes) or field in {
        "forbidden_domain_kept",
        "has_c_unit",
        "no_surface_reference_guard",
    }:
        return "boolean"
    return "categorical"


def _normalize_categorical(field: str, value: Any) -> str:
    text = str(value)
    if field in {"junction_type", "scene_type"} and (
        "merge" in text.casefold() or "diverge" in text.casefold()
    ):
        return "MERGE_DIVERGE_CONTEXT"
    return text


def _verified_output(
    outputs: Mapping[str, Any],
    key: str,
    strict_hashes: bool,
) -> Path:
    record = dict(outputs.get(key) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(
        strict=True
    )
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"P9 source output hash mismatch: {key}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = [
    "EncodedSourceRow",
    "SourceFoldTransform",
    "build_source_fold_transform",
    "encode_source_rows",
    "load_p9_inputs",
]
