from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .models import T12ContractError


@dataclass(frozen=True)
class QualityIssueDefinition:
    issue_code: str
    object_type: str
    issue_group: str
    issue_type: str
    issue_name_zh: str
    issue_description_zh: str
    repair_domain: str
    repair_hint_zh: str


QUALITY_ISSUES = {
    item.issue_type: item
    for item in (
        QualityIssueDefinition(
            issue_code="S01",
            object_type="segment",
            issue_group="segment_passability",
            issue_type="segment_required_direction_unavailable",
            issue_name_zh="路段必需方向不可通行",
            issue_description_zh=(
                "SWSD 要求的通行方向在原始 1V1 FRCSD 中缺少方向合法的等价载体。"
            ),
            repair_domain="frcsd_segment_direction",
            repair_hint_zh="复核并修正当前 Segment 锚点间 RCSD Road 的方向或缺失载体。",
        ),
        QualityIssueDefinition(
            issue_code="S02",
            object_type="segment",
            issue_group="segment_passability",
            issue_type="segment_required_connection_missing",
            issue_name_zh="路段必需连接缺失",
            issue_description_zh=(
                "SWSD 要求的局部连接在原始 1V1 FRCSD 中缺少物理连续的等价载体。"
            ),
            repair_domain="frcsd_segment_connectivity",
            repair_hint_zh="复核锚点间 RCSD Road/Node 连接关系并补齐缺失的物理连接。",
        ),
        QualityIssueDefinition(
            issue_code="S03",
            object_type="segment",
            issue_group="segment_passability",
            issue_type="segment_unexpected_reverse_passability",
            issue_name_zh="路段存在非预期反向通行",
            issue_description_zh=(
                "SWSD 为单向 Segment，但原始 1V1 FRCSD 在明确锚点区间内存在归属于当前 Segment 的反向载体。"
            ),
            repair_domain="frcsd_segment_direction",
            repair_hint_zh="复核当前 Segment 区间内 RCSD Road 的方向和归属，移除非预期反向能力。",
        ),
        QualityIssueDefinition(
            issue_code="J01",
            object_type="junction",
            issue_group="junction_topology",
            issue_type="junction_required_topology_missing",
            issue_name_zh="路口必需拓扑缺失",
            issue_description_zh=(
                "SWSD 路口所需的臂悬或连接关系在原始 1V1 FRCSD 局部拓扑中缺失。"
            ),
            repair_domain="frcsd_junction_topology",
            repair_hint_zh="复核路口支撑 Road、terminal endpoint 与缺失的路口连接关系。",
        ),
        QualityIssueDefinition(
            issue_code="J02",
            object_type="junction",
            issue_group="junction_topology",
            issue_type="junction_unmatched_support_topology",
            issue_name_zh="路口存在未匹配支撑拓扑",
            issue_description_zh=(
                "SWSD 路口目标只解释了原始 1V1 FRCSD 的部分支撑分量，仍存在未匹配的有效支撑拓扑。"
            ),
            repair_domain="frcsd_junction_support",
            repair_hint_zh="复核未匹配支撑分量及其现实变化、采集精度或拓扑归属原因。",
        ),
        QualityIssueDefinition(
            issue_code="J03",
            object_type="junction",
            issue_group="junction_anchor_relation",
            issue_type="junction_anchor_one_to_many",
            issue_name_zh="单路口锚定到多个路口面",
            issue_description_zh=(
                "同一个多节点 SWSD 语义路口在 T07 Step2 命中多个 RCSDIntersection。"
            ),
            repair_domain="rcsd_intersection_partition",
            repair_hint_zh="复核 RCSDIntersection 分面边界，确保一个语义路口只对应一个可消费路口面。",
        ),
        QualityIssueDefinition(
            issue_code="J04",
            object_type="junction",
            issue_group="junction_anchor_relation",
            issue_type="junction_anchor_many_to_one",
            issue_name_zh="多个路口锚定到同一路口面",
            issue_description_zh=(
                "多个参与 T07 Step2 的 SWSD 语义路口命中同一个 RCSDIntersection。"
            ),
            repair_domain="rcsd_intersection_partition",
            repair_hint_zh="复核 RCSDIntersection 合并范围，拆分错误覆盖多个语义路口的路口面。",
        ),
    )
}


