# 内网全量 RCSD 指标基线

## 记录范围

本页记录内网全量 RCSD 指标基线，供项目汇报、周报和后续 summary 级基线比对引用。

当前登记三个版本：

1. 无人工标注基线指标：内网初次执行结果，未消费人工标注。
2. 人工标注1基线指标：第一次人工标注后的内网执行结果。
3. 人工标注2基线指标：第二次人工标注后的内网正式结果。

三版结果均来自内网全量 Step2 summary、Step3 summary 与未替换 RCSD 反向归因 summary。汇报未替换 RCSD 根因构成时，优先使用 `final_attribution_class` / `by_final_attribution_class`。历史粗口径 `attribution_class` 仅保留为实现对照，不作为项目汇报主口径。

原三大类汇总不再作为项目汇报主口径；当前采用 5+1 分类展示：5 类为实际根因构成，第 6 类为人工审计兜底类。当前三版内网基线中第 6 类均为 0。

## 基线元信息

| 指标 | 值 |
|---|---|
| run_id | `t06_innernet_precheck` |
| 无人工标注/人工标注1登记来源 | 内网全量 Step2 summary、Step3 summary 与未替换 RCSD 反向归因 summary |
| 人工标注2运行根目录 | `/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t11_manual_rerun_innernet_partial/run_20260703T232329Z` |
| CRS | `EPSG:3857` |
| RCSD 反向归因 buffer | `50.0m` |
| 当前汇报归因口径 | `final_attribution_class` |
| 当前汇报分类 | 5+1 分类，当前实际 5 类有结果 |
| 反向归因 summary | `step3_segment_replacement/t06_step3_unreplaced_rcsd_attribution_summary.json` |

## 三版核心替换结果

| 指标 | 无人工标注 | 人工标注1 | 人工标注2 | 标注1-无人工 | 标注2-标注1 | 标注2-无人工 |
|---|---:|---:|---:|---:|---:|---:|
| total_rcsd_road_count | 134,428 | 134,455 | 134,482 | +27 | +27 | +54 |
| total_rcsd_road_length_m | 12,922,164.809 | 12,922,164.809 | 12,922,164.809 | 0.000 | 0.000 | 0.000 |
| replaced_rcsd_road_count | 102,077 | 103,006 | 103,578 | +929 | +572 | +1,501 |
| replaced_rcsd_road_length_m | 9,663,991.210 | 9,904,579.906 | 9,977,530.494 | +240,588.696 | +72,950.588 | +313,539.284 |
| replaced_rcsd_road_rate_by_count | 75.9343% | 76.6100% | 77.0200% | +0.6757 pct | +0.4100 pct | +1.0857 pct |
| replaced_rcsd_road_rate_by_length | 74.7862% | 76.6480% | 77.2125% | +1.8618 pct | +0.5645 pct | +2.4263 pct |
| unreplaced_rcsd_road_count | 32,351 | 31,449 | 30,904 | -902 | -545 | -1,447 |
| unreplaced_rcsd_road_length_m | 3,258,173.599 | 3,017,584.903 | 2,944,634.315 | -240,588.696 | -72,950.588 | -313,539.284 |

## T06 替换漏斗对比

以下漏斗以 T06 Step2 `input_fusion_unit_count` 为主要分母，反映 relation、候选、可替换和 replacement plan 的前置能力变化。

