# 内网执行基线指标

## 记录范围

本基线记录来自内网执行 `run_id=t06_innernet_precheck` 的 4 个 summary：

- `step1_identify_fusion_units/t06_step1_summary.json`
- `step2_extract_rcsd_segments/t06_step2_summary.json`
- `step3_segment_replacement/t06_step3_summary.json`
- `step3_segment_replacement/t06_step3_unreplaced_rcsd_attribution_summary.json`

本记录只沉淀 summary 级指标，不依赖 CSV/GPKG 明细。后续 PPT、周报或基线比对可以按本页字段做同口径对照；若需要定位具体 Segment、Road 或 Node，仍需回到对应审计明细。

## 与测试用例的对比边界

本页是内网全量执行基线，不是 1885118 单 case 或 4-case 测试基线。它只能和后续同一内网数据范围、同一 summary 口径的 T06 run 做基线比对；不能用绝对数和测试用例直接比较。

以本轮内网全量和 1885118 单 case 最新本地结果为例，分母差异已经足以导致指标相差巨大：

| 指标 | 内网全量 | 1885118 单 case | 倍数 |
|---|---:|---:|---:|
| Segment relation count | 43,430 | 2,161 | 20.10x |
| Step3 input replaceable | 17,995 | 916 | 19.65x |
| Step3 success units | 15,516 | 955 | 16.25x |
| F-RCSD road count | 132,793 | 7,052 | 18.83x |
| topology fail rows | 1,083 | 25 | 43.32x |
| total RCSD road count | 134,428 | 6,436 | 20.89x |
| RCSD replaced rate by count | 60.7403% | 78.2784% | 不适用 |
| RCSD replaced rate by length | 57.0138% | 79.1163% | 不适用 |

因此，后续 PPT 中应把这些数值标注为“内网全量基线”；测试用例只用于代码回归、策略定位和 case 级问题解释，不作为内网全量指标的验收分母。

## 基线元信息

| 指标 | 值 |
|---|---:|
| run_id | `t06_innernet_precheck` |
| 内网运行根目录 | `/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t10_innernet_full_pipeline/t10_innernet_full_no_t08_20260627_215704/t06_segment_fusion_precheck/t06_innernet_precheck` |
| CRS | `EPSG:3857` |
| Step2 candidate strategy | `buffer_segment_extraction` |
| Step2 write_json_outputs | `false` |
| RCSD 反向归因 buffer | `50.0m` |
| RCSD 反向归因优先级 | `5 > 4 > 3 > 2 > 1 > 6` |

## 总体漏斗

| 阶段 | 核心口径 | 数量 | 说明 |
|---|---:|---:|---|
| Step1 输入 SWSD Segment | `input_segment_count` | 43,430 | T01 Segment 输入总量 |
| Step1 EVD 候选 | `evd_candidate_count` | 25,831 | 占输入 59.48% |
| Step1 最终 fusion unit | `final_fusion_unit_count` | 24,646 | 占输入 56.75%，占 EVD 候选 95.41% |
| Step2 relation 成功 | `relation_success_count` | 22,126 | 占 Step1 最终 fusion unit 89.78% |
| Step2 RCSD candidate | `rcsd_candidate_count` | 18,293 | buffer-based RCSDSegment 候选 |
| Step2 replaceable | `replaceable_count` | 17,995 | 占 Step1 最终 fusion unit 73.01%，占 RCSD candidate 98.37% |
| Step2 replacement plan | `replacement_plan_count` | 19,803 | Step2 发布 plan 总数 |
| Step2 ready plan | `replacement_plan_ready_count` | 15,832 | 占 plan 总数 79.95% |
| Step3 输入 replaceable | `input_replaceable_count` | 17,995 | 与 Step2 replaceable 对齐 |
| Step3 输入 replacement plan | `input_replacement_plan_count` | 19,631 | Step3 实际消费的 plan 行数 |
| Step3 replacement unit | `replacement_unit_count` | 15,687 | Step3 形成的执行单元 |
| Step3 成功 unit | `replacement_unit_success_count` | 15,516 | unit 成功率 98.91% |
| Step3 失败 unit | `replacement_unit_failure_count` | 171 | 仍需专项审计 |

## Step1 指标

| 指标 | 值 |
|---|---:|
| input_segment_count | 43,430 |
| evd_candidate_count | 25,831 |
| swsd_candidate_count | 25,831 |
| final_fusion_unit_count | 24,646 |
| swsd_final_fusion_unit_count | 24,646 |
| rejected_before_evd_count | 17,599 |
| rejected_after_evd_count | 1,185 |

Step1 reject reason：

