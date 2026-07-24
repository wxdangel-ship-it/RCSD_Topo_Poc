from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd

from .io import write_json


def build_milestone_report(
    *,
    summary: dict[str, Any],
    decisions: gpd.GeoDataFrame,
    old_road_comparison: gpd.GeoDataFrame,
) -> str:
    assignment = summary["assignment"]
    skeleton = summary["skeleton"]
    profile = summary["profile"]
    comparison = summary["comparison"]
    business = summary.get("business_analysis", {})
    direction = business.get("lane_direction_evidence", {})
    topo = business.get("lane_topo_readiness", {})
    coverage = business.get("swsd_evidence_coverage", {})
    contexts = business.get("decision_by_context", {})
    thresholds = business.get("threshold_neighborhoods", {})
    narrow = _examples(decisions, "width_state", "narrow_candidate", "inferred_lane_width_m")
    wide = _examples(decisions, "width_state", "wide_or_boundary_gap", "inferred_lane_width_m", ascending=False)
    ambiguous = _examples(decisions, "owner_state", "review_required", "owner_score_margin")
    mixed_roads = old_road_comparison[
        old_road_comparison["comparison_state"] == "mixed_swsd_owner"
    ].head(20)

    lines = [
        "# P04 Road 直出第一里程碑真实数据报告",
        "",
        f"- run_id：`{summary['run_id']}`",
        f"- terminal_status：`{summary['terminal_status']}`",
        f"- 分析 CRS：`{summary['analysis_crs']}`",
        "- 业务范围：SWSD semantic skeleton -> Patch evidence pool -> Lane-Boundary 宽度 -> Lane assignment。",
        "- 当前成果是 POC candidate，不是正式 RCSD/F-RCSD，也不回写 T00-T12。",
        "",
        "## 1. 输入与结构守恒",
        "",
        f"- Patch：{profile['patch_count']}；Vector 类型：{profile['object_type_count']}，非空 {profile['nonempty_object_type_count']}，空 {profile['empty_object_type_count']}。",
        f"- SWSD RoadSection：{skeleton['road_count']}；Junction：{skeleton['junction_count']}；Arm：{skeleton['arm_count']}。",
        f"- 内部 overlap Road：{skeleton['internal_overlap_road_count']}；外部开放边界 Road：{skeleton['open_boundary_road_count']}。",
        "",
        "## 2. Lane assignment 结果",
        "",
        f"- Lane 总数：{assignment['lane_count']}；decision 分布：`{assignment['decision_counts']}`。",
        f"- owner 状态：`{assignment['owner_state_counts']}`。",
        f"- accepted Lane 缺少唯一 owner：{assignment['accepted_missing_owner_count']}。",
        f"- width 状态：`{assignment['width_state_counts']}`。",
        f"- 双侧 Boundary 全采样覆盖：{assignment['bilateral_full_coverage_count']}；双侧资料不足：{assignment['bilateral_insufficient_count']}。",
        "",
        "当前阈值来自 1885118 原始分布的首轮候选，只用于 POC 分层，未固化为生产规则。",
        "`narrow_candidate`、`wide_or_boundary_gap` 与 `unstable` 均进入 review，不据此自动删除 Lane。",
        "",
        "## 3. 旧 Road/LaneGroup 差异",
        "",
        f"- 旧 Road：{comparison['old_road_count']}；同一旧 Road 出现多个 SWSD owner：{comparison['mixed_owner_old_road_count']}。",
        f"- 有 accepted Lane 的 SWSD owner：{comparison['swsd_owner_with_accepted_lane_count']}；跨多个旧 Road 分组：{comparison['swsd_owner_fragmented_across_old_roads_count']}。",
        "- 该差异只用于证明旧 LaneGroup 的分组问题，不把当前 Road 反向提升为目标真值。",
        "",
        "## 4. 典型异常明细",
        "",
        "### 4.1 窄 Lane 候选",
        "",
        _markdown_rows(narrow),
        "",
        "### 4.2 宽度过宽/疑似 Boundary 缺口",
        "",
        _markdown_rows(wide),
        "",
        "### 4.3 Owner 需要复核",
        "",
        _markdown_rows(ambiguous),
        "",
        "### 4.4 旧 Road 混合多个 SWSD owner",
        "",
        _markdown_rows(
            mixed_roads[
                ["old_road_id", "lane_count", "swsd_owner_ids", "swsd_owner_count", "comparison_state"]
            ].to_dict("records")
        ),
        "",
        "## 5. LaneTopo 一致性准备度与参数敏感区",
        "",
        f"- LaneNextLane：{direction.get('link_count')}；可检查端点方向：{direction.get('endpoint_geometry_available_count')}；Lane end -> NextLane start 为最近端点的比例：`{direction.get('end_to_start_closest_ratio')}`。",
        f"- 双端 Lane 均 accepted 的关系：{topo.get('both_lane_accepted_link_count')}；同一 SWSD owner：{topo.get('accepted_same_owner_link_count')}；跨 owner：{topo.get('accepted_cross_owner_link_count')}。",
        f"- 跨 owner 的 SWSD 节点关系：`{topo.get('cross_owner_semantic_state_counts')}`。",
        f"- 有任意 Lane owner 的 SWSD Road：{coverage.get('road_with_any_lane_owner_count')}；有 accepted Lane 的 SWSD Road：{coverage.get('road_with_accepted_lane_count')}；无 accepted Lane：{coverage.get('road_without_accepted_lane_count')}。",
        f"- 路口 Lane：{contexts.get('intersection_lane_count')}，decision：`{contexts.get('intersection_decision_counts')}`；非路口 Lane：{contexts.get('non_intersection_lane_count')}，decision：`{contexts.get('non_intersection_decision_counts')}`。",
        f"- 参数敏感邻域样本：`{thresholds}`。这些样本只进入复核，不据此自动修复。",
        "- 本里程碑只形成 LaneTopo movement projection 的输入准备度基线，不发布 movement。",
        "",
        "## 6. 当前结论与边界",
        "",
        "- 第一里程碑核心计算只有在 `core_gate_pass=true` 时才算完成；QGIS 工程和覆盖率门禁完成前，terminal status 保持 pending。",
        "- 未确认枚举、RoadSplit 和 FlowNum 精确语义未进入强规则。",
        "- 当前仅有一个带 Patch Vector 的 Case，参数不能直接升格为生产阈值。",
        "- 下一里程碑只能在本轮 owner、width 和差异样例经检查后进入 Road 几何实例化。",
        "",
    ]
    return "\n".join(lines)


