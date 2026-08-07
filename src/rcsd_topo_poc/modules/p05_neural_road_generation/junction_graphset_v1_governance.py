from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class FeatureContractError(ValueError):
    """Raised when a compatibility feature violates the frozen v1 contract."""


class DevelopmentIsolationError(ValueError):
    """Raised when feature and development-label shards are not isolated."""


class BlindTestAccessError(RuntimeError):
    """Raised when the sealed blind-test identities are accessed before T029."""


class FeatureSourceClass(str, Enum):
    RAW_FIELD = "raw"
    DERIVED_GEOMETRY = "derived_geometry"
    CANDIDATE_METADATA = "candidate_metadata"
    FORBIDDEN = "forbidden"


class StageVisibility(str, Enum):
    STEP1 = "step1"
    POST_STEP1 = "post_step1"
    DISABLED = "disabled"


@dataclass(frozen=True)
class FeatureFieldSpec:
    vector_type: str
    index: int
    name: str
    source_class: FeatureSourceClass
    visibility: StageVisibility
    source: str
    note: str = ""


def _field(
    vector_type: str,
    index: int,
    name: str,
    source_class: FeatureSourceClass,
    visibility: StageVisibility,
    source: str,
    note: str = "",
) -> FeatureFieldSpec:
    return FeatureFieldSpec(
        vector_type=vector_type,
        index=index,
        name=name,
        source_class=source_class,
        visibility=visibility,
        source=source,
        note=note,
    )


STEP1_OBJECT_INDICES = (0, 1, 2, 3, 13, 14, 15, 21, 22, 23, 24)


_OBJECT_NAMES = (
    "swsd_kind_norm",
    "swsd_kind2_norm",
    "swsd_grade_norm",
    "swsd_closed_con_norm",
    "rcsd_node_group_count",
    "rcsd_node_group_count_le25",
    "rcsd_node_group_count_le50",
    "rcsd_node_group_count_le80",
    "rcsd_node_group_count_le120",
    "rcsd_node_group_min_distance",
    "rcsd_intersection_surface_count",
    "rcsd_intersection_surface_touch_count",
    "rcsd_intersection_surface_min_distance",
    "swsd_arm_count",
    "swsd_unique_bearing_count",
    "swsd_bearing_dispersion",
    "rcsd_road_count",
    "rcsd_road_count_le10",
    "rcsd_road_count_le25",
    "rcsd_road_count_le50",
    "rcsd_road_min_distance",
    "drivezone_count",
    "drivezone_cover_count",
    "drivezone_min_distance",
    "containing_drivezone_area_log",
)


def _object_specs() -> tuple[FeatureFieldSpec, ...]:
    specs: list[FeatureFieldSpec] = []
    for index, name in enumerate(_OBJECT_NAMES):
        visibility = (
            StageVisibility.STEP1
            if index in STEP1_OBJECT_INDICES
            else StageVisibility.POST_STEP1
        )
        if index <= 3:
            source_class = FeatureSourceClass.RAW_FIELD
            source = "SWSD Junction attributes"
        elif index <= 9:
            source_class = FeatureSourceClass.DERIVED_GEOMETRY
            source = "RCSD Node/group geometry"
        elif index <= 12:
            source_class = FeatureSourceClass.DERIVED_GEOMETRY
            source = "RCSDIntersection geometry"
        elif index <= 15:
            source_class = FeatureSourceClass.DERIVED_GEOMETRY
            source = "SWSD arm geometry"
        elif index <= 20:
            source_class = FeatureSourceClass.DERIVED_GEOMETRY
            source = "RCSD Road geometry"
        else:
            source_class = FeatureSourceClass.DERIVED_GEOMETRY
            source = "DriveZone geometry"
        specs.append(
            _field(
                "object64",
                index,
                name,
                source_class,
                visibility,
                source,
            )
        )
    specs.extend(
        _field(
            "object64",
            index,
            f"padding_{index}",
            FeatureSourceClass.FORBIDDEN,
            StageVisibility.DISABLED,
            "constant zero padding",
            "Must remain zero and must not be learned as evidence.",
        )
        for index in range(25, 64)
    )
    return tuple(specs)