| 阶段 | 无人工标注 | 人工标注1 | 人工标注2 | 标注1-无人工 | 标注2-标注1 | 标注2-无人工 |
|---|---:|---:|---:|---:|---:|---:|
| input_fusion_unit_count | 24,646 (100.00%) | 24,831 (100.00%) | 24,896 (100.00%) | +185 | +65 | +250 |
| relation_success_count | 22,126 (89.78%) | 22,339 (89.96%) | 22,417 (90.04%) | +213 | +78 | +291 |
| relation_failure_count | 2,520 | 2,492 | 2,479 | -28 | -13 | -41 |
| rcsd_candidate_count | 18,305 (74.27%) | 18,516 (74.57%) | 18,579 (74.63%) | +211 | +63 | +274 |
| replaceable_count | 18,305 (74.27%) | 18,516 (74.57%) | 18,579 (74.63%) | +211 | +63 | +274 |
| rejected_count | 6,341 | 6,315 | 6,317 | -26 | +2 | -24 |
| replacement_plan_count | 20,152 | 20,372 | 20,578 | +220 | +206 | +426 |
| replacement_plan_ready_count | 18,672 (75.76%) | 18,866 (75.98%) | 18,979 (76.23%) | +194 | +113 | +307 |
| replaceable_rcsd_road_unique_count | 98,302 | 98,989 | 99,136 | +687 | +147 | +834 |
| replaceable_rcsd_road_unique_length_m | 9,554,518.993 | 9,783,421.657 | 9,812,411.938 | +228,902.664 | +28,990.281 | +257,892.945 |

## RCSD Road 替换情况漏斗

以下为 RCSD Road 视角的替换情况。`Step2 可替换唯一 RCSD Road` 是 precheck 能力指标，不是 Step3 最终替换结果的严格子集；Step3 的 surface-aware plan 与规则恢复会影响最终落地数量。

| 版本 | RCSD Road 总量 | Step2 可替换唯一 RCSD Road | Step3 最终已替换 RCSD Road | Step3 最终未替换 RCSD Road |
|---|---:|---:|---:|---:|
| 无人工标注 | 134,428 / 12,922.2km (100.00%) | 98,302 / 9,554.5km (73.13% / 73.94%) | 102,077 / 9,664.0km (75.93% / 74.79%) | 32,351 / 3,258.2km (24.07% / 25.21%) |
| 人工标注1 | 134,455 / 12,922.2km (100.00%) | 98,989 / 9,783.4km (73.62% / 75.71%) | 103,006 / 9,904.6km (76.61% / 76.65%) | 31,449 / 3,017.6km (23.39% / 23.35%) |
| 人工标注2 | 134,482 / 12,922.2km (100.00%) | 99,136 / 9,812.4km (73.72% / 75.93%) | 103,578 / 9,977.5km (77.02% / 77.21%) | 30,904 / 2,944.6km (22.98% / 22.79%) |

## Segment 关系结果

| 指标 | 无人工标注 | 人工标注1 | 人工标注2 | 标注1-无人工 | 标注2-标注1 | 标注2-无人工 |
|---|---:|---:|---:|---:|---:|---:|
| swsd_segment_count | 43,430 | 43,430 | 43,430 | 0 | 0 | 0 |
| evidence_segment_count | 25,831 | 25,831 | 25,831 | 0 | 0 | 0 |
| relation_scope_segment_count | 22,127 | 22,341 | 22,419 | +214 | +78 | +292 |
| step2_reported_relation_success_count | 22,126 | 22,339 | 22,417 | +213 | +78 | +291 |
| step2_reported_relation_failure_count | 2,520 | 2,492 | 2,479 | -28 | -13 | -41 |
| replaceable_scope_segment_count | 19,979 | 20,189 | 20,393 | +210 | +204 | +414 |
| segment_relation_count | 43,430 | 43,430 | 43,430 | 0 | 0 | 0 |
| segment_relation_replaced_count | 17,883 | 18,076 | 18,279 | +193 | +203 | +396 |
| segment_relation_retained_swsd_count | 25,471 | 25,277 | 25,082 | -194 | -195 | -389 |
| segment_relation_failed_count | 9 | 9 | 0 | 0 | -9 | -9 |

## 未替换 RCSD 5+1 分类定义

