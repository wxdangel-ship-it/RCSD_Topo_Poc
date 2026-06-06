from __future__ import annotations

from typing import Any, Iterable

from .phase2_models import (
    SCENE_DIRECT,
    SCENE_FAILURE,
    SCENE_GROUP_EXISTING,
    SCENE_NO_RCSD,
    SCENE_ROAD_SPLIT,
    Phase2Evidence,
    SceneDecision,
)


SOURCE_T07 = "T07"
SOURCE_T02_INPUT = "T02_INPUT"
SOURCE_T03 = "T03"
SOURCE_T04 = "T04"
SOURCE_PRIORITY = {SOURCE_T07: 0, SOURCE_T02_INPUT: 1, SOURCE_T03: 2, SOURCE_T04: 3}
T04_FALLBACK_SCENES = {
    "main_evidence_with_rcsdroad_fallback",
    "no_main_evidence_with_rcsdroad_fallback_and_swsd",
}


def build_evidence_rows(
    *,
    t02_rows: Iterable[dict[str, Any]],
    t07_rows: Iterable[dict[str, Any]] = (),
    t03_rows: Iterable[dict[str, Any]],
    t04_rows: Iterable[dict[str, Any]],
) -> list[Phase2Evidence]:
    records: list[Phase2Evidence] = []
    for source_module, rows in (
        (SOURCE_T07, t07_rows),
        (SOURCE_T02_INPUT, t02_rows),
        (SOURCE_T03, t03_rows),
        (SOURCE_T04, t04_rows),
    ):
        for row in rows:
            target_id = _text(row.get("target_id"))
            if not target_id:
                continue
            case_id = _text(row.get("case_id") or row.get("representative_node_id"))
            records.append(Phase2Evidence(source_module=source_module, row=dict(row), target_id=target_id, case_id=case_id))
    return sorted(records, key=lambda item: (item.target_id, SOURCE_PRIORITY.get(item.source_module, 99), item.case_id or ""))


def classify_evidence(evidence: Phase2Evidence, *, junction_type: str) -> SceneDecision:
    row = evidence.row
    relation_state = _text(row.get("relation_state"))
    status_suggested = _text(row.get("status_suggested"))
    base_ids = tuple(_int_ids(_split_values(row.get("base_id_candidate"))))
    required_nodes = tuple(
        _int_ids(
            _split_values(row.get("required_rcsdnode_ids"))
            + _split_values(row.get("required_rcsd_node_ids"))
        )
    )
    selected_nodes = tuple(_int_ids(_split_values(row.get("selected_rcsdnode_ids"))))
    road_ids = tuple(
        _int_ids(
            _split_values(row.get("fallback_rcsdroad_ids"))
            + _split_values(row.get("support_rcsdroad_ids"))
            + _split_values(row.get("selected_rcsdroad_ids"))
            + _split_values(row.get("required_rcsdroad_ids"))
        )
    )
    case_id = evidence.case_id
    source = evidence.source_module

    if source == SOURCE_T02_INPUT:
        if relation_state == "existing_rcsdintersection_matched" and base_ids:
            return SceneDecision(
                scene=SCENE_DIRECT,
                action="direct_relation",
                reason=relation_state,
                source_module=source,
                source_case_id=case_id,
                base_id_candidates=base_ids,
                multi_base_relation=len(base_ids) > 1,
            )
        return _failure_or_no_rcsd(evidence, relation_state or "t02_no_existing_rcsdintersection")

    if source == SOURCE_T04 and base_ids and status_suggested == "0" and _t04_relation_only_success(row):
        return SceneDecision(
            scene=SCENE_DIRECT,
            action="direct_relation",
            reason=relation_state or "t04_relation_only_fallback",
            source_module=source,
            source_case_id=case_id,
            base_id_candidates=base_ids,
            multi_base_relation=len(base_ids) > 1,
        )

    if base_ids and status_suggested == "0":
        return SceneDecision(
            scene=SCENE_DIRECT,
            action="direct_relation",
            reason=relation_state or "base_id_candidate_present",
            source_module=source,
            source_case_id=case_id,
            base_id_candidates=base_ids,
            multi_base_relation=len(base_ids) > 1,
        )

    if required_nodes:
        if len(required_nodes) == 1:
            return SceneDecision(
                scene=SCENE_DIRECT,
                action="direct_relation",
                reason=relation_state or "required_rcsdnode_present",
                source_module=source,
                source_case_id=case_id,
                base_id_candidates=required_nodes,
            )
        return SceneDecision(
            scene=SCENE_GROUP_EXISTING,
            action="group_existing_rcsd_nodes",
            reason=_group_reason(source, junction_type),
            source_module=source,
            source_case_id=case_id,
            rcsdnode_ids=required_nodes,
        )

    if source == SOURCE_T04 and junction_type == "complex_divmerge" and len(selected_nodes) > 1:
        return SceneDecision(
            scene=SCENE_GROUP_EXISTING,
            action="group_existing_rcsd_nodes",
            reason="t04_complex_multi_rcsdnode",
            source_module=source,
            source_case_id=case_id,
            rcsdnode_ids=selected_nodes,
        )

    if source == SOURCE_T04 and road_ids and _t04_fallback_scene(row):
        scene_type = _t04_fallback_scene(row)
        alignment_type = _text(row.get("rcsd_alignment_type"))
        if alignment_type and alignment_type != "rcsdroad_only_alignment":
            return _failure_or_no_rcsd(evidence, f"unsupported_t04_alignment:{alignment_type}")
        if not alignment_type:
            return _failure_or_no_rcsd(evidence, "missing_t04_rcsd_alignment_type")
        return SceneDecision(
            scene=SCENE_ROAD_SPLIT,
            action="split_rcsdroad_generate_rcsdnode",
            reason=scene_type,
            source_module=source,
            source_case_id=case_id,
            rcsdroad_ids=road_ids,
            reference_mode=_reference_mode(source, row),
        )

    if relation_state == "rcsd_present_not_junction" and road_ids:
        return SceneDecision(
            scene=SCENE_ROAD_SPLIT,
            action="split_rcsdroad_generate_rcsdnode",
            reason=_road_split_reason(source, row),
            source_module=source,
            source_case_id=case_id,
            rcsdroad_ids=road_ids,
            reference_mode=_reference_mode(source, row),
        )

    if relation_state == "no_related_rcsd":
        return SceneDecision(
            scene=SCENE_NO_RCSD,
            action="failure_relation",
            reason="no_related_rcsd",
            source_module=source,
            source_case_id=case_id,
        )
    return _failure_or_no_rcsd(evidence, relation_state or "insufficient_relation_evidence")