| reason | count |
|---|---:|
| has_evd_not_yes | 9,599 |
| has_evd_missing | 6,871 |
| is_anchor_not_eligible | 1,185 |
| swsd_pair_nodes_not_distinct | 1,129 |

## Step2 指标

| 指标 | 值 |
|---|---:|
| input_fusion_unit_count | 24,646 |
| relation_success_count | 22,126 |
| relation_failure_count | 2,520 |
| junc_kind2_relation_exempt_segment_count | 3,718 |
| junc_kind2_relation_exempt_node_count | 7,666 |
| rcsd_candidate_count | 18,293 |
| replaceable_count | 17,995 |
| rejected_count | 6,651 |
| single_segment_input_count | 5,522 |
| single_segment_replaceable_count | 4,598 |
| dual_segment_input_count | 16,604 |
| dual_segment_replaceable_count | 13,397 |
| buffer_segment_count | 18,293 |
| buffer_rejected_count | 3,649 |
| buffer_retained_road_count_total | 102,375 |
| buffer_excluded_advance_right_turn_road_count_total | 19,594 |

Step2 replacement plan：

| 指标 | 值 |
|---|---:|
| replacement_plan_count | 19,803 |
| replacement_plan_ready_count | 15,832 |
| standard_segment | 17,995 |
| path_corridor_group | 1,636 |
| special_junction_group_internal | 172 |

特殊路口组与 group replacement：

| 指标 | 值 |
|---|---:|
| special_junction_group_count | 357 |
| special_junction_group_passed_count | 172 |
| special_junction_group_blocked_count | 185 |
| special_junction_blocked_segment_count | 558 |
| special_junction_gate_removed_replaceable_count | 298 |
| group_replacement_audit_count | 4,690 |
| group_replacement_candidate_ready_count | 313 |
| group_replacement_closure_blocked_count | 2,302 |

Step2 rejected reason：

| reason | count |
|---|---:|
| invalid_pair_relation_status | 2,455 |
| rcsd_not_bidirectional_for_swsd_dual | 1,421 |
| required_semantic_nodes_not_connected_in_buffer | 1,360 |
| retained_geometry_outside_swsd_buffer_scope | 380 |
| special_junction_group_not_fully_replaceable | 298 |
| rcsd_directed_path_missing | 207 |
| rcsd_pair_nodes_not_distinct | 185 |
| swsd_geometry_not_covered_by_retained_rcsd | 170 |
| retained_road_buffer_overlap_insufficient | 78 |
| missing_pair_relation | 64 |
| required_semantic_nodes_missing_from_buffer_graph | 33 |

Problem registry：

| status | count |
|---|---:|
| requires_upstream_iteration | 5,612 |
| covered_by_replacement_plan | 977 |
| resolved_in_step2_plan | 781 |
| requires_upstream_side_group_or_rcsd_directionality_review | 300 |
| accepted_non_replaceable | 142 |

## Step3 指标

| 指标 | 值 |
|---|---:|
| input_replaceable_count | 17,995 |
| input_replacement_plan_count | 19,631 |
| input_standard_replacement_plan_count | 14,684 |
| replacement_plan_source | `step2_replacement_plan` |
| replacement_unit_count | 15,687 |
| replacement_unit_success_count | 15,516 |
| replacement_unit_failure_count | 171 |
| group_replacement_audit_input_row_count | 19,631 |
| group_replacement_passed_row_count | 976 |
| group_replacement_plan_count | 658 |
| group_replacement_assignment_segment_count | 1,003 |
| group_replacement_created_unit_count | 1,003 |
| group_replacement_skipped_row_count | 18,655 |

替换执行结果：

| 指标 | 值 |
|---|---:|
| removed_swsd_road_count | 38,811 |
| removed_swsd_node_count | 21,569 |
| removed_swsd_node_preserved_by_retained_road_count | 15,593 |
| added_rcsd_road_count | 86,627 |
| added_rcsd_node_count | 99,737 |
| unreplaced_rcsd_road_count | 52,776 |
| unreplaced_rcsd_road_length_m | 5,554,741.597 |
| frcsd_road_count | 132,793 |
| frcsd_node_count | 146,223 |

保留 SWSD 与补充拓扑：

| 指标 | 值 |
|---|---:|
| detached_junc_retained_segment_count | 757 |
| detached_junc_retained_swsd_road_count | 1,175 |
| topology_supplement_retained_segment_count | 5,661 |
| topology_supplement_retained_swsd_road_count | 8,587 |
| topology_supplement_materialized_candidate_road_count | 3,212 |
| topology_supplement_materialized_rcsd_road_count | 123 |
| topology_supplement_materialized_missing_attachment_node_count | 215 |
| topology_supplement_formal_body_retained_restored_count | 8,490 |
| group_path_corridor_coverage_fallback_segment_count | 651 |
| group_path_corridor_coverage_fallback_swsd_road_count | 986 |
| group_path_corridor_coverage_fallback_swsd_node_count | 1,645 |

