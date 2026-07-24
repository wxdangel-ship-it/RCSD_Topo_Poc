from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


def build_run_summary(
    *,
    run_id: str,
    analysis_crs: str,
    terminal_status: str,
    core_gate_pass: bool,
    core_gates: dict[str, bool],
    skeleton: dict[str, object],
    target_coverage: dict[str, object],
    target_realization: dict[str, object],
    junctions: dict[str, object],
    evidence: dict[str, object],
    carrier_plan: dict[str, object],
    movement_split: dict[str, object],
    road_lineage_split: dict[str, object],
    swsd_topology: dict[str, object],
    swsd_junction_movements: dict[str, object],
    junction_internal_carriers: dict[str, object],
    junction_carrier_fallback_triggers: gpd.GeoDataFrame,
    geometry: dict[str, object],
    geometry_quality: dict[str, object],
    continuity_audit: gpd.GeoDataFrame,
    suppressed_local_connector_keys: set[str],
    suppressed_junction_carrier_ids: set[str],
    access_realization: gpd.GeoDataFrame,
    nodes: dict[str, object],
    topology: dict[str, object],
    lane_topo: gpd.GeoDataFrame,
    soft_review: gpd.GeoDataFrame,
    independent_quality: dict[str, object],
    qgis_project: Path,
    qgis_layer_count: int,
    qgis_readback_pass: bool,
    qgis_missing_layers: tuple[str, ...],
    elapsed_seconds: float,
    formal_gpkg: Path,
    audit_gpkg: Path,
    relations_gpkg: Path,
    comparison_gpkg: Path,
    independent_quality_json: Path,
) -> dict[str, Any]:
    fallback_segment_ids = {
        segment_id
        for value in junction_carrier_fallback_triggers.get(
            "fallback_segment_ids",
            pd.Series(dtype=str),
        ).astype(str)
        for segment_id in value.split(",")
        if segment_id
    }
    return {
        "run_id": run_id,
        "pipeline_version": "p04-segment-first-v2-target-coverage",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "terminal_status": terminal_status,
        "analysis_crs": analysis_crs,
        "core_gate_pass": core_gate_pass,
        "core_gates": core_gates,
        "skeleton": skeleton,
        "target_coverage": target_coverage,
        "target_realization": target_realization,
        "junctions": junctions,
        "evidence": evidence,
        "carrier_plan": carrier_plan,
        "movement_split": movement_split,
        "road_lineage_split": road_lineage_split,
        "swsd_topology": swsd_topology,
        "swsd_junction_movements": swsd_junction_movements,
        "junction_internal_carriers": junction_internal_carriers,
        "junction_carrier_fallback": {
            "segment_count": int(len(fallback_segment_ids)),
            "rejected_spoke_count": int(
                len(junction_carrier_fallback_triggers)
            ),
        },
        "geometry": geometry,
        "geometry_quality": geometry_quality,
        "built_road_continuity": {
            "endpoint_count": int(len(continuity_audit)),
            "hard_failure_count": int(
                continuity_audit["hard_failure"].sum()
            ),
            "suppressed_incomplete_local_connector_count": int(
                len(suppressed_local_connector_keys)
            ),
            "suppressed_orphan_junction_carrier_count": int(
                len(suppressed_junction_carrier_ids)
            ),
            "maximum_endpoint_shift_m": (
                float(continuity_audit["endpoint_shift_m"].max())
                if not continuity_audit.empty
                else 0.0
            ),
        },
        "access_realization": {
            "access_count": int(len(access_realization)),
            "realized_count": int(
                access_realization["access_realized"].sum()
            ),
            "missing_count": int(
                (~access_realization["access_realized"]).sum()
            ),
        },
        "nodes": nodes,
        "topology": topology,
        "lane_topo": lane_topo["projection_state"].value_counts().to_dict(),
        "soft_review": {
            "feature_count": int(len(soft_review)),
            "reason_counts": (
                soft_review["reason_codes"].value_counts().to_dict()
                if not soft_review.empty
                else {}
            ),
        },
        "independent_quality": independent_quality,
        "qgis": {
            "project": str(qgis_project),
            "layer_count": qgis_layer_count,
            "readback_pass": qgis_readback_pass,
            "missing_layers": list(qgis_missing_layers),
        },
        "performance": {"elapsed_seconds": elapsed_seconds},
        "outputs": {
            "formal_gpkg": str(formal_gpkg),
            "audit_gpkg": str(audit_gpkg),
            "relations_gpkg": str(relations_gpkg),
            "comparison_gpkg": str(comparison_gpkg),
            "independent_quality_json": str(independent_quality_json),
            "qgis_project": str(qgis_project),
        },
    }


def render_run_report(summary: dict[str, Any]) -> str:
    states = summary["carrier_plan"]["state_counts"]
    access = summary["access_realization"]
    geometry = summary["geometry_quality"]
    nodes = summary["nodes"]
    soft_review = summary["soft_review"]
    targets = summary["target_realization"]
    return "\n".join(
        [
            "# P04 Segment-first Road 直出报告",
            "",
            f"- Run：`{summary['run_id']}`",
            f"- 终态：`{summary['terminal_status']}`",
            f"- CRS：`{summary['analysis_crs']}`；耗时：{summary['performance']['elapsed_seconds']:.3f}s",
            "",
            "## 业务结果",
            "",
            f"- Segment：{summary['skeleton']['segment_count']}；四态：{states}",
            f"- Road/Node/RoadNextRoad：{summary['geometry']['road_count']} / {nodes['node_count']} / {summary['topology']['road_next_road_count']}",
            f"- built/retained Road：{summary['geometry']['built_road_count']} / {summary['geometry']['retained_road_count']}",
            f"- Baseline高精实现：{targets['baseline_realized_count']} / {targets['baseline_target_count']}；未实现：{targets['baseline_unresolved_count']}",
            f"- DirectBuild高精实现：{targets['direct_build_realized_count']} / {targets['direct_build_required_count']}；未实现：{targets['direct_build_unresolved_count']}",
            f"- DirectBuild例外：Patch资料不足 {targets['patch_data_insufficient_count']}；RealityChange {targets['reality_change_count']}（仍完整发布）",
            f"- Segment access：{access['realized_count']} / {access['access_count']}；缺失：{access['missing_count']}",
            f"- SWSD路口方向合同：{summary['swsd_topology']['preserved_access_count']} / {summary['swsd_topology']['access_contract_count']}；失败Segment：{summary['swsd_topology']['failed_segment_count']}",
            f"- SWSD路口Movement合同：{summary['swsd_junction_movements']['preserved_junction_count']} / {summary['swsd_junction_movements']['junction_contract_count']}；显式T04关系：{summary['swsd_junction_movements']['explicit_swsd_movement_count']}",
            f"- Patch Road：{summary['evidence']['assigned_patch_road_count']} assigned / {summary['evidence']['patch_road_count']} total；rejected：{summary['evidence']['rejected_patch_road_count']}",
            f"- LaneTopo去向：{summary['lane_topo']}",
            "",
            "## Hard gate 与几何审计",
            "",
            f"- built Road SWSD坐标直接拼接：{summary['geometry']['built_swsd_splice_count']}",
            f"- 几何hard failure：{geometry['hard_failure_count']}；几何Review：{geometry['review_required_count']}；最大最终转角：{geometry['max_final_turn_deg']:.3f}°",
            f"- built access受约束交接：{nodes['built_access_handoff_count']}；最大accepted-surface距离：{nodes['built_access_handoff_max_surface_distance_m']:.3f}m",
            f"- Soft Review：{soft_review['feature_count']}；原因：{soft_review['reason_counts']}",
            f"- 独立QA：{summary['independent_quality']['gate_pass']}；违规：{summary['independent_quality']['counts']['violation']}",
            f"- QGIS回读：{summary['qgis']['readback_pass']}；图层：{summary['qgis']['layer_count']}",
            "",
            "## 口径说明",
            "",
            "本结果是有SWSD且功能结构未变化场景下的Active POC候选，不替代T01–T12正式主链。新建Road只由hp_observed与hp_constrained_completion组成；单Segment hard failure原子回退。Soft Review随成果发布，但不能绕过hard gate。无SWSD构图、已确认现实结构变化、缺失调头/短连接主动恢复、Restriction/Laneinfo/RoadSplit正式语义不在本轮范围。",
        ]
    )


__all__ = ["build_run_summary", "render_run_report"]
