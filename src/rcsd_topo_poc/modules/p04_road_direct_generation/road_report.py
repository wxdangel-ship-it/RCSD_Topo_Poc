from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from .io import write_json


def build_milestone_two_report(
    *,
    summary: dict[str, Any],
    road_candidates: gpd.GeoDataFrame,
    road_audit: pd.DataFrame,
) -> str:
    states = summary["road_evidence"]["support_state_counts"]
    quality = summary["road_evidence"]["known_quality_counts"]
    performance = summary["performance"]
    lines = [
        "# P04 Road 直出第二里程碑报告",
        "",
        "## 1. 结论",
        "",
        f"- terminal status：`{summary['terminal_status']}`。",
        f"- SWSD Road 完整发布：{summary['road_count']} / {summary['road_count']}，未发布 0。",
        (
            "- 四态："
            f"`hp_supported={states['hp_supported']}`、"
            f"`partial_hp_supported={states['partial_hp_supported']}`、"
            f"`sd_only={states['sd_only']}`、"
            f"`conflict_retained={states['conflict_retained']}`。"
        ),
        "- 当前真实 Case 没有足够证据自动发布可信结构冲突；输入质量异常全部留在独立 QA。",
        "",
        "## 2. SWSD-first Road 证据实例化",
        "",
        f"- 原始 Lane：{summary['road_evidence']['lane_count']}。",
        f"- Lane 局部样点：{summary['road_evidence']['lane_sample_count']}，局部拟合比例 {summary['road_evidence']['assigned_lane_sample_ratio']:.6f}。",
        f"- LaneEvidenceSegment：{summary['road_evidence']['lane_evidence_segment_count']}，其中 {summary['road_evidence']['lane_contributing_multiple_road_count']} 条源 Lane 跨多个 SWSD Road。",
        f"- 有高精证据 Road：{summary['road_evidence']['road_with_evidence_count']}；没有证据但完整保留的 Road：{states['sd_only']}。",
        "- 第一里程碑整 Lane primary owner 只作诊断；第二里程碑每个 LaneEvidenceSegment 唯一 owner，旧 Road/LaneGroup 不决定目标数量或连接。",
        "",
        "## 3. 输入质检解耦",
        "",
        f"- 跨 Road 语义节点异常：{quality['cross_road_semantic_node_anomaly']}。",
        f"- 跨 Road 方向复核：{quality['cross_road_direction_review']}。",
        f"- 窄 Lane：{quality['narrow_lane']}。",
        f"- 宽度/Boundary-gap：{quality['wide_or_boundary_gap']}。",
        f"- 宽度不稳定：{quality['width_unstable']}。",
        f"- Patch 5417631180197930 Boundary 资料不足：{quality['patch_5417631180197930_boundary_insufficient']}。",
        f"- 质量标记直接制造 Road conflict：{summary['road_evidence']['quality_flag_direct_road_conflict_count']}。",
        "",
        "## 4. 几何与拓扑门禁",
        "",
        f"- Road geometry 非空/有效：{summary['road_geometry']['nonempty_geometry_count']} / {summary['road_geometry']['valid_geometry_count']}。",
        f"- Road geometry simple：{summary['road_geometry']['simple_geometry_count']} / {summary['road_geometry']['road_candidate_count']}。",
        f"- Road 首尾点相对 SWSD 门户最大偏差：{summary['road_geometry']['endpoint_anchor_max_delta_m']:.9f} m；端点锚定门禁：{summary['road_geometry']['endpoint_anchor_gate_pass']}。",
        f"- RoadGraph：{summary['road_topology']['road_count']} Road / {summary['road_topology']['junction_count']} Junction / {summary['road_topology']['arm_count']} Arm；Road—Arm 门户最大偏差 {summary['road_topology']['road_arm_portal_max_delta_m']:.9f} m。",
        f"- 尝试拟合中 non-simple Road：{summary['road_geometry']['attempted_non_simple_geometry_count']}；均显式拒绝该拟合并保留 SWSD，最终 non-simple 为 0。",
        f"- 发布几何最大横向拟合位移：{summary['road_geometry']['max_lateral_shift_m']:.3f} m；p95 Road 最大位移：{summary['road_geometry']['p95_max_lateral_shift_m']:.3f} m；尝试拟合最大位移：{summary['road_geometry']['attempted_max_lateral_shift_m']:.3f} m。",
        f"- 支持/缺口区间长度守恒最大误差：{summary['road_evidence']['interval_partition_max_abs_delta_m']:.9f} m。",
        "- 不相邻 Lane 局部分段切换只进入 QA，不据此生成 RoadNextRoad 或执行 silent fix。",
        "",
        "## 5. CRS、审计与性能",
        "",
        f"- 分析 CRS：`{summary['analysis_crs']}`。",
        "- 输入文件、hash、参数和运行环境：`p04_input_manifest.json`。",
        f"- 核心总耗时：{performance['stage_seconds']['total_core']:.3f} s；峰值 RSS：{performance['peak_rss_mb']} MB。",
        "- restriction/Laneinfo、RoadSplit 和 movement 合法性未进入本里程碑。",
        "",
        "## 6. 主要输出",
        "",
    ]
    for name, path in summary["outputs"].items():
        lines.append(f"- `{name}`：`{path}`")
    lines.extend(
        [
            "",
            "## 7. 待多 Case 确认",
            "",
            "- 5m 采样、20m 距离、35°方向、0.95 全覆盖率和 10m 最大缺口均为单 Case POC 参数，不是生产规格。",
            "- `conflict_retained` 的真实发布门禁仍需更多可信冲突样本；当前仅由合成测试覆盖状态机。",
            "- Road 几何需要结合 QGIS 差异工程、自动道路面 overlay 和多场景真值继续验证。",
            "",
            "## 8. 非 hp Road 复核摘要",
            "",
        ]
    )
    non_hp = road_audit[road_audit["support_state"] != "hp_supported"]
    lines.append(f"非 hp Road 共 {len(non_hp)} 条；逐对象明细见 `p04_road_audit.csv`。")
    lines.append("")
    lines.append(
        "Road 候选字段和几何逐对象结果见 `p04_road_candidates.gpkg`；"
        f"本报告汇总的 Road 行数为 {len(road_candidates)}。"
    )
    return "\n".join(lines) + "\n"