_NODE_CANDIDATE_NAMES = {
    0: "distance",
    1: "distance_le5",
    2: "distance_le10",
    3: "distance_le25",
    4: "distance_le50",
    5: "distance_le80",
    6: "distance_le120",
    7: "member_count",
    8: "max_kind",
    9: "max_cross_flag",
    10: "layer_cardinality",
    11: "incident_road_total",
    12: "incident_direction_0_count",
    13: "incident_direction_1_count",
    14: "incident_direction_2_count",
    15: "incident_direction_3_count",
    16: "rcsd_intersection_surface_exists",
    17: "rcsd_intersection_type",
    18: "rcsd_intersection_level",
    19: "rcsd_intersection_is_highway",
    20: "rcsd_intersection_node_count",
    21: "rcsd_intersection_inner_road_count",
    22: "rcsd_intersection_surface_distance",
    23: "offset_dx",
    24: "offset_dy",
    25: "offset_abs_dx",
    26: "offset_abs_dy",
    27: "is_road_bundle",
    28: "swsd_arm_count",
    29: "candidate_arm_count",
    30: "arm_count_abs_difference",
    31: "swsd_to_candidate_arm_alignment",
    32: "candidate_to_swsd_arm_alignment",
    33: "arm_count_equal",
    34: "swsd_arm_dispersion",
    35: "candidate_arm_dispersion",
}


def _node_candidate_specs() -> tuple[FeatureFieldSpec, ...]:
    raw_indices = set(range(8, 16)) | set(range(17, 22))
    metadata_indices = {7, 27}
    specs: list[FeatureFieldSpec] = []
    for index in range(36):
        if index in raw_indices:
            source_class = FeatureSourceClass.RAW_FIELD
            source = "RCSD Node/RCSDIntersection attributes"
        elif index in metadata_indices:
            source_class = FeatureSourceClass.CANDIDATE_METADATA
            source = "candidate construction metadata"
        else:
            source_class = FeatureSourceClass.DERIVED_GEOMETRY
            source = "SWSD-to-RCSD geometry/topology derivation"
        specs.append(
            _field(
                "node_candidate64",
                index,
                _NODE_CANDIDATE_NAMES[index],
                source_class,
                StageVisibility.POST_STEP1,
                source,
            )
        )
    specs.extend(
        _field(
            "node_candidate64",
            index,
            f"padding_{index}",
            FeatureSourceClass.FORBIDDEN,
            StageVisibility.DISABLED,
            "constant zero padding",
            "Must remain zero.",
        )
        for index in range(36, 64)
    )
    return tuple(specs)


_ROAD_BUNDLE_NAMES = {
    0: "min_distance",
    1: "distance_le5",
    2: "distance_le10",
    3: "distance_le25",
    4: "distance_le50",
    5: "distance_le80",
    6: "distance_le120",
    7: "road_count",
    8: "total_length",
    9: "max_length",
    10: "graph_node_count",
    11: "connected_component_count",
    12: "leaf_count",
    13: "branch_count",
    14: "direction_0_count",
    15: "direction_1_count",
    16: "direction_2_count",
    17: "direction_3_count",
    18: "max_function_class",
    19: "projection_fraction",
    20: "generator_threshold",
    21: "generator_is_road_single",
    22: "generator_is_road_nearest_prefix",
    23: "generator_is_road_distance_set",
    24: "generator_is_road_connected_component",
    25: "generator_reserved_25",
    26: "generator_reserved_26",
    27: "is_road_bundle",
    28: "swsd_arm_count",
    29: "candidate_arm_count",
    30: "arm_count_abs_difference",
    31: "swsd_to_candidate_arm_alignment",
    32: "candidate_to_swsd_arm_alignment",
    33: "arm_count_equal",
    34: "swsd_arm_dispersion",
    35: "candidate_arm_dispersion",
    36: "corridor_min_distance",
    37: "corridor_coverage_buffer_5",
    38: "corridor_coverage_buffer_10",
    39: "corridor_coverage_buffer_20",
    40: "corridor_coverage_buffer_35",
    41: "local_corridor_coverage_buffer_5",
    42: "local_corridor_coverage_buffer_10",
    43: "local_corridor_coverage_buffer_20",
    44: "local_corridor_coverage_buffer_35",
}


