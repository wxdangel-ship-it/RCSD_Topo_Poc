from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


COMPLETE_ACTIONS = {
    "direct_relation",
    "group_existing_rcsd_nodes",
    "split_rcsdroad_generate_rcsdnode",
    "failure_relation",
}


@dataclass(frozen=True)
class JunctionRelationGold:
    sample_id: str
    case_id: str
    source_scope: str
    family: str
    split: str
    sample_weight: float
    business_state: str
    action: str
    supervision_scope: str
    action_supervised: bool
    object_set_exact_supervised: bool
    final_relation_supervised: bool
    relation_object_kind: str
    acceptable_object_id_sets: tuple[tuple[str, ...], ...]
    preferred_main_source_node_id: str
    final_relation_expected: bool
    final_relation_base_mode: str
    final_relation_base_id: str
    materializer_source_node_ids: tuple[str, ...]
    materializer_source_road_ids: tuple[str, ...]
    terminal_business_signature: str


def build_strong_junction_relation_gold(
    final_labels: Iterable[Mapping[str, Any]],
    *,
    split_by_sample: Mapping[str, str],
) -> tuple[JunctionRelationGold, ...]:
    rows = tuple(final_labels)
    sample_ids = tuple(str(row["sample_id"]) for row in rows)
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("junction relation Gold sample_id is duplicated")
    if set(sample_ids) != set(split_by_sample):
        raise ValueError("junction relation Gold split scope differs")
    result = tuple(
        _relation_gold(row, split=str(split_by_sample[str(row["sample_id"])]))
        for row in rows
    )
    _validate_relation_paths(rows, result)
    return result


def relation_gold_row(row: JunctionRelationGold) -> dict[str, Any]:
    value = asdict(row)
    value["acceptable_object_id_sets"] = [
        list(option) for option in row.acceptable_object_id_sets
    ]
    value["materializer_source_node_ids"] = list(
        row.materializer_source_node_ids
    )
    value["materializer_source_road_ids"] = list(
        row.materializer_source_road_ids
    )
    return value


def _relation_gold(
    source: Mapping[str, Any],
    *,
    split: str,
) -> JunctionRelationGold:
    sample_id = str(source["sample_id"])
    action = str(source.get("junctionization_action") or "")
    action_status = str(source.get("junctionization_action_gold_status") or "")
    complete_status = str(source.get("complete_junction_gold_status") or "")
    business_state = str(source.get("anchor_business_state") or "")
    main_node = _id(source.get("selected_main_rcsdnode_id"))
    original_nodes = _ids(source.get("t05_original_rcsdnode_ids"))
    grouped_nodes = _ids(source.get("t05_grouped_rcsdnode_ids"))
    original_roads = _ids(source.get("t05_original_rcsdroad_ids"))
    new_nodes = _ids(source.get("t05_new_rcsdnode_ids"))

    if action_status == "READY" and complete_status == "READY":
        supervision_scope = "COMPLETE_RELATION_PLAN"
        if action not in COMPLETE_ACTIONS:
            raise ValueError(f"unknown complete relation action: {sample_id}/{action}")
        object_kind, options = _complete_object_targets(
            action,
            main_node=main_node,
            grouped_nodes=grouped_nodes,
            original_roads=original_roads,
            sample_id=sample_id,
        )
        action_supervised = True
        object_supervised = True
        final_supervised = True
    elif action_status == "ACTION_ONLY" and complete_status == "SAFETY_ONLY":
        if action not in COMPLETE_ACTIONS:
            raise ValueError(f"unknown action-only relation: {sample_id}/{action}")
        supervision_scope = "ACTION_ONLY"
        object_kind, options = "UNSUPERVISED", ()
        action_supervised = True
        object_supervised = False
        final_supervised = False
    elif action_status == "NOT_APPLICABLE" and complete_status == "READY":
        if action:
            raise ValueError(f"not-applicable relation has action: {sample_id}")
        supervision_scope = "STATE_ONLY"
        object_kind, options = "UNSUPERVISED", ()
        action_supervised = False
        object_supervised = False
        final_supervised = False
    else:
        raise ValueError(
            "junction relation Gold status combination is unsupported: "
            f"{sample_id}/{action_status}/{complete_status}"
        )

    relation_expected = (
        supervision_scope == "COMPLETE_RELATION_PLAN"
        and action != "failure_relation"
    )
    if relation_expected and not main_node:
        raise ValueError(f"successful relation has no final base: {sample_id}")
    if action == "failure_relation" and main_node:
        raise ValueError(f"failure relation unexpectedly has base: {sample_id}")
    if action in {"direct_relation", "group_existing_rcsd_nodes"}:
        base_mode = "SOURCE_RCSD_NODE"
        base_id = main_node
    elif action == "split_rcsdroad_generate_rcsdnode":
        base_mode = (
            "REUSED_SOURCE_RCSD_NODE"
            if main_node in original_nodes
            else "GENERATED_RCSD_NODE"
            if main_node in new_nodes
            else "MATERIALIZED_RCSD_NODE"
        )
        base_id = ""
    elif action == "failure_relation":
        base_mode = "NO_RELATION"
        base_id = ""
    else:
        base_mode = "UNSUPERVISED"
        base_id = ""

    return JunctionRelationGold(
        sample_id=sample_id,
        case_id=str(source["case_id"]),
        source_scope=str(source["source_scope"]),
        family=str(source["family"]),
        split=split,
        sample_weight=float(source.get("label_weight") or 1.0),
        business_state=business_state,
        action=action,
        supervision_scope=supervision_scope,
        action_supervised=action_supervised,
        object_set_exact_supervised=object_supervised,
        final_relation_supervised=final_supervised,
        relation_object_kind=object_kind,
        acceptable_object_id_sets=options,
        preferred_main_source_node_id=(
            main_node
            if action in {"direct_relation", "group_existing_rcsd_nodes"}
            else ""
        ),
        final_relation_expected=relation_expected,
        final_relation_base_mode=base_mode,
        final_relation_base_id=base_id,
        materializer_source_node_ids=(
            grouped_nodes
            if action == "group_existing_rcsd_nodes"
            else (main_node,)
            if action == "direct_relation" and main_node
            else ()
        ),
        materializer_source_road_ids=(
            original_roads
            if action == "split_rcsdroad_generate_rcsdnode"
            else ()
        ),
        terminal_business_signature=str(
            source.get("terminal_business_signature") or ""
        ),
    )


