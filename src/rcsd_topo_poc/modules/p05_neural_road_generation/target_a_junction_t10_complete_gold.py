from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


COMPLETE_ACTIONS = {
    "direct_relation",
    "group_existing_rcsd_nodes",
    "split_rcsdroad_generate_rcsdnode",
    "failure_relation",
}


@dataclass(frozen=True)
class T10CompleteJunctionGold:
    target_id: str
    action: str
    status: int
    relation_object_kind: str
    complete_object_ids: tuple[str, ...]
    selected_main_rcsdnode_id: str
    original_rcsdroad_ids: tuple[str, ...]
    original_rcsdnode_ids: tuple[str, ...]
    new_rcsdnode_ids: tuple[str, ...]
    grouped_rcsdnode_ids: tuple[str, ...]
    rcsdnode_output_path: Path

    def topology_label(self) -> dict[str, Any]:
        return {
            "anchor_business_state": (
                "SUCCESS" if self.action != "failure_relation" else "QUALITY_ISSUE"
            ),
            "junctionization_action": self.action,
            "selected_main_rcsdnode_id": self.selected_main_rcsdnode_id,
            "t05_original_rcsdroad_ids": list(self.original_rcsdroad_ids),
            "t05_original_rcsdnode_ids": list(self.original_rcsdnode_ids),
            "t05_new_rcsdnode_ids": list(self.new_rcsdnode_ids),
            "t05_grouped_rcsdnode_ids": list(self.grouped_rcsdnode_ids),
            "t05_phase2_rcsdnode_path": str(self.rcsdnode_output_path),
        }


def read_t10_complete_junction_gold(
    baseline_case_root: Path,
) -> tuple[dict[str, T10CompleteJunctionGold], tuple[Path, ...]]:
    phase2_root = Path(baseline_case_root).resolve(strict=True) / "t05/t05_phase2"
    audit_path = phase2_root / "rcsd_junctionization_audit.json"
    relation_path = phase2_root / "intersection_match_all.geojson"
    rcsdnode_path = phase2_root / "rcsdnode_out.gpkg"
    for path in (audit_path, relation_path, rcsdnode_path):
        path.resolve(strict=True)

    audit_payload = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    audit_rows = audit_payload.get("rows") or ()
    if int(audit_payload.get("row_count") or 0) != len(audit_rows):
        raise ValueError("T10 T05 junctionization row_count differs")
    relation_payload = json.loads(relation_path.read_text(encoding="utf-8-sig"))
    relation_rows = relation_payload.get("features") or ()
    if len(relation_rows) != len(audit_rows):
        raise ValueError("T10 T05 relation and junctionization scope differs")

    relations: dict[str, Mapping[str, Any]] = {}
    for feature in relation_rows:
        properties = feature.get("properties") or {}
        target_id = _id(properties.get("target_id"))
        if not target_id or target_id in relations:
            raise ValueError(f"T10 T05 relation target_id is invalid: {target_id}")
        relations[target_id] = properties

    result: dict[str, T10CompleteJunctionGold] = {}
    for row in audit_rows:
        target_id = _id(row.get("target_id"))
        if not target_id or target_id in result:
            raise ValueError(f"T10 T05 audit target_id is invalid: {target_id}")
        action = str(row.get("action") or "")
        if action not in COMPLETE_ACTIONS:
            raise ValueError(f"unknown T10 T05 action: {target_id}/{action}")
        status = int(row.get("status"))
        selected_main = _id(row.get("selected_main_rcsdnode_id"))
        relation = relations.get(target_id)
        if relation is None:
            raise ValueError(f"T10 T05 final relation is missing: {target_id}")
        relation_status = int(relation.get("status"))
        relation_base = _id(relation.get("base_id"))
        if relation_status != status:
            raise ValueError(f"T10 T05 final relation status differs: {target_id}")
        if status == 0 and (not selected_main or relation_base != selected_main):
            raise ValueError(f"T10 T05 final relation base differs: {target_id}")
        if status == 1 and relation_base not in {"", "0"}:
            raise ValueError(f"T10 T05 failure relation has a base: {target_id}")

        grouped_nodes = _ids(row.get("grouped_rcsdnode_ids"))
        original_roads = _ids(row.get("original_rcsdroad_ids"))
        if action == "direct_relation":
            if status != 0 or not selected_main:
                raise ValueError(f"T10 direct relation is incomplete: {target_id}")
            object_kind = "NODE"
            object_ids = (f"NODE:{selected_main}",)
        elif action == "group_existing_rcsd_nodes":
            if status != 0 or len(grouped_nodes) < 2 or selected_main not in grouped_nodes:
                raise ValueError(f"T10 grouped relation is incomplete: {target_id}")
            object_kind = "NODE"
            object_ids = tuple(f"NODE:{value}" for value in grouped_nodes)
        elif action == "split_rcsdroad_generate_rcsdnode":
            if status != 0 or not original_roads or not selected_main:
                raise ValueError(f"T10 split relation is incomplete: {target_id}")
            object_kind = "ROAD"
            object_ids = tuple(f"ROAD:{value}" for value in original_roads)
        else:
            if status != 1 or selected_main:
                raise ValueError(f"T10 failure relation is incomplete: {target_id}")
            object_kind = "NONE"
            object_ids = ()

        result[target_id] = T10CompleteJunctionGold(
            target_id=target_id,
            action=action,
            status=status,
            relation_object_kind=object_kind,
            complete_object_ids=object_ids,
            selected_main_rcsdnode_id=selected_main,
            original_rcsdroad_ids=original_roads,
            original_rcsdnode_ids=_ids(row.get("original_rcsdnode_ids")),
            new_rcsdnode_ids=_ids(row.get("new_rcsdnode_ids")),
            grouped_rcsdnode_ids=grouped_nodes,
            rcsdnode_output_path=rcsdnode_path,
        )
    if set(result) != set(relations):
        raise ValueError("T10 T05 relation and audit target IDs differ")
    return result, (audit_path, relation_path, rcsdnode_path)


def _id(value: Any) -> str:
    text = str(value or "").strip()
    return text[:-2] if text.endswith(".0") else text


def _ids(value: Any) -> tuple[str, ...]:
    if value in (None, "", (), [], {}):
        return ()
    raw = (
        value
        if isinstance(value, (list, tuple, set))
        else str(value).replace(",", "|").split("|")
    )
    return tuple(
        sorted({_id(item) for item in raw if _id(item) not in {"", "0", "-1"}})
    )


__all__ = [
    "T10CompleteJunctionGold",
    "read_t10_complete_junction_gold",
]
