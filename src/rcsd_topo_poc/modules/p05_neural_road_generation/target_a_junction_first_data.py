from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch


FEATURE_DIM = 64
STAGE1_OBJECT_INDICES = (0, 1, 2, 3, 13, 14, 15, 21, 22, 23, 24)
MEMBER_FEATURE_DIM = 12

TASK_CLASSES: Mapping[str, tuple[str, ...]] = {
    "t07_step1": ("no", "yes"),
    "t07_step2": ("no", "yes", "fail1", "fail2"),
    "route": ("NO_EVIDENCE", "T07", "T03", "T04", "UNRESOLVED"),
    "t07_relation": (
        "existing_rcsdintersection_matched",
        "intersection_shared_by_multiple_groups",
        "multiple_intersections_for_group",
        "no_existing_rcsdintersection",
        "not_evaluated_no_evidence",
        "rcsdintersection_no_rcsd_semantic_node",
        "t_junction_not_strict_single_surface",
        "t_junction_surface_contains_other_swsd_semantic_junction",
        "t_junction_surface_multiple_rcsd_semantic_nodes",
        "t_junction_surface_no_rcsd_semantic_node",
    ),
    "t03_surface": ("accepted", "rejected"),
    "t03_association": ("A", "B", "C"),
    "t03_relation": (
        "geometry_not_accepted",
        "no_related_rcsd",
        "rcsd_present_not_junction",
        "success_required_rcsd_junction",
    ),
    "t04_surface": ("accepted", "rejected", "runtime_failed"),
    "t04_relation": (
        "geometry_not_accepted",
        "no_related_rcsd",
        "rcsd_present_not_junction",
        "success_offset_fact_with_rcsd_junction",
        "success_required_rcsd_junction",
    ),
    "t05_surface_source": ("T02_INPUT", "T03", "T04"),
    "t05_junctionization": (
        "direct_relation",
        "failure_relation",
        "group_existing_rcsd_nodes",
        "split_rcsdroad_generate_rcsdnode",
    ),
    "t05_graph": (
        "base_mainnodeid_graph_incident",
        "base_node_graph_incident",
        "base_node_group_graph_incident",
        "relation_not_success",
    ),
    "t05_relation": ("0", "1"),
    "anchor_status": (
        "SUCCESS",
        "NO_EVIDENCE",
        "AMBIGUOUS",
        "ABSTAIN",
        "UNSUPPORTED_COMPOSITE_ANCHOR",
    ),
}

TASK_INDEX: Mapping[str, Mapping[str, int]] = {
    task: {value: index for index, value in enumerate(values)}
    for task, values in TASK_CLASSES.items()
}


@dataclass(frozen=True)
class JunctionFirstExample:
    sample_id: str
    case_key: str
    family: str
    anchor_id: str
    fold: int
    sample_weight: float
    stage1_features: tuple[float, ...]
    object_features: tuple[float, ...]
    candidate_ids: tuple[str, ...]
    candidate_features: tuple[tuple[float, ...], ...]
    member_ids: tuple[str, ...]
    member_features: tuple[tuple[float, ...], ...]
    task_labels: Mapping[str, int]
    task_masks: Mapping[str, bool]
    candidate_acceptable_indices: tuple[int, ...]
    candidate_supervised: bool
    member_acceptable_sets: tuple[tuple[int, ...], ...]
    member_supervised: bool