LEGACY_ISSUE_TYPE_MAP = {
    "directed_carrier_missing": "segment_required_direction_unavailable",
    "required_local_connectivity_missing": "segment_required_connection_missing",
    "unexpected_reverse_carrier": "segment_unexpected_reverse_passability",
    "junction_required_topology_missing": "junction_required_topology_missing",
    "junction_reality_or_precision_gap": "junction_unmatched_support_topology",
}


RESULT_STATUS_BY_REVIEW_STATUS = {
    "confirmed_frcsd_quality_issue": "confirmed",
    "excluded_false_positive": "excluded",
    "manual_review_required": "manual_review",
}


def normalize_issue_type(value: Any) -> str:
    issue_type = str(value or "").strip()
    if not issue_type:
        return ""
    if issue_type == "junction_relation_cardinality_mismatch":
        raise T12ContractError(
            "junction_relation_cardinality_mismatch must be regenerated from "
            "T07 Step2 fail1/fail2"
        )
    if issue_type in QUALITY_ISSUES:
        return issue_type
    mapped = LEGACY_ISSUE_TYPE_MAP.get(issue_type)
    if mapped:
        return mapped
    raise T12ContractError(f"unknown T12 issue_type: {issue_type}")


def enrich_quality_result(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    review_status = str(result.get("review_status") or "")
    expected_status = RESULT_STATUS_BY_REVIEW_STATUS.get(review_status)
    if expected_status is None:
        raise T12ContractError(f"unknown T12 review_status: {review_status}")
    existing_status = str(result.get("result_status") or "")
    if existing_status and existing_status != expected_status:
        raise T12ContractError(
            "result_status conflicts with review_status: "
            f"{existing_status} != {expected_status}"
        )
    result["result_status"] = expected_status
    raw_issue_type = str(result.get("issue_type") or "").strip()
    legacy_issue_type = str(result.get("legacy_issue_type") or "").strip()
    if not legacy_issue_type:
        suggested = str(result.get("suggested_issue_type") or "").strip()
        if suggested in LEGACY_ISSUE_TYPE_MAP:
            legacy_issue_type = suggested
        elif raw_issue_type in LEGACY_ISSUE_TYPE_MAP:
            legacy_issue_type = raw_issue_type

    root_cause_type = str(
        result.get("root_cause_type")
        or result.get("source_failure_type")
        or result.get("detection_rule")
        or result.get("decision_rule")
        or legacy_issue_type
        or raw_issue_type
        or ""
    )
    result["root_cause_type"] = root_cause_type
    result.setdefault("source_failure_type", "")
    result["legacy_issue_type"] = legacy_issue_type
    if expected_status == "confirmed":
        issue_type = normalize_issue_type(raw_issue_type)
        if not issue_type:
            raise T12ContractError("confirmed T12 result has empty issue_type")
        definition = QUALITY_ISSUES[issue_type]
        object_type = str(result.get("object_type") or "")
        if object_type != definition.object_type:
            raise T12ContractError(
                f"issue_type {issue_type} is incompatible with object_type {object_type}"
            )
        result.update(
            issue_group=definition.issue_group,
            issue_code=definition.issue_code,
            issue_type=definition.issue_type,
            issue_name_zh=definition.issue_name_zh,
            issue_description_zh=definition.issue_description_zh,
            repair_domain=definition.repair_domain,
            repair_hint_zh=definition.repair_hint_zh,
        )
        if not root_cause_type:
            raise T12ContractError(
                f"confirmed T12 result has empty root_cause_type: {issue_type}"
            )
    else:
        if raw_issue_type:
            raise T12ContractError(
                "issue_type is only allowed for confirmed T12 results"
            )
        result.update(
            issue_group="",
            issue_code="",
            issue_type="",
            issue_name_zh="",
            issue_description_zh="",
            repair_domain="",
            repair_hint_zh="",
        )
    if bool(result.get("silent_fix")):
        raise T12ContractError("T12 result cannot declare silent_fix=true")
    result["silent_fix"] = False
    return result


def enrich_quality_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [enrich_quality_result(row) for row in rows]
