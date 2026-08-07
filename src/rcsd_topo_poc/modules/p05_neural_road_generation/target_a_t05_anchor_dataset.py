from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona
import networkx as nx
import numpy as np
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_evidence import (
    ANCHOR_MEMBER_LOCAL_FEATURE_DIM,
    AnchorStructuralEvidence,
    build_anchor_structural_evidence,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_members import (
    ordered_anchor_candidate_members,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_business_adjudications import (
    user_anchor_adjudication,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    TARGET_A_FEATURE_DIM,
    AnchorPretrainExample,
    TargetACaseBundle,
    build_anchor_pretrain_examples,
    read_anchor_pretraining_stores,
    write_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


SEMANTIC_JUNCTION_KINDS = frozenset({4, 8, 16, 64, 128, 2048})
NODE_PAIR_CANDIDATE_LIMIT = 6
NODE_TRIPLE_CANDIDATE_LIMIT = 4


@dataclass(frozen=True)
class T05AnchorDataset:
    examples: tuple[AnchorPretrainExample, ...]
    summary: Mapping[str, Any]


@dataclass(frozen=True)
class _SwsdNode:
    node_id: str
    point: Point
    kind: int
    kind_2: int
    grade: int
    closed_con: int


@dataclass(frozen=True)
class _RawNodeGroup:
    group_id: str
    member_ids: tuple[str, ...]
    points: tuple[Point, ...]
    kinds: tuple[int, ...]
    cross_flags: tuple[int, ...]
    layers: tuple[int, ...]


@dataclass(frozen=True)
class _T07Surface:
    surface_id: str
    geometry: BaseGeometry
    intersection_type: int
    level: int
    is_highway: int
    node_count: int
    inner_road_count: int


@dataclass(frozen=True)
class _RawRoad:
    road_id: str
    start_node_id: str
    end_node_id: str
    direction: int
    function_class: int
    geometry: BaseGeometry


@dataclass(frozen=True)
class _RoadBundle:
    road_ids: tuple[str, ...]
    generator: str
    threshold_m: float


@dataclass(frozen=True)
class _DriveZone:
    geometry: BaseGeometry


@dataclass(frozen=True)
class _T11ManualAnchorLabel:
    case_key: str
    target_id: str
    relation_type: str
    selected_ids: tuple[str, ...]


def build_t05_anchor_pretrain_examples(
    bundles: Sequence[TargetACaseBundle],
    *,
    label_store_root: Path,
    t11_manual_labels_path: Path | None = None,
    radius_m: float = 200.0,
    max_candidates: int = 64,
) -> T05AnchorDataset:
    """Build T05 anchor supervision without exposing T05 fields to features."""
    if radius_m <= 0 or max_candidates < 1:
        raise ValueError("T05 anchor candidate controls are invalid")
    label_root = normalize_runtime_path(label_store_root).resolve(strict=True)
    folds = _case_folds(label_root / "case_inventory.jsonl")
    target_segments = _case_target_segments(
        label_root / "segment_inventory.jsonl"
    )
    manual_labels, manual_path = _read_t11_manual_labels(
        t11_manual_labels_path
    )
    manual_seen: set[tuple[str, str]] = set()
    examples: list[AnchorPretrainExample] = []
    counts: Counter[str] = Counter()
    scene_counts: Counter[str] = Counter()
    for bundle in sorted(bundles, key=lambda row: row.case_key):
        if bundle.case_key not in folds:
            raise ValueError(f"T05 anchor Case lacks a fold: {bundle.case_key}")
        swsd_nodes, semantic_anchor_by_node = _read_swsd_nodes(bundle.t01_nodes)
        target_dependencies = _selected_target_dependencies(
            bundle,
            target_segments.get(bundle.case_key, set()),
            semantic_anchor_by_node,
        )
        target_ids = set(target_dependencies)
        raw_node_path = (
            bundle.source_case_root
            / "external_inputs"
            / "rcsdnode"
            / "rcsdnode_slice.gpkg"
        )
        raw_road_path = (
            bundle.source_case_root
            / "external_inputs"
            / "rcsdroad"
            / "rcsdroad_slice.gpkg"
        )
        t07_path = (
            bundle.source_case_root
            / "external_inputs"
            / "rcsd_intersection"
            / "rcsd_intersection_slice.gpkg"
        )
        drivezone_path = (
            bundle.source_case_root
            / "external_inputs"
            / "drivezone"
            / "drivezone_slice.gpkg"
        )
        groups, group_tree, group_geometries = _read_raw_node_groups(raw_node_path)
        group_by_id = {row.group_id: row for row in groups}
        group_id_by_node_id = {
            node_id: group.group_id
            for group in groups
            for node_id in (group.group_id, *group.member_ids)
        }
        (
            roads,
            road_tree,
            road_geometries,
            incident,
            raw_roads_by_node,
        ) = _read_raw_roads(raw_road_path)
        road_by_id = {row.road_id: row for row in roads}
        swsd_roads_by_anchor = _read_swsd_roads(
            bundle.t01_roads,
            semantic_anchor_by_node,
        )
        surfaces, surface_tree, surface_geometries = _read_t07_surfaces(t07_path)
        surface_by_id = {row.surface_id: row for row in surfaces}
        drivezones, drivezone_tree, drivezone_geometries = _read_drivezones(
            drivezone_path
        )
        audit_path = bundle.t05_relation.parent / "rcsd_junctionization_audit.csv"
        audit_rows = _read_csv_by_target(audit_path)
        input_hashes = tuple(
            sorted(
                (
                    (role, sha256_file(path))
                    for role, path in (
                        ("t01_segment", bundle.t01_segment),
                        ("t01_nodes", bundle.t01_nodes),
                        ("t01_roads", bundle.t01_roads),
                        ("raw_rcsd_nodes", raw_node_path),
                        ("raw_rcsd_roads", raw_road_path),
                        ("t07_drivezone", drivezone_path),
                        ("t07_rcsd_intersection", t07_path),
                    )
                )
            )
        )
        for target_id in sorted(target_ids):
            audit = audit_rows.get(target_id)
            manual = manual_labels.get((bundle.case_key, target_id))
            user_adjudication = user_anchor_adjudication(
                bundle.case_key,
                target_id,
            )
            if manual is not None:
                manual_seen.add((bundle.case_key, target_id))
            target = swsd_nodes.get(target_id)
            if target is None:
                continue
            status = (
                AnchorStatus(user_adjudication.business_status)
                if user_adjudication is not None
                else (
                    _manual_anchor_status(manual)
                    if manual is not None
                    else (
                        _anchor_status_for_audit(audit)
                        if audit is not None
                        else AnchorStatus.ABSTAIN
                    )
                )
            )
            swsd_arms = _road_arms(
                swsd_roads_by_anchor.get(target_id, ()),
                target.point,
            )
            swsd_corridor_roads = swsd_roads_by_anchor.get(target_id, ())
            object_features = _object_features(
                target,
                groups,
                group_tree,
                group_geometries,
                surfaces,
                surface_tree,
                surface_geometries,
                roads,
                road_tree,
                road_geometries,
                drivezones,
                drivezone_tree,
                drivezone_geometries,
                swsd_arms,
                radius_m=radius_m,
            )
            candidate_groups = _nearby_groups(
                target.point,
                groups,
                group_tree,
                group_geometries,
                radius_m=radius_m,
                limit=max_candidates,
            )
            candidate_group_bundles = _nearby_group_bundles(candidate_groups)
            road_bundles = _nearby_road_bundles(
                target.point,
                roads,
                road_tree,
                road_geometries,
                radius_m=radius_m,
                limit=max(16, max_candidates // 2),
            )
            road_corridor_features = _road_corridor_feature_map(
                {
                    road_id
                    for road_bundle in road_bundles
                    for road_id in road_bundle.road_ids
                },
                road_by_id,
                swsd_corridor_roads,
                target.point,
                radius_m=radius_m,
            )
            candidate_ids = tuple(
                f"NODE:{row.group_id}" for row in candidate_groups
            ) + tuple(
                f"NODE:{row.group_id}" for row in candidate_group_bundles
            ) + tuple(_road_bundle_id(row.road_ids) for row in road_bundles)
            candidate_features = tuple(
                tuple(
                    _candidate_features(
                        target,
                        group,
                        incident,
                        raw_roads_by_node,
                        surface_by_id,
                        swsd_arms,
                        radius_m=radius_m,
                    )
                )
                for group in candidate_groups
            ) + tuple(
                tuple(
                    _candidate_features(
                        target,
                        group,
                        incident,
                        raw_roads_by_node,
                        surface_by_id,
                        swsd_arms,
                        radius_m=radius_m,
                    )
                )
                for group in candidate_group_bundles
            ) + tuple(
                tuple(
                    _road_bundle_features(
                        target,
                        bundle,
                        road_by_id,
                        swsd_arms,
                        road_corridor_features,
                        radius_m=radius_m,
                    )
                )
                for bundle in road_bundles
            )
            if not candidate_features:
                candidate_ids = ("NO_RAW_RCSD_CANDIDATE",)
                candidate_features = ((0.0,) * TARGET_A_FEATURE_DIM,)
            structural = _structural_anchor_evidence(
                target,
                candidate_ids,
                candidate_features,
                group_by_id,
                raw_roads_by_node,
                road_by_id,
                swsd_arms,
                radius_m=radius_m,
            )
            base_id = (
                f"NODE:{_canonical_id(audit.get('base_id'))}"
                if audit is not None
                else "NODE:"
            )
            road_label_id = _road_bundle_id(
                tuple(
                    sorted(
                        _split_ids(audit.get("original_rcsdroad_ids"))
                        if audit is not None
                        else ()
                    )
                )
            )
            if user_adjudication is not None:
                accepted_ids = set(
                    user_adjudication.acceptable_candidate_ids
                )
            elif manual is not None:
                manual_candidate_id = _manual_candidate_id(
                    manual,
                    group_id_by_node_id=group_id_by_node_id,
                )
                accepted_ids = (
                    {manual_candidate_id} if manual_candidate_id else set()
                )
            else:
                accepted_ids = {base_id}
                if (
                    audit is not None
                    and str(audit.get("scene") or "") == "road_only_split"
                ):
                    accepted_ids.add(road_label_id)
            acceptable = tuple(
                index
                for index, candidate_id in enumerate(candidate_ids)
                if status is AnchorStatus.SUCCESS and candidate_id in accepted_ids
            )
            candidate_supervised = bool(acceptable)
            preferred = acceptable[0] if acceptable else -1
            examples.append(
                AnchorPretrainExample(
                    sample_id=_sample_id(bundle.case_key, target_id),
                    case_key=bundle.case_key,
                    anchor_id=target_id,
                    fold=folds[bundle.case_key],
                    object_features=tuple(object_features),
                    candidate_ids=tuple(candidate_ids),
                    candidate_features=candidate_features,
                    status_label=ANCHOR_STATUS_INDEX[status],
                    candidate_acceptable_indices=acceptable,
                    preferred_candidate_index=preferred,
                    candidate_supervised=candidate_supervised,
                    sample_weight=(
                        user_adjudication.sample_weight
                        if user_adjudication is not None
                        else (
                            1.0
                            if manual is not None
                            else float(bundle.target_weight)
                        )
                    ),
                    input_hashes=input_hashes,
                    label_reason=(
                        (
                            f"user_manual_anchor:{user_adjudication.reason}:"
                            + (
                                "object_reachable"
                                if candidate_supervised
                                else "object_unspecified"
                            )
                        )
                        if user_adjudication is not None
                        else (
                            _manual_label_reason(
                                manual,
                                candidate_supervised,
                            )
                            if manual is not None
                            else (
                                _label_reason(audit, candidate_supervised)
                                if audit is not None
                                else (
                                    "t05:relation_record_absent:"
                                    "unresolved:abstain"
                                )
                            )
                        )
                    ),
                    dependency_anchor_ids=target_dependencies[target_id],
                    status_supervised=(
                        user_adjudication.status_supervised
                        if user_adjudication is not None
                        else _anchor_status_is_supervised(
                            audit=audit,
                            manual=manual,
                        )
                    ),
                    structural_member_ids=structural.member_ids,
                    swsd_arm_features=structural.swsd_arm_features,
                    member_arm_features=structural.member_arm_features,
                    member_local_features=structural.member_local_features,
                    member_relation_edges=structural.member_relation_edges,
                )
            )
            counts["example"] += 1
            counts[f"status:{status.value}"] += 1
            counts["candidate_supervised"] += int(candidate_supervised)
            counts["success_candidate_unreachable"] += int(
                status is AnchorStatus.SUCCESS and not candidate_supervised
            )
            counts["success_raw_base_reachable"] += int(
                status is AnchorStatus.SUCCESS
                and any(candidate_ids[index].startswith("NODE:") for index in acceptable)
            )
            counts["success_road_bundle_reachable"] += int(
                status is AnchorStatus.SUCCESS
                and any(candidate_ids[index].startswith("ROAD:") for index in acceptable)
            )
            counts["t11_manual_label"] += int(manual is not None)
            counts["t11_manual_no_valid_relation"] += int(
                manual is not None
                and manual.relation_type == "no_valid_relation"
            )
            counts["t11_manual_candidate_supervised"] += int(
                manual is not None and candidate_supervised
            )
            counts["t11_manual_positive_unreachable"] += int(
                manual is not None
                and status is AnchorStatus.SUCCESS
                and not candidate_supervised
            )
            counts["user_manual_anchor_adjudication"] += int(
                user_adjudication is not None
            )
            counts["user_manual_anchor_candidate_unspecified"] += int(
                user_adjudication is not None
                and status is AnchorStatus.SUCCESS
                and not candidate_supervised
            )
            scene_counts[
                (
                    "user_manual_anchor"
                    if user_adjudication is not None
                    else (
                        f"t11_manual:{manual.relation_type}"
                        if manual is not None
                        else (
                            str(audit.get("scene") or "unknown")
                            if audit is not None
                            else "relation_record_absent"
                        )
                    )
                )
            ] += 1
    missing_manual = sorted(set(manual_labels) - manual_seen)
    if missing_manual:
        raise ValueError(
            "T11 manual anchors are outside the T05 training scope: "
            + "|".join(f"{case_key}/{target_id}" for case_key, target_id in missing_manual)
        )
    summary = {
        "stage": "T05_ANCHOR_OBJECT_ADAPTER",
        "case_count": len({row.case_key for row in examples}),
        "counts": dict(sorted(counts.items())),
        "scene_counts": dict(sorted(scene_counts.items())),
        "candidate_radius_m": radius_m,
        "max_candidates": max_candidates,
        "node_pair_candidate_limit": NODE_PAIR_CANDIDATE_LIMIT,
        "node_triple_candidate_limit": NODE_TRIPLE_CANDIDATE_LIMIT,
        "candidate_feature_uses_truth": False,
        "terminal_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "raw_id_embedding_count": 0,
        "t05_used_as_label_only": True,
        "training_example_scope_uses_label_store": True,
        "candidate_content_uses_label_store": False,
        "t11_manual_label_count": len(manual_seen),
        "user_manual_anchor_adjudication_count": counts[
            "user_manual_anchor_adjudication"
        ],
        "t11_manual_labels": (
            {
                "path": str(manual_path),
                "sha256": sha256_file(manual_path),
            }
            if manual_path is not None
            else None
        ),
        "unsupported_first_slice": (
            "T05 or T11 success whose exact RCSD Junction/Road object is not "
            "present in the truth-free candidate set retains SUCCESS status "
            "supervision but masks object selection."
        ),
    }
    return T05AnchorDataset(
        examples=tuple(sorted(examples, key=lambda row: (row.case_key, row.sample_id))),
        summary=summary,
    )


def write_joint_anchor_pretraining_store(
    bundles: Sequence[TargetACaseBundle],
    *,
    poc_data_root: Path,
    label_store_root: Path,
    t11_manual_labels_path: Path | None = None,
    output_root: Path,
    run_id: str,
    radius_m: float = 200.0,
    max_candidates: int = 64,
) -> Path:
    t05 = build_t05_anchor_pretrain_examples(
        bundles,
        label_store_root=label_store_root,
        t11_manual_labels_path=t11_manual_labels_path,
        radius_m=radius_m,
        max_candidates=max_candidates,
    )
    single_point = build_anchor_pretrain_examples(poc_data_root)
    examples = sorted(
        [*single_point, *t05.examples],
        key=lambda row: (row.case_key, row.sample_id),
    )
    root = write_anchor_pretraining_stores(
        examples,
        output_root=output_root,
        run_id=run_id,
    )
    summary_path = root / "t05_anchor_adapter_summary.json"
    summary_path.write_text(
        json.dumps(t05.summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"] = {
        "single_point_example_count": len(single_point),
        "t05_example_count": len(t05.examples),
        "t05_adapter_summary": {
            "path": str(summary_path.resolve()),
            "sha256": sha256_file(summary_path),
        },
    }
    if t11_manual_labels_path is not None:
        manual_path = normalize_runtime_path(
            t11_manual_labels_path
        ).resolve(strict=True)
        manifest["sources"]["t11_manual_labels"] = {
            "path": str(manual_path),
            "sha256": sha256_file(manual_path),
        }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def write_replayed_single_point_anchor_store(
    *,
    source_store_root: Path,
    poc_data_root: Path,
    formal_replay_summary_path: Path,
    output_root: Path,
    run_id: str,
    radius_m: float = 200.0,
    max_candidates: int = 64,
) -> Path:
    """Replace legacy single-point rows with final-scope formal replay labels."""
    if radius_m <= 0 or max_candidates < 1:
        raise ValueError("single-point anchor candidate controls are invalid")
    source_root = normalize_runtime_path(source_store_root).resolve(strict=True)
    poc_root = normalize_runtime_path(poc_data_root).resolve(strict=True)
    replay_path = normalize_runtime_path(
        formal_replay_summary_path
    ).resolve(strict=True)
    replay_payload = json.loads(replay_path.read_text(encoding="utf-8"))
    if (
        replay_payload.get("schema_version")
        != "p05-target-a-single-point-t03-t04-t05-formal-replay-v1"
    ):
        raise ValueError(f"formal replay summary schema differs: {replay_path}")
    replay_by_case = {
        str(row["case_key"]): row
        for row in replay_payload.get("results", ())
    }
    source_examples = read_anchor_pretraining_stores(source_root)
    positive_cases = {
        row.case_key
        for row in source_examples
        if row.case_key.split(":", 1)[0] in {"T03", "T04"}
    }
    if set(replay_by_case) != positive_cases:
        missing = sorted(positive_cases - set(replay_by_case))
        extra = sorted(set(replay_by_case) - positive_cases)
        raise ValueError(
            "formal replay/single-point success scope differs: "
            f"missing={missing}; extra={extra}"
        )

    replacements: list[AnchorPretrainExample] = []
    counts: Counter[str] = Counter()
    scene_counts: Counter[str] = Counter()
    for source in source_examples:
        family, case_id = source.case_key.split(":", 1)
        if family not in {"T03", "T04", "T03_Error", "T04_Error"}:
            continue
        replay = replay_by_case.get(source.case_key)
        case_root = poc_root / family / case_id
        representation = _single_point_t05_representation(
            case_root,
            target_id=source.anchor_id,
            radius_m=radius_m,
            max_candidates=max_candidates,
        )
        candidate_ids = representation["candidate_ids"]
        candidate_features = representation["candidate_features"]
        if replay is not None:
            _verify_formal_replay_input_hashes(case_root, replay)
            audit = replay.get("target_audit")
            if audit is not None and str(audit.get("status") or "") == "0":
                status = AnchorStatus.SUCCESS
                status_supervised = True
                scene = str(audit.get("scene") or "success_unknown_scene")
                accepted_id = (
                    _road_bundle_id(
                        tuple(
                            sorted(
                                _split_ids(
                                    audit.get("original_rcsdroad_ids")
                                )
                            )
                        )
                    )
                    if scene == "road_only_split"
                    else f"NODE:{_canonical_id(audit.get('base_id'))}"
                )
                acceptable = tuple(
                    index
                    for index, candidate_id in enumerate(candidate_ids)
                    if candidate_id == accepted_id
                )
                label_reason = (
                    f"formal_t03_t04_to_t05:{scene}:"
                    + (
                        "final_object_reachable"
                        if acceptable
                        else "final_object_unreachable"
                    )
                )
            elif (
                audit is not None
                and str(audit.get("scene") or "") == "no_related_rcsd"
            ):
                status = AnchorStatus.NO_EVIDENCE
                status_supervised = True
                scene = "no_related_rcsd"
                acceptable = ()
                label_reason = (
                    "formal_t03_t04_to_t05:no_related_rcsd:"
                    "positive_keep_swsd_clue_false"
                )
            else:
                status = AnchorStatus.ABSTAIN
                status_supervised = False
                scene = (
                    str((audit or {}).get("scene") or "")
                    or str(replay.get("replay_status") or "")
                    or "final_anchor_unknown"
                )
                acceptable = ()
                label_reason = (
                    "formal_t03_t04_to_t05:upstream_surface_success:"
                    "final_anchor_status_unknown"
                )
        else:
            status = AnchorStatus.ABSTAIN
            status_supervised = True
            scene = "upstream_hard_gate_failure"
            acceptable = ()
            label_reason = (
                "user_confirmed_t03_t04_upstream_failure:"
                "final_anchor_blocked_reason_unspecified"
            )
        candidate_supervised = bool(acceptable)
        preferred = acceptable[0] if acceptable else -1
        replacements.append(
            AnchorPretrainExample(
                sample_id=source.sample_id,
                case_key=source.case_key,
                anchor_id=source.anchor_id,
                fold=source.fold,
                object_features=representation["object_features"],
                candidate_ids=candidate_ids,
                candidate_features=candidate_features,
                status_label=ANCHOR_STATUS_INDEX[status],
                candidate_acceptable_indices=acceptable,
                preferred_candidate_index=preferred,
                candidate_supervised=candidate_supervised,
                sample_weight=1.0,
                input_hashes=representation["input_hashes"],
                label_reason=label_reason,
                dependency_anchor_ids=source.dependency_anchor_ids,
                status_supervised=status_supervised,
                gate_label=int(
                    status
                    in {AnchorStatus.SUCCESS, AnchorStatus.NO_EVIDENCE}
                ),
                gate_supervised=status_supervised,
                structural_member_ids=representation[
                    "structural_member_ids"
                ],
                swsd_arm_features=representation["swsd_arm_features"],
                member_arm_features=representation["member_arm_features"],
                member_local_features=representation[
                    "member_local_features"
                ],
                member_relation_edges=representation[
                    "member_relation_edges"
                ],
            )
        )
        counts["example"] += 1
        counts["status_supervised"] += int(status_supervised)
        counts["status_masked"] += int(not status_supervised)
        counts[f"status:{status.value}"] += int(status_supervised)
        counts["candidate_supervised"] += int(candidate_supervised)
        counts["success_candidate_unreachable"] += int(
            status is AnchorStatus.SUCCESS and not candidate_supervised
        )
        scene_counts[scene] += 1

    replacement_by_case = {row.case_key: row for row in replacements}
    if len(replacement_by_case) != len(replacements):
        raise ValueError("single-point anchor replacement scope is not unique")
    combined = []
    for row in source_examples:
        replaced = replacement_by_case.get(row.case_key)
        if replaced is not None:
            combined.append(replaced)
            continue
        status = list(AnchorStatus)[row.status_label]
        gate_resolved = status in {
            AnchorStatus.SUCCESS,
            AnchorStatus.NO_EVIDENCE,
        }
        combined.append(
            replace(
                row,
                gate_label=int(gate_resolved),
                gate_supervised=row.status_supervised,
            )
        )
    root = write_anchor_pretraining_stores(
        combined,
        output_root=output_root,
        run_id=run_id,
    )
    adapter_summary = {
        "stage": "T03_T04_FINAL_ANCHOR_FORMAL_REPLAY_ADAPTER",
        "source_store_root": str(source_root),
        "formal_replay_summary": {
            "path": str(replay_path),
            "sha256": sha256_file(replay_path),
        },
        "candidate_radius_m": radius_m,
        "max_candidates": max_candidates,
        "candidate_feature_uses_truth": False,
        "final_status_uses_formal_replay_label_only": True,
        "upstream_success_is_not_final_anchor_success": True,
        "gate_positive_scope": (
            "Any supervised final SUCCESS/NO_EVIDENCE anchor is resolved "
            "enough to emit a positive business state."
        ),
        "gate_negative_scope": (
            "Any supervised final ABSTAIN anchor is unresolved; this does not "
            "invent its NO_EVIDENCE, ambiguity, or Clue reason."
        ),
        "gate_masked_scope": (
            "Final status unknown, including 12 upstream-success single-point "
            "Cases without a proven final T05 anchor state."
        ),
        "counts": dict(sorted(counts.items())),
        "scene_counts": dict(sorted(scene_counts.items())),
    }
    summary_path = root / "single_point_formal_replay_adapter_summary.json"
    summary_path.write_text(
        json.dumps(adapter_summary, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    source_manifest_path = source_root / "manifest.json"
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"] = {
        "source_anchor_store_manifest": {
            "path": str(source_manifest_path),
            "sha256": sha256_file(source_manifest_path),
        },
        "formal_replay_summary": {
            "path": str(replay_path),
            "sha256": sha256_file(replay_path),
        },
        "single_point_formal_replay_adapter_summary": {
            "path": str(summary_path.resolve()),
            "sha256": sha256_file(summary_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def _single_point_t05_representation(
    case_root: Path,
    *,
    target_id: str,
    radius_m: float,
    max_candidates: int,
) -> dict[str, Any]:
    inputs = {
        "nodes.gpkg": case_root / "nodes.gpkg",
        "roads.gpkg": case_root / "roads.gpkg",
        "rcsdnode.gpkg": case_root / "rcsdnode.gpkg",
        "rcsdroad.gpkg": case_root / "rcsdroad.gpkg",
        "drivezone.gpkg": case_root / "drivezone.gpkg",
        "manifest.json": case_root / "manifest.json",
    }
    missing = sorted(name for name, path in inputs.items() if not path.is_file())
    if missing:
        raise FileNotFoundError(f"{case_root}: missing single-point inputs {missing}")
    swsd_nodes, semantic_anchor_by_node = _read_swsd_nodes(inputs["nodes.gpkg"])
    target = swsd_nodes.get(target_id)
    if target is None:
        raise ValueError(f"{case_root}: target anchor is absent: {target_id}")
    groups, group_tree, group_geometries = _read_raw_node_groups(
        inputs["rcsdnode.gpkg"]
    )
    group_by_id = {row.group_id: row for row in groups}
    (
        roads,
        road_tree,
        road_geometries,
        incident,
        raw_roads_by_node,
    ) = _read_raw_roads(inputs["rcsdroad.gpkg"])
    road_by_id = {row.road_id: row for row in roads}
    swsd_roads_by_anchor = _read_swsd_roads(
        inputs["roads.gpkg"],
        semantic_anchor_by_node,
    )
    drivezones, drivezone_tree, drivezone_geometries = _read_drivezones(
        inputs["drivezone.gpkg"]
    )
    swsd_arms = _road_arms(
        swsd_roads_by_anchor.get(target_id, ()),
        target.point,
    )
    swsd_corridor_roads = swsd_roads_by_anchor.get(target_id, ())
    empty_tree = STRtree(())
    object_features = tuple(
        _object_features(
            target,
            groups,
            group_tree,
            group_geometries,
            (),
            empty_tree,
            (),
            roads,
            road_tree,
            road_geometries,
            drivezones,
            drivezone_tree,
            drivezone_geometries,
            swsd_arms,
            radius_m=radius_m,
        )
    )
    candidate_groups = _nearby_groups(
        target.point,
        groups,
        group_tree,
        group_geometries,
        radius_m=radius_m,
        limit=max_candidates,
    )
    candidate_group_bundles = _nearby_group_bundles(candidate_groups)
    road_bundles = _nearby_road_bundles(
        target.point,
        roads,
        road_tree,
        road_geometries,
        radius_m=radius_m,
        limit=max(16, max_candidates // 2),
    )
    road_corridor_features = _road_corridor_feature_map(
        {
            road_id
            for road_bundle in road_bundles
            for road_id in road_bundle.road_ids
        },
        road_by_id,
        swsd_corridor_roads,
        target.point,
        radius_m=radius_m,
    )
    candidate_ids = tuple(
        f"NODE:{row.group_id}" for row in candidate_groups
    ) + tuple(
        f"NODE:{row.group_id}" for row in candidate_group_bundles
    ) + tuple(
        _road_bundle_id(row.road_ids) for row in road_bundles
    )
    candidate_features = tuple(
        tuple(
            _candidate_features(
                target,
                group,
                incident,
                raw_roads_by_node,
                {},
                swsd_arms,
                radius_m=radius_m,
            )
        )
        for group in (*candidate_groups, *candidate_group_bundles)
    ) + tuple(
        tuple(
            _road_bundle_features(
                target,
                bundle,
                road_by_id,
                swsd_arms,
                road_corridor_features,
                radius_m=radius_m,
            )
        )
        for bundle in road_bundles
    )
    if not candidate_features:
        candidate_ids = ("NO_RAW_RCSD_CANDIDATE",)
        candidate_features = ((0.0,) * TARGET_A_FEATURE_DIM,)
    structural = _structural_anchor_evidence(
        target,
        candidate_ids,
        candidate_features,
        group_by_id,
        raw_roads_by_node,
        road_by_id,
        swsd_arms,
        radius_m=radius_m,
    )
    return {
        "object_features": object_features,
        "candidate_ids": tuple(candidate_ids),
        "candidate_features": candidate_features,
        "structural_member_ids": structural.member_ids,
        "swsd_arm_features": structural.swsd_arm_features,
        "member_arm_features": structural.member_arm_features,
        "member_local_features": structural.member_local_features,
        "member_relation_edges": structural.member_relation_edges,
        "input_hashes": tuple(
            sorted((name, sha256_file(path)) for name, path in inputs.items())
        ),
    }


def _verify_formal_replay_input_hashes(
    case_root: Path,
    replay: Mapping[str, Any],
) -> None:
    expected = {
        str(name): str(digest)
        for name, digest in (replay.get("input_hashes") or {}).items()
    }
    if not expected:
        raise ValueError(
            f"{case_root}: formal replay input hashes are absent"
        )
    actual = {
        name: sha256_file(case_root / name)
        for name in expected
    }
    if actual != expected:
        raise ValueError(
            f"{case_root}: formal replay input hashes differ"
        )


def _selected_target_dependencies(
    bundle: TargetACaseBundle,
    target_segment_ids: set[str],
    semantic_anchor_by_node: Mapping[str, str],
) -> Mapping[str, tuple[str, ...]]:
    if not target_segment_ids:
        raise ValueError(f"T05 anchor Case lacks target Segment scope: {bundle.case_key}")
    dependencies: dict[str, set[str]] = defaultdict(set)
    found: set[str] = set()
    with fiona.open(bundle.t01_segment) as source:
        for feature in source:
            properties = dict(feature["properties"])
            segment_id = _canonical_id(
                properties.get("id")
                or properties.get("segmentid")
                or properties.get("segment_id")
            )
            if segment_id not in target_segment_ids:
                continue
            found.add(segment_id)
            referenced = {
                *_split_ids(properties.get("pair_nodes")),
                *_split_ids(properties.get("junc_nodes")),
            }
            semantic_anchors = {
                semantic_anchor_by_node[node_id]
                for node_id in referenced
                if node_id in semantic_anchor_by_node
            }
            for anchor_id in semantic_anchors:
                dependencies[anchor_id].update(semantic_anchors)
    if found != target_segment_ids:
        raise ValueError(
            f"T05 anchor target Segment scope differs: {bundle.case_key}"
        )
    return {
        anchor_id: tuple(sorted(values | {anchor_id}))
        for anchor_id, values in sorted(dependencies.items())
    }


def _read_swsd_nodes(
    path: Path,
) -> tuple[dict[str, _SwsdNode], dict[str, str]]:
    rows: dict[str, _SwsdNode] = {}
    metadata: list[tuple[str, str, int]] = []
    with fiona.open(path) as source:
        _require_epsg_3857(source, path)
        for feature in source:
            if not feature["geometry"]:
                continue
            properties = dict(feature["properties"])
            node_id = _canonical_id(properties.get("id"))
            point = shape(feature["geometry"])
            if not node_id or not isinstance(point, Point):
                continue
            row = _SwsdNode(
                node_id=node_id,
                point=point,
                kind=_integer(properties.get("kind")),
                kind_2=_integer(properties.get("kind_2")),
                grade=_integer(properties.get("grade")),
                closed_con=_integer(properties.get("closed_con")),
            )
            rows[node_id] = row
            main = _canonical_id(properties.get("mainnodeid"))
            if main:
                rows.setdefault(main, row)
            metadata.append((node_id, main or node_id, row.kind_2))
    semantic_targets = {
        main_node_id
        for _, main_node_id, kind_2 in metadata
        if kind_2 in SEMANTIC_JUNCTION_KINDS
    }
    semantic_anchor_by_node: dict[str, str] = {}
    for node_id, main_node_id, kind_2 in metadata:
        if (
            kind_2 in SEMANTIC_JUNCTION_KINDS
            or main_node_id in semantic_targets
        ):
            semantic_anchor_by_node[node_id] = main_node_id
            semantic_anchor_by_node[main_node_id] = main_node_id
    return rows, semantic_anchor_by_node


def _read_raw_node_groups(
    path: Path,
) -> tuple[list[_RawNodeGroup], STRtree, list[Point]]:
    members: dict[str, list[tuple[str, Point, int, int, int]]] = defaultdict(list)
    with fiona.open(path) as source:
        _require_epsg_3857(source, path)
        for feature in source:
            if not feature["geometry"]:
                continue
            properties = dict(feature["properties"])
            node_id = _canonical_id(properties.get("id"))
            point = shape(feature["geometry"])
            if not node_id or not isinstance(point, Point):
                continue
            main = _canonical_id(properties.get("mainnodeid"))
            group_id = main or node_id
            members[group_id].append(
                (
                    node_id,
                    point,
                    _integer(properties.get("kind")),
                    _integer(properties.get("cross_flag")),
                    _integer(properties.get("layer")),
                )
            )
    groups = [
        _RawNodeGroup(
            group_id=group_id,
            member_ids=tuple(row[0] for row in values),
            points=tuple(row[1] for row in values),
            kinds=tuple(row[2] for row in values),
            cross_flags=tuple(row[3] for row in values),
            layers=tuple(row[4] for row in values),
        )
        for group_id, values in sorted(members.items())
    ]
    geometries = [
        min(group.points, key=lambda point: (point.x, point.y))
        if len(group.points) == 1
        else Point(
            sum(point.x for point in group.points) / len(group.points),
            sum(point.y for point in group.points) / len(group.points),
        )
        for group in groups
    ]
    return groups, STRtree(geometries), geometries


def _read_raw_roads(
    path: Path,
) -> tuple[
    list[_RawRoad],
    STRtree,
    list[BaseGeometry],
    Mapping[str, Counter[str]],
    Mapping[str, tuple[_RawRoad, ...]],
]:
    roads: list[_RawRoad] = []
    rows: dict[str, Counter[str]] = defaultdict(Counter)
    roads_by_node: dict[str, list[_RawRoad]] = defaultdict(list)
    with fiona.open(path) as source:
        _require_epsg_3857(source, path)
        for feature in source:
            if not feature["geometry"]:
                continue
            properties = dict(feature["properties"])
            road_id = _canonical_id(properties.get("id"))
            start_node_id = _canonical_id(properties.get("snodeid"))
            end_node_id = _canonical_id(properties.get("enodeid"))
            if not road_id or not start_node_id or not end_node_id:
                continue
            direction = str(_integer(properties.get("direction")))
            road = _RawRoad(
                road_id=road_id,
                start_node_id=start_node_id,
                end_node_id=end_node_id,
                direction=int(direction),
                function_class=_integer(properties.get("funcclass")),
                geometry=shape(feature["geometry"]),
            )
            roads.append(road)
            for node_id in (start_node_id, end_node_id):
                rows[node_id]["total"] += 1
                rows[node_id][f"direction:{direction}"] += 1
                roads_by_node[node_id].append(road)
    roads.sort(key=lambda row: row.road_id)
    geometries = [row.geometry for row in roads]
    return (
        roads,
        STRtree(geometries),
        geometries,
        rows,
        {
            node_id: tuple(sorted(values, key=lambda row: row.road_id))
            for node_id, values in roads_by_node.items()
        },
    )


def _read_swsd_roads(
    path: Path,
    semantic_anchor_by_node: Mapping[str, str],
) -> Mapping[str, tuple[_RawRoad, ...]]:
    roads_by_anchor: dict[str, list[_RawRoad]] = defaultdict(list)
    with fiona.open(path) as source:
        _require_epsg_3857(source, path)
        for feature in source:
            if not feature["geometry"]:
                continue
            properties = dict(feature["properties"])
            road_id = _canonical_id(properties.get("id"))
            start_node_id = _canonical_id(properties.get("snodeid"))
            end_node_id = _canonical_id(properties.get("enodeid"))
            if not road_id or not start_node_id or not end_node_id:
                continue
            road = _RawRoad(
                road_id=road_id,
                start_node_id=start_node_id,
                end_node_id=end_node_id,
                direction=_integer(properties.get("direction")),
                function_class=_integer(
                    properties.get("road_kind") or properties.get("kind")
                ),
                geometry=shape(feature["geometry"]),
            )
            for node_id in (start_node_id, end_node_id):
                anchor_id = semantic_anchor_by_node.get(node_id)
                if anchor_id:
                    roads_by_anchor[anchor_id].append(road)
    return {
        anchor_id: tuple(
            sorted(
                {row.road_id: row for row in values}.values(),
                key=lambda row: row.road_id,
            )
        )
        for anchor_id, values in roads_by_anchor.items()
    }


def _read_t07_surfaces(
    path: Path,
) -> tuple[list[_T07Surface], STRtree, list[BaseGeometry]]:
    rows: list[_T07Surface] = []
    with fiona.open(path) as source:
        _require_epsg_3857(source, path)
        for feature in source:
            if not feature["geometry"]:
                continue
            properties = dict(feature["properties"])
            surface_id = _canonical_id(properties.get("id"))
            if not surface_id:
                continue
            rows.append(
                _T07Surface(
                    surface_id=surface_id,
                    geometry=shape(feature["geometry"]),
                    intersection_type=_integer(properties.get("type")),
                    level=_integer(properties.get("level")),
                    is_highway=_integer(properties.get("is_highway")),
                    node_count=len(_split_ids(properties.get("node_ids"))),
                    inner_road_count=len(_split_ids(properties.get("inner_link"))),
                )
            )
    geometries = [row.geometry for row in rows]
    return rows, STRtree(geometries), geometries


def _read_drivezones(
    path: Path,
) -> tuple[list[_DriveZone], STRtree, list[BaseGeometry]]:
    rows: list[_DriveZone] = []
    with fiona.open(path) as source:
        _require_epsg_3857(source, path)
        for feature in source:
            if feature["geometry"]:
                rows.append(_DriveZone(geometry=shape(feature["geometry"])))
    geometries = [row.geometry for row in rows]
    return rows, STRtree(geometries), geometries


def _nearby_groups(
    target: Point,
    groups: Sequence[_RawNodeGroup],
    tree: STRtree,
    geometries: Sequence[Point],
    *,
    radius_m: float,
    limit: int,
) -> list[_RawNodeGroup]:
    indices = _tree_indices(tree, target.buffer(radius_m))
    ranked = sorted(
        (
            (
                min(target.distance(point) for point in groups[index].points),
                groups[index].group_id,
                groups[index],
            )
            for index in indices
            if min(target.distance(point) for point in groups[index].points)
            <= radius_m
        ),
        key=lambda row: (row[0], row[1]),
    )
    return [row[2] for row in ranked[:limit]]


def _nearby_group_bundles(
    ranked_groups: Sequence[_RawNodeGroup],
) -> tuple[_RawNodeGroup, ...]:
    """Build bounded truth-free multi-Node semantic Junction candidates."""
    selections = (
        *combinations(ranked_groups[:NODE_PAIR_CANDIDATE_LIMIT], 2),
        *combinations(ranked_groups[:NODE_TRIPLE_CANDIDATE_LIMIT], 3),
    )
    return tuple(_merge_node_groups(values) for values in selections)


def _merge_node_groups(
    groups: Sequence[_RawNodeGroup],
) -> _RawNodeGroup:
    if len(groups) < 2:
        raise ValueError("multi-Node anchor candidate requires multiple groups")
    ordered = sorted(groups, key=lambda row: row.group_id)
    return _RawNodeGroup(
        group_id="|".join(row.group_id for row in ordered),
        member_ids=tuple(
            member_id for row in ordered for member_id in row.member_ids
        ),
        points=tuple(point for row in ordered for point in row.points),
        kinds=tuple(value for row in ordered for value in row.kinds),
        cross_flags=tuple(
            value for row in ordered for value in row.cross_flags
        ),
        layers=tuple(value for row in ordered for value in row.layers),
    )


def _nearby_road_bundles(
    target: Point,
    roads: Sequence[_RawRoad],
    tree: STRtree,
    geometries: Sequence[BaseGeometry],
    *,
    radius_m: float,
    limit: int,
) -> list[_RoadBundle]:
    indices = [
        index
        for index in _tree_indices(tree, target.buffer(radius_m))
        if roads[index].geometry.distance(target) <= radius_m
    ]
    ranked = sorted(
        indices,
        key=lambda index: (
            roads[index].geometry.distance(target),
            roads[index].road_id,
        ),
    )
    distance_by_id = {
        roads[index].road_id: float(roads[index].geometry.distance(target))
        for index in ranked
    }
    proposals: dict[tuple[str, ...], _RoadBundle] = {}

    def add(road_ids: Iterable[str], generator: str, threshold: float) -> None:
        key = tuple(sorted(set(road_ids)))
        if not key:
            return
        current = proposals.get(key)
        row = _RoadBundle(key, generator, threshold)
        if current is None or (threshold, generator) < (
            current.threshold_m,
            current.generator,
        ):
            proposals[key] = row

    for index in ranked[:16]:
        add((roads[index].road_id,), "ROAD_SINGLE", 0.0)
    for count in (2, 3, 4, 6, 8, 12, 16):
        add(
            (roads[index].road_id for index in ranked[:count]),
            "ROAD_NEAREST_PREFIX",
            float(count),
        )
    for threshold in (5.0, 10.0, 25.0, 50.0, 80.0, 120.0, radius_m):
        selected = [
            index
            for index in ranked
            if roads[index].geometry.distance(target) <= threshold
        ]
        add(
            (roads[index].road_id for index in selected),
            "ROAD_DISTANCE_SET",
            threshold,
        )
        graph = nx.Graph()
        for index in selected:
            road = roads[index]
            graph.add_edge(
                road.start_node_id,
                road.end_node_id,
                road_id=road.road_id,
            )
        for component in nx.connected_components(graph):
            road_ids = {
                str(data["road_id"])
                for _, _, data in graph.subgraph(component).edges(data=True)
            }
            add(road_ids, "ROAD_CONNECTED_COMPONENT", threshold)
    ordered = sorted(
        proposals.values(),
        key=lambda row: (
            min(distance_by_id[road_id] for road_id in row.road_ids),
            len(row.road_ids),
            row.threshold_m,
            row.road_ids,
        ),
    )
    return ordered[:limit]


def _object_features(
    target: _SwsdNode,
    groups: Sequence[_RawNodeGroup],
    group_tree: STRtree,
    group_geometries: Sequence[Point],
    surfaces: Sequence[_T07Surface],
    surface_tree: STRtree,
    surface_geometries: Sequence[BaseGeometry],
    roads: Sequence[_RawRoad],
    road_tree: STRtree,
    road_geometries: Sequence[BaseGeometry],
    drivezones: Sequence[_DriveZone],
    drivezone_tree: STRtree,
    drivezone_geometries: Sequence[BaseGeometry],
    swsd_arms: Sequence[tuple[float, int, int]],
    *,
    radius_m: float,
) -> tuple[float, ...]:
    nearby_groups = _tree_indices(group_tree, target.point.buffer(radius_m))
    group_distances = [
        min(target.point.distance(point) for point in groups[index].points)
        for index in nearby_groups
    ]
    nearby_surfaces = _tree_indices(surface_tree, target.point.buffer(radius_m))
    surface_distances = [
        target.point.distance(surfaces[index].geometry)
        for index in nearby_surfaces
    ]
    nearby_roads = _tree_indices(road_tree, target.point.buffer(radius_m))
    road_distances = [
        target.point.distance(roads[index].geometry)
        for index in nearby_roads
    ]
    nearby_drivezones = _tree_indices(
        drivezone_tree,
        target.point.buffer(radius_m),
    )
    drivezone_distances = [
        target.point.distance(drivezones[index].geometry)
        for index in nearby_drivezones
    ]
    containing_drivezone_areas = [
        float(drivezones[index].geometry.area)
        for index in nearby_drivezones
        if drivezones[index].geometry.covers(target.point)
    ]
    swsd_bearings = [row[0] for row in swsd_arms]
    values = [
        target.kind / 16.0,
        target.kind_2 / 2048.0,
        target.grade / 10.0,
        target.closed_con / 10.0,
        len(group_distances) / 64.0,
        sum(distance <= 25.0 for distance in group_distances) / 32.0,
        sum(distance <= 50.0 for distance in group_distances) / 32.0,
        sum(distance <= 80.0 for distance in group_distances) / 32.0,
        sum(distance <= 120.0 for distance in group_distances) / 32.0,
        min(group_distances, default=radius_m) / radius_m,
        len(surface_distances) / 32.0,
        sum(distance == 0.0 for distance in surface_distances) / 8.0,
        min(surface_distances, default=radius_m) / radius_m,
        len(swsd_arms) / 16.0,
        len({round(value, 1) for value in swsd_bearings}) / 16.0,
        _circular_dispersion(swsd_bearings),
        len(road_distances) / 128.0,
        sum(distance <= 10.0 for distance in road_distances) / 32.0,
        sum(distance <= 25.0 for distance in road_distances) / 32.0,
        sum(distance <= 50.0 for distance in road_distances) / 64.0,
        min(road_distances, default=radius_m) / radius_m,
        len(drivezone_distances) / 32.0,
        sum(distance == 0.0 for distance in drivezone_distances) / 8.0,
        min(drivezone_distances, default=radius_m) / radius_m,
        min(
            math.log1p(value) / 20.0
            for value in containing_drivezone_areas
        )
        if containing_drivezone_areas
        else 0.0,
    ]
    return tuple(_pad(values))


def _road_bundle_features(
    target: _SwsdNode,
    bundle: _RoadBundle,
    roads: Mapping[str, _RawRoad],
    swsd_arms: Sequence[tuple[float, int, int]],
    road_corridor_features: Mapping[str, tuple[float, ...]],
    *,
    radius_m: float,
) -> list[float]:
    selected = [roads[road_id] for road_id in bundle.road_ids]
    distances = [float(row.geometry.distance(target.point)) for row in selected]
    lengths = [float(row.geometry.length) for row in selected]
    graph = nx.Graph()
    for row in selected:
        graph.add_edge(row.start_node_id, row.end_node_id)
    direction_counts = Counter(row.direction for row in selected)
    projection = min(
        (
            row.geometry.project(target.point) / max(row.geometry.length, 0.01)
            for row in selected
        ),
        default=0.0,
    )
    values = [
        min(distances, default=radius_m) / radius_m,
        float(min(distances, default=radius_m) <= 5.0),
        float(min(distances, default=radius_m) <= 10.0),
        float(min(distances, default=radius_m) <= 25.0),
        float(min(distances, default=radius_m) <= 50.0),
        float(min(distances, default=radius_m) <= 80.0),
        float(min(distances, default=radius_m) <= 120.0),
        len(selected) / 32.0,
        sum(lengths) / 2_000.0,
        max(lengths, default=0.0) / 500.0,
        len(graph) / 32.0,
        nx.number_connected_components(graph) / 8.0 if graph else 0.0,
        sum(degree == 1 for _, degree in graph.degree()) / 16.0,
        sum(degree > 2 for _, degree in graph.degree()) / 8.0,
        direction_counts[0] / 16.0,
        direction_counts[1] / 16.0,
        direction_counts[2] / 16.0,
        direction_counts[3] / 16.0,
        max((row.function_class for row in selected), default=0) / 8.0,
        projection,
        bundle.threshold_m / max(radius_m, 1.0),
        float(bundle.generator == "ROAD_SINGLE"),
        float(bundle.generator == "ROAD_NEAREST_PREFIX"),
        float(bundle.generator == "ROAD_DISTANCE_SET"),
        float(bundle.generator == "ROAD_CONNECTED_COMPONENT"),
        0.0,
        0.0,
        1.0,
        *_arm_context_features(
            swsd_arms,
            _road_arms(selected, target.point),
        ),
        *_aggregate_road_corridor_features(
            bundle.road_ids,
            road_corridor_features,
        ),
    ]
    return _pad(values)


def _road_corridor_feature_map(
    road_ids: Iterable[str],
    roads: Mapping[str, _RawRoad],
    swsd_roads: Sequence[_RawRoad],
    target: Point,
    *,
    radius_m: float,
) -> dict[str, tuple[float, ...]]:
    """Compute each atomic RCSD Road once for one SWSD semantic anchor."""
    ordered_ids = tuple(
        sorted(
            road_id
            for road_id in set(road_ids)
            if road_id in roads
        )
    )
    if not ordered_ids:
        return {}
    if not swsd_roads:
        return {road_id: (0.0,) * 9 for road_id in ordered_ids}
    corridor = unary_union(
        tuple(road.geometry for road in swsd_roads)
    )
    local_window = target.buffer(min(radius_m, 120.0))
    local_corridor = corridor.intersection(local_window)
    buffer_values = (5.0, 10.0, 20.0, 35.0)
    corridor_buffers = {
        value: corridor.buffer(value) for value in buffer_values
    }
    local_buffers = {
        value: local_corridor.buffer(value) for value in buffer_values
    }
    result = {}
    for road_id in ordered_ids:
        geometry = roads[road_id].geometry
        local_geometry = geometry.intersection(local_window)
        length = max(float(geometry.length), 1.0e-6)
        local_length = max(float(local_geometry.length), 1.0e-6)
        values = [
            min(float(geometry.distance(corridor)) / radius_m, 4.0)
        ]
        values.extend(
            float(
                geometry.intersection(corridor_buffers[value]).length
            )
            / length
            for value in buffer_values
        )
        values.extend(
            float(
                local_geometry.intersection(local_buffers[value]).length
            )
            / local_length
            for value in buffer_values
        )
        result[road_id] = tuple(values)
    return result


def _aggregate_road_corridor_features(
    road_ids: Sequence[str],
    feature_by_road_id: Mapping[str, tuple[float, ...]],
) -> tuple[float, ...]:
    rows = [
        feature_by_road_id[road_id]
        for road_id in road_ids
        if road_id in feature_by_road_id
    ]
    if not rows:
        return (0.0,) * 9
    return (
        min(row[0] for row in rows),
        *(
            sum(row[index] for row in rows) / len(rows)
            for index in range(1, 9)
        ),
    )


def _road_corridor_features(
    selected: Sequence[_RawRoad],
    swsd_roads: Sequence[_RawRoad],
    target: Point,
    *,
    radius_m: float,
) -> tuple[float, ...]:
    """Test-facing singleton/bundle wrapper around the cached encoder."""
    road_by_id = {road.road_id: road for road in selected}
    feature_map = _road_corridor_feature_map(
        road_by_id,
        road_by_id,
        swsd_roads,
        target,
        radius_m=radius_m,
    )
    return _aggregate_road_corridor_features(
        tuple(road_by_id),
        feature_map,
    )


def _candidate_features(
    target: _SwsdNode,
    group: _RawNodeGroup,
    incident: Mapping[str, Counter[str]],
    raw_roads_by_node: Mapping[str, tuple[_RawRoad, ...]],
    surfaces: Mapping[str, _T07Surface],
    swsd_arms: Sequence[tuple[float, int, int]],
    *,
    radius_m: float,
) -> list[float]:
    closest = min(group.points, key=lambda point: target.point.distance(point))
    distance = float(target.point.distance(closest))
    surface = surfaces.get(group.group_id)
    road_counts: Counter[str] = Counter()
    for member_id in group.member_ids:
        road_counts.update(incident.get(member_id, Counter()))
    candidate_roads = {
        road.road_id: road
        for member_id in group.member_ids
        for road in raw_roads_by_node.get(member_id, ())
    }
    dx = (closest.x - target.point.x) / radius_m
    dy = (closest.y - target.point.y) / radius_m
    values = [
        distance / radius_m,
        float(distance <= 5.0),
        float(distance <= 10.0),
        float(distance <= 25.0),
        float(distance <= 50.0),
        float(distance <= 80.0),
        float(distance <= 120.0),
        len(group.member_ids) / 16.0,
        max(group.kinds, default=0) / 16.0,
        max(group.cross_flags, default=0) / 8.0,
        len(set(group.layers)) / 8.0,
        road_counts["total"] / 16.0,
        road_counts["direction:0"] / 8.0,
        road_counts["direction:1"] / 8.0,
        road_counts["direction:2"] / 8.0,
        road_counts["direction:3"] / 8.0,
        float(surface is not None),
        (surface.intersection_type / 32.0 if surface else 0.0),
        (surface.level / 8.0 if surface else 0.0),
        (surface.is_highway if surface else 0.0),
        (surface.node_count / 16.0 if surface else 0.0),
        (surface.inner_road_count / 16.0 if surface else 0.0),
        (
            target.point.distance(surface.geometry) / radius_m
            if surface is not None
            else 1.0
        ),
        dx,
        dy,
        abs(dx),
        abs(dy),
        0.0,
        *_arm_context_features(
            swsd_arms,
            _road_arms(tuple(candidate_roads.values()), closest),
        ),
    ]
    return _pad(values)


def _road_arms(
    roads: Sequence[_RawRoad],
    target: Point,
) -> tuple[tuple[float, int, int], ...]:
    arms: list[tuple[float, int, int]] = []
    seen: set[str] = set()
    for road in roads:
        if road.road_id in seen:
            continue
        seen.add(road.road_id)
        lines = (
            [road.geometry]
            if road.geometry.geom_type == "LineString"
            else []
        )
        if not lines:
            lines = [
                part
                for part in getattr(road.geometry, "geoms", ())
                if part.geom_type == "LineString"
            ]
        lines = [line for line in lines if line is not None and len(line.coords) >= 2]
        if not lines:
            continue
        line = max(lines, key=lambda value: value.length)
        coordinates = list(line.coords)
        start = Point(coordinates[0][:2])
        end = Point(coordinates[-1][:2])
        if start.distance(target) <= end.distance(target):
            origin = start
            outward = Point(coordinates[1][:2])
        else:
            origin = end
            outward = Point(coordinates[-2][:2])
        dx = outward.x - origin.x
        dy = outward.y - origin.y
        if math.hypot(dx, dy) <= 1e-6:
            continue
        arms.append(
            (
                math.atan2(dy, dx),
                road.function_class,
                road.direction,
            )
        )
    return tuple(sorted(arms, key=lambda row: (row[0], row[1], row[2])))


def _structural_anchor_evidence(
    target: _SwsdNode,
    candidate_ids: Sequence[str],
    candidate_features: Sequence[Sequence[float]],
    group_by_id: Mapping[str, _RawNodeGroup],
    raw_roads_by_node: Mapping[str, tuple[_RawRoad, ...]],
    road_by_id: Mapping[str, _RawRoad],
    swsd_arms: Sequence[tuple[float, int, int]],
    *,
    radius_m: float,
) -> AnchorStructuralEvidence:
    member_keys = ordered_anchor_candidate_members(
        candidate_ids,
        candidate_features,
    )
    member_arms: dict[
        tuple[bool, str],
        tuple[tuple[float, int, int], ...],
    ] = {}
    member_local_features: dict[
        tuple[bool, str],
        tuple[float, ...],
    ] = {}
    for is_road, member_id in member_keys:
        if is_road:
            road = road_by_id.get(member_id)
            member_arms[(is_road, member_id)] = (
                _road_arms((road,), target.point)
                if road is not None
                else ()
            )
            member_local_features[(is_road, member_id)] = (
                _road_member_local_features(
                    road,
                    target.point,
                    radius_m=radius_m,
                )
                if road is not None
                else _missing_member_local_features(is_road=True)
            )
            continue
        group = group_by_id.get(member_id)
        if group is None:
            member_arms[(is_road, member_id)] = ()
            member_local_features[(is_road, member_id)] = (
                _missing_member_local_features(is_road=False)
            )
            continue
        closest = min(
            group.points,
            key=lambda point: target.point.distance(point),
        )
        candidate_roads = {
            road.road_id: road
            for raw_node_id in group.member_ids
            for road in raw_roads_by_node.get(raw_node_id, ())
        }
        member_arms[(is_road, member_id)] = _road_arms(
            tuple(candidate_roads.values()),
            closest,
        )
        member_local_features[(is_road, member_id)] = (
            _node_member_local_features(
                closest,
                target.point,
                radius_m=radius_m,
            )
        )
    road_endpoints = {
        member_id: (
            road.start_node_id,
            road.end_node_id,
            road.direction,
            road.function_class,
        )
        for is_road, member_id in member_keys
        if is_road
        for road in (road_by_id.get(member_id),)
        if road is not None
    }
    return build_anchor_structural_evidence(
        member_keys,
        swsd_arms=swsd_arms,
        member_arms=member_arms,
        road_endpoints=road_endpoints,
        member_local_features=member_local_features,
    )


def _road_member_local_features(
    road: _RawRoad,
    target: Point,
    *,
    radius_m: float,
) -> tuple[float, ...]:
    lines = (
        [road.geometry]
        if road.geometry.geom_type == "LineString"
        else [
            part
            for part in getattr(road.geometry, "geoms", ())
            if part.geom_type == "LineString"
        ]
    )
    lines = [
        line
        for line in lines
        if line is not None and len(line.coords) >= 2
    ]
    if not lines:
        return _missing_member_local_features(is_road=True)
    line = min(lines, key=lambda value: value.distance(target))
    length = max(float(line.length), 1e-6)
    projection = float(line.project(target))
    projected = line.interpolate(projection)
    coordinates = list(line.coords)
    start = Point(coordinates[0][:2])
    end = Point(coordinates[-1][:2])
    window = min(5.0, max(0.5, length * 0.02))
    before = line.interpolate(max(0.0, projection - window))
    after = line.interpolate(min(length, projection + window))
    dx = after.x - before.x
    dy = after.y - before.y
    norm = math.hypot(dx, dy)
    tangent_sin = dy / norm if norm > 1e-6 else 0.0
    tangent_cos = dx / norm if norm > 1e-6 else 0.0
    distance = float(projected.distance(target))
    row = (
        1.0,
        min(distance / radius_m, 4.0),
        float(distance <= 5.0),
        float(distance <= 10.0),
        float(distance <= 25.0),
        float(distance <= 50.0),
        projection / length,
        min(float(start.distance(target)) / radius_m, 4.0),
        min(float(end.distance(target)) / radius_m, 4.0),
        tangent_sin,
        tangent_cos,
        min(length / 500.0, 4.0),
    )
    if len(row) != ANCHOR_MEMBER_LOCAL_FEATURE_DIM:
        raise AssertionError("anchor Road-local feature dimension drifted")
    return row


def _node_member_local_features(
    closest: Point,
    target: Point,
    *,
    radius_m: float,
) -> tuple[float, ...]:
    distance = float(closest.distance(target))
    row = (
        0.0,
        min(distance / radius_m, 4.0),
        float(distance <= 5.0),
        float(distance <= 10.0),
        float(distance <= 25.0),
        float(distance <= 50.0),
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )
    if len(row) != ANCHOR_MEMBER_LOCAL_FEATURE_DIM:
        raise AssertionError("anchor Node-local feature dimension drifted")
    return row


def _missing_member_local_features(
    *,
    is_road: bool,
) -> tuple[float, ...]:
    return (
        float(is_road),
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )


def _arm_context_features(
    swsd_arms: Sequence[tuple[float, int, int]],
    candidate_arms: Sequence[tuple[float, int, int]],
) -> list[float]:
    swsd_bearings = [row[0] for row in swsd_arms]
    candidate_bearings = [row[0] for row in candidate_arms]
    return [
        len(swsd_arms) / 16.0,
        len(candidate_arms) / 16.0,
        abs(len(swsd_arms) - len(candidate_arms)) / 16.0,
        _bearing_alignment(swsd_bearings, candidate_bearings),
        _bearing_alignment(candidate_bearings, swsd_bearings),
        float(bool(swsd_arms) and len(swsd_arms) == len(candidate_arms)),
        _circular_dispersion(swsd_bearings),
        _circular_dispersion(candidate_bearings),
    ]


def _bearing_alignment(
    source: Sequence[float],
    target: Sequence[float],
) -> float:
    if not source or not target:
        return 0.0
    return sum(
        max((math.cos(left - right) + 1.0) / 2.0 for right in target)
        for left in source
    ) / len(source)


def _circular_dispersion(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    cosine = sum(math.cos(value) for value in values) / len(values)
    sine = sum(math.sin(value) for value in values) / len(values)
    return 1.0 - min(1.0, math.hypot(cosine, sine))


def _road_bundle_id(road_ids: Sequence[str]) -> str:
    return "ROAD:" + "|".join(sorted(set(road_ids)))


def _anchor_status_for_audit(audit: Mapping[str, str]) -> AnchorStatus:
    if str(audit.get("status") or "") == "0":
        return AnchorStatus.SUCCESS
    scene = str(audit.get("scene") or "").casefold()
    reason = str(audit.get("reason") or "").casefold()
    if scene == "no_related_rcsd" or reason == "no_existing_rcsdintersection":
        return AnchorStatus.NO_EVIDENCE
    if any(token in reason for token in ("multiple", "cardinality", "ambiguous")):
        return AnchorStatus.AMBIGUOUS
    return AnchorStatus.ABSTAIN


def _anchor_status_is_supervised(
    *,
    audit: Mapping[str, str] | None,
    manual: _T11ManualAnchorLabel | None,
) -> bool:
    """A missing T05 record is unknown, while T05/T11 records are labels."""
    return audit is not None or manual is not None


def _label_reason(audit: Mapping[str, str], reachable: bool) -> str:
    reason = str(audit.get("reason") or "unspecified")
    scene = str(audit.get("scene") or "unknown")
    suffix = "object_reachable" if reachable else "object_selection_masked"
    return f"t05:{scene}:{reason}:{suffix}"


def _read_t11_manual_labels(
    path: Path | None,
) -> tuple[dict[tuple[str, str], _T11ManualAnchorLabel], Path | None]:
    if path is None:
        return {}, None
    source = normalize_runtime_path(path).resolve(strict=True)
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    supported = {
        "1v1_rcsd_junction",
        "1vn_rcsd_junction",
        "1v1_rcsd_road",
        "no_valid_relation",
    }
    result: dict[tuple[str, str], _T11ManualAnchorLabel] = {}
    for index, row in enumerate(rows, start=2):
        case_id = _canonical_id(row.get("case_id"))
        target_id = _canonical_id(row.get("target_id"))
        relation_type = str(
            row.get("manual_relation_type") or ""
        ).strip().casefold()
        selected_ids = tuple(sorted(_split_ids(row.get("selected_ids"))))
        if not case_id or not target_id or relation_type not in supported:
            raise ValueError(f"T11 manual anchor row {index} is invalid")
        if relation_type == "no_valid_relation":
            if selected_ids:
                raise ValueError(
                    f"T11 no_valid_relation row {index} selects an object"
                )
        elif not selected_ids:
            raise ValueError(
                f"T11 positive manual anchor row {index} lacks selected IDs"
            )
        label = _T11ManualAnchorLabel(
            case_key=f"T10:{case_id}",
            target_id=target_id,
            relation_type=relation_type,
            selected_ids=selected_ids,
        )
        key = (label.case_key, label.target_id)
        if key in result:
            raise ValueError(
                f"T11 manual anchor is duplicated: {label.case_key}/{target_id}"
            )
        result[key] = label
    return result, source


def _manual_anchor_status(label: _T11ManualAnchorLabel) -> AnchorStatus:
    if label.relation_type == "no_valid_relation":
        return AnchorStatus.ABSTAIN
    return AnchorStatus.SUCCESS


def _manual_candidate_id(
    label: _T11ManualAnchorLabel,
    *,
    group_id_by_node_id: Mapping[str, str] | None = None,
) -> str:
    if label.relation_type == "no_valid_relation":
        return ""
    if label.relation_type == "1v1_rcsd_road":
        return "ROAD:" + "|".join(label.selected_ids)
    lookup = group_id_by_node_id or {}
    normalized = sorted(
        {lookup.get(node_id, node_id) for node_id in label.selected_ids}
    )
    return "NODE:" + "|".join(normalized)


def _manual_label_reason(
    label: _T11ManualAnchorLabel,
    reachable: bool,
) -> str:
    if label.relation_type == "no_valid_relation":
        return "t11_manual:no_valid_relation:unresolved:abstain"
    suffix = "object_reachable" if reachable else "object_selection_masked"
    return f"t11_manual:{label.relation_type}:{suffix}"


def _read_csv_by_target(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        target_id = _canonical_id(row.get("target_id"))
        if target_id:
            result[target_id] = dict(row)
    return result


def _case_folds(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        result[str(row["case_key"])] = int(row["fold"])
    return result


def _case_target_segments(path: Path) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        if str(row.get("label_scope") or "") != "TARGET":
            continue
        result[str(row["case_key"])].add(str(row["segment_id"]))
    return result


def _tree_indices(tree: STRtree, geometry: BaseGeometry) -> list[int]:
    result = tree.query(geometry)
    if len(result) == 0:
        return []
    first = result[0]
    if isinstance(first, (int, np.integer)):
        return [int(value) for value in result]
    geometry_by_id = {id(value): index for index, value in enumerate(tree.geometries)}
    return [geometry_by_id[id(value)] for value in result]


def _split_ids(value: Any) -> set[str]:
    if value is None:
        return set()
    text = str(value).strip()
    if not text:
        return set()
    if text.startswith("["):
        try:
            payload = json.loads(text)
            return {
                canonical
                for item in payload
                if (canonical := _canonical_id(item))
            }
        except json.JSONDecodeError:
            pass
    return {
        canonical
        for part in text.replace("|", ",").split(",")
        if (canonical := _canonical_id(part))
    }


def _canonical_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.casefold() in {"null", "none", "nan", "0", "0.0"}:
        return ""
    unsigned = text[1:] if text.startswith("-") else text
    if unsigned.isdigit():
        return str(int(text))
    integer_part, separator, decimal_part = unsigned.partition(".")
    if (
        separator
        and integer_part.isdigit()
        and decimal_part
        and set(decimal_part) == {"0"}
    ):
        sign = "-" if text.startswith("-") else ""
        return str(int(sign + integer_part))
    return text


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _pad(values: Iterable[float]) -> list[float]:
    result = [float(value) for value in values]
    if len(result) > TARGET_A_FEATURE_DIM:
        raise ValueError("T05 anchor feature vector exceeds configured dimension")
    return result + [0.0] * (TARGET_A_FEATURE_DIM - len(result))


def _sample_id(case_key: str, target_id: str) -> str:
    digest = hashlib.sha256(f"{case_key}:{target_id}".encode("utf-8")).hexdigest()
    return f"anchor-t05:{digest[:20]}"


def _require_epsg_3857(source: fiona.Collection, path: Path) -> None:
    crs = source.crs
    epsg = crs.to_epsg() if hasattr(crs, "to_epsg") else None
    if epsg != 3857:
        raise ValueError(f"T05 anchor input CRS differs from EPSG:3857: {path}")


__all__ = [
    "T05AnchorDataset",
    "build_t05_anchor_pretrain_examples",
    "write_joint_anchor_pretraining_store",
]