@dataclass(frozen=True)
class JunctionFirstBatch:
    sample_ids: tuple[str, ...]
    case_keys: tuple[str, ...]
    folds: torch.Tensor
    sample_weights: torch.Tensor
    stage1_features: torch.Tensor
    object_features: torch.Tensor
    candidate_features: torch.Tensor
    candidate_mask: torch.Tensor
    candidate_acceptable: torch.Tensor
    candidate_task_mask: torch.Tensor
    member_features: torch.Tensor
    member_mask: torch.Tensor
    member_is_road: torch.Tensor
    member_acceptable_sets: torch.Tensor
    member_acceptable_set_mask: torch.Tensor
    member_task_mask: torch.Tensor
    task_labels: Mapping[str, torch.Tensor]
    task_masks: Mapping[str, torch.Tensor]

    def to(self, device: torch.device | str) -> JunctionFirstBatch:
        return JunctionFirstBatch(
            sample_ids=self.sample_ids,
            case_keys=self.case_keys,
            folds=self.folds.to(device),
            sample_weights=self.sample_weights.to(device),
            stage1_features=self.stage1_features.to(device),
            object_features=self.object_features.to(device),
            candidate_features=self.candidate_features.to(device),
            candidate_mask=self.candidate_mask.to(device),
            candidate_acceptable=self.candidate_acceptable.to(device),
            candidate_task_mask=self.candidate_task_mask.to(device),
            member_features=self.member_features.to(device),
            member_mask=self.member_mask.to(device),
            member_is_road=self.member_is_road.to(device),
            member_acceptable_sets=self.member_acceptable_sets.to(device),
            member_acceptable_set_mask=self.member_acceptable_set_mask.to(device),
            member_task_mask=self.member_task_mask.to(device),
            task_labels={key: value.to(device) for key, value in self.task_labels.items()},
            task_masks={key: value.to(device) for key, value in self.task_masks.items()},
        )


def read_junction_first_examples(
    *,
    anchor_store_root: Path,
    junction_audit_path: Path,
) -> tuple[JunctionFirstExample, ...]:
    root = Path(anchor_store_root).resolve(strict=True)
    audit_path = Path(junction_audit_path).resolve(strict=True)
    features = list(
        _read_jsonl(root / "inference_feature_store/anchor_features.jsonl")
    )
    labels = {
        str(row["sample_id"]): row
        for row in _read_jsonl(root / "training_label_store/anchor_labels.jsonl")
    }
    audits = {
        str(row["sample_id"]): row for row in _read_jsonl(audit_path)
    }
    if set(labels) != {str(row["sample_id"]) for row in features}:
        raise ValueError("junction feature and anchor label sample scopes differ")
    if not set(audits).issubset(labels):
        raise ValueError("junction audit contains unknown anchor samples")

    examples = [
        _example(feature, labels[str(feature["sample_id"])], audits.get(str(feature["sample_id"])))
        for feature in features
    ]
    return tuple(sorted(examples, key=lambda row: (row.case_key, row.anchor_id)))