Segment relation：

| relation_status | count | 占 Segment 总数 |
|---|---:|---:|
| replaced | 14,819 | 34.12% |
| retained_swsd | 27,907 | 64.26% |
| replaced+retained_swsd | 697 | 1.60% |
| failed | 7 | 0.02% |
| total | 43,430 | 100.00% |

语义路口与 mainnode：

| 指标 | 值 |
|---|---:|
| junction_c_count | 23,912 |
| junction_rebuilt_count | 19,277 |
| mainnode_reselected_count | 12,527 |
| relation_node_map_backfilled_entry_count | 5,014 |
| relation_node_map_backfilled_row_count | 2,407 |
| retained_swsd_carrier_mainnode_candidate_count | 8,721 |
| retained_swsd_carrier_mainnode_synced_count | 7,254 |
| retained_swsd_carrier_rcsd_mainnode_filled_count | 1,750 |
| retained_swsd_carrier_mainnode_row_count | 11,775 |
| semantic_junction_group_count | 12,065 |
| semantic_junction_group_node_count | 41,436 |

advance-right / attachment：

| 指标 | 值 |
|---|---:|
| rcsd_advance_right_closure_candidate_road_count | 7,183 |
| rcsd_advance_right_closure_repaired_endpoint_count | 131 |
| rcsd_advance_right_closure_failed_endpoint_count | 173 |
| advance_right_contract_candidate_road_count | 3,222 |
| advance_right_contract_retained_candidate_road_count | 3,217 |
| advance_right_contract_swsd_mainnode_normalized_node_count | 4,982 |
| advance_right_contract_swsd_node_snapped_count | 5,111 |
| advance_right_contract_rcsd_node_generated_count | 4,764 |
| advance_right_contract_rcsd_split_original_road_count | 4,731 |
| advance_right_contract_rcsd_split_road_count | 9,495 |
| advance_right_contract_audit_row_count | 10,133 |
| advance_right_attachment_swsd_mainnode_synced_count | 361 |

Topology connectivity audit：

| status | count | 占审计行 |
|---|---:|---:|
| pass | 234,132 | 91.47% |
| warn | 20,750 | 8.11% |
| fail | 1,083 | 0.42% |
| total | 255,965 | 100.00% |

## RCSD 替换与审计指标

Step2 RCSD 覆盖：

| 指标 | 值 |
|---|---:|
| rcsd_road_total_count | 134,428 |
| rcsd_road_total_length_m | 12,922,164.809 |
| replaceable_rcsd_road_unique_count | 96,488 |
| replaceable_rcsd_road_unique_length_m | 9,387,367.345 |
| replaceable_rcsd_road_unique_count_rate | 71.78% |
| replaceable_rcsd_road_unique_length_rate | 72.65% |
| replaceable_rcsd_road_reference_count | 101,027 |
| replaceable_rcsd_road_reference_length_m | 9,648,641.554 |
| rcsd_semantic_node_alias_count | 50,958 |
| rcsd_semantic_node_group_count | 83,039 |

最终 RCSD 替换率：

| 指标 | 值 |
|---|---:|
| total_rcsd_road_count | 134,428 |
| total_rcsd_road_length_m | 12,922,164.809 |
| replaced_rcsd_road_count | 81,652 |
| replaced_rcsd_road_length_m | 7,367,423.199 |
| replaced_rcsd_road_rate_by_count | 60.7403% |
| replaced_rcsd_road_rate_by_length | 57.0138% |
| unreplaced_rcsd_road_count | 52,776 |
| unreplaced_rcsd_road_length_m | 5,554,741.610 |
| unreplaced_rcsd_road_rate_by_count | 39.26% |
| unreplaced_rcsd_road_rate_by_length | 42.99% |

未替换 RCSD 大类归因：

| attribution_class | count | length_m | unreplaced_length_rate | total_length_rate |
|---|---:|---:|---:|---:|
| 5_replaceable_scope_unreplaced | 45,816 | 4,840,860.542 | 87.1483% | 37.4617% |
| 4_relation_scope_not_replaceable | 3,104 | 339,374.845 | 6.1096% | 2.6263% |
| 2_swsd_scope_no_t06_evidence | 2,137 | 198,356.752 | 3.5709% | 1.5350% |
| 3_evidence_scope_relation_incomplete | 1,719 | 176,149.471 | 3.1712% | 1.3632% |

未替换 RCSD owner 归因：