def finalize_run(run_root: str | Path) -> dict[str, Any]:
    root = Path(run_root).expanduser().resolve()
    summary_path = root / "p04_run_summary.json"
    report_path = root / "p04_milestone1_report.md"
    qgis_qa_path = root / "p04_qgis_project_qa.json"
    overlay_path = root / "p04_qgis_overlay_gate.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    qgis_qa = json.loads(qgis_qa_path.read_text(encoding="utf-8")) if qgis_qa_path.is_file() else None
    overlay = json.loads(overlay_path.read_text(encoding="utf-8")) if overlay_path.is_file() else None
    qgis_pass = bool(qgis_qa and qgis_qa.get("status") == "passed")
    overlay_pass = bool(overlay and overlay.get("gate_pass"))
    final_pass = bool(summary.get("core_gate_pass")) and qgis_pass and overlay_pass
    summary["qgis_project_qa"] = qgis_qa
    summary["qgis_overlay_gate"] = overlay
    summary["qgis_gate_pass"] = qgis_pass
    summary["overlay_gate_pass"] = overlay_pass
    summary["terminal_status"] = "passed" if final_pass else "failed"
    summary["milestone_gate_pass"] = final_pass
    write_json(summary_path, summary)
    report_text = report_path.read_text(encoding="utf-8")
    report_text = report_text.replace(
        "- terminal_status：`core_passed_qgis_pending`",
        f"- terminal_status：`{summary['terminal_status']}`",
        1,
    )
    report_text = report_text.split("\n## 7. QGIS 与空间覆盖终验", maxsplit=1)[0].rstrip() + "\n"
    report_path.write_text(report_text, encoding="utf-8")
    with report_path.open("a", encoding="utf-8") as handle:
        handle.write("\n## 7. QGIS 与空间覆盖终验\n\n")
        handle.write(f"- QGIS project QA：`{'passed' if qgis_pass else 'failed'}`。\n")
        handle.write(f"- DriveZone overlay gate：`{'passed' if overlay_pass else 'failed'}`。\n")
        if overlay:
            handle.write(f"- overall in-road ratio：`{overlay.get('overall', {}).get('in_road_ratio')}`。\n")
            handle.write(f"- fail reasons：`{overlay.get('fail_reasons', [])}`。\n")
        handle.write(f"- 第一里程碑终态：`{summary['terminal_status']}`。\n")
    return summary


def _examples(
    frame: gpd.GeoDataFrame,
    field: str,
    value: str,
    sort_field: str,
    *,
    ascending: bool = True,
) -> list[dict[str, Any]]:
    selected = frame[frame[field] == value].copy()
    if sort_field in selected.columns:
        selected = selected.sort_values(sort_field, ascending=ascending, na_position="last")
    columns = [
        column
        for column in (
            "lane_id",
            "source_patch_ids",
            "swsd_unit_id",
            "decision",
            "reason_codes",
            "owner_score_margin",
            "inferred_lane_width_m",
            "width_sample_coverage",
            "left_boundary_id",
            "right_boundary_id",
        )
        if column in selected.columns
    ]
    return selected[columns].head(20).to_dict("records")


def _markdown_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "无。"
    columns = list(rows[0])
    output = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in rows:
        output.append(
            "| "
            + " | ".join(str(row.get(column, "")).replace("|", "\\|") for column in columns)
            + " |"
        )
    return "\n".join(output)


__all__ = ["build_milestone_report", "finalize_run"]