def collate_junction_first(
    examples: Sequence[JunctionFirstExample],
) -> JunctionFirstBatch:
    if not examples:
        raise ValueError("junction-first batch is empty")
    batch_size = len(examples)
    max_candidates = max(len(row.candidate_ids) for row in examples)
    max_members = max(1, max(len(row.member_ids) for row in examples))
    max_options = max(1, max(len(row.member_acceptable_sets) for row in examples))

    stage1 = torch.zeros(batch_size, len(STAGE1_OBJECT_INDICES), dtype=torch.float32)
    objects = torch.zeros(batch_size, FEATURE_DIM, dtype=torch.float32)
    candidates = torch.zeros(batch_size, max_candidates, FEATURE_DIM, dtype=torch.float32)
    candidate_mask = torch.zeros(batch_size, max_candidates, dtype=torch.bool)
    candidate_acceptable = torch.zeros(batch_size, max_candidates, dtype=torch.bool)
    members = torch.zeros(batch_size, max_members, MEMBER_FEATURE_DIM, dtype=torch.float32)
    member_mask = torch.zeros(batch_size, max_members, dtype=torch.bool)
    member_is_road = torch.zeros(batch_size, max_members, dtype=torch.bool)
    member_sets = torch.zeros(batch_size, max_options, max_members, dtype=torch.bool)
    member_set_mask = torch.zeros(batch_size, max_options, dtype=torch.bool)

    task_labels = {
        task: torch.full((batch_size,), -1, dtype=torch.long) for task in TASK_CLASSES
    }
    task_masks = {
        task: torch.zeros(batch_size, dtype=torch.bool) for task in TASK_CLASSES
    }
    for batch_index, row in enumerate(examples):
        _require_dim(row.stage1_features, len(STAGE1_OBJECT_INDICES), "stage1")
        _require_dim(row.object_features, FEATURE_DIM, "object")
        stage1[batch_index] = torch.tensor(row.stage1_features)
        objects[batch_index] = torch.tensor(row.object_features)
        for candidate_index, values in enumerate(row.candidate_features):
            _require_dim(values, FEATURE_DIM, "candidate")
            candidates[batch_index, candidate_index] = torch.tensor(values)
            candidate_mask[batch_index, candidate_index] = True
        for candidate_index in row.candidate_acceptable_indices:
            if candidate_index < 0 or candidate_index >= len(row.candidate_ids):
                raise ValueError("acceptable anchor candidate index is out of range")
            candidate_acceptable[batch_index, candidate_index] = True
        for member_index, values in enumerate(row.member_features):
            _require_dim(values, MEMBER_FEATURE_DIM, "member")
            members[batch_index, member_index] = torch.tensor(values)
            member_mask[batch_index, member_index] = True
            member_is_road[batch_index, member_index] = row.member_ids[
                member_index
            ].startswith("ROAD:")
        for option_index, option in enumerate(row.member_acceptable_sets):
            member_set_mask[batch_index, option_index] = True
            for member_index in option:
                if member_index < 0 or member_index >= len(row.member_ids):
                    raise ValueError("acceptable anchor member index is out of range")
                member_sets[batch_index, option_index, member_index] = True
        for task in TASK_CLASSES:
            task_labels[task][batch_index] = int(row.task_labels.get(task, -1))
            task_masks[task][batch_index] = bool(row.task_masks.get(task, False))

    return JunctionFirstBatch(
        sample_ids=tuple(row.sample_id for row in examples),
        case_keys=tuple(row.case_key for row in examples),
        folds=torch.tensor([row.fold for row in examples], dtype=torch.long),
        sample_weights=torch.tensor(
            [row.sample_weight for row in examples], dtype=torch.float32
        ),
        stage1_features=stage1,
        object_features=objects,
        candidate_features=candidates,
        candidate_mask=candidate_mask,
        candidate_acceptable=candidate_acceptable,
        candidate_task_mask=torch.tensor(
            [row.candidate_supervised for row in examples], dtype=torch.bool
        ),
        member_features=members,
        member_mask=member_mask,
        member_is_road=member_is_road,
        member_acceptable_sets=member_sets,
        member_acceptable_set_mask=member_set_mask,
        member_task_mask=torch.tensor(
            [row.member_supervised for row in examples], dtype=torch.bool
        ),
        task_labels=task_labels,
        task_masks=task_masks,
    )