def _road_bundle_specs() -> tuple[FeatureFieldSpec, ...]:
    raw_indices = set(range(14, 19))
    metadata_indices = {7} | set(range(20, 28))
    specs: list[FeatureFieldSpec] = []
    for index in range(45):
        if index in raw_indices:
            source_class = FeatureSourceClass.RAW_FIELD
            source = "RCSD Road attributes"
        elif index in metadata_indices:
            source_class = FeatureSourceClass.CANDIDATE_METADATA
            source = "candidate generation metadata"
        else:
            source_class = FeatureSourceClass.DERIVED_GEOMETRY
            source = "Road bundle geometry/topology derivation"
        note = ""
        if index in {25, 26}:
            note = "Reserved legacy metadata dimension; not business evidence."
        specs.append(
            _field(
                "road_bundle64",
                index,
                _ROAD_BUNDLE_NAMES[index],
                source_class,
                (
                    StageVisibility.DISABLED
                    if index in {25, 26}
                    else StageVisibility.POST_STEP1
                ),
                source,
                note,
            )
        )
    specs.extend(
        _field(
            "road_bundle64",
            index,
            f"padding_{index}",
            FeatureSourceClass.FORBIDDEN,
            StageVisibility.DISABLED,
            "constant zero padding",
            "Must remain zero.",
        )
        for index in range(45, 64)
    )
    return tuple(specs)


_MEMBER_NAMES = (
    "is_road",
    "distance_or_radius",
    "distance_le5",
    "distance_le10",
    "distance_le25",
    "distance_le50",
    "projection_fraction",
    "start_distance",
    "end_distance",
    "tangent_sin",
    "tangent_cos",
    "length_norm",
)


def _member_specs() -> tuple[FeatureFieldSpec, ...]:
    return tuple(
        _field(
            "member12",
            index,
            name,
            (
                FeatureSourceClass.CANDIDATE_METADATA
                if index == 0
                else FeatureSourceClass.DERIVED_GEOMETRY
            ),
            StageVisibility.POST_STEP1,
            (
                "member object type"
                if index == 0
                else "member-to-Junction geometry derivation"
            ),
            (
                "Node members must keep indices 6-11 at zero."
                if index in range(6, 12)
                else ""
            ),
        )
        for index, name in enumerate(_MEMBER_NAMES)
    )


OBJECT64_SPECS = _object_specs()
NODE_CANDIDATE64_SPECS = _node_candidate_specs()
ROAD_BUNDLE64_SPECS = _road_bundle_specs()
MEMBER12_SPECS = _member_specs()

FEATURE_SPECS: Mapping[str, tuple[FeatureFieldSpec, ...]] = {
    "object64": OBJECT64_SPECS,
    "node_candidate64": NODE_CANDIDATE64_SPECS,
    "road_bundle64": ROAD_BUNDLE64_SPECS,
    "member12": MEMBER12_SPECS,
}


EXPECTED_SOURCE_COUNTS: Mapping[str, Mapping[str, int]] = {
    "object64": {"raw": 4, "derived_geometry": 21, "candidate_metadata": 0, "forbidden": 39},
    "node_candidate64": {"raw": 13, "derived_geometry": 21, "candidate_metadata": 2, "forbidden": 28},
    "road_bundle64": {"raw": 5, "derived_geometry": 31, "candidate_metadata": 9, "forbidden": 19},
    "member12": {"raw": 0, "derived_geometry": 11, "candidate_metadata": 1, "forbidden": 0},
}


def audit_feature_contract() -> Mapping[str, Any]:
    dimensions: dict[str, int] = {}
    source_counts: dict[str, dict[str, int]] = {}
    for vector_type, specs in FEATURE_SPECS.items():
        dimensions[vector_type] = len(specs)
        indices = tuple(spec.index for spec in specs)
        if indices != tuple(range(len(specs))):
            raise FeatureContractError(f"{vector_type} indices are not contiguous")
        counts = Counter(spec.source_class.value for spec in specs)
        normalized_counts = {
            source_class.value: counts[source_class.value]
            for source_class in FeatureSourceClass
        }
        if normalized_counts != EXPECTED_SOURCE_COUNTS[vector_type]:
            raise FeatureContractError(
                f"{vector_type} source counts changed: {normalized_counts}"
            )
        source_counts[vector_type] = normalized_counts

    if dimensions != {
        "object64": 64,
        "node_candidate64": 64,
        "road_bundle64": 64,
        "member12": 12,
    }:
        raise FeatureContractError(f"feature dimensions changed: {dimensions}")

    step1_fields = tuple(
        spec.index
        for vector_type, specs in FEATURE_SPECS.items()
        for spec in specs
        if spec.visibility == StageVisibility.STEP1 and vector_type == "object64"
    )
    foreign_step1_fields = tuple(
        (vector_type, spec.index)
        for vector_type, specs in FEATURE_SPECS.items()
        for spec in specs
        if spec.visibility == StageVisibility.STEP1 and vector_type != "object64"
    )
    if step1_fields != STEP1_OBJECT_INDICES or foreign_step1_fields:
        raise FeatureContractError(
            f"Step1 visibility changed: object={step1_fields}, foreign={foreign_step1_fields}"
        )
    if any(
        spec.visibility != StageVisibility.DISABLED
        for specs in FEATURE_SPECS.values()
        for spec in specs
        if spec.source_class == FeatureSourceClass.FORBIDDEN
    ):
        raise FeatureContractError("forbidden feature dimension is enabled")

    return {
        "dimensions": dimensions,
        "source_counts": source_counts,
        "total_typed_dimensions": sum(dimensions.values()),
        "step1_object_indices": STEP1_OBJECT_INDICES,
    }