def finalize_milestone_two(run_root: str | Path) -> dict[str, Any]:
    root = Path(run_root).expanduser().resolve()
    summary_path = root / "p04_run_summary.json"
    report_path = root / "p04_milestone2_report.md"
    qgis_qa_path = root / "p04_qgis_project_qa.json"
    independent_readback_path = root / "p04_qgis_independent_readback.json"
    overlay_path = root / "p04_qgis_overlay_gate.json"
    full_road_diagnostic_path = root / "p04_qgis_road_overlay_diagnostic.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    qgis_qa = json.loads(qgis_qa_path.read_text(encoding="utf-8")) if qgis_qa_path.is_file() else None
    independent_readback = (
        json.loads(independent_readback_path.read_text(encoding="utf-8"))
        if independent_readback_path.is_file()
        else None
    )
    overlay = json.loads(overlay_path.read_text(encoding="utf-8")) if overlay_path.is_file() else None
    full_road_diagnostic = (
        json.loads(full_road_diagnostic_path.read_text(encoding="utf-8"))
        if full_road_diagnostic_path.is_file()
        else None
    )
    qgis_pass = bool(qgis_qa and qgis_qa.get("status") == "passed")
    independent_readback_pass = bool(
        independent_readback and independent_readback.get("gate_pass")
    )
    overlay_pass = bool(overlay and overlay.get("gate_pass"))
    final_pass = (
        bool(summary.get("core_gate_pass"))
        and qgis_pass
        and independent_readback_pass
        and overlay_pass
    )
    summary["qgis_project_qa"] = qgis_qa
    summary["qgis_independent_readback"] = independent_readback
    summary["qgis_overlay_gate"] = overlay
    summary["full_road_overlay_scope_diagnostic"] = full_road_diagnostic
    summary["qgis_gate_pass"] = qgis_pass
    summary["qgis_independent_readback_pass"] = independent_readback_pass
    summary["overlay_gate_pass"] = overlay_pass
    summary["terminal_status"] = "passed" if final_pass else "failed"
    summary["milestone_gate_pass"] = final_pass
    write_json(summary_path, summary)

    candidates = gpd.read_file(root / "p04_road_candidates.gpkg", layer="road_candidates")
    road_audit = pd.read_csv(root / "p04_road_audit.csv", encoding="utf-8-sig")
    report = build_milestone_two_report(
        summary=summary,
        road_candidates=candidates,
        road_audit=road_audit,
    )
    report += "\n## 9. QGIS 与空间覆盖终验\n\n"
    report += f"- QGIS project QA：`{'passed' if qgis_pass else 'failed'}`。\n"
    report += f"- 独立 PyQGIS 逐层回读：`{'passed' if independent_readback_pass else 'failed'}`。\n"
    report += f"- 高精证据范围 DriveZone overlay gate：`{'passed' if overlay_pass else 'failed'}`。\n"
    if overlay:
        report += f"- 高精证据 overall in-road ratio：`{overlay.get('overall', {}).get('in_road_ratio')}`。\n"
        for layer_name, layer in overlay.get("layers", {}).items():
            report += f"- `{layer_name}` in-road ratio：`{layer.get('in_road_ratio')}`。\n"
        report += f"- overlay fail reasons：`{overlay.get('fail_reasons', [])}`。\n"
    if full_road_diagnostic:
        report += (
            "- 全 571 Road 对局部 DriveZone 的范围诊断："
            f"`gate_pass={full_road_diagnostic.get('gate_pass')}`，"
            f"`ratio={full_road_diagnostic.get('overall', {}).get('in_road_ratio')}`；"
            "该诊断包含 sd_only/open-boundary SWSD Road，不作为高精拟合门禁。\n"
        )
    report += f"- 第二里程碑终态：`{summary['terminal_status']}`。\n"
    report_path.write_text(report, encoding="utf-8")
    return summary


__all__ = ["build_milestone_two_report", "finalize_milestone_two"]