| 分类 | 字段值 | 中文指标名 | 业务含义 |
|---|---|---|---|
| 1 | `1_outside_swsd_segment_scope` | RCSD超出SWSD Segment范围 | RCSD 相比 SWSD 多出的路网表达，可能来自现实道路变化、SWSD 路网精简或覆盖范围差异。具有连通性的 RCSD 可牵引现实变更确认；单独端点挂接且不具备连通性的 RCSD 可通过策略补齐，但收益通常有限。 |
| 2 | `2_swsd_scope_no_t06_evidence` | SWSD范围内缺少有效替换证据 | RCSD 位于 SWSD Segment 范围内，但 Segment 没有形成可支撑整体替换的有效道路面或路网证据。常见表现是 Segment 只有局部 RCSD 支撑，整体构成不完整。 |
| 3 | `3_evidence_scope_relation_incomplete` | 有替换证据但路口关联不完整 | Segment 已有替换证据，但关键路口、端点或通行关系未正确关联，导致替换前提不完整。原因可能来自 SWSD 数据质量、Patch 质量或算法策略。 |
| 4 | `4_relation_scope_not_replaceable` | 路口关联完整但RCSD不可替换 | Segment 的关键路口和关系前提已满足，但 RCSD 在连通性、方向性、路径覆盖或拓扑质量上不满足替换要求。常见表现是中间存在不连通断点或承载路径不完整。 |
| 5 | `5_replaceable_scope_unreplaced` | 可替换范围内RCSD未落地 | RCSD 位于已具备替换条件的范围内，但最终融合结果没有采用该 RCSD。当前仍需继续追查，可能与候选选择、局部覆盖、冲突裁剪、保留原 SWSD 或替换落地策略有关。 |
| 6 | `6_unattributed_manual_audit` | 未归因/需人工审计 | 当前规则无法稳定解释，需要人工结合地图、证据、关系和最终结果继续审计。当前三版内网基线中该类为 0。 |

说明：字段值保留历史命名，中文指标名与业务含义用于项目汇报。反向审计归因只能做到近似分析，不能作为绝对根因；比例可用于判断主要结构和优化方向。

## 未替换 RCSD 根因构成

| 分类 | 无人工标注 | 人工标注1 | 人工标注2 | 标注2-标注1长度变化 | 标注2-无人工长度变化 |
|---|---:|---:|---:|---:|---:|
| 1 RCSD超出SWSD Segment范围 | 319 / 33,474.426m / 1.03% | 312 / 31,682.327m / 1.05% | 312 / 31,682.327m / 1.08% | 0.000 | -1,792.099 |
| 2 SWSD范围内缺少有效替换证据 | 9,551 / 1,059,380.448m / 32.51% | 9,554 / 1,043,243.691m / 34.57% | 9,550 / 1,042,874.666m / 35.42% | -369.025 | -16,505.782 |
| 3 有替换证据但路口关联不完整 | 7,451 / 954,711.201m / 29.30% | 6,502 / 747,417.759m / 24.77% | 6,258 / 711,939.647m / 24.18% | -35,478.112 | -242,771.554 |
| 4 路口关联完整但RCSD不可替换 | 8,802 / 848,528.083m / 26.04% | 8,780 / 849,928.136m / 28.17% | 8,502 / 815,153.987m / 27.68% | -34,774.149 | -33,374.096 |
| 5 可替换范围内RCSD未落地 | 6,228 / 362,079.441m / 11.11% | 6,301 / 345,312.990m / 11.44% | 6,282 / 342,983.688m / 11.65% | -2,329.302 | -19,095.753 |
| 6 未归因/需人工审计 | 0 / 0.000m / 0.00% | 0 / 0.000m / 0.00% | 0 / 0.000m / 0.00% | 0.000 | 0.000 |
| 合计 | 32,351 / 3,258,173.599m / 100.00% | 31,449 / 3,017,584.903m / 100.00% | 30,904 / 2,944,634.315m / 100.00% | -72,950.588 | -313,539.284 |

## PPT 归因三桶口径

PPT 三桶口径用于 summary 级展示，仍以 `final_attribution_class` 为底层来源。