def choose_actionable_decisions(decisions: list[SceneDecision]) -> list[SceneDecision]:
    successes = [item for item in decisions if item.scene in {SCENE_DIRECT, SCENE_GROUP_EXISTING}]
    if successes:
        return successes
    split_decisions = [item for item in decisions if item.scene == SCENE_ROAD_SPLIT]
    if split_decisions:
        return split_decisions[:1]
    if decisions:
        return [decisions[0]]
    return []


def _group_reason(source: str, junction_type: str) -> str:
    if source == SOURCE_T03:
        return "t03_a_multi_rcsdnode_semantic_core"
    if source == SOURCE_T04 and junction_type == "complex_divmerge":
        return "t04_complex_multi_rcsdnode"
    return "multi_rcsdnode_semantic_core"


def _road_split_reason(source: str, row: dict[str, Any]) -> str:
    scene_type = _t04_fallback_scene(row) if source == SOURCE_T04 else _text(row.get("scene_type"))
    if source == SOURCE_T04 and scene_type:
        return scene_type
    if source == SOURCE_T03:
        return "t03_b2_road_only_support"
    return "rcsdroad_only_alignment"


def _reference_mode(source: str, row: dict[str, Any]) -> str:
    scene_type = _t04_fallback_scene(row) if source == SOURCE_T04 else _text(row.get("scene_type"))
    if source == SOURCE_T04 and scene_type == "main_evidence_with_rcsdroad_fallback":
        return "fact"
    return "swsd"


def _t04_fallback_scene(row: dict[str, Any]) -> str | None:
    for key in ("surface_scenario_type", "scene_type"):
        value = _text(row.get(key))
        if value in T04_FALLBACK_SCENES:
            return value
    return None


def _t04_relation_only_success(row: dict[str, Any]) -> bool:
    return (
        str(row.get("surface_candidate_present", "")).strip() in {"0", "false", "False"}
        and _text(row.get("relation_state")).startswith("success_")
    )


def _failure_or_no_rcsd(evidence: Phase2Evidence, reason: str) -> SceneDecision:
    scene = SCENE_NO_RCSD if reason in {"no_related_rcsd", "no_existing_rcsdintersection"} else SCENE_FAILURE
    return SceneDecision(
        scene=scene,
        action="failure_relation",
        reason=reason,
        source_module=evidence.source_module,
        source_case_id=evidence.case_id,
    )


def _split_values(value: Any) -> list[str]:
    if value in (None, "", -1, "-1", 0, "0"):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.replace(",", "|").split("|") if part.strip() and part.strip() not in {"-1", "0"}]


def _int_ids(values: Iterable[str]) -> list[int]:
    ids: list[int] = []
    for value in values:
        try:
            ids.append(int(str(value).strip()))
        except ValueError:
            continue
    return sorted(set(ids))


def _text(value: Any) -> str:
    return str(value or "").strip()