def _example(
    feature: Mapping[str, Any],
    anchor_label: Mapping[str, Any],
    audit: Mapping[str, Any] | None,
) -> JunctionFirstExample:
    family = str(feature["case_key"]).partition(":")[0]
    object_features = tuple(float(value) for value in feature["object_features"])
    if len(object_features) != FEATURE_DIM:
        raise ValueError("junction object feature dimension differs")
    labels = {task: -1 for task in TASK_CLASSES}
    masks = {task: False for task in TASK_CLASSES}
    labels["anchor_status"] = int(anchor_label["status_label"])
    masks["anchor_status"] = bool(anchor_label["status_supervised"])

    if audit is not None:
        _set_label(labels, masks, "t07_step1", audit.get("t07_step1_status"))
        _set_label(labels, masks, "t07_step2", audit.get("t07_step2_status"))
        _set_label(labels, masks, "t07_relation", audit.get("t07_relation_state"))
        _set_label(labels, masks, "t03_surface", audit.get("t03_step7_state"))
        _set_label(labels, masks, "t03_association", audit.get("t03_association_class"))
        _set_label(labels, masks, "t03_relation", audit.get("t03_relation_state"))
        _set_label(labels, masks, "t04_surface", audit.get("t04_final_state"))
        _set_label(labels, masks, "t04_relation", audit.get("t04_relation_state"))
        _set_label(labels, masks, "t05_surface_source", audit.get("t05_surface_sources"))
        _set_label(
            labels,
            masks,
            "t05_junctionization",
            audit.get("t05_junctionization_action"),
        )
        _set_label(labels, masks, "t05_graph", audit.get("t05_graph_status"))
        _set_label(labels, masks, "t05_relation", audit.get("t05_relation_status"))
        if masks["t07_step1"]:
            _set_label(labels, masks, "route", _route_label(audit))
    if family in {"T03", "T03_Error"}:
        _set_label(labels, masks, "route", "T03")
    elif family in {"T04", "T04_Error"}:
        _set_label(labels, masks, "route", "T04")

    candidate_ids = tuple(str(value) for value in feature["candidate_ids"])
    candidate_features = tuple(
        tuple(float(value) for value in row) for row in feature["candidate_features"]
    )
    if len(candidate_ids) != len(candidate_features) or not candidate_ids:
        raise ValueError("junction candidate IDs and features differ")
    member_ids = tuple(str(value) for value in feature.get("structural_member_ids") or ())
    member_features = tuple(
        tuple(float(value) for value in row)
        for row in feature.get("member_local_features") or ()
    )
    if len(member_ids) != len(member_features):
        raise ValueError("junction member IDs and features differ")
    return JunctionFirstExample(
        sample_id=str(feature["sample_id"]),
        case_key=str(feature["case_key"]),
        family=family,
        anchor_id=str(feature["anchor_id"]),
        fold=int(feature["fold"]),
        sample_weight=float(anchor_label["sample_weight"]),
        stage1_features=tuple(object_features[index] for index in STAGE1_OBJECT_INDICES),
        object_features=object_features,
        candidate_ids=candidate_ids,
        candidate_features=candidate_features,
        member_ids=member_ids,
        member_features=member_features,
        task_labels=labels,
        task_masks=masks,
        candidate_acceptable_indices=tuple(
            int(value) for value in anchor_label.get("candidate_acceptable_indices") or ()
        ),
        candidate_supervised=bool(anchor_label.get("candidate_supervised")),
        member_acceptable_sets=tuple(
            tuple(int(value) for value in option)
            for option in anchor_label.get("member_acceptable_sets") or ()
        ),
        member_supervised=bool(anchor_label.get("member_supervised")),
    )


def _route_label(audit: Mapping[str, Any]) -> str:
    step1 = str(audit.get("t07_step1_status") or "")
    step2 = str(audit.get("t07_step2_status") or "")
    if step1 == "no":
        return "NO_EVIDENCE"
    if step2 in {"yes", "fail1", "fail2"}:
        return "T07"
    if bool(audit.get("t03_available")):
        return "T03"
    if bool(audit.get("t04_available")):
        return "T04"
    return "UNRESOLVED"


def _set_label(
    labels: dict[str, int],
    masks: dict[str, bool],
    task: str,
    raw_value: Any,
) -> None:
    value = str(raw_value if raw_value is not None else "").strip()
    if not value:
        return
    if value not in TASK_INDEX[task]:
        raise ValueError(f"unknown {task} label: {value}")
    labels[task] = TASK_INDEX[task][value]
    masks[task] = True


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _require_dim(values: Sequence[float], expected: int, role: str) -> None:
    if len(values) != expected:
        raise ValueError(f"junction {role} feature dimension differs")


__all__ = [
    "FEATURE_DIM",
    "JunctionFirstBatch",
    "JunctionFirstExample",
    "MEMBER_FEATURE_DIM",
    "STAGE1_OBJECT_INDICES",
    "TASK_CLASSES",
    "TASK_INDEX",
    "collate_junction_first",
    "read_junction_first_examples",
]
