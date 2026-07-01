# 内网执行基线指标

## 记录范围

本页记录 T06 内网全量最新 summary 级基线，命名为“内网执行基线指标”。

当前最新 RCSD 指标来自：

- `step3_segment_replacement/t06_step3_unreplaced_rcsd_attribution_summary.json`

历史漏斗字段保留 summary 级口径，不展开庞大的 `t06_step3_summary.json` 明细。后续 PPT、周报和基线比对优先引用本页表格；若需要定位具体 Segment、Road 或 Node，仍回到 GPKG/CSV 审计明细。

## 对比边界

内网全量和 4-case 测试基线的分母不同。4-case 用于代码回归、策略定位和 case 级问题解释，不作为内网全量验收分母。本文允许横向展示比例，但不使用绝对数量直接判定全量业务回归。

## 基线元信息

| 指标 | 值 |
|---|---:|
| run_id | `t06_innernet_precheck` |
| 内网运行根目录 | `/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t10_innernet_full_pipeline/t10_innernet_full_no_t08_20260627_215704/t06_segment_fusion_precheck/t06_innernet_precheck` |
| CRS | `EPSG:3857` |
| RCSD 反向归因 buffer | `50.0m` |
| RCSD 反向归因优先级 | `5 > 4 > 3 > 2 > 1 > 6` |
| 最新记录口径 | `t06_step3_unreplaced_rcsd_attribution_summary.json` |
| 4-case baseline | `outputs/baselines/t10_4cases_08aa76c_20260628_155754` |

## 最新内网全量漏斗

| 阶段 | 指标 | 数量 | 说明 |
|---|---|---:|---|
| SWSD 输入 | `swsd_segment_count` | 43,430 | T01 Segment 输入总量 |
| T06 证据范围 | `evidence_segment_count` | 25,831 | 占 SWSD 输入 59.48% |
| Relation 范围 | `relation_scope_segment_count` | 22,127 | 占 SWSD 输入 50.95% |
| Step2 relation 成功 | `step2_reported_relation_success_count` | 22,126 | 成功 relation Segment |
| Step2 relation 失败 | `step2_reported_relation_failure_count` | 2,520 | relation 未满足 Segment |
| 可替换范围 | `replaceable_scope_segment_count` | 19,650 | 占 SWSD 输入 45.24% |

## 最新 RCSD 替换率

| 指标 | 值 |
|---|---:|
| total_rcsd_road_count | 134,428 |
| total_rcsd_road_length_m | 12,922,164.809 |
| replaced_rcsd_road_count | 98,908 |
| replaced_rcsd_road_length_m | 9,358,852.672 |
| replaced_rcsd_road_rate_by_count | 73.5769% |
| replaced_rcsd_road_rate_by_length | 72.4248% |
| unreplaced_rcsd_road_count | 35,520 |
| unreplaced_rcsd_road_length_m | 3,563,312.137 |

## 相对旧内网基线变化

旧基线是本页上一版记录的内网全量结果：RCSD 数量替换率 `60.7403%`，里程替换率 `57.0138%`。

| 指标 | 旧基线 | 最新 | 变化 |
|---|---:|---:|---:|
| replaced_rcsd_road_count | 81,652 | 98,908 | +17,256 |
| replaced_rcsd_road_length_m | 7,367,423.199 | 9,358,852.672 | +1,991,429.473 |
| replaced_rcsd_road_rate_by_count | 60.7403% | 73.5769% | +12.8366 pct |
| replaced_rcsd_road_rate_by_length | 57.0138% | 72.4248% | +15.4110 pct |
| unreplaced_rcsd_road_count | 52,776 | 35,520 | -17,256 |
| unreplaced_rcsd_road_length_m | 5,554,741.610 | 3,563,312.137 | -1,991,429.473 |

## 未替换 RCSD 大类归因

| attribution_class | count | length_m | unreplaced_length_rate | total_length_rate |
|---|---:|---:|---:|---:|
| 5_replaceable_scope_unreplaced | 28,584 | 2,851,304.528 | 80.0184% | 22.0652% |
| 4_relation_scope_not_replaceable | 3,079 | 337,456.888 | 9.4703% | 2.6115% |
| 2_swsd_scope_no_t06_evidence | 2,138 | 198,401.250 | 5.5679% | 1.5354% |
| 3_evidence_scope_relation_incomplete | 1,719 | 176,149.471 | 4.9434% | 1.3632% |

## 未替换 RCSD owner 归因

| owner | count | length_m | unreplaced_length_rate | total_length_rate |
|---|---:|---:|---:|---:|
| T06_algorithm_strategy | 28,584 | 2,851,304.528 | 80.0184% | 22.0652% |
| SWSD_data_quality | 3,079 | 337,456.888 | 9.4703% | 2.6115% |
| RCSD_patch_version_mismatch | 2,138 | 198,401.250 | 5.5679% | 1.5354% |
| pre_T05_junction_anchor | 1,719 | 176,149.471 | 4.9434% | 1.3632% |