def validate_compatibility_vector(
    vector_type: str,
    values: Sequence[float],
) -> tuple[float, ...]:
    if vector_type not in FEATURE_SPECS:
        raise FeatureContractError(
            f"unknown or untyped compatibility vector: {vector_type!r}"
        )
    specs = FEATURE_SPECS[vector_type]
    if len(values) != len(specs):
        raise FeatureContractError(
            f"{vector_type} requires {len(specs)} values, got {len(values)}"
        )
    normalized = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in normalized):
        raise FeatureContractError(f"{vector_type} contains a non-finite value")
    nonzero_disabled = tuple(
        spec.index
        for spec in specs
        if spec.visibility == StageVisibility.DISABLED
        and abs(normalized[spec.index]) > 1e-12
    )
    if nonzero_disabled:
        raise FeatureContractError(
            f"{vector_type} forbidden/disabled dimensions are nonzero: {nonzero_disabled}"
        )
    return normalized


def project_step1_object_features(values: Sequence[float]) -> tuple[float, ...]:
    normalized = validate_compatibility_vector("object64", values)
    return tuple(normalized[index] for index in STEP1_OBJECT_INDICES)


_ALLOWED_FEATURE_KEYS = frozenset(
    {
        "sample_id",
        "anchor_id",
        "input_fingerprint",
        "object_features",
        "candidate_ids",
        "candidate_features",
        "candidate_vector_types",
        "structural_member_ids",
        "swsd_arm_features",
        "member_arm_features",
        "member_local_features",
        "member_relation_edges",
        "geometry_token_features",
        "geometry_object_spans",
        "geometry_relation_edges",
        "drivezone_grid_indices",
    }
)
_FORBIDDEN_FEATURE_KEY_TOKENS = (
    "label",
    "truth",
    "preferred",
    "acceptable",
    "selected",
    "status",
    "split",
    "fold",
    "family",
    "route",
    "t03",
    "t04",
    "t05",
)


