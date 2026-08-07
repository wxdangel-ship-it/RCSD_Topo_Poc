from __future__ import annotations

import hashlib
import json
import math
import mmap
import random
import time
from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_firewall import (
    EvidenceStage,
    StageEvidenceView,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_materializer import (
    business_topology_signature,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_model import (
    JunctionGraphSetModel,
    JunctionGraphSetRawOutput,
    JunctionTrainingOverlay,
    PairConstraint,
    RoadBreakTarget,
    compute_multitask_loss,
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


T017_SAMPLE_IDS = (
    "junction-gold:POC_Data:T03:705014:047b73f223d573b8",
    "junction-gold:POC_Data:T03:54265667:cf76fefb1ae0250e",
    "junction-gold:POC_Data:T03:705817:923de89807918ed4",
    "junction-gold:POC_Data:T03:948228:316c6f6342336cac",
    "junction-gold:POC_Data:T03_Error:620571692:f5d47f132aa118d2",
    "junction-gold:POC_Data:T03:765154:9ca35aa4a09d480d",
    "junction-gold:POC_Data:T03:74419702:fdbf2c05caa9c28d",
    "junction-gold:POC_Data:T03:500860756:4c90bb8cdd9612c4",
)

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
class T017DataPaths:
    derived_labels: Path
    derived_manifest: Path
    feature_store: Path
    feature_manifest: Path
    strong_labels: Path
    strong_manifest: Path
    surface_constraints: Path
    surface_manifest: Path

    @classmethod
    def from_output_root(cls, output_root: Path) -> T017DataPaths:
        root = Path(output_root)
        derived = root / "target_a_junction_result_derived_label_overlay_20260806_v1r3"
        features = root / "target_a_junction_joint_store_20260805_v10_geometry_graph"
        strong = root / "target_a_junction_gold_final_labels_20260805_v2_scheme_a"
        surface = root / "target_a_virtual_surface_constraint_overlay_20260806_v1r2"
        return cls(
            derived_labels=derived / "junction_result_derived_labels.jsonl",
            derived_manifest=derived / "manifest.json",
            feature_store=features / "inference_feature_store" / "junction_features.jsonl",
            feature_manifest=features / "manifest.json",
            strong_labels=strong / "junction_gold_final_labels.jsonl",
            strong_manifest=strong / "summary.json",
            surface_constraints=surface / "virtual_surface_constraint_labels.jsonl",
            surface_manifest=surface / "manifest.json",
        )


@dataclass(frozen=True)
class T017OverfitConfig:
    data_paths: T017DataPaths
    output_dir: Path
    sample_ids: tuple[str, ...] = T017_SAMPLE_IDS
    seed: int = 20260808
    hidden_dim: int = 384
    learning_rate: float = 0.002
    max_steps: int = 1500
    evaluation_interval: int = 25
    required_consecutive_passes: int = 3
    maximum_total_loss: float = 0.02
    road_break_fraction_tolerance: float = 0.01
    device: str = "auto"

    def validate(self) -> None:
        if not self.sample_ids or len(set(self.sample_ids)) != len(self.sample_ids):
            raise ValueError("T017 sample IDs must be non-empty and unique")
        if self.hidden_dim < 1 or self.max_steps < 1 or self.evaluation_interval < 1:
            raise ValueError("T017 model/training dimensions are invalid")
        if self.required_consecutive_passes < 1:
            raise ValueError("T017 consecutive pass count must be positive")
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0.0:
            raise ValueError("T017 learning rate must be positive")
        if not math.isfinite(self.maximum_total_loss) or self.maximum_total_loss <= 0.0:
            raise ValueError("T017 loss threshold must be positive")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("T017 device must be auto, cpu, or cuda")


@dataclass(frozen=True)
class T017PreparedBatch:
    examples: tuple[JunctionEvidenceExample, ...]
    overlays: tuple[JunctionTrainingOverlay, ...]
    teacher_step1_indices: torch.Tensor
    teacher_surface_indices: torch.Tensor
    sample_audit: tuple[Mapping[str, Any], ...]
    selected_row_sha256: Mapping[str, str]


@dataclass(frozen=True)
class T017CachedViews:
    step1: tuple[StageEvidenceView, ...]
    surface: tuple[StageEvidenceView, ...]
    anchor: tuple[StageEvidenceView, ...]


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


def extract_exact_jsonl_rows(
    path: Path,
    sample_ids: Sequence[str],
    *,
    optional: bool = False,
) -> dict[str, Mapping[str, Any]]:
    """Decode only exact requested rows; unrelated and blind rows are never parsed."""

    normalized = tuple(sample_ids)
    rows: dict[str, Mapping[str, Any]] = {}
    with Path(path).open("rb") as stream:
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            for sample_id in normalized:
                needle = json.dumps(
                    sample_id,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                position = mapped.find(needle)
                if position < 0:
                    if optional:
                        continue
                    raise JunctionPredictionError(
                        f"T017 row is absent from {Path(path).name}: {sample_id}"
                    )
                line_start = mapped.rfind(b"\n", 0, position) + 1
                line_end = mapped.find(b"\n", position)
                if line_end < 0:
                    line_end = len(mapped)
                row = json.loads(mapped[line_start:line_end])
                if row.get("sample_id") != sample_id:
                    raise JunctionPredictionError(
                        f"T017 exact-row identity mismatch: {sample_id}"
                    )
                if mapped.find(needle, line_end) >= 0:
                    raise JunctionPredictionError(
                        f"T017 sample ID is duplicated in {Path(path).name}: {sample_id}"
                    )
                rows[sample_id] = row
    return rows


def _parse_feature_ref(span: Mapping[str, Any]) -> ObjectRef:
    role_index = int(span["role_index"])
    if role_index not in FEATURE_ROLE_BY_INDEX:
        raise JunctionPredictionError(f"unknown T017 feature role index: {role_index}")
    encoded_id = str(span["object_id"])
    prefix, separator, object_id = encoded_id.partition(":")
    if not separator or prefix != EXPECTED_FEATURE_PREFIX[role_index] or not object_id:
        raise JunctionPredictionError(f"invalid T017 feature object ID: {encoded_id}")
    return ObjectRef(FEATURE_ROLE_BY_INDEX[role_index], object_id)


def _parse_rcsd_object_ref(encoded_id: str) -> ObjectRef:
    prefix, separator, object_id = str(encoded_id).partition(":")
    if not separator or not object_id:
        raise JunctionPredictionError(f"invalid RCSD object key: {encoded_id}")
    if prefix == "NODE":
        return ObjectRef(EvidenceRole.RCSD_NODE, object_id)
    if prefix == "ROAD":
        return ObjectRef(EvidenceRole.RCSD_ROAD, object_id)
    raise JunctionPredictionError(f"unsupported RCSD object key: {encoded_id}")


def _parse_anchor_node_ref(encoded_id: str) -> AnchorNodeRef:
    normalized = str(encoded_id)
    if normalized.startswith("NODE:"):
        return AnchorNodeRef.source_node(_parse_rcsd_object_ref(normalized))
    prefix = "BREAK:ROAD:"
    if normalized.startswith(prefix) and "#" in normalized:
        road_id, break_rank = normalized[len(prefix) :].rsplit("#", 1)
        return AnchorNodeRef.road_break_point(
            ObjectRef(EvidenceRole.RCSD_ROAD, road_id),
            int(break_rank),
        )
    raise JunctionPredictionError(f"invalid canonical anchor Node key: {encoded_id}")


def _surface_plan(
    derived: Mapping[str, Any],
    surface_row: Mapping[str, Any] | None,
) -> SurfacePlan:
    mode = SurfaceMode(str(derived["surface_mode"]))
    if mode == SurfaceMode.VIRTUAL_SURFACE:
        membership = derived["virtual_surface_membership"]
        member_ids: tuple[str, ...] = ()
        if bool(membership.get("supervised")):
            member_ids = tuple(str(value) for value in membership.get("object_ids", ()))
        if surface_row is not None and bool(surface_row.get("supervised")):
            required = tuple(
                str(value) for value in surface_row.get("required_visible_object_ids", ())
            )
            # The formal surface ledger is independent from normalized anchor
            # topology and therefore overrides the older derived member field.
            member_ids = required
        return SurfacePlan(
            mode=mode,
            virtual_member_refs=tuple(
                sorted((_parse_rcsd_object_ref(value) for value in member_ids))
            ),
            virtual_surface_recipe=VirtualSurfaceRecipe(
                recipe_type="ASSOCIATED_OBJECT_BUFFER_HULL",
                parameters=(("buffer_m", 5.0),),
            ),
        )
    if mode == SurfaceMode.EXISTING_RCSD_INTERSECTION:
        raise JunctionPredictionError(
            "T017 batch does not contain a typed existing-intersection object Gold"
        )
    return SurfacePlan(mode=mode)


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
        raise JunctionPredictionError("T017 SUCCESS row lacks normalized exact topology")
    topology = normalized_plan.get("canonical_topology")
    if not isinstance(topology, Mapping):
        raise JunctionPredictionError("T017 SUCCESS row lacks canonical topology")

    source_refs = tuple(
        sorted(_parse_rcsd_object_ref(value) for value in topology["source_rcsd_objects"])
    )
    node_refs = tuple(ref for ref in source_refs if ref.role == EvidenceRole.RCSD_NODE)
    road_refs = tuple(ref for ref in source_refs if ref.role == EvidenceRole.RCSD_ROAD)

    targets_by_road: dict[ObjectRef, list[tuple[int, float]]] = {}
    for target in normalized_plan.get("break_geometry_targets", ()):
        road_ref = _parse_rcsd_object_ref(str(target["road_object_id"]))
        targets_by_road.setdefault(road_ref, []).append(
            (int(target["break_rank"]), float(target["fraction"]))
        )
    operations: list[RoadBreakOperation] = []
    for road_ref in sorted(targets_by_road):
        ranked = tuple(sorted(targets_by_road[road_ref]))
        if tuple(rank for rank, _ in ranked) != tuple(range(len(ranked))):
            raise JunctionPredictionError("T017 Road-break ranks are not contiguous")
        fractions = tuple(fraction for _, fraction in ranked)
        if fractions != tuple(sorted(fractions)):
            raise JunctionPredictionError("T017 Road-break ranks disagree with fractions")
        operations.append(RoadBreakOperation(road_ref, fractions))

    equivalence = tuple(
        _parse_anchor_node_ref(value)
        for value in topology.get("junction_node_equivalence_class", ())
    )
    result = AnchorResult(
        state=state,
        associated_rcsd_node_refs=node_refs,
        associated_rcsd_road_refs=road_refs,
        selected_main_anchor=_parse_anchor_node_ref(str(topology["main_anchor"])),
        node_equivalence_classes=(NodeEquivalenceClass(equivalence),)
        if equivalence
        else (),
        road_break_operations=tuple(operations),
    )
    result.validate()
    return result


def _quality_state(anchor_state: AnchorState) -> QualityState:
    return {
        AnchorState.SUCCESS: QualityState.NORMAL,
        AnchorState.NO_RCSD_EVIDENCE: QualityState.NO_EVIDENCE,
        AnchorState.AMBIGUOUS: QualityState.AMBIGUOUS,
        AnchorState.QUALITY_ISSUE: QualityState.QUALITY_ISSUE,
        AnchorState.ABSTAIN: QualityState.REVIEW,
    }[anchor_state]


def _step1_state(strong: Mapping[str, Any]) -> Step1DriveZoneState:
    value = str(strong["t07_step1_has_evd"]).strip().lower()
    if value == "yes":
        return Step1DriveZoneState.EVIDENCE
    if value == "no":
        return Step1DriveZoneState.NO_EVIDENCE
    raise JunctionPredictionError(f"T017 Step1 Gold is not binary: {value}")


def _with_plan_id(plan: CandidatePlan, plan_id: str) -> CandidatePlan:
    return replace(plan, plan_id=plan_id)


def _change_anchor(plan: CandidatePlan, anchor: AnchorResult, plan_id: str) -> CandidatePlan:
    return replace(
        plan,
        plan_id=plan_id,
        anchor_result=anchor,
        planned_topology_signature=business_topology_signature(anchor),
    )


def _candidate_decoys(gold: CandidatePlan) -> tuple[CandidatePlan, CandidatePlan]:
    if gold.anchor_result.state != AnchorState.SUCCESS:
        abstain = CandidatePlan(
            plan_id="decoy:abstain",
            step1_drivezone_state=Step1DriveZoneState.ABSTAIN,
            surface_plan=SurfacePlan(mode=SurfaceMode.ABSTAIN),
            anchor_result=AnchorResult(state=AnchorState.ABSTAIN),
            quality_state=QualityState.REVIEW,
            review_reason="T017_TRAINING_ORACLE_DECOY",
            planned_topology_signature="",
        )
        alternative_anchor = (
            AnchorState.AMBIGUOUS
            if gold.anchor_result.state != AnchorState.AMBIGUOUS
            else AnchorState.QUALITY_ISSUE
        )
        alternative_surface = (
            SurfacePlan(mode=SurfaceMode.NO_VALID_SURFACE)
            if gold.surface_plan.mode != SurfaceMode.NO_VALID_SURFACE
            else SurfacePlan(
                mode=SurfaceMode.VIRTUAL_SURFACE,
                virtual_surface_recipe=VirtualSurfaceRecipe(
                    "ASSOCIATED_OBJECT_BUFFER_HULL",
                    (("buffer_m", 5.0),),
                ),
            )
        )
        alternative = CandidatePlan(
            plan_id="decoy:alternate-state",
            step1_drivezone_state=gold.step1_drivezone_state,
            surface_plan=alternative_surface,
            anchor_result=AnchorResult(state=alternative_anchor),
            quality_state=_quality_state(alternative_anchor),
            review_reason="T017_TRAINING_ORACLE_DECOY",
            planned_topology_signature="",
        )
        return abstain, alternative

    anchor = gold.anchor_result
    possible_main_refs: list[AnchorNodeRef] = [
        AnchorNodeRef.source_node(ref) for ref in anchor.associated_rcsd_node_refs
    ]
    for operation in anchor.road_break_operations:
        possible_main_refs.extend(
            AnchorNodeRef.road_break_point(operation.road_ref, rank)
            for rank in range(len(operation.fractions))
        )
    alternate_main = next(
        (ref for ref in possible_main_refs if ref != anchor.selected_main_anchor),
        None,
    )
    if alternate_main is not None:
        first = _change_anchor(
            gold,
            replace(anchor, selected_main_anchor=alternate_main),
            "decoy:main-anchor",
        )
    elif gold.surface_plan.virtual_member_refs:
        first = replace(
            gold,
            plan_id="decoy:surface-membership",
            surface_plan=replace(
                gold.surface_plan,
                virtual_member_refs=gold.surface_plan.virtual_member_refs[:-1],
            ),
        )
    else:
        first = replace(
            gold,
            plan_id="decoy:quality",
            quality_state=QualityState.REVIEW,
            review_reason="T017_TRAINING_ORACLE_DECOY",
        )

    if anchor.node_equivalence_classes:
        group = anchor.node_equivalence_classes[0]
        changed_groups = (
            (NodeEquivalenceClass(group.node_refs[:1]),)
            + anchor.node_equivalence_classes[1:]
            if len(group.node_refs) > 1
            else anchor.node_equivalence_classes[1:]
        )
        second = _change_anchor(
            gold,
            replace(anchor, node_equivalence_classes=changed_groups),
            "decoy:node-equivalence",
        )
    else:
        second = replace(
            gold,
            plan_id="decoy:quality",
            quality_state=QualityState.REVIEW,
            review_reason="T017_TRAINING_ORACLE_DECOY",
        )
    first.validate()
    second.validate()
    return first, second


def _build_example(
    sample_id: str,
    feature: Mapping[str, Any],
    derived: Mapping[str, Any],
    strong: Mapping[str, Any],
    surface_row: Mapping[str, Any] | None,
) -> tuple[JunctionEvidenceExample, JunctionTrainingOverlay, Mapping[str, Any]]:
    if derived.get("split") != "train" or derived.get("source") != "STRONG_GOLD":
        raise JunctionPredictionError(f"T017 sample is not strong train Gold: {sample_id}")
    if float(strong.get("label_weight", -1.0)) != 1.0:
        raise JunctionPredictionError(f"T017 strong Gold weight changed: {sample_id}")
    if feature.get("input_fingerprint") != strong.get("input_fingerprint"):
        raise JunctionPredictionError(f"T017 input fingerprint mismatch: {sample_id}")

    span_rows = tuple(feature["geometry_object_spans"])
    object_refs = tuple(_parse_feature_ref(span) for span in span_rows)
    if len(set(object_refs)) != len(object_refs):
        raise JunctionPredictionError(f"T017 feature objects are duplicated: {sample_id}")
    spans = tuple(
        ObjectTokenSpan(
            object_ref,
            int(span["token_start"]),
            int(span["token_end"]),
        )
        for object_ref, span in zip(object_refs, span_rows)
    )
    geometry_tokens = torch.tensor(
        feature["geometry_token_features"],
        dtype=torch.float32,
    )
    relation_edges = tuple(feature["geometry_relation_edges"])
    if relation_edges:
        edge_indices = torch.tensor(
            (
                tuple(spans[int(edge[0])].start for edge in relation_edges),
                tuple(spans[int(edge[1])].start for edge in relation_edges),
            ),
            dtype=torch.long,
        )
        edge_features = torch.tensor(
            tuple(edge[2] for edge in relation_edges),
            dtype=torch.float32,
        )
    else:
        edge_indices = torch.zeros((2, 0), dtype=torch.long)
        edge_features = torch.zeros((0, 8), dtype=torch.float32)

    anchor = _anchor_result(derived)
    surface = _surface_plan(derived, surface_row)
    step1 = _step1_state(strong)
    quality = _quality_state(anchor.state)
    gold = CandidatePlan(
        plan_id="gold",
        step1_drivezone_state=step1,
        surface_plan=surface,
        anchor_result=anchor,
        quality_state=quality,
        review_reason="" if quality == QualityState.NORMAL else f"T017_GOLD_{quality.value}",
        planned_topology_signature=(
            business_topology_signature(anchor)
            if anchor.state == AnchorState.SUCCESS
            else ""
        ),
    )
    decoys = _candidate_decoys(gold)
    case_key = ":".join(sample_id.split(":")[1:-1])
    semantic_id = str(feature["anchor_id"])
    junction_key = f"{case_key}|{semantic_id}"
    plans = (_with_plan_id(gold, "gold"),) + decoys
    binding = CandidateBinding(
        junction_key=junction_key,
        allowed_object_refs=object_refs,
        plans=plans,
    )
    example = JunctionEvidenceExample(
        junction_key=junction_key,
        case_key=case_key,
        semantic_junction_id=semantic_id,
        geometry_tokens=geometry_tokens,
        object_spans=spans,
        topology_edge_indices=edge_indices,
        topology_edge_features=edge_features,
        candidate_binding=binding,
    )
    example.validate()

    virtual_constraints: list[SurfaceConstraint] = []
    if surface_row is not None and bool(surface_row.get("supervised")):
        for encoded_id in surface_row.get("required_visible_object_ids", ()):
            virtual_constraints.append(
                SurfaceConstraint(
                    _parse_rcsd_object_ref(encoded_id),
                    ConstraintState.REQUIRED,
                    1.0,
                )
            )
        for encoded_id in surface_row.get("forbidden_visible_object_ids", ()):
            virtual_constraints.append(
                SurfaceConstraint(
                    _parse_rcsd_object_ref(encoded_id),
                    ConstraintState.FORBIDDEN,
                    1.0,
                )
            )
        for encoded_id in surface_row.get("rule_reference_only_object_ids", ()):
            virtual_constraints.append(
                SurfaceConstraint(
                    _parse_rcsd_object_ref(encoded_id),
                    ConstraintState.UNKNOWN,
                    0.0,
                )
            )

    visible_rcsd_refs = tuple(
        ref
        for ref in object_refs
        if ref.role in {EvidenceRole.RCSD_NODE, EvidenceRole.RCSD_ROAD}
    )
    anchor_constraints: list[SurfaceConstraint] = []
    if anchor.state == AnchorState.SUCCESS:
        selected = set(anchor.associated_rcsd_node_refs) | set(
            anchor.associated_rcsd_road_refs
        )
        anchor_constraints = [
            SurfaceConstraint(
                ref,
                ConstraintState.REQUIRED if ref in selected else ConstraintState.FORBIDDEN,
                1.0,
            )
            for ref in visible_rcsd_refs
        ]

    pair_constraints: list[PairConstraint] = []
    for equivalence_class in anchor.node_equivalence_classes:
        source_nodes = tuple(
            ref.node_ref
            for ref in equivalence_class.node_refs
            if ref.kind == AnchorNodeKind.SOURCE_RCSD_NODE and ref.node_ref is not None
        )
        pair_constraints.extend(
            PairConstraint(left, right, ConstraintState.REQUIRED, 1.0)
            for left, right in combinations(source_nodes, 2)
        )

    break_by_road = {
        operation.road_ref: operation for operation in anchor.road_break_operations
    }
    road_break_targets: list[RoadBreakTarget] = []
    for road_ref in anchor.associated_rcsd_road_refs:
        operation = break_by_road.get(road_ref)
        if operation is None:
            road_break_targets.append(RoadBreakTarget(road_ref, False, None, 1.0))
        elif len(operation.fractions) == 1:
            road_break_targets.append(
                RoadBreakTarget(road_ref, True, operation.fractions[0], 1.0)
            )

    main_refs = (
        (anchor.selected_main_anchor,)
        if anchor.selected_main_anchor is not None
        and anchor.selected_main_anchor.kind == AnchorNodeKind.SOURCE_RCSD_NODE
        else ()
    )
    overlay = JunctionTrainingOverlay(
        junction_key=junction_key,
        source_weight=1.0,
        step1_acceptable_indices=(tuple(Step1DriveZoneState).index(step1),),
        surface_mode_acceptable_indices=(tuple(SurfaceMode).index(surface.mode),),
        anchor_state_acceptable_indices=(tuple(AnchorState).index(anchor.state),),
        quality_acceptable_indices=(tuple(QualityState).index(quality),),
        acceptable_complete_plan_ids=("gold",),
        virtual_surface_constraints=tuple(virtual_constraints),
        anchor_member_constraints=tuple(anchor_constraints),
        acceptable_main_anchor_refs=main_refs,
        pair_constraints=tuple(pair_constraints),
        road_break_targets=tuple(road_break_targets),
    )
    audit = {
        "sample_id": sample_id,
        "junction_key": junction_key,
        "split": derived["split"],
        "source": derived["source"],
        "source_weight": 1.0,
        "token_count": int(geometry_tokens.shape[0]),
        "object_count": len(object_refs),
        "step1_state": step1.value,
        "surface_mode": surface.mode.value,
        "anchor_state": anchor.state.value,
        "quality_state": quality.value,
        "main_anchor_kind": (
            anchor.selected_main_anchor.kind.value
            if anchor.selected_main_anchor is not None
            else None
        ),
        "break_point_count": sum(
            len(operation.fractions) for operation in anchor.road_break_operations
        ),
        "mixed_equivalence": any(
            {ref.kind for ref in group.node_refs}
            == {AnchorNodeKind.SOURCE_RCSD_NODE, AnchorNodeKind.ROAD_BREAK_POINT}
            for group in anchor.node_equivalence_classes
        ),
        "surface_constraint_count": len(virtual_constraints),
        "anchor_constraint_count": len(anchor_constraints),
        "candidate_count": len(plans),
        "candidate_catalog": "TRAINING_ORACLE_ONLY",
        "external_topology_signature": derived["normalized_junctionization_plan"].get(
            "topology_signature", ""
        ),
        "model_topology_signature": gold.planned_topology_signature,
    }
    return example, overlay, audit


def prepare_t017_batch(config: T017OverfitConfig) -> T017PreparedBatch:
    config.validate()
    paths = config.data_paths
    for path in (
        paths.derived_labels,
        paths.derived_manifest,
        paths.feature_store,
        paths.feature_manifest,
        paths.strong_labels,
        paths.strong_manifest,
        paths.surface_constraints,
        paths.surface_manifest,
    ):
        if not Path(path).is_file():
            raise FileNotFoundError(path)
    derived_manifest = json.loads(paths.derived_manifest.read_text(encoding="utf-8"))
    if (
        bool(derived_manifest.get("training_executed"))
        or bool(derived_manifest.get("frozen_test_labels_aggregated"))
        or int(derived_manifest.get("sealed_test_row_count", -1)) != 106
    ):
        raise JunctionPredictionError("T017 development overlay isolation contract changed")

    requested = tuple(config.sample_ids)
    source_rows = {
        "derived": extract_exact_jsonl_rows(paths.derived_labels, requested),
        "feature": extract_exact_jsonl_rows(paths.feature_store, requested),
        "strong": extract_exact_jsonl_rows(paths.strong_labels, requested),
        "surface": extract_exact_jsonl_rows(
            paths.surface_constraints,
            requested,
            optional=True,
        ),
    }
    examples: list[JunctionEvidenceExample] = []
    overlays: list[JunctionTrainingOverlay] = []
    sample_audit: list[Mapping[str, Any]] = []
    for sample_id in requested:
        example, overlay, audit = _build_example(
            sample_id,
            source_rows["feature"][sample_id],
            source_rows["derived"][sample_id],
            source_rows["strong"][sample_id],
            source_rows["surface"].get(sample_id),
        )
        examples.append(example)
        overlays.append(overlay)
        sample_audit.append(audit)
    row_hashes = {
        name: hashlib.sha256(
            b"\n".join(
                _canonical_json_bytes(rows[sample_id])
                for sample_id in requested
                if sample_id in rows
            )
        ).hexdigest()
        for name, rows in source_rows.items()
    }
    return T017PreparedBatch(
        examples=tuple(examples),
        overlays=tuple(overlays),
        teacher_step1_indices=torch.tensor(
            [overlay.step1_acceptable_indices[0] for overlay in overlays],
            dtype=torch.long,
        ),
        teacher_surface_indices=torch.tensor(
            [overlay.surface_mode_acceptable_indices[0] for overlay in overlays],
            dtype=torch.long,
        ),
        sample_audit=tuple(sample_audit),
        selected_row_sha256=row_hashes,
    )


def _move_view(view: StageEvidenceView, device: torch.device) -> StageEvidenceView:
    return replace(
        view,
        geometry_tokens=view.geometry_tokens.to(device=device),
        topology_edge_indices=view.topology_edge_indices.to(device=device),
        topology_edge_features=view.topology_edge_features.to(device=device),
    )


def build_cached_views(
    model: JunctionGraphSetModel,
    examples: Sequence[JunctionEvidenceExample],
    device: torch.device,
) -> T017CachedViews:
    normalized = tuple(examples)
    return T017CachedViews(
        step1=tuple(
            _move_view(model.firewall.build_view(example, EvidenceStage.STEP1), device)
            for example in normalized
        ),
        surface=tuple(
            _move_view(model.firewall.build_view(example, EvidenceStage.SURFACE), device)
            for example in normalized
        ),
        anchor=tuple(
            _move_view(model.firewall.build_view(example, EvidenceStage.ANCHOR), device)
            for example in normalized
        ),
    )


def _forward(
    model: JunctionGraphSetModel,
    prepared: T017PreparedBatch,
    views: T017CachedViews,
    *,
    teacher_forced: bool,
    device: torch.device,
) -> JunctionGraphSetRawOutput:
    return model.forward_stage_views(
        step1_views=views.step1,
        surface_views=views.surface,
        anchor_views=views.anchor,
        candidate_bindings=tuple(
            example.candidate_binding for example in prepared.examples
        ),
        step1_state_indices=(
            prepared.teacher_step1_indices.to(device=device)
            if teacher_forced
            else None
        ),
        surface_mode_indices=(
            prepared.teacher_surface_indices.to(device=device)
            if teacher_forced
            else None
        ),
    )


def evaluate_t017_output(
    output: JunctionGraphSetRawOutput,
    overlays: Sequence[JunctionTrainingOverlay],
    *,
    fraction_tolerance: float,
) -> Mapping[str, Any]:
    normalized = tuple(overlays)
    sample_exact = [True] * len(normalized)
    component: dict[str, list[int]] = {}

    def record(name: str, batch_index: int, correct: bool) -> None:
        counts = component.setdefault(name, [0, 0])
        counts[1] += 1
        counts[0] += int(correct)
        sample_exact[batch_index] = sample_exact[batch_index] and correct

    class_outputs = (
        ("step1", output.step1_logits, "step1_acceptable_indices"),
        ("surface_mode", output.surface.mode_logits, "surface_mode_acceptable_indices"),
        ("anchor_state", output.anchor_state_logits, "anchor_state_acceptable_indices"),
        ("quality", output.quality_logits, "quality_acceptable_indices"),
    )
    for name, logits, field_name in class_outputs:
        predictions = logits.argmax(dim=-1).tolist()
        for batch_index, overlay in enumerate(normalized):
            acceptable = getattr(overlay, field_name)
            if acceptable:
                record(name, batch_index, predictions[batch_index] in acceptable)

    def member_checks(
        name: str,
        logits: torch.Tensor,
        refs: Sequence[ObjectRef],
        batches: torch.Tensor,
        constraint_field: str,
    ) -> None:
        positions = {
            (int(batches[index]), ref): index for index, ref in enumerate(refs)
        }
        for batch_index, overlay in enumerate(normalized):
            for constraint in getattr(overlay, constraint_field):
                if constraint.state in {ConstraintState.UNKNOWN, ConstraintState.REVIEW}:
                    continue
                position = positions.get((batch_index, constraint.object_ref))
                correct = False
                if position is not None:
                    predicted = bool(float(torch.sigmoid(logits[position])) >= 0.5)
                    expected = constraint.state == ConstraintState.REQUIRED
                    correct = predicted == expected
                record(name, batch_index, correct)

    member_checks(
        "virtual_surface_member",
        output.surface.virtual_member_logits,
        output.surface.virtual_member_refs,
        output.anchor_member_batch_indices,
        "virtual_surface_constraints",
    )
    member_checks(
        "anchor_member",
        output.anchor_member_logits,
        output.anchor_member_refs,
        output.anchor_member_batch_indices,
        "anchor_member_constraints",
    )

    main_positions = {
        (int(output.main_anchor_batch_indices[index]), ref): index
        for index, ref in enumerate(output.main_anchor_refs)
    }
    for batch_index, overlay in enumerate(normalized):
        if not overlay.acceptable_main_anchor_refs:
            continue
        local = tuple(
            (ref, position)
            for (row, ref), position in main_positions.items()
            if row == batch_index
        )
        if local:
            best_ref = max(local, key=lambda item: float(output.main_anchor_logits[item[1]]))[0]
            record("main_anchor_source_aux", batch_index, best_ref in overlay.acceptable_main_anchor_refs)
        else:
            record("main_anchor_source_aux", batch_index, False)

    pair_positions = {
        (
            int(output.node_equivalence.pair_batch_indices[index]),
            frozenset(pair),
        ): index
        for index, pair in enumerate(output.node_equivalence.pair_refs)
    }
    for batch_index, overlay in enumerate(normalized):
        for constraint in overlay.pair_constraints:
            if constraint.state in {ConstraintState.UNKNOWN, ConstraintState.REVIEW}:
                continue
            position = pair_positions.get(
                (batch_index, frozenset((constraint.left, constraint.right)))
            )
            correct = False
            if position is not None:
                predicted = bool(
                    float(torch.sigmoid(output.node_equivalence.logits[position])) >= 0.5
                )
                expected = constraint.state == ConstraintState.REQUIRED
                correct = predicted == expected
            record("node_equivalence_source_aux", batch_index, correct)

    break_positions = {
        (int(output.road_break.road_batch_indices[index]), ref): index
        for index, ref in enumerate(output.road_break.road_refs)
    }
    for batch_index, overlay in enumerate(normalized):
        for target in overlay.road_break_targets:
            position = break_positions.get((batch_index, target.road_ref))
            presence_correct = False
            fraction_correct = True
            if position is not None:
                predicted_presence = bool(
                    float(torch.sigmoid(output.road_break.presence_logits[position]))
                    >= 0.5
                )
                presence_correct = predicted_presence == target.present
                if target.present and target.fraction is not None:
                    fraction_correct = (
                        abs(float(output.road_break.fractions[position]) - target.fraction)
                        <= fraction_tolerance
                    )
            record("road_break_presence_aux", batch_index, presence_correct)
            if target.present and target.fraction is not None:
                record("road_break_fraction_aux", batch_index, fraction_correct)

    for batch_index, overlay in enumerate(normalized):
        positions = tuple(
            index
            for index in range(len(output.complete_plan.plan_ids))
            if int(output.complete_plan.plan_batch_indices[index]) == batch_index
        )
        if not positions:
            record("complete_plan", batch_index, False)
            continue
        best = max(positions, key=lambda index: float(output.complete_plan.logits[index]))
        record(
            "complete_plan",
            batch_index,
            output.complete_plan.plan_ids[best] in overlay.acceptable_complete_plan_ids,
        )

    return {
        "complete_exact_count": sum(sample_exact),
        "complete_exact_denominator": len(sample_exact),
        "per_sample_exact": {
            overlay.junction_key: sample_exact[index]
            for index, overlay in enumerate(normalized)
        },
        "components": {
            name: {"correct": counts[0], "denominator": counts[1]}
            for name, counts in sorted(component.items())
        },
        "break_main_supervision": "COMPLETE_PLAN_HEAD",
        "mixed_equivalence_supervision": "COMPLETE_PLAN_HEAD",
    }


def _select_device(requested: str) -> torch.device:
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("T017 requested CUDA but CUDA is unavailable")
    if requested in {"auto", "cuda"} and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _write_json(path: Path, payload: Any) -> None:
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_t017_overfit(config: T017OverfitConfig) -> Mapping[str, Any]:
    """Run the authorized training-fold representation gate, never the blind test."""

    config.validate()
    output_dir = Path(config.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"T017 output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.perf_counter()
    random.seed(config.seed)
    torch.manual_seed(config.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(config.seed)
    device = _select_device(config.device)
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    prepared = prepare_t017_batch(config)
    model = JunctionGraphSetModel(
        hidden_dim=config.hidden_dim,
        dropout=0.0,
    ).to(device)
    views = build_cached_views(model, prepared.examples, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=0.0,
    )
    history: list[Mapping[str, Any]] = []
    consecutive_passes = 0
    converged_step: int | None = None

    for step in range(1, config.max_steps + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        teacher_output = _forward(
            model,
            prepared,
            views,
            teacher_forced=True,
            device=device,
        )
        losses = compute_multitask_loss(teacher_output, prepared.overlays)
        losses["total"].backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()

        should_evaluate = step == 1 or step % config.evaluation_interval == 0
        if not should_evaluate:
            continue
        model.eval()
        with torch.no_grad():
            teacher_output = _forward(
                model,
                prepared,
                views,
                teacher_forced=True,
                device=device,
            )
            teacher_losses = compute_multitask_loss(
                teacher_output,
                prepared.overlays,
            )
            free_output = _forward(
                model,
                prepared,
                views,
                teacher_forced=False,
                device=device,
            )
            teacher_metrics = evaluate_t017_output(
                teacher_output,
                prepared.overlays,
                fraction_tolerance=config.road_break_fraction_tolerance,
            )
            free_metrics = evaluate_t017_output(
                free_output,
                prepared.overlays,
                fraction_tolerance=config.road_break_fraction_tolerance,
            )
        total_loss = float(teacher_losses["total"])
        sample_count = len(prepared.examples)
        passed_now = (
            total_loss <= config.maximum_total_loss
            and teacher_metrics["complete_exact_count"] == sample_count
            and free_metrics["complete_exact_count"] == sample_count
        )
        consecutive_passes = consecutive_passes + 1 if passed_now else 0
        history.append(
            {
                "step": step,
                "losses": {
                    name: float(value) for name, value in teacher_losses.items()
                },
                "teacher": teacher_metrics,
                "free_run": free_metrics,
                "passed_now": passed_now,
                "consecutive_passes": consecutive_passes,
            }
        )
        if consecutive_passes >= config.required_consecutive_passes:
            converged_step = step
            break

    if not history:
        raise RuntimeError("T017 produced no evaluation history")
    final = history[-1]
    passed = converged_step is not None
    checkpoint_path = output_dir / "checkpoint.pt"
    torch.save(
        {
            "schema_version": "p05-junction-graphset-v1-t017-overfit-v1",
            "model_state_dict": {
                name: value.detach().cpu() for name, value in model.state_dict().items()
            },
            "config": {
                "seed": config.seed,
                "hidden_dim": config.hidden_dim,
                "learning_rate": config.learning_rate,
                "max_steps": config.max_steps,
                "evaluation_interval": config.evaluation_interval,
            },
            "sample_ids": config.sample_ids,
            "passed": passed,
            "converged_step": converged_step,
        },
        checkpoint_path,
    )
    _write_json(output_dir / "history.json", history)

    manifest_paths = {
        "derived": config.data_paths.derived_manifest,
        "feature": config.data_paths.feature_manifest,
        "strong": config.data_paths.strong_manifest,
        "surface": config.data_paths.surface_manifest,
    }
    summary = {
        "schema_version": "p05-junction-graphset-v1-t017-overfit-v1",
        "status": "PASS" if passed else "REPRESENTATION_NO_GO",
        "task": "T017_TRAINING_FOLD_STRONG_GOLD_OVERFIT",
        "training_executed": True,
        "canary_executed": False,
        "blind_test_labels_read": False,
        "blind_test_access_count": 0,
        "sample_count": len(prepared.examples),
        "sample_ids": list(config.sample_ids),
        "sample_set_sha256": hashlib.sha256(
            "\n".join(config.sample_ids).encode("utf-8")
        ).hexdigest(),
        "sample_audit": list(prepared.sample_audit),
        "selected_row_sha256": dict(prepared.selected_row_sha256),
        "source_manifest_sha256": {
            name: _sha256_file(path) for name, path in manifest_paths.items()
        },
        "candidate_catalog": "TRAINING_ORACLE_ONLY",
        "candidate_catalog_warning": (
            "Only proves representation/heads can learn bound complete plans; "
            "it is not inference candidate generation and does not authorize canary."
        ),
        "device": str(device),
        "device_name": (
            torch.cuda.get_device_name(device) if device.type == "cuda" else "CPU"
        ),
        "torch_version": torch.__version__,
        "model_parameter_count": model.parameter_count,
        "encoder_parameter_count": model.encoder.parameter_count,
        "config": {
            "seed": config.seed,
            "hidden_dim": config.hidden_dim,
            "learning_rate": config.learning_rate,
            "max_steps": config.max_steps,
            "evaluation_interval": config.evaluation_interval,
            "required_consecutive_passes": config.required_consecutive_passes,
            "maximum_total_loss": config.maximum_total_loss,
            "road_break_fraction_tolerance": config.road_break_fraction_tolerance,
        },
        "completed_step": int(final["step"]),
        "converged_step": converged_step,
        "final_losses": final["losses"],
        "teacher_forced": final["teacher"],
        "free_run": final["free_run"],
        "elapsed_seconds": time.perf_counter() - started_at,
        "peak_cuda_memory_bytes": (
            int(torch.cuda.max_memory_allocated(device))
            if device.type == "cuda"
            else 0
        ),
        "checkpoint": str(checkpoint_path),
        "next_gate_authorized": False,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary
