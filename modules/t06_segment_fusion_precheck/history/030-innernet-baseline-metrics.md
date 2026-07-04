# 内网全量 RCSD 指标基线

## 记录范围

本页记录内网全量 RCSD 指标基线，供项目汇报、周报和后续 summary 级基线比对引用。

当前登记两个版本：

1. 无人工标注基线指标：内网初次执行结果，未消费人工标注。
2. 人工标注1基线指标：第一次人工标注后的内网执行结果。

两版结果均来自内网全量 Step2 summary、Step3 summary 与未替换 RCSD 反向归因 summary。汇报未替换 RCSD 根因构成时，优先使用 `final_attribution_class` / `by_final_attribution_class`。历史粗口径 `attribution_class` 仅保留为实现对照，不作为项目汇报主口径。

原三大类汇总不再作为项目汇报主口径；当前采用 5+1 分类展示：5 类为实际根因构成，第 6 类为人工审计兜底类。当前两版内网基线中第 6 类均为 0。

## 基线元信息

| 指标 | 值 |
|---|---|
| run_id | `t06_innernet_precheck` |
| 内网运行根目录 | `/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t10_innernet_full_pipeline/t10_innernet_full_no_t08_20260627_215704/t06_segment_fusion_precheck/t06_innernet_precheck` |
| CRS | `EPSG:3857` |
| RCSD 反向归因 buffer | `50.0m` |
| 当前汇报归因口径 | `final_attribution_class` |
| 当前汇报分类 | 5+1 分类，当前实际 5 类有结果 |
| 反向归因 summary | `step3_segment_replacement/t06_step3_unreplaced_rcsd_attribution_summary.json` |

## 两版核心替换结果

| 指标 | 无人工标注 | 人工标注1 | 变化 |
|---|---:|---:|---:|
| total_rcsd_road_count | 134,428 | 134,455 | +27 |
| total_rcsd_road_length_m | 12,922,164.809 | 12,922,164.809 | 0.000 |
| replaced_rcsd_road_count | 102,077 | 103,006 | +929 |
| replaced_rcsd_road_length_m | 9,663,991.210 | 9,904,579.906 | +240,588.696 |
| replaced_rcsd_road_rate_by_count | 75.9343% | 76.6100% | +0.6757 pct |
| replaced_rcsd_road_rate_by_length | 74.7862% | 76.6480% | +1.8618 pct |
| unreplaced_rcsd_road_count | 32,351 | 31,449 | -902 |
| unreplaced_rcsd_road_length_m | 3,258,173.599 | 3,017,584.903 | -240,588.696 |

## 替换漏斗对比

| 指标 | 无人工标注 | 人工标注1 | 变化 |
|---|---:|---:|---:|
| input_fusion_unit_count | 24,646 | 24,831 | +185 |
| relation_success_count | 22,126 | 22,339 | +213 |
| relation_failure_count | 2,520 | 2,492 | -28 |
| rcsd_candidate_count | 18,305 | 18,516 | +211 |
| replaceable_count | 18,305 | 18,516 | +211 |
| rejected_count | 6,341 | 6,315 | -26 |
| replacement_plan_count | 20,152 | 20,372 | +220 |
| replacement_plan_ready_count | 18,672 | 18,866 | +194 |
| replaceable_rcsd_road_unique_count | 98,302 | 98,989 | +687 |
| replaceable_rcsd_road_unique_length_m | 9,554,518.993 | 9,783,421.657 | +228,902.664 |

## Segment 关系结果

| 指标 | 无人工标注 | 人工标注1 | 变化 |
|---|---:|---:|---:|
| swsd_segment_count | 43,430 | 43,430 | 0 |
| evidence_segment_count | 25,831 | 25,831 | 0 |
| relation_scope_segment_count | 22,127 | 22,341 | +214 |
| step2_reported_relation_success_count | 22,126 | 22,339 | +213 |
| step2_reported_relation_failure_count | 2,520 | 2,492 | -28 |
| replaceable_scope_segment_count | 19,979 | 20,189 | +210 |
| segment_relation_count | 43,430 | 43,430 | 0 |
| segment_relation_replaced_count | 17,883 | 18,076 | +193 |
| segment_relation_retained_swsd_count | 25,471 | 25,277 | -194 |
| segment_relation_failed_count | 9 | 9 | 0 |

## 未替换 RCSD 5+1 分类定义

| 分类 | 字段值 | 中文指标名 | 业务含义 |
|---|---|---|---|
| 1 | `1_outside_swsd_segment_scope` | RCSD超出SWSD Segment范围 | RCSD 相比 SWSD 多出的路网表达，可能来自现实道路变化、SWSD 路网精简或覆盖范围差异。具有连通性的 RCSD 可牵引现实变更确认；单独端点挂接且不具备连通性的 RCSD 可通过策略补齐，但收益通常有限。 |
| 2 | `2_swsd_scope_no_t06_evidence` | SWSD范围内缺少有效替换证据 | RCSD 位于 SWSD Segment 范围内，但 Segment 没有形成可支撑整体替换的有效道路面或路网证据。常见表现是 Segment 只有局部 RCSD 支撑，整体构成不完整。 |
| 3 | `3_evidence_scope_relation_incomplete` | 有替换证据但路口关联不完整 | Segment 已有替换证据，但关键路口、端点或通行关系未正确关联，导致替换前提不完整。原因可能来自 SWSD 数据质量、Patch 质量或算法策略。 |
| 4 | `4_relation_scope_not_replaceable` | 路口关联完整但RCSD不可替换 | Segment 的关键路口和关系前提已满足，但 RCSD 在连通性、方向性、路径覆盖或拓扑质量上不满足替换要求。常见表现是中间存在不连通断点或承载路径不完整。 |
| 5 | `5_replaceable_scope_unreplaced` | 可替换范围内RCSD未落地 | RCSD 位于已具备替换条件的范围内，但最终融合结果没有采用该 RCSD。当前仍需继续追查，可能与候选选择、局部覆盖、冲突裁剪、保留原 SWSD 或替换落地策略有关。 |
| 6 | `6_unattributed_manual_audit` | 未归因/需人工审计 | 当前规则无法稳定解释，需要人工结合地图、证据、关系和最终结果继续审计。当前两版内网基线中该类为 0。 |

说明：字段值保留历史命名，中文指标名与业务含义用于项目汇报。反向审计归因只能做到近似分析，不能作为绝对根因；比例可用于判断主要结构和优化方向。

## 未替换 RCSD 根因构成

| 分类 | 无人工标注 count | 无人工标注 length_m | 无人工标注未替换长度占比 | 人工标注1 count | 人工标注1 length_m | 人工标注1未替换长度占比 | 长度变化 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 RCSD超出SWSD Segment范围 | 319 | 33,474.426 | 1.03% | 312 | 31,682.327 | 1.05% | -1,792.099 |
| 2 SWSD范围内缺少有效替换证据 | 9,551 | 1,059,380.448 | 32.51% | 9,554 | 1,043,243.691 | 34.57% | -16,136.757 |
| 3 有替换证据但路口关联不完整 | 7,451 | 954,711.201 | 29.30% | 6,502 | 747,417.759 | 24.77% | -207,293.442 |
| 4 路口关联完整但RCSD不可替换 | 8,802 | 848,528.083 | 26.04% | 8,780 | 849,928.136 | 28.17% | +1,400.053 |
| 5 可替换范围内RCSD未落地 | 6,228 | 362,079.441 | 11.11% | 6,301 | 345,312.990 | 11.44% | -16,766.451 |
| 6 未归因/需人工审计 | 0 | 0.000 | 0.00% | 0 | 0.000 | 0.00% | 0.000 |
| 合计 | 32,351 | 3,258,173.599 | 100.00% | 31,449 | 3,017,584.903 | 100.00% | -240,588.696 |

## 汇报解读

- 人工标注1后，未替换 RCSD 从 `32,351` 条降至 `31,449` 条，减少 `902` 条；未替换里程从 `3,258.174km` 降至 `3,017.585km`，减少 `240.589km`。
- 主要收益来自 `3 有替换证据但路口关联不完整`：减少 `949` 条、`207.293km`。这说明人工标注主要补齐了路口、端点或通行关系前提。
- `2 SWSD范围内缺少有效替换证据` 条数基本不变，长度小幅下降；这类更偏证据覆盖或局部构成问题，不是单靠路口关系标注就能完全消化。
- `4 路口关联完整但RCSD不可替换` 绝对长度基本不降，说明路口关系前提补齐后，剩余瓶颈更多暴露为 RCSD 连通性、方向性、路径覆盖或拓扑质量问题。
- `5 可替换范围内RCSD未落地` 长度小幅下降但条数小幅上升，当前仍需继续追查具体落地原因，不宜过早定性。
- `6 未归因/需人工审计` 当前为 0；图表可按 5 类实际构成展示，同时保留第 6 类作为后续兜底口径。

## 后续基线比对字段

后续内网重跑或项目汇报至少对比以下字段：

- 替换漏斗：`input_fusion_unit_count`、`relation_success_count`、`relation_failure_count`、`replaceable_count`、`rejected_count`、`replacement_plan_count`、`replacement_plan_ready_count`
- RCSD 替换：`total_rcsd_road_count`、`total_rcsd_road_length_m`、`replaced_rcsd_road_count`、`replaced_rcsd_road_length_m`、`replaced_rcsd_road_rate_by_count`、`replaced_rcsd_road_rate_by_length`
- RCSD 未替换：`unreplaced_rcsd_road_count`、`unreplaced_rcsd_road_length_m`
- 反向归因：`by_final_attribution_class`

## 质量与可追溯说明

- CRS 与坐标变换：两版 summary 均以 `EPSG:3857` 作为归因统计坐标系。
- 拓扑一致性：本页不改写 Step3 topology audit 结果；拓扑明细需回到 `t06_step3_topology_connectivity_audit.*`。
- 几何语义：RCSD 替换率以 RCSDRoad count/length 为分母，未替换归因使用 `50.0m` Segment buffer 与最终主归属规则。
- 审计可追溯：本页记录输入版本、分母、替换率、未替换清单归因和 summary 来源；具体 Road/Segment 需回到 GPKG/CSV 审计明细。
- 性能可验证：本页只归档 summary 级指标，不代表重新执行内网任务；性能对比需使用实际 run summary 或运行日志。