## 未替换 RCSD 子类 Top 10

| attribution_subclass | count | length_m | unreplaced_length_rate | total_length_rate |
|---|---:|---:|---:|---:|
| 5_replaceable_scope_not_consumed | 21,965 | 2,195,197.979 | 61.6055% | 16.9879% |
| 5_plan_blocked | 6,359 | 629,191.267 | 17.6575% | 4.8691% |
| is_anchor_not_eligible | 1,157 | 119,166.491 | 3.3443% | 0.9222% |
| required_semantic_nodes_not_connected_in_buffer | 1,106 | 113,238.778 | 3.1779% | 0.8763% |
| has_evd_not_yes | 1,139 | 110,049.094 | 3.0884% | 0.8516% |
| rcsd_not_bidirectional_for_swsd_dual | 882 | 105,882.596 | 2.9715% | 0.8194% |
| has_evd_missing | 924 | 83,558.528 | 2.3450% | 0.6466% |
| invalid_pair_relation_status | 499 | 52,790.618 | 1.4815% | 0.4085% |
| special_junction_group_not_fully_replaceable | 483 | 34,959.151 | 0.9811% | 0.2705% |
| swsd_geometry_not_covered_by_retained_rcsd | 177 | 28,749.357 | 0.8068% | 0.2225% |

## 与 4-case 测试基线对比

| 范围 | Segment total | Segment replaced | retained_swsd | failed | topology fail | RCSD total | RCSD replaced | RCSD count rate | RCSD length rate | unreplaced RCSD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 内网全量 | 43,430 | - | - | - | - | 134,428 | 98,908 | 73.5769% | 72.4248% | 35,520 |
| 1885118 | 2,161 | 896 | 1,260 | 0 | 23 | 6,437 | 5,010 | 77.8313% | 78.8718% | 1,427 |
| 609214532 | 1,664 | 604 | 1,059 | 0 | 25 | 5,034 | 3,395 | 67.4414% | 66.6875% | 1,639 |
| 74155468 | 157 | 78 | 79 | 0 | 0 | 518 | 272 | 52.5097% | 47.3382% | 246 |
| 991176 | 224 | 130 | 94 | 0 | 0 | 668 | 455 | 68.1138% | 70.8150% | 213 |
| 4-case 合计 | 4,206 | 1,708 | 2,492 | 0 | 48 | 12,657 | 9,132 | 72.1498% | 72.3819% | 3,525 |

说明：

- `Segment replaced` 为 `segment_relation_replaced_count`，不含 `replaced+retained_swsd` 残差状态。
- 4-case `RCSD count rate / length rate` 使用各 case attribution summary 的 total RCSD 分母。
- 内网全量当前附件只提供 RCSD attribution summary，不在本页展开庞大的 final `t06_step3_summary.json`。

## PPT 摘要口径

- 最新内网全量 RCSD 数量替换率为 `73.5769%`，里程替换率为 `72.4248%`。
- 相对旧内网基线，RCSD 数量替换率提升 `12.8366 pct`，里程替换率提升 `15.4110 pct`。
- 未替换 RCSD 从 `52,776` 条降到 `35,520` 条，减少 `17,256` 条。
- 未替换 RCSD 里程从 `5,554.742km` 降到 `3,563.312km`，减少 `1,991.429km`。
- 未替换里程中 `80.0184%` 仍归入 `T06_algorithm_strategy`，是后续策略优化主方向。
- 4-case 合计 RCSD 数量替换率为 `72.1498%`，里程替换率为 `72.3819%`，与最新内网全量比例接近，但分母不同，不作为绝对验收依据。

## 后续基线比对字段

后续内网重跑或 PPT 模块至少对比以下 summary 字段：

- T06 范围：`swsd_segment_count`、`evidence_segment_count`、`relation_scope_segment_count`、`replaceable_scope_segment_count`
- RCSD 替换：`total_rcsd_road_count`、`total_rcsd_road_length_m`、`replaced_rcsd_road_count`、`replaced_rcsd_road_length_m`、`replaced_rcsd_road_rate_by_count`、`replaced_rcsd_road_rate_by_length`
- RCSD 未替换：`unreplaced_rcsd_road_count`、`unreplaced_rcsd_road_length_m`
- 归因审计：`by_attribution_class`、`by_attribution_owner`、`by_attribution_subclass`

## 质量与可追溯说明

- CRS 与坐标变换：summary 显示 RCSD attribution 使用 `EPSG:3857`。
- 拓扑一致性：本页不把 Step3 hard fail 改写为 pass；拓扑明细需回到 `t06_step3_topology_connectivity_audit.*`。
- 几何语义：RCSD 替换率以 RCSDRoad count/length 为分母，未替换归因使用 50m Segment buffer。
- 审计可追溯：本页记录输入范围、RCSD 替换分母、未替换归因和 4-case baseline 来源。
- 性能可验证：本页不展开 `t06_step3_summary.json` 巨型明细，只保留可直接用于 PPT 与基线比对的稳定字段。