def _scan_feature_keys(value: Any, path: str = "feature_row") -> None:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            normalized_key = str(key).strip().lower()
            if any(token in normalized_key for token in _FORBIDDEN_FEATURE_KEY_TOKENS):
                raise DevelopmentIsolationError(
                    f"terminal/label key is forbidden in feature shard: {path}.{key}"
                )
            _scan_feature_keys(nested_value, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested_value in enumerate(value):
            _scan_feature_keys(nested_value, f"{path}[{index}]")


def validate_inference_feature_row(row: Mapping[str, Any]) -> None:
    unknown_keys = sorted(set(row) - _ALLOWED_FEATURE_KEYS)
    if unknown_keys:
        raise DevelopmentIsolationError(
            f"unknown feature keys are not allowed: {unknown_keys}"
        )
    _scan_feature_keys(row)
    sample_id = str(row.get("sample_id") or "").strip()
    if not sample_id:
        raise DevelopmentIsolationError("feature row requires sample_id")
    if "object_features" not in row:
        raise DevelopmentIsolationError("feature row requires object_features")
    validate_compatibility_vector("object64", row["object_features"])

    candidate_features = row.get("candidate_features")
    candidate_types = row.get("candidate_vector_types")
    if candidate_features is None and candidate_types is None:
        return
    if not isinstance(candidate_features, Sequence) or not isinstance(
        candidate_types, Sequence
    ):
        raise DevelopmentIsolationError(
            "candidate_features and candidate_vector_types must both be sequences"
        )
    if len(candidate_features) != len(candidate_types):
        raise DevelopmentIsolationError(
            "candidate_features and candidate_vector_types lengths differ"
        )
    for vector_type, values in zip(candidate_types, candidate_features):
        if vector_type not in {"node_candidate64", "road_bundle64"}:
            raise DevelopmentIsolationError(
                f"candidate vector type must be explicit, got {vector_type!r}"
            )
        validate_compatibility_vector(str(vector_type), values)


@dataclass(frozen=True)
class DevelopmentExample:
    sample_id: str
    split: str
    features: Mapping[str, Any]
    labels: Mapping[str, Any]


def _index_unique_rows(
    rows: Sequence[Mapping[str, Any]],
    shard_name: str,
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        sample_id = str(row.get("sample_id") or "").strip()
        if not sample_id:
            raise DevelopmentIsolationError(f"{shard_name} row requires sample_id")
        if sample_id in indexed:
            raise DevelopmentIsolationError(
                f"duplicate {shard_name} sample_id: {sample_id}"
            )
        indexed[sample_id] = row
    return indexed


def build_development_view(
    feature_rows: Sequence[Mapping[str, Any]],
    label_rows: Sequence[Mapping[str, Any]],
) -> tuple[DevelopmentExample, ...]:
    """Join physically separate development shards without ever admitting test labels."""

    feature_by_id = _index_unique_rows(feature_rows, "feature")
    label_by_id = _index_unique_rows(label_rows, "label")
    if set(feature_by_id) != set(label_by_id):
        missing_features = sorted(set(label_by_id) - set(feature_by_id))
        missing_labels = sorted(set(feature_by_id) - set(label_by_id))
        raise DevelopmentIsolationError(
            "feature/label identities differ: "
            f"missing_features={missing_features}, missing_labels={missing_labels}"
        )

    examples: list[DevelopmentExample] = []
    for sample_id in sorted(feature_by_id):
        feature_row = feature_by_id[sample_id]
        label_row = label_by_id[sample_id]
        validate_inference_feature_row(feature_row)
        split = str(label_row.get("split") or "").strip().lower()
        if split not in {"train", "validation"}:
            raise BlindTestAccessError(
                f"development view cannot read split={split!r} for {sample_id}"
            )
        examples.append(
            DevelopmentExample(
                sample_id=sample_id,
                split=split,
                features=feature_row,
                labels=label_row,
            )
        )
    return tuple(examples)


def aggregate_identity_sha256(sample_ids: Sequence[str]) -> str:
    normalized = sorted(str(sample_id).strip() for sample_id in sample_ids)
    if any(not sample_id for sample_id in normalized):
        raise ValueError("blank sample_id is not allowed")
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate sample_id is not allowed")
    payload = "".join(f"{sample_id}\n" for sample_id in normalized).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class BlindTestSeal:
    split_file_sha256: str
    sealed_test_count: int
    schema_discovery_quarantine_sample_id: str
    remaining_blind_count: int
    remaining_blind_identity_sha256: str

    def validate(self) -> None:
        if self.sealed_test_count != self.remaining_blind_count + 1:
            raise FeatureContractError("blind-test seal count is inconsistent")
        for field_name, digest in (
            ("split_file_sha256", self.split_file_sha256),
            ("remaining_blind_identity_sha256", self.remaining_blind_identity_sha256),
        ):
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise FeatureContractError(f"{field_name} is not a lowercase SHA-256")
        if not self.schema_discovery_quarantine_sample_id:
            raise FeatureContractError("quarantine sample_id is required")


FROZEN_BLIND_TEST_SEAL = BlindTestSeal(
    split_file_sha256="7b9246416c0f3a5d101d89b576e6946f5c2213556dcb451228dd6c7ffb6b5a27",
    sealed_test_count=106,
    schema_discovery_quarantine_sample_id=(
        "junction-gold:POC_Data:T04_Error:1010449:6f546311f57ad6aa"
    ),
    remaining_blind_count=105,
    remaining_blind_identity_sha256=(
        "db46622ac3f04e965beed64b534885c1e79d9728a38295d3684df5dd17db5dc4"
    ),
)


def open_blind_test_view(*_args: Any, **_kwargs: Any) -> None:
    raise BlindTestAccessError(
        "105 blind-test identities and labels remain sealed; access is forbidden until T029"
    )


audit_feature_contract()
FROZEN_BLIND_TEST_SEAL.validate()
