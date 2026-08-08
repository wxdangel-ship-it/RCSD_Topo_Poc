from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass, replace
from itertools import combinations, zip_longest
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence, TextIO

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_governance import (
    FROZEN_BLIND_TEST_SEAL,
    validate_inference_feature_row,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_materializer import (
    business_topology_signature,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_model import (
    JunctionTrainingOverlay,
    PairConstraint,
    RoadBreakSetTarget,
    RoadBreakTarget,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorNodeKind,
    AnchorNodeRef,
    AnchorResult,
    AnchorState,
    CandidateBinding,
    CandidatePlan,
    JunctionEvidenceExample,
    JunctionPredictionError,
    NodeEquivalenceClass,
    ObjectTokenSpan,
    QualityState,
    RoadBreakOperation,
    Step1DriveZoneState,
    SurfaceMode,
    SurfacePlan,
    VirtualSurfaceRecipe,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_surface import (
    ConstraintState,
    SurfaceConstraint,
)


EXPECTED_DEVELOPMENT_COUNT = 4_288
EXPECTED_SOURCE_COUNTS = {"STRONG_GOLD": 602, "T10_WEAK": 3_686}
EXPECTED_SPLIT_COUNTS = {"train": 3_645, "validation": 643}
EXPECTED_SOURCE_WEIGHTS = {"STRONG_GOLD": 1.0, "T10_WEAK": 0.7}

FEATURE_ROLE_BY_INDEX: Mapping[int, EvidenceRole] = {
    0: EvidenceRole.SWSD_NODE,
    1: EvidenceRole.SWSD_ROAD,
    2: EvidenceRole.DRIVEZONE,
    3: EvidenceRole.RCSD_NODE,
    4: EvidenceRole.RCSD_ROAD,
    5: EvidenceRole.DIVSTRIP,
    6: EvidenceRole.RCSD_INTERSECTION,
}
EXPECTED_FEATURE_PREFIX: Mapping[int, str] = {
    0: "SWSD_NODE",
    1: "SWSD_ROAD",
    2: "DRIVEZONE",
    3: "NODE",
    4: "ROAD",
    5: "DIVSTRIP",
    6: "RCSD_INTERSECTION",
}


@dataclass(frozen=True)
class T021DataPaths:
    output_root: Path
    derived_labels: Path
    derived_manifest: Path
    derived_summary: Path
    surface_constraints: Path
    surface_manifest: Path
    surface_summary: Path
    strong_feature_store: Path
    strong_label_store: Path
    strong_lineage_store: Path
    strong_manifest: Path
    strong_split_file: Path
    strong_split_summary: Path
    t10_store_root: Path
    t10_manifest: Path

    @classmethod
    def from_output_root(cls, output_root: Path) -> T021DataPaths:
        root = Path(output_root)
        derived = root / "target_a_junction_result_derived_label_overlay_20260806_v1r3"
        surface = root / "target_a_virtual_surface_constraint_overlay_20260806_v1r2"
        strong = root / "target_a_junction_joint_store_20260805_v10_geometry_graph"
        split = root / "target_a_junction_gold_split_20260804_v2"
        t10 = root / "target_a_junction_joint_t10_store_20260805_v5r2_manual_precedence"
        return cls(
            output_root=root,
            derived_labels=derived / "junction_result_derived_labels.jsonl",
            derived_manifest=derived / "manifest.json",
            derived_summary=derived / "summary.json",
            surface_constraints=surface / "virtual_surface_constraint_labels.jsonl",
            surface_manifest=surface / "manifest.json",
            surface_summary=surface / "summary.json",
            strong_feature_store=strong / "inference_feature_store" / "junction_features.jsonl",
            strong_label_store=strong / "training_label_store" / "junction_labels.jsonl",
            strong_lineage_store=strong / "lineage_store" / "junction_lineage.jsonl",
            strong_manifest=strong / "manifest.json",
            strong_split_file=split / "junction_gold_split_samples.jsonl",
            strong_split_summary=split / "summary.json",
            t10_store_root=t10,
            t10_manifest=t10 / "manifest.json",
        )

    def required_files(self) -> tuple[Path, ...]:
        return (
            self.derived_labels,
            self.derived_manifest,
            self.derived_summary,
            self.surface_constraints,
            self.surface_manifest,
            self.surface_summary,
            self.strong_feature_store,
            self.strong_label_store,
            self.strong_lineage_store,
            self.strong_manifest,
            self.strong_split_file,
            self.strong_split_summary,
            self.t10_manifest,
        )


@dataclass(frozen=True)
class T021CacheConfig:
    data_paths: T021DataPaths
    output_dir: Path
    max_samples_per_shard: int = 32
    max_geometry_tokens_per_shard: int = 100_000

    def validate(self) -> None:
        if self.max_samples_per_shard < 1:
            raise ValueError("T021 max_samples_per_shard must be positive")
        if self.max_geometry_tokens_per_shard < 1:
            raise ValueError("T021 max_geometry_tokens_per_shard must be positive")
        for path in self.data_paths.required_files():
            if not Path(path).is_file():
                raise FileNotFoundError(path)


@dataclass(frozen=True)
class T021FeatureRecord:
    sample_id: str
    input_fingerprint: str
    example: JunctionEvidenceExample


@dataclass(frozen=True)
class T021LabelRecord:
    sample_id: str
    source: str
    split: str
    case_group_key: str
    overlay: JunctionTrainingOverlay
    teacher_step1_index: int
    teacher_surface_index: int
    teacher_candidate_binding: CandidateBinding
    task_masks: tuple[tuple[str, bool], ...]
    complete_plan_supervised: bool
    old_source_weight: float
    source_weight_normalized: bool
    legacy_candidate_acceptable_count: int


@dataclass(frozen=True)
class T021JoinedRecord:
    feature: T021FeatureRecord
    label: T021LabelRecord

    @property
    def teacher_example(self) -> JunctionEvidenceExample:
        return replace(
            self.feature.example,
            candidate_binding=self.label.teacher_candidate_binding,
        )


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise JunctionPredictionError(f"JSON object required: {path}")
    return value


def _read_jsonl_index(path: Path) -> dict[str, Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            row = json.loads(line)
            sample_id = str(row.get("sample_id") or "").strip()
            if not sample_id or sample_id in rows:
                raise JunctionPredictionError(
                    f"invalid or duplicate sample_id in {path.name}:{line_number}"
                )
            if str(row.get("split") or "").lower() == "test":
                raise JunctionPredictionError(
                    f"development overlay unexpectedly contains test row: {path.name}"
                )
            rows[sample_id] = row
    return rows


def _open_text(path: Path) -> TextIO:
    if Path(path).suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return Path(path).open("r", encoding="utf-8")


def iter_aligned_jsonl(
    paths: Sequence[Path],
    *,
    raw_prefix_skip: int = 0,
) -> Iterator[tuple[Mapping[str, Any], ...]]:
    """Join aligned stores while never decoding a sealed raw prefix."""

    streams = tuple(_open_text(Path(path)) for path in paths)
    try:
        for line_index, lines in enumerate(zip_longest(*streams)):
            if any(line is None for line in lines):
                raise JunctionPredictionError("aligned T021 source stores differ in length")
            if line_index < raw_prefix_skip:
                continue
            rows = tuple(json.loads(str(line)) for line in lines)
            sample_ids = tuple(str(row.get("sample_id") or "") for row in rows)
            if not sample_ids[0] or len(set(sample_ids)) != 1:
                raise JunctionPredictionError(
                    "aligned T021 source stores differ in sample identity"
                )
            yield rows
    finally:
        for stream in streams:
            stream.close()


def _parse_feature_ref(span: Mapping[str, Any]) -> ObjectRef:
    role_index = int(span["role_index"])
    if role_index not in FEATURE_ROLE_BY_INDEX:
        raise JunctionPredictionError(f"unknown T021 feature role index: {role_index}")
    encoded_id = str(span["object_id"])
    prefix, separator, object_id = encoded_id.partition(":")
    if not separator or prefix != EXPECTED_FEATURE_PREFIX[role_index] or not object_id:
        raise JunctionPredictionError(f"invalid T021 feature object ID: {encoded_id}")
    return ObjectRef(FEATURE_ROLE_BY_INDEX[role_index], object_id)


def _parse_object_ref(encoded_id: str) -> ObjectRef:
    prefix, separator, object_id = str(encoded_id).partition(":")
    if not separator or not object_id:
        raise JunctionPredictionError(f"invalid T021 object key: {encoded_id}")
    role = {
        "NODE": EvidenceRole.RCSD_NODE,
        "ROAD": EvidenceRole.RCSD_ROAD,
        "RCSD_INTERSECTION": EvidenceRole.RCSD_INTERSECTION,
    }.get(prefix)
    if role is None:
        raise JunctionPredictionError(f"unsupported T021 object key: {encoded_id}")
    return ObjectRef(role, object_id)


def _parse_anchor_node_ref(encoded_id: str) -> AnchorNodeRef:
    normalized = str(encoded_id)
    if normalized.startswith("NODE:"):
        return AnchorNodeRef.source_node(_parse_object_ref(normalized))
    prefix = "BREAK:ROAD:"
    if normalized.startswith(prefix) and "#" in normalized:
        road_id, break_rank = normalized[len(prefix) :].rsplit("#", 1)
        return AnchorNodeRef.road_break_point(
            ObjectRef(EvidenceRole.RCSD_ROAD, road_id),
            int(break_rank),
        )
    raise JunctionPredictionError(f"invalid canonical anchor Node key: {encoded_id}")


def _build_geometry_example(
    *,
    sample_id: str,
    feature: Mapping[str, Any],
    case_key: str,
) -> JunctionEvidenceExample:
    # Only fields that enter the network are passed to the frozen leakage validator.
    validate_inference_feature_row(
        {
            key: feature[key]
            for key in (
                "sample_id",
                "anchor_id",
                "input_fingerprint",
                "object_features",
                "structural_member_ids",
                "swsd_arm_features",
                "member_arm_features",
                "member_local_features",
                "member_relation_edges",
                "geometry_token_features",
                "geometry_object_spans",
                "geometry_relation_edges",
                "drivezone_grid_indices",
            )
            if key in feature
        }
    )
    span_rows = tuple(feature["geometry_object_spans"])
    object_refs = tuple(_parse_feature_ref(span) for span in span_rows)
    if len(set(object_refs)) != len(object_refs):
        raise JunctionPredictionError(f"T021 feature objects are duplicated: {sample_id}")
    spans = tuple(
        ObjectTokenSpan(ref, int(span["token_start"]), int(span["token_end"]))
        for ref, span in zip(object_refs, span_rows)
    )
    geometry_tokens = torch.tensor(feature["geometry_token_features"], dtype=torch.float32)
    relation_edges = tuple(feature["geometry_relation_edges"])
    if relation_edges:
        topology_edge_indices = torch.tensor(
            (
                tuple(spans[int(edge[0])].start for edge in relation_edges),
                tuple(spans[int(edge[1])].start for edge in relation_edges),
            ),
            dtype=torch.long,
        )
        topology_edge_features = torch.tensor(
            tuple(edge[2] for edge in relation_edges),
            dtype=torch.float32,
        )
    else:
        topology_edge_indices = torch.zeros((2, 0), dtype=torch.long)
        topology_edge_features = torch.zeros((0, 8), dtype=torch.float32)

    semantic_id = str(feature["anchor_id"])
    junction_key = f"{case_key}|{semantic_id}"
    example = JunctionEvidenceExample(
        junction_key=junction_key,
        case_key=case_key,
        semantic_junction_id=semantic_id,
        geometry_tokens=geometry_tokens,
        object_spans=spans,
        topology_edge_indices=topology_edge_indices,
        topology_edge_features=topology_edge_features,
        candidate_binding=CandidateBinding(
            junction_key=junction_key,
            allowed_object_refs=object_refs,
            plans=(_safe_abstain_plan(),),
        ),
    )
    example.validate()
    return example


def _safe_abstain_plan() -> CandidatePlan:
    return CandidatePlan(
        plan_id="safe:abstain",
        step1_drivezone_state=Step1DriveZoneState.ABSTAIN,
        surface_plan=SurfacePlan(mode=SurfaceMode.ABSTAIN),
        anchor_result=AnchorResult(state=AnchorState.ABSTAIN),
        quality_state=QualityState.REVIEW,
        review_reason="MODEL_ABSTAIN",
        planned_topology_signature="",
    )


def _quality_state(anchor_state: AnchorState) -> QualityState:
    return {
        AnchorState.SUCCESS: QualityState.NORMAL,
        AnchorState.NO_RCSD_EVIDENCE: QualityState.NO_EVIDENCE,
        AnchorState.AMBIGUOUS: QualityState.AMBIGUOUS,
        AnchorState.QUALITY_ISSUE: QualityState.QUALITY_ISSUE,
        AnchorState.ABSTAIN: QualityState.REVIEW,
    }[anchor_state]


def _review_reason(label: Mapping[str, Any], anchor_state: AnchorState) -> str:
    if anchor_state == AnchorState.SUCCESS:
        return ""
    if anchor_state == AnchorState.NO_RCSD_EVIDENCE:
        return "PROVEN_NO_RCSD_EVIDENCE"
    task_labels = label.get("task_labels", {})
    relation = str(task_labels.get("relation_state") or "").strip()
    if relation:
        return relation.upper()
    weak_reason = str(label.get("weak_label_reason") or "").strip()
    if weak_reason:
        return weak_reason
    return f"{anchor_state.value}_GOLD"


def _step1_state(label: Mapping[str, Any]) -> Step1DriveZoneState:
    value = str(label["task_labels"]["t07_step1"]).strip().lower()
    if value == "yes":
        return Step1DriveZoneState.EVIDENCE
    if value == "no":
        return Step1DriveZoneState.NO_EVIDENCE
    raise JunctionPredictionError(f"T021 Step1 label is not binary: {value!r}")


def _anchor_result(derived: Mapping[str, Any]) -> AnchorResult:
    state = AnchorState(str(derived["anchor_business_state"]))
    if state != AnchorState.SUCCESS:
        return AnchorResult(state=state)
    normalized_plan = derived["normalized_junctionization_plan"]
    if not (
        normalized_plan.get("applicable")
        and normalized_plan.get("supervised")
        and normalized_plan.get("state") == "NORMALIZED_EXACT"
    ):
        raise JunctionPredictionError("T021 SUCCESS row lacks normalized exact topology")
    topology = normalized_plan.get("canonical_topology")
    if not isinstance(topology, Mapping):
        raise JunctionPredictionError("T021 SUCCESS row lacks canonical topology")
    source_refs = tuple(
        sorted(_parse_object_ref(value) for value in topology["source_rcsd_objects"])
    )
    equivalence = tuple(
        _parse_anchor_node_ref(value)
        for value in topology.get("junction_node_equivalence_class", ())
    )
    main_anchor = _parse_anchor_node_ref(str(topology["main_anchor"]))
    node_refs = tuple(
        sorted(
            {
                *(ref for ref in source_refs if ref.role == EvidenceRole.RCSD_NODE),
                *(
                    ref.node_ref
                    for ref in equivalence + (main_anchor,)
                    if ref.kind == AnchorNodeKind.SOURCE_RCSD_NODE
                    and ref.node_ref is not None
                ),
            }
        )
    )
    road_refs = tuple(ref for ref in source_refs if ref.role == EvidenceRole.RCSD_ROAD)

    targets_by_road: dict[ObjectRef, list[tuple[int, float]]] = {}
    for target in normalized_plan.get("break_geometry_targets", ()):
        road_ref = _parse_object_ref(str(target["road_object_id"]))
        targets_by_road.setdefault(road_ref, []).append(
            (int(target["break_rank"]), float(target["fraction"]))
        )
    operations: list[RoadBreakOperation] = []
    for road_ref in sorted(targets_by_road):
        ranked = tuple(sorted(targets_by_road[road_ref]))
        if tuple(rank for rank, _ in ranked) != tuple(range(len(ranked))):
            raise JunctionPredictionError("T021 Road-break ranks are not contiguous")
        fractions = tuple(fraction for _, fraction in ranked)
        if fractions != tuple(sorted(fractions)):
            raise JunctionPredictionError("T021 Road-break ranks disagree with fractions")
        operations.append(RoadBreakOperation(road_ref, fractions))
    result = AnchorResult(
        state=state,
        associated_rcsd_node_refs=node_refs,
        associated_rcsd_road_refs=road_refs,
        selected_main_anchor=main_anchor,
        node_equivalence_classes=(NodeEquivalenceClass(equivalence),)
        if equivalence
        else (),
        road_break_operations=tuple(operations),
    )
    result.validate()
    return result


def _surface_plan(
    *,
    label: Mapping[str, Any],
    surface_row: Mapping[str, Any] | None,
    allow_unsupervised_members: bool,
) -> tuple[SurfacePlan, bool]:
    mode = SurfaceMode(str(label["task_labels"]["surface_mode"]))
    if mode == SurfaceMode.EXISTING_RCSD_INTERSECTION:
        target_sets = tuple(label.get("surface_object_target_object_sets", ()))
        if not bool(label.get("surface_object_supervised")) or len(target_sets) != 1:
            return SurfacePlan(mode=SurfaceMode.ABSTAIN), False
        refs = tuple(sorted(_parse_object_ref(value) for value in target_sets[0]))
        return SurfacePlan(mode=mode, selected_rcsdintersection_refs=refs), bool(refs)
    if mode == SurfaceMode.VIRTUAL_SURFACE:
        if (
            surface_row is None or not bool(surface_row.get("supervised"))
        ) and not allow_unsupervised_members:
            return SurfacePlan(mode=SurfaceMode.ABSTAIN), False
        members = tuple(
            sorted(
                _parse_object_ref(value)
                for value in (
                    surface_row.get("required_visible_object_ids", ())
                    if surface_row is not None and bool(surface_row.get("supervised"))
                    else ()
                )
            )
        )
        return (
            SurfacePlan(
                mode=mode,
                virtual_member_refs=members,
                virtual_surface_recipe=VirtualSurfaceRecipe(
                    "ASSOCIATED_OBJECT_BUFFER_HULL",
                    (("buffer_m", 5.0),),
                ),
            ),
            True,
        )
    return SurfacePlan(mode=mode), True


def _alternate_plan(gold: CandidatePlan) -> CandidatePlan:
    alternate_state = (
        AnchorState.QUALITY_ISSUE
        if gold.anchor_result.state != AnchorState.QUALITY_ISSUE
        else AnchorState.AMBIGUOUS
    )
    return CandidatePlan(
        plan_id="decoy:alternate-state",
        step1_drivezone_state=gold.step1_drivezone_state,
        surface_plan=gold.surface_plan,
        anchor_result=AnchorResult(state=alternate_state),
        quality_state=_quality_state(alternate_state),
        review_reason="T021_TEACHER_ORACLE_DECOY",
        planned_topology_signature="",
    )


def _candidate_binding(
    *,
    example: JunctionEvidenceExample,
    gold: CandidatePlan | None,
) -> CandidateBinding:
    plans = (
        (gold, _safe_abstain_plan(), _alternate_plan(gold))
        if gold is not None
        else (_safe_abstain_plan(),)
    )
    binding = CandidateBinding(
        junction_key=example.junction_key,
        allowed_object_refs=tuple(span.object_ref for span in example.object_spans),
        plans=plans,
    )
    binding.validate()
    return binding


def _surface_constraints(
    *,
    example: JunctionEvidenceExample,
    label: Mapping[str, Any],
    surface_row: Mapping[str, Any] | None,
) -> tuple[
    tuple[SurfaceConstraint, ...],
    tuple[SurfaceConstraint, ...],
    tuple[int, ...],
]:
    visible = tuple(span.object_ref for span in example.object_spans)
    intersections = tuple(
        ref for ref in visible if ref.role == EvidenceRole.RCSD_INTERSECTION
    )
    existing: tuple[SurfaceConstraint, ...] = ()
    if bool(label.get("surface_object_supervised")):
        target_sets = tuple(label.get("surface_object_target_object_sets", ()))
        if len(target_sets) != 1:
            raise JunctionPredictionError(
                "T021 existing-surface alternatives require a typed acceptable set"
            )
        selected = {_parse_object_ref(value) for value in target_sets[0]}
        if not selected.issubset(intersections):
            raise JunctionPredictionError("existing-surface target is not visible")
        existing = tuple(
            SurfaceConstraint(
                ref,
                ConstraintState.REQUIRED if ref in selected else ConstraintState.FORBIDDEN,
                1.0,
            )
            for ref in intersections
        )

    virtual: tuple[SurfaceConstraint, ...] = ()
    acceptable_cardinalities: tuple[int, ...] = ()
    if surface_row is not None and bool(surface_row.get("supervised")):
        virtual_refs = tuple(
            ref
            for ref in visible
            if ref.role in {EvidenceRole.RCSD_NODE, EvidenceRole.RCSD_ROAD}
        )
        required = {
            _parse_object_ref(value)
            for value in surface_row.get("required_visible_object_ids", ())
        }
        forbidden = {
            _parse_object_ref(value)
            for value in surface_row.get("forbidden_visible_object_ids", ())
        }
        if required.intersection(forbidden):
            raise JunctionPredictionError("T021 surface REQUIRED/FORBIDDEN overlap")
        if not required.union(forbidden).issubset(virtual_refs):
            raise JunctionPredictionError("T021 surface constraint is not visible")
        virtual = tuple(
            SurfaceConstraint(
                ref,
                ConstraintState.REQUIRED
                if ref in required
                else ConstraintState.FORBIDDEN
                if ref in forbidden
                else ConstraintState.UNKNOWN,
                1.0 if ref in required or ref in forbidden else 0.0,
            )
            for ref in virtual_refs
        )
        acceptable_cardinalities = tuple(
            range(len(required), len(virtual_refs) - len(forbidden) + 1)
        )
    return existing, virtual, acceptable_cardinalities


def _anchor_constraints(
    *,
    example: JunctionEvidenceExample,
    anchor: AnchorResult | None,
) -> tuple[
    tuple[SurfaceConstraint, ...],
    tuple[int, ...],
    tuple[AnchorNodeRef, ...],
    tuple[PairConstraint, ...],
    tuple[RoadBreakTarget, ...],
    tuple[RoadBreakSetTarget, ...],
]:
    if anchor is None or anchor.state != AnchorState.SUCCESS:
        return (), (), (), (), (), ()
    visible = tuple(
        span.object_ref
        for span in example.object_spans
        if span.object_ref.role in {EvidenceRole.RCSD_NODE, EvidenceRole.RCSD_ROAD}
    )
    selected = set(anchor.associated_rcsd_node_refs) | set(
        anchor.associated_rcsd_road_refs
    )
    if not selected.issubset(visible):
        raise JunctionPredictionError("T021 anchor target is not visible")
    constraints = tuple(
        SurfaceConstraint(
            ref,
            ConstraintState.REQUIRED if ref in selected else ConstraintState.FORBIDDEN,
            1.0,
        )
        for ref in visible
    )
    main_refs = (
        (anchor.selected_main_anchor,)
        if anchor.selected_main_anchor is not None
        and anchor.selected_main_anchor.kind == AnchorNodeKind.SOURCE_RCSD_NODE
        else ()
    )
    equivalence_sets = tuple(
        frozenset(
            ref.node_ref
            for ref in group.node_refs
            if ref.kind == AnchorNodeKind.SOURCE_RCSD_NODE and ref.node_ref is not None
        )
        for group in anchor.node_equivalence_classes
    )
    pair_constraints = tuple(
        PairConstraint(
            left,
            right,
            ConstraintState.REQUIRED
            if any({left, right}.issubset(group) for group in equivalence_sets)
            else ConstraintState.FORBIDDEN,
            1.0,
        )
        for left, right in combinations(anchor.associated_rcsd_node_refs, 2)
    )
    breaks = {operation.road_ref: operation for operation in anchor.road_break_operations}
    break_targets: list[RoadBreakTarget] = []
    break_set_targets: list[RoadBreakSetTarget] = []
    for road_ref in anchor.associated_rcsd_road_refs:
        operation = breaks.get(road_ref)
        fractions = operation.fractions if operation is not None else ()
        break_set_targets.append(RoadBreakSetTarget(road_ref, fractions, 1.0))
        if operation is None:
            break_targets.append(RoadBreakTarget(road_ref, False, None, 1.0))
        elif len(fractions) == 1:
            break_targets.append(RoadBreakTarget(road_ref, True, fractions[0], 1.0))
    return (
        constraints,
        (len(selected),),
        main_refs,
        pair_constraints,
        tuple(break_targets),
        tuple(break_set_targets),
    )


def _source_weight(source: str, label: Mapping[str, Any]) -> tuple[float, float, bool]:
    if source not in EXPECTED_SOURCE_WEIGHTS:
        raise JunctionPredictionError(f"unknown T021 source: {source}")
    expected = EXPECTED_SOURCE_WEIGHTS[source]
    old = float(label.get("sample_weight", math.nan))
    if not math.isfinite(old):
        raise JunctionPredictionError("T021 source label weight is not finite")
    if source == "T10_WEAK" and old != expected:
        raise JunctionPredictionError("T10 weak label weight changed from 0.7")
    if source == "STRONG_GOLD" and old not in {0.5, 1.0}:
        raise JunctionPredictionError("strong Gold legacy weight is outside {0.5, 1.0}")
    return expected, old, old != expected


def build_t021_record(
    *,
    feature: Mapping[str, Any],
    label: Mapping[str, Any],
    lineage: Mapping[str, Any],
    derived: Mapping[str, Any],
    surface_row: Mapping[str, Any] | None,
    source: str,
) -> T021JoinedRecord:
    sample_id = str(feature.get("sample_id") or "")
    if not sample_id or any(
        str(row.get("sample_id") or "") != sample_id
        for row in (label, lineage, derived)
    ):
        raise JunctionPredictionError("T021 joined source identities differ")
    split = str(label.get("split") or "").lower()
    if split not in {"train", "validation"}:
        raise JunctionPredictionError("T021 development row is not train/validation")
    if str(derived.get("split") or "").lower() != split:
        raise JunctionPredictionError("T021 derived/label split differs")
    if str(derived.get("source") or "") != source:
        raise JunctionPredictionError("T021 derived/source class differs")
    fingerprint = str(feature.get("input_fingerprint") or "")
    if not fingerprint or fingerprint != str(lineage.get("input_fingerprint") or ""):
        raise JunctionPredictionError("T021 feature/lineage fingerprint differs")

    if source == "STRONG_GOLD":
        base_case_key = ":".join(
            (
                str(lineage["source_scope"]),
                str(lineage["family"]),
                str(lineage["case_id"]),
            )
        )
        case_key = f"{base_case_key}@{fingerprint[:16]}"
        case_group_key = base_case_key
    else:
        base_case_key = str(lineage["case_key"])
        case_key = base_case_key
        case_group_key = base_case_key

    example = _build_geometry_example(
        sample_id=sample_id,
        feature=feature,
        case_key=case_key,
    )
    task_masks = {
        str(key): bool(value) for key, value in label.get("task_masks", {}).items()
    }
    step1 = _step1_state(label)
    surface_mode = SurfaceMode(str(label["task_labels"]["surface_mode"]))
    anchor: AnchorResult | None = None
    anchor_state: AnchorState | None = None
    if task_masks.get("final_state", False):
        anchor_state = AnchorState(str(label["task_labels"]["final_state"]))
        if anchor_state == AnchorState.SUCCESS:
            normalized = derived.get("normalized_junctionization_plan", {})
            if bool(normalized.get("supervised")):
                anchor = _anchor_result(derived)
        else:
            anchor = AnchorResult(state=anchor_state)

    surface_plan, surface_plan_exact = _surface_plan(
        label=label,
        surface_row=surface_row,
        allow_unsupervised_members=(
            anchor_state is not None and anchor_state != AnchorState.SUCCESS
        ),
    )
    oracle = derived["current_phase_result_oracle"]
    surface_complete_expressible = (
        bool(surface_row.get("complete_result_oracle_expressible"))
        if surface_row is not None and bool(surface_row.get("applicable"))
        else True
    )
    complete_plan_supervised = bool(
        oracle.get("measurable") and surface_complete_expressible
    )
    if complete_plan_supervised and (
        not task_masks.get("t07_step1", False)
        or not task_masks.get("surface_mode", False)
        or anchor is None
        or not surface_plan_exact
    ):
        raise JunctionPredictionError(
            "T021 measurable complete result lacks a required component"
        )

    gold: CandidatePlan | None = None
    if complete_plan_supervised and anchor is not None:
        topology_signature = (
            business_topology_signature(anchor)
            if anchor.state == AnchorState.SUCCESS
            else ""
        )
        gold = CandidatePlan(
            plan_id="gold",
            step1_drivezone_state=step1,
            surface_plan=surface_plan,
            anchor_result=anchor,
            quality_state=_quality_state(anchor.state),
            review_reason=_review_reason(label, anchor.state),
            planned_topology_signature=topology_signature,
        )
        gold.validate()
    teacher_binding = _candidate_binding(example=example, gold=gold)

    existing_constraints, virtual_constraints, virtual_cardinalities = (
        _surface_constraints(
            example=example,
            label=label,
            surface_row=surface_row,
        )
    )
    (
        anchor_constraints,
        anchor_cardinalities,
        main_refs,
        pair_constraints,
        road_break_targets,
        road_break_set_targets,
    ) = _anchor_constraints(example=example, anchor=anchor)
    weight, old_weight, normalized_weight = _source_weight(source, label)
    overlay = JunctionTrainingOverlay(
        junction_key=example.junction_key,
        source_weight=weight,
        step1_acceptable_indices=(tuple(Step1DriveZoneState).index(step1),)
        if task_masks.get("t07_step1", False)
        else (),
        surface_mode_acceptable_indices=(tuple(SurfaceMode).index(surface_mode),)
        if task_masks.get("surface_mode", False)
        else (),
        anchor_state_acceptable_indices=(tuple(AnchorState).index(anchor_state),)
        if anchor_state is not None
        else (),
        quality_acceptable_indices=(tuple(QualityState).index(_quality_state(anchor_state)),)
        if anchor_state is not None
        else (),
        acceptable_complete_plan_ids=("gold",) if gold is not None else (),
        existing_surface_constraints=existing_constraints,
        virtual_surface_constraints=virtual_constraints,
        virtual_surface_acceptable_cardinalities=virtual_cardinalities,
        anchor_member_constraints=anchor_constraints,
        anchor_member_acceptable_cardinalities=anchor_cardinalities,
        acceptable_main_anchor_refs=main_refs,
        pair_constraints=pair_constraints,
        road_break_targets=road_break_targets,
        road_break_set_targets=road_break_set_targets,
    )
    return T021JoinedRecord(
        feature=T021FeatureRecord(
            sample_id=sample_id,
            input_fingerprint=fingerprint,
            example=example,
        ),
        label=T021LabelRecord(
            sample_id=sample_id,
            source=source,
            split=split,
            case_group_key=case_group_key,
            overlay=overlay,
            teacher_step1_index=tuple(Step1DriveZoneState).index(step1),
            teacher_surface_index=tuple(SurfaceMode).index(surface_mode),
            teacher_candidate_binding=teacher_binding,
            task_masks=tuple(sorted(task_masks.items())),
            complete_plan_supervised=complete_plan_supervised,
            old_source_weight=old_weight,
            source_weight_normalized=normalized_weight,
            legacy_candidate_acceptable_count=len(
                label.get("candidate_acceptable_indices", ())
            ),
        ),
    )


class _ShardWriter:
    def __init__(self, output_dir: Path, config: T021CacheConfig) -> None:
        self.output_dir = Path(output_dir)
        self.config = config
        self.features: list[T021FeatureRecord] = []
        self.labels: list[T021LabelRecord] = []
        self.token_count = 0
        self.shard_index = 0
        self.shards: list[Mapping[str, Any]] = []
        self.partition: tuple[str, str] | None = None

    def add(self, record: T021JoinedRecord) -> None:
        local_tokens = int(record.feature.example.geometry_tokens.shape[0])
        partition = (record.label.source, record.label.split)
        if self.features and (
            partition != self.partition
            or len(self.features) >= self.config.max_samples_per_shard
            or self.token_count + local_tokens
            > self.config.max_geometry_tokens_per_shard
        ):
            self.flush()
        self.partition = partition
        self.features.append(record.feature)
        self.labels.append(record.label)
        self.token_count += local_tokens

    def flush(self) -> None:
        if not self.features:
            return
        stem = f"shard-{self.shard_index:04d}"
        feature_path = self.output_dir / f"{stem}.features.pt"
        label_path = self.output_dir / f"{stem}.labels.pt"
        torch.save(tuple(self.features), feature_path)
        torch.save(tuple(self.labels), label_path)
        self.shards.append(
            {
                "shard_id": stem,
                "source": self.partition[0],
                "split": self.partition[1],
                "sample_count": len(self.features),
                "geometry_token_count": self.token_count,
                "feature_path": feature_path.name,
                "feature_size_bytes": feature_path.stat().st_size,
                "feature_sha256": _sha256_file(feature_path),
                "label_path": label_path.name,
                "label_size_bytes": label_path.stat().st_size,
                "label_sha256": _sha256_file(label_path),
            }
        )
        self.features.clear()
        self.labels.clear()
        self.token_count = 0
        self.partition = None
        self.shard_index += 1


def _contract_audit(paths: T021DataPaths) -> Mapping[str, Any]:
    derived_manifest = _read_json(paths.derived_manifest)
    derived_summary = _read_json(paths.derived_summary)
    surface_manifest = _read_json(paths.surface_manifest)
    surface_summary = _read_json(paths.surface_summary)
    strong_manifest = _read_json(paths.strong_manifest)
    split_summary = _read_json(paths.strong_split_summary)
    t10_manifest = _read_json(paths.t10_manifest)
    if any(
        bool(value)
        for value in (
            derived_manifest.get("training_executed"),
            derived_manifest.get("frozen_test_labels_aggregated"),
            surface_manifest.get("training_executed"),
            surface_manifest.get("frozen_test_labels_read_for_derivation"),
            t10_manifest.get("frozen_test_evaluated"),
            t10_manifest.get("test_shard_included"),
        )
    ):
        raise JunctionPredictionError("T021 source isolation contract changed")
    if int(derived_summary.get("development_row_count", -1)) != EXPECTED_DEVELOPMENT_COUNT:
        raise JunctionPredictionError("T021 derived development count changed")
    if int(surface_summary.get("development_row_count", -1)) != EXPECTED_DEVELOPMENT_COUNT:
        raise JunctionPredictionError("T021 surface development count changed")
    if int(strong_manifest.get("example_count", -1)) != 708:
        raise JunctionPredictionError("T021 strong store count changed")
    if int(t10_manifest.get("example_count", -1)) != EXPECTED_SOURCE_COUNTS["T10_WEAK"]:
        raise JunctionPredictionError("T021 T10 store count changed")
    split_hash = _sha256_file(paths.strong_split_file)
    if split_hash != FROZEN_BLIND_TEST_SEAL.split_file_sha256:
        raise JunctionPredictionError("T021 frozen strong split hash changed")
    if split_summary.get("split_sample_counts") != {
        "test": 106,
        "train": 497,
        "validation": 105,
    }:
        raise JunctionPredictionError("T021 strong split counts changed")
    return {
        "source_manifest_sha256": {
            "derived": _sha256_file(paths.derived_manifest),
            "surface": _sha256_file(paths.surface_manifest),
            "strong": _sha256_file(paths.strong_manifest),
            "strong_split": split_hash,
            "t10": _sha256_file(paths.t10_manifest),
        },
        "declared_source_artifact_sha256": {
            "strong_features": strong_manifest["artifacts"]["inference_features"]["sha256"],
            "strong_labels": strong_manifest["artifacts"]["training_labels"]["sha256"],
            "strong_lineage": strong_manifest["artifacts"]["lineage"]["sha256"],
            "t10_features": [
                row["inference_features"]["sha256"]
                for row in t10_manifest["artifacts"]["case_shards"]
            ],
            "t10_labels": [
                row["training_labels"]["sha256"]
                for row in t10_manifest["artifacts"]["case_shards"]
            ],
            "t10_lineage": [
                row["lineage"]["sha256"]
                for row in t10_manifest["artifacts"]["case_shards"]
            ],
        },
        "crs_and_geometry_contract": {
            "source_store_geometry_changed": bool(strong_manifest["geometry_changed"])
            or bool(t10_manifest["geometry_changed"]),
            "source_store_silent_fix": bool(strong_manifest["silent_fix"])
            or bool(t10_manifest["silent_fix"]),
            "raw_gis_reopened": False,
        },
        "t10_case_shards": t10_manifest["artifacts"]["case_shards"],
    }


def _record_stats(
    record: T021JoinedRecord,
    *,
    counters: Counter[str],
    sample_ids: set[str],
    junction_keys: set[str],
    train_cases: set[str],
    validation_cases: set[str],
) -> None:
    sample_id = record.feature.sample_id
    if sample_id in sample_ids:
        raise JunctionPredictionError(f"duplicate T021 sample_id: {sample_id}")
    sample_ids.add(sample_id)
    junction_key = record.feature.example.junction_key
    if junction_key in junction_keys:
        raise JunctionPredictionError(f"duplicate T021 forward identity: {junction_key}")
    junction_keys.add(junction_key)
    label = record.label
    cases = train_cases if label.split == "train" else validation_cases
    cases.add(label.case_group_key)
    counters["sample_count"] += 1
    counters[f"source:{label.source}"] += 1
    counters[f"split:{label.split}"] += 1
    counters[f"weight:{label.overlay.source_weight}"] += 1
    counters["geometry_token_count"] += int(
        record.feature.example.geometry_tokens.shape[0]
    )
    counters["topology_edge_count"] += int(
        record.feature.example.topology_edge_features.shape[0]
    )
    counters["complete_plan_supervised"] += int(label.complete_plan_supervised)
    counters["source_weight_normalized"] += int(label.source_weight_normalized)
    counters["legacy_multi_candidate_label"] += int(
        label.legacy_candidate_acceptable_count > 1
    )
    counters["existing_surface_supervised"] += int(
        bool(label.overlay.existing_surface_constraints)
    )
    counters["virtual_surface_supervised"] += int(
        bool(label.overlay.virtual_surface_acceptable_cardinalities)
    )
    counters["anchor_object_set_supervised"] += int(
        bool(label.overlay.anchor_member_acceptable_cardinalities)
    )
    for task, enabled in label.task_masks:
        counters[f"task_mask:{task}:{enabled}"] += 1


def _t10_shard_paths(root: Path, shard: Mapping[str, Any]) -> tuple[Path, Path, Path]:
    case_id = str(shard["case_key"]).split(":", 1)[1]
    return (
        root / "inference_feature_store" / f"{case_id}.jsonl.gz",
        root / "training_label_store" / f"{case_id}.jsonl.gz",
        root / "lineage_store" / f"{case_id}.jsonl.gz",
    )


def build_t021_cache(config: T021CacheConfig) -> Mapping[str, Any]:
    """Build the full non-blind P1 cache without constructing an optimizer."""

    config.validate()
    output_dir = Path(config.output_dir)
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    contract = _contract_audit(config.data_paths)
    source_read_counts: Counter[str] = Counter(
        {
            str(config.data_paths.derived_labels): 1,
            str(config.data_paths.surface_constraints): 1,
        }
    )
    derived_by_id = _read_jsonl_index(config.data_paths.derived_labels)
    surface_by_id = _read_jsonl_index(config.data_paths.surface_constraints)
    if len(derived_by_id) != EXPECTED_DEVELOPMENT_COUNT:
        raise JunctionPredictionError("T021 derived overlay row count changed")

    writer = _ShardWriter(output_dir, config)
    counters: Counter[str] = Counter()
    sample_ids: set[str] = set()
    junction_keys: set[str] = set()
    train_cases: set[str] = set()
    validation_cases: set[str] = set()

    strong_paths = (
        config.data_paths.strong_feature_store,
        config.data_paths.strong_label_store,
        config.data_paths.strong_lineage_store,
    )
    for path in strong_paths:
        source_read_counts[str(path)] += 1
    for feature, label, lineage in iter_aligned_jsonl(
        strong_paths,
        raw_prefix_skip=FROZEN_BLIND_TEST_SEAL.sealed_test_count,
    ):
        sample_id = str(feature["sample_id"])
        derived = derived_by_id.get(sample_id)
        if derived is None:
            raise JunctionPredictionError("strong development row lacks derived overlay")
        record = build_t021_record(
            feature=feature,
            label=label,
            lineage=lineage,
            derived=derived,
            surface_row=surface_by_id.get(sample_id),
            source="STRONG_GOLD",
        )
        _record_stats(
            record,
            counters=counters,
            sample_ids=sample_ids,
            junction_keys=junction_keys,
            train_cases=train_cases,
            validation_cases=validation_cases,
        )
        writer.add(record)

    for shard in contract["t10_case_shards"]:
        shard_paths = _t10_shard_paths(config.data_paths.t10_store_root, shard)
        for path in shard_paths:
            source_read_counts[str(path)] += 1
        for feature, label, lineage in iter_aligned_jsonl(shard_paths):
            sample_id = str(feature["sample_id"])
            derived = derived_by_id.get(sample_id)
            if derived is None:
                raise JunctionPredictionError("T10 development row lacks derived overlay")
            record = build_t021_record(
                feature=feature,
                label=label,
                lineage=lineage,
                derived=derived,
                surface_row=surface_by_id.get(sample_id),
                source="T10_WEAK",
            )
            _record_stats(
                record,
                counters=counters,
                sample_ids=sample_ids,
                junction_keys=junction_keys,
                train_cases=train_cases,
                validation_cases=validation_cases,
            )
            writer.add(record)
    writer.flush()

    if counters["sample_count"] != EXPECTED_DEVELOPMENT_COUNT:
        raise JunctionPredictionError("T021 development sample count changed")
    if {
        source: counters[f"source:{source}"] for source in EXPECTED_SOURCE_COUNTS
    } != EXPECTED_SOURCE_COUNTS:
        raise JunctionPredictionError("T021 source counts changed")
    if {
        split: counters[f"split:{split}"] for split in EXPECTED_SPLIT_COUNTS
    } != EXPECTED_SPLIT_COUNTS:
        raise JunctionPredictionError("T021 split counts changed")
    case_overlap = sorted(train_cases.intersection(validation_cases))
    if case_overlap:
        raise JunctionPredictionError(
            f"T021 Case-disjoint split failed for {len(case_overlap)} cases"
        )
    if set(derived_by_id) != sample_ids:
        raise JunctionPredictionError("T021 derived overlay identities differ from cache")
    if any(count != 1 for count in source_read_counts.values()):
        raise JunctionPredictionError("T021 source store was read more than once")

    manifest = {
        "schema_version": "p05-junction-graphset-v1-t021-cache-v1",
        "status": "T021_NON_BLIND_CACHE_READY",
        "training_executed": False,
        "optimizer_created": False,
        "blind_test_access_count": 0,
        "blind_test_labels_read": False,
        "sealed_strong_prefix_skipped_without_json_decode": (
            FROZEN_BLIND_TEST_SEAL.sealed_test_count
        ),
        "candidate_catalog_mode": "T021_TEACHER_ORACLE_ONLY",
        "candidate_catalog_inference_eligible": False,
        "feature_label_physical_separation": True,
        "raw_gis_reopened": False,
        "source_store_read_policy": "ONE_SEQUENTIAL_READ_PER_SOURCE_SHARD",
        "source_file_read_counts": dict(sorted(source_read_counts.items())),
        "sample_count": counters["sample_count"],
        "source_counts": {
            source: counters[f"source:{source}"]
            for source in EXPECTED_SOURCE_COUNTS
        },
        "split_counts": {
            split: counters[f"split:{split}"] for split in EXPECTED_SPLIT_COUNTS
        },
        "source_weight_counts": {
            weight: counters[f"weight:{weight}"] for weight in (1.0, 0.7)
        },
        "strong_legacy_half_weight_normalized_count": counters[
            "source_weight_normalized"
        ],
        "task_mask_counts": {
            key.removeprefix("task_mask:"): value
            for key, value in sorted(counters.items())
            if key.startswith("task_mask:")
        },
        "complete_plan_supervised_count": counters["complete_plan_supervised"],
        "existing_surface_supervised_count": counters[
            "existing_surface_supervised"
        ],
        "virtual_surface_supervised_count": counters[
            "virtual_surface_supervised"
        ],
        "anchor_object_set_supervised_count": counters[
            "anchor_object_set_supervised"
        ],
        "legacy_multi_candidate_label_count": counters[
            "legacy_multi_candidate_label"
        ],
        "geometry_token_count": counters["geometry_token_count"],
        "topology_edge_count": counters["topology_edge_count"],
        "train_case_group_count": len(train_cases),
        "validation_case_group_count": len(validation_cases),
        "case_group_overlap_count": 0,
        "sample_identity_sha256": hashlib.sha256(
            b"".join(f"{sample_id}\n".encode("utf-8") for sample_id in sorted(sample_ids))
        ).hexdigest(),
        "source_contract": {
            key: value for key, value in contract.items() if key != "t10_case_shards"
        },
        "shards": writer.shards,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_bytes(_canonical_json_bytes(manifest) + b"\n")
    return manifest


def load_t021_shard(
    cache_root: Path,
    shard: Mapping[str, Any],
) -> tuple[T021JoinedRecord, ...]:
    feature_path = Path(cache_root) / str(shard["feature_path"])
    label_path = Path(cache_root) / str(shard["label_path"])
    features = torch.load(feature_path, map_location="cpu", weights_only=False)
    labels = torch.load(label_path, map_location="cpu", weights_only=False)
    if not isinstance(features, tuple) or not isinstance(labels, tuple):
        raise JunctionPredictionError("T021 cache shard payload must be a tuple")
    if len(features) != len(labels) or len(features) != int(shard["sample_count"]):
        raise JunctionPredictionError("T021 cache feature/label shard lengths differ")
    records: list[T021JoinedRecord] = []
    for feature, label in zip(features, labels):
        if not isinstance(feature, T021FeatureRecord) or not isinstance(
            label, T021LabelRecord
        ):
            raise JunctionPredictionError("T021 cache shard record type changed")
        if feature.sample_id != label.sample_id:
            raise JunctionPredictionError("T021 cache feature/label identities differ")
        records.append(T021JoinedRecord(feature=feature, label=label))
    return tuple(records)


def iter_t021_cache(cache_root: Path) -> Iterator[T021JoinedRecord]:
    manifest = _read_json(Path(cache_root) / "manifest.json")
    if manifest.get("status") != "T021_NON_BLIND_CACHE_READY":
        raise JunctionPredictionError("T021 cache manifest is not ready")
    for shard in manifest["shards"]:
        yield from load_t021_shard(cache_root, shard)


__all__ = [
    "EXPECTED_DEVELOPMENT_COUNT",
    "EXPECTED_SOURCE_COUNTS",
    "EXPECTED_SPLIT_COUNTS",
    "T021CacheConfig",
    "T021DataPaths",
    "T021FeatureRecord",
    "T021JoinedRecord",
    "T021LabelRecord",
    "build_t021_cache",
    "build_t021_record",
    "iter_aligned_jsonl",
    "iter_t021_cache",
    "load_t021_shard",
]