def _complete_object_targets(
    action: str,
    *,
    main_node: str,
    grouped_nodes: tuple[str, ...],
    original_roads: tuple[str, ...],
    sample_id: str,
) -> tuple[str, tuple[tuple[str, ...], ...]]:
    if action == "direct_relation":
        if not main_node:
            raise ValueError(f"direct relation has no main Node: {sample_id}")
        return "RCSD_NODE", ((f"NODE:{main_node}",),)
    if action == "group_existing_rcsd_nodes":
        if len(grouped_nodes) < 2 or main_node not in grouped_nodes:
            raise ValueError(f"group relation member set is invalid: {sample_id}")
        return "RCSD_NODE", (
            tuple(f"NODE:{value}" for value in grouped_nodes),
        )
    if action == "split_rcsdroad_generate_rcsdnode":
        if not original_roads:
            raise ValueError(f"split relation has no source Road: {sample_id}")
        return "RCSD_ROAD", (
            tuple(f"ROAD:{value}" for value in original_roads),
        )
    if action == "failure_relation":
        return "NONE", ((),)
    raise ValueError(f"unsupported complete relation action: {sample_id}/{action}")


def _validate_relation_paths(
    sources: tuple[Mapping[str, Any], ...],
    gold: tuple[JunctionRelationGold, ...],
) -> None:
    gold_by_sample = {row.sample_id: row for row in gold}
    for source in sources:
        row = gold_by_sample[str(source["sample_id"])]
        if not row.final_relation_supervised:
            continue
        path = Path(str(source.get("t05_phase2_relation_path") or ""))
        if not path.is_file():
            raise ValueError(f"formal T05 relation output is missing: {row.sample_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features") or ()
        if len(features) != 1:
            raise ValueError(f"formal T05 relation is not unique: {row.sample_id}")
        properties = features[0].get("properties") or {}
        status = int(properties.get("status"))
        base_id = _id(properties.get("base_id"))
        if row.final_relation_expected:
            source_base = _id(source.get("selected_main_rcsdnode_id"))
            if status != 0 or base_id != source_base:
                raise ValueError(f"formal T05 success relation differs: {row.sample_id}")
        elif status != 1 or base_id not in {"", "0"}:
            raise ValueError(f"formal T05 failure relation differs: {row.sample_id}")


def _id(value: Any) -> str:
    text = str(value or "").strip()
    return text[:-2] if text.endswith(".0") else text


def _ids(values: Any) -> tuple[str, ...]:
    if values in (None, "", (), [], {}):
        return ()
    raw = values if isinstance(values, (list, tuple, set)) else str(values).replace(",", "|").split("|")
    return tuple(sorted({_id(value) for value in raw if _id(value) not in {"", "0", "-1"}}))


__all__ = [
    "JunctionRelationGold",
    "build_strong_junction_relation_gold",
    "relation_gold_row",
]