| owner | count | length_m | unreplaced_length_rate | total_length_rate |
|---|---:|---:|---:|---:|
| T06_algorithm_strategy | 45,816 | 4,840,860.542 | 87.1483% | 37.4617% |
| SWSD_data_quality | 3,104 | 339,374.845 | 6.1096% | 2.6263% |
| RCSD_patch_version_mismatch | 2,137 | 198,356.752 | 3.5709% | 1.5350% |
| pre_T05_junction_anchor | 1,719 | 176,149.471 | 3.1712% | 1.3632% |

未替换 RCSD 子类 Top 10：

| attribution_subclass | count | length_m | unreplaced_length_rate |
|---|---:|---:|---:|
| 5_replaceable_scope_not_consumed | 28,401 | 3,081,113.841 | 55.4682% |
| 5_plan_blocked | 15,431 | 1,562,575.341 | 28.1305% |
| 5_partial_replaced_retained_swsd | 1,925 | 194,517.961 | 3.5018% |
| is_anchor_not_eligible | 1,157 | 119,166.491 | 2.1453% |
| required_semantic_nodes_not_connected_in_buffer | 1,106 | 113,238.778 | 2.0386% |
| has_evd_not_yes | 1,137 | 109,953.415 | 1.9795% |
| rcsd_not_bidirectional_for_swsd_dual | 887 | 106,176.392 | 1.9115% |
| has_evd_missing | 925 | 83,609.709 | 1.5052% |
| invalid_pair_relation_status | 499 | 52,790.618 | 0.9504% |
| special_junction_group_not_fully_replaceable | 483 | 34,959.151 | 0.6294% |

## PPT 摘要口径

- T06 内网输入 `43,430` 个 SWSD Segment，Step1 形成 `24,646` 个 fusion unit。
- Step2 形成 `17,995` 个 replaceable Segment，按 Step1 最终 fusion unit 口径替换候选率为 `73.01%`。
- Step3 成功执行 `15,516` 个 replacement unit，unit 成功率 `98.91%`。
- 最终 F-RCSD 输出 `132,793` 条 Road、`146,223` 个 Node。
- Segment relation 中 `14,819` 个纯替换、`27,907` 个保留 SWSD、`697` 个混合替换、`7` 个失败。
- RCSD 总量 `134,428` 条、`12,922.165km`；最终替换 `81,652` 条、`7,367.423km`。
- RCSD 替换率按数量为 `60.7403%`，按里程为 `57.0138%`。
- 未替换 RCSD `52,776` 条、`5,554.742km`；其中 `87.1483%` 未替换里程归入 `T06_algorithm_strategy`。
- topology connectivity audit hard fail 为 `1,083` 行，占审计行 `0.42%`。

## 后续基线比对字段

后续内网重跑或 PPT 模块应至少对比以下字段：

- Step1：`input_segment_count`、`evd_candidate_count`、`final_fusion_unit_count`、`reject_reason_counts`
- Step2：`input_fusion_unit_count`、`relation_success_count`、`replaceable_count`、`rejected_count`、`replacement_plan_count`、`replacement_plan_ready_count`、`problem_registry_status_counts`
- Step3：`replacement_unit_success_count`、`replacement_unit_failure_count`、`segment_relation_replaced_count`、`segment_relation_retained_swsd_count`、`segment_relation_failed_count`、`topology_connectivity_fail_count`
- RCSD：`total_rcsd_road_count`、`total_rcsd_road_length_m`、`replaced_rcsd_road_count`、`replaced_rcsd_road_length_m`、`replaced_rcsd_road_rate_by_count`、`replaced_rcsd_road_rate_by_length`、`by_attribution_class`、`by_attribution_owner`

## 质量与可追溯说明

- CRS 与坐标变换：summary 显示 Step2/Step3 与 RCSD attribution 均使用 `EPSG:3857`。
- 拓扑一致性：Step2 记录 canonicalized RCSD semantic nodes、component coverage 与 special junction group gating；Step3 记录 post-replacement connectivity audit。
- 不 silent fix：失败、warning、保留 SWSD carrier、topology supplement、mainnode sync 均在 summary 中有计数；该基线不把 hard fail 解释为 pass。
- 几何语义：SWSD geometry 定义 buffer window，RCSD geometry 用于候选选择和替换输出，Step2 replacement plan 是 Step3 正式执行边界。
- 审计可追溯：summary 记录输入路径、参数、输出路径、reject reason、problem registry、replacement unit、relation、topology audit 和 RCSD attribution 聚合。
- 性能可验证：Step2 使用 `write_json_outputs=false`，summary 记录输入规模、候选规模、输出路径和可复现实验参数。