| PPT 归因桶 | 人工标注2 count | 人工标注2 length_m | 人工标注2未替换长度占比 | 业务含义 |
|---|---:|---:|---:|---|
| `2_segment_replacement_prerequisite_unsatisfied` | 15,808 | 1,754,814.313 | 59.59% | Segment 替换前提不足，合并 2/3 类。 |
| `1_segment_rcsd_quality_unreplaceable` | 14,784 | 1,158,137.675 | 39.33% | Segment 已进入可解释范围，但 RCSD 质量或落地策略仍阻塞，合并 4/5 类。 |
| `3_rcsd_outside_segment_scope` | 312 | 31,682.327 | 1.08% | RCSD 超出当前 SWSD Segment 可替换范围。 |

## 汇报解读

- 人工标注2后，RCSD 里程替换率达到 `77.2125%`，相对无人工标注提升 `+2.4263 pct`，相对人工标注1继续提升 `+0.5645 pct`。
- 人工标注2后，未替换 RCSD 从 `32,351` 条降至 `30,904` 条，减少 `1,447` 条；未替换里程从 `3,258.174km` 降至 `2,944.634km`，减少 `313.539km`。
- 主要累计收益仍来自 `3 有替换证据但路口关联不完整`：未替换里程从 `954.711km` 降至 `711.940km`，累计减少 `242.772km`。这说明人工标注主要补齐了路口、端点或通行关系前提。
- 人工标注2相对人工标注1的新增收益分散在 `3 有替换证据但路口关联不完整`（`-35.478km`）与 `4 路口关联完整但RCSD不可替换`（`-34.774km`），说明 Relation 修复后仍会继续暴露 RCSD 路径、方向、拓扑或落地策略问题。
- `2 SWSD范围内缺少有效替换证据` 在人工标注1到人工标注2之间几乎不变（`-0.369km`），这类更偏证据覆盖或局部构成问题，不是单靠路口关系标注就能完全消化。
- `segment_relation_failed_count` 从 `9` 降为 `0`，但最终仍有 `30,904` 条、`2,944.634km` RCSD 未替换，后续优化重点应继续落在证据前提、RCSD 质量、替换落地策略和可解释归因闭环。

## 后续基线比对字段

后续内网重跑或项目汇报至少对比以下字段：

- 替换漏斗：`input_fusion_unit_count`、`relation_success_count`、`relation_failure_count`、`replaceable_count`、`rejected_count`、`replacement_plan_count`、`replacement_plan_ready_count`
- RCSD 替换：`total_rcsd_road_count`、`total_rcsd_road_length_m`、`replaceable_rcsd_road_unique_count`、`replaceable_rcsd_road_unique_length_m`、`replaced_rcsd_road_count`、`replaced_rcsd_road_length_m`、`replaced_rcsd_road_rate_by_count`、`replaced_rcsd_road_rate_by_length`
- RCSD 未替换：`unreplaced_rcsd_road_count`、`unreplaced_rcsd_road_length_m`
- Segment 结果：`relation_scope_segment_count`、`segment_relation_replaced_count`、`segment_relation_retained_swsd_count`、`segment_relation_failed_count`
- 反向归因：`by_final_attribution_class`、`by_ppt_attribution_class`

## 质量与可追溯说明

- CRS 与坐标变换：三版 summary 均以 `EPSG:3857` 作为归因统计坐标系。
- 拓扑一致性：本页不改写 Step3 topology audit 结果；拓扑明细需回到 `t06_step3_topology_connectivity_audit.*`。人工标注2 Step3 summary 状态为 `completed_with_failed_units`，拓扑与 surface topology 质量问题需回到明细审计文件继续定位。
- 几何语义：RCSD 替换率以 RCSDRoad count/length 为分母，未替换归因使用 `50.0m` Segment buffer 与最终主归属规则。
- 审计可追溯：本页记录输入版本、分母、替换率、未替换清单归因和 summary 来源；具体 Road/Segment 需回到 GPKG/CSV 审计明细。
- 性能可验证：本页只归档 summary 级指标，不代表重新执行内网任务；性能对比需使用实际 run summary 或运行日志。
