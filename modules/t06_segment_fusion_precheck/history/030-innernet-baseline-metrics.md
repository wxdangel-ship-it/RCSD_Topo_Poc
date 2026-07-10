# 内网全量 RCSD 正式指标基线

## 记录范围

本页只保留两套正式内网全量指标：

1. **未人工标注**：未消费 T11 人工关系的全量结果。
2. **人工标注**：消费 T11 人工关系后的全量结果。

两套结果均来自 2026-07-08 之后的同版全量底座，`swsd_segment_count=43,228`，RCSD 总长度均为 `12,922,164.809m`，可用于正式相对比较。其他历史试跑和中间标注版本不再作为基线，不应在项目汇报、周报或后续指标对比中引用。

未替换 RCSD 主归因使用 `final_attribution_class` / `by_final_attribution_class`，采用 5+1 分类；历史粗口径 `attribution_class` 只用于实现审计，不作为正式汇报口径。

## 基线元信息

| 指标 | 未人工标注 | 人工标注 |
|---|---|---|
| run_id | `t06_innernet_precheck` | `t06_innernet_precheck` |
| 运行根目录 | `/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t10_innernet_full_pipeline/t10_innernet_full_no_t08_20260708_173130` | `/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t11_manual_rerun_innernet_full_from_20260709T094758Z/run_20260709T135617Z` |
| T05 summary 产出时间 | `2026-07-08T21:51:50+00:00` | `2026-07-09T14:03:45+00:00` |
| T06/归因工作 CRS | `EPSG:3857` | `EPSG:3857` |
| RCSD 反向归因 buffer | `50.0m` | `50.0m` |
| 正式归因口径 | `final_attribution_class` | `final_attribution_class` |
| 正式分类 | 5+1 分类 | 5+1 分类 |

正式反向归因 summary 位于各运行根目录下：

`t06_segment_fusion_precheck/t06_innernet_precheck/step3_segment_replacement/t06_step3_unreplaced_rcsd_attribution_summary.json`

## 正式结论

- T11 人工关系在 T05 层共输入 `346` 条，分类 `346` 条，成功 `346` 条，失败 `0` 条，源层消费完整。
- 人工标注相对未人工标注，T06 Step2 relation 成功增加 `158`，可替换 FusionUnit 增加 `105`，Step3 最终替换 Segment 增加 `143`。
- 最终已替换 RCSDRoad 增加 `1,258` 条、`169.724km`；count 替换率由 `79.9658%` 提升到 `80.8753%`，增加 `0.9095 pct`；里程替换率由 `79.0626%` 提升到 `80.3760%`，增加 `1.3134 pct`。
- 未替换 RCSDRoad 减少 `1,214` 条、`169.724km`。主要净收益来自根因3减少 `88.158km`、根因4减少 `48.055km`和第6类审计兜底减少 `19.264km`。
- 根因5 count 减少 `57`，但长度增加 `0.806km`。其中 `5_replaceable_scope_not_consumed` 减少 `49 / 3.733km`，被 `5_T06_strategy_unlanded` 增加 `4.539km`抵消，根因5不是本轮人工标注净收益的主要来源。

## T05 人工关系消费

| 指标 | 未人工标注 | 人工标注 | 人工标注 - 未人工标注 |
|---|---:|---:|---:|
| T11_MANUAL input_count | 0 | 346 | +346 |
| T11_MANUAL classified_input_count | 0 | 346 | +346 |
| T11_MANUAL relation_success_count | 0 | 346 | +346 |
| T11_MANUAL relation_failure_count | 0 | 0 | 0 |
| `pre_success_rcsd_semantic_relation` 成功 | 0 | 303 | +303 |
| `pre_success_rcsdroad_junctionization` 成功 | 0 | 43 | +43 |
| intersection_match_all_feature_count | 27,685 | 27,768 | +83 |
| status_0_count | 25,587 | 25,711 | +124 |
| status_1_count | 2,098 | 2,057 | -41 |
| relation_graph_consumable_count | 25,581 | 25,704 | +123 |
| relation_graph_unconsumable_success_count | 6 | 7 | +1 |
| relation_cardinality_error_count | 396 | 396 | 0 |
| many_target_to_one_base_count | 396 | 396 | 0 |
| blocking_error_count | 0 | 0 | 0 |
| T05 total_sec | 352.877 | 380.255 | +27.378 |

说明：`346` 条 T11 人工成功是 T05 source 层关系消费量，不等同于全局 `status_0_count`、graph 可消费 relation 或 T06 Segment 成功的净增量。同一人工关系可能覆盖已有自动证据，或在下游按 FusionUnit、Segment 和 RCSDRoad 不同粒度产生一对多/多对一影响。

## T06 Step2 替换漏斗

以下比例以各版本 `input_fusion_unit_count` 为分母。

| 阶段 | 未人工标注 | 人工标注 | 人工标注 - 未人工标注 |
|---|---:|---:|---:|
| input_fusion_unit_count | 26,027 (100.00%) | 26,106 (100.00%) | +79 |
| relation_success_count | 23,010 (88.41%) | 23,168 (88.75%) | +158 / +0.34 pct |
| relation_failure_count | 3,017 | 2,938 | -79 |
| rcsd_candidate_count | 19,913 (76.51%) | 20,018 (76.68%) | +105 / +0.17 pct |
| replaceable_count | 19,913 (76.51%) | 20,018 (76.68%) | +105 / +0.17 pct |
| rejected_count | 6,114 | 6,088 | -26 |
| replacement_plan_count | 21,901 | 22,007 | +106 |
| replacement_plan_ready_count | 19,815 (76.13%) | 19,862 (76.08%) | +47 / -0.05 pct |
| replaceable_rcsd_road_unique_count | 101,573 | 102,494 | +921 |
| replaceable_rcsd_road_unique_length_m | 9,916,596.012 | 10,060,108.379 | +143,512.367 |

`replaceable_rcsd_road_unique_*` 是 Step2 precheck 能力指标；Step3 最终替换还会经过 replacement plan、surface-aware plan、拓扑审计和最终输出规则，因此不应与最终已替换 RCSDRoad 混为同一指标。

## T06 Step3 Segment 漏斗

| 指标 | 未人工标注 | 人工标注 | 人工标注 - 未人工标注 |
|---|---:|---:|---:|
| swsd_segment_count | 43,228 | 43,228 | 0 |
| evidence_segment_count | 26,825 | 26,825 | 0 |
| relation_scope_segment_count | 23,012 | 23,169 | +157 |
| step2_reported_relation_success_count | 23,010 | 23,168 | +158 |
| step2_reported_relation_failure_count | 3,017 | 2,938 | -79 |
| replaceable_scope_segment_count | 21,711 | 21,810 | +99 |
| input_replaceable_count | 19,913 | 20,018 | +105 |
| input_replacement_plan_count | 21,901 | 22,007 | +106 |
| replacement_unit_count | 19,994 | 20,134 | +140 |
| replacement_unit_success_count | 19,994 | 20,134 | +140 |
| replacement_unit_failure_count | 0 | 0 | 0 |
| segment_relation_count | 43,228 | 43,228 | 0 |
| segment_relation_replaced_count | 19,303 | 19,446 | +143 |
| segment_relation_mixed_count | 369 | 369 | 0 |
| segment_relation_retained_swsd_count | 23,556 | 23,413 | -143 |
| segment_relation_failed_count | 0 | 0 | 0 |

`segment_relation_mixed_count=369` 表示同时存在 RCSD 替换与 SWSD 保留的 Segment relation；两套正式基线数量一致。

## RCSD Road 替换率

| 指标 | 未人工标注 | 人工标注 | 人工标注 - 未人工标注 |
|---|---:|---:|---:|
| RCSD Road 总量 | 134,400 / 12,922.165km | 134,444 / 12,922.165km | +44 / 0.000km |
| Step2 可替换唯一 RCSD Road | 101,573 / 9,916.596km | 102,494 / 10,060.108km | +921 / +143.512km |
| Step2 可替换率 count / length | 75.5751% / 76.7410% | 76.2355% / 77.8516% | +0.6603 / +1.1106 pct |
| Step3 最终已替换 RCSD Road | 107,474 / 10,216.596km | 108,732 / 10,386.319km | +1,258 / +169.724km |
| Step3 最终替换率 count / length | 79.9658% / 79.0626% | 80.8753% / 80.3760% | +0.9095 / +1.3134 pct |
| Step3 最终未替换 RCSD Road | 26,926 / 2,705.569km | 25,712 / 2,535.845km | -1,214 / -169.724km |
| Step3 最终未替换率 count / length | 20.0342% / 20.9374% | 19.1247% / 19.6240% | -0.9095 / -1.3134 pct |

两套结果的 RCSD 总长度完全一致，但 Road count 相差 `44`，因此 count 维度同时受到道路表达数量变化影响。本页未对这 `44` 条差异逐 Road 审计，不将其直接解释为业务新增或具体拆分来源。正式总体收益同时报告 count 和 length，跨运行稳定性优先参考 length 替换率。

## 未替换 RCSD 5+1 归因

表中占比为各类里程占该版本全部未替换 RCSD 里程的比例。

| 分类 | 未人工标注 count / length / 占比 | 人工标注 count / length / 占比 | 人工标注 - 未人工标注 |
|---|---:|---:|---:|
| 1 RCSD超出SWSD Segment范围 | 574 / 51.217km / 1.89% | 569 / 49.608km / 1.96% | -5 / -1.610km |
| 2 SWSD范围内缺少有效替换证据 | 8,077 / 948.399km / 35.05% | 8,043 / 934.955km / 36.87% | -34 / -13.444km |
| 3 有替换证据但路口关联不完整 | 6,321 / 723.908km / 26.76% | 5,727 / 635.750km / 25.07% | -594 / -88.158km |
| 4 路口关联完整但RCSD不可替换 | 7,795 / 757.719km / 28.01% | 7,476 / 709.665km / 27.99% | -319 / -48.055km |
| 5 可替换范围内RCSD未落地 | 529 / 33.405km / 1.23% | 472 / 34.211km / 1.35% | -57 / +0.806km |
| 6 未归因/需人工审计 | 3,630 / 190.921km / 7.06% | 3,425 / 171.657km / 6.77% | -205 / -19.264km |
| 合计 | 26,926 / 2,705.569km / 100.00% | 25,712 / 2,535.845km / 100.00% | -1,214 / -169.724km |

### 根因5细分

| 子类 | 未人工标注 | 人工标注 | 人工标注 - 未人工标注 |
|---|---:|---:|---:|
| `5_replaceable_scope_not_consumed` | 306 / 19.660km | 257 / 15.928km | -49 / -3.733km |
| `5_T06_strategy_unlanded` | 223 / 13.744km | 215 / 18.283km | -8 / +4.539km |
| 根因5合计 | 529 / 33.405km | 472 / 34.211km | -57 / +0.806km |

根因5内部存在长度流转：`not_consumed` 已改善，但 `strategy_unlanded` 的平均 Road 长度增加，抵消后根因5总长度略升。后续评估根因5策略收益时，应继续使用 Road-level 流向核对“目标 Segment 已替换 / 其他 Segment 消费 / 仍未替换 / 转入其他子类”，不能只看 summary 净值。

## PPT 归因桶

| PPT 归因桶 | 未人工标注 | 人工标注 | 人工标注 - 未人工标注 |
|---|---:|---:|---:|
| `2_segment_replacement_prerequisite_unsatisfied` | 14,398 / 1,672.307km | 13,770 / 1,570.705km | -628 / -101.602km |
| `1_segment_rcsd_quality_unreplaceable` | 8,324 / 791.124km | 7,948 / 743.876km | -376 / -47.249km |
| `3_rcsd_outside_segment_scope` | 574 / 51.217km | 569 / 49.608km | -5 / -1.610km |
| `6_manual_audit` | 3,630 / 190.921km | 3,425 / 171.657km | -205 / -19.264km |

## 未替换 RCSD 5+1 分类定义

| 分类 | 字段值 | 中文指标名 | 业务含义 |
|---|---|---|---|
| 1 | `1_outside_swsd_segment_scope` | RCSD超出SWSD Segment范围 | RCSD 相比 SWSD 多出的路网表达，可能来自现实变化、SWSD 精简或覆盖范围差异。 |
| 2 | `2_swsd_scope_no_t06_evidence` | SWSD范围内缺少有效替换证据 | RCSD 位于 SWSD 范围内，但没有形成可供 T06 使用的有效替换证据。 |
| 3 | `3_evidence_scope_relation_incomplete` | 有替换证据但路口关联不完整 | 已有候选或替换证据，但路口锚定、pair/junction relation 或关联状态不完整。 |
| 4 | `4_relation_scope_not_replaceable` | 路口关联完整但RCSD不可替换 | 关系已进入 T06 作用域，但受连通性、双向性、路径或 plan 阻断等条件限制，未形成可替换结果。 |
| 5 | `5_replaceable_scope_unreplaced` | 可替换范围内RCSD未落地 | Segment 已进入可替换范围，但部分 RCSD 未被最终消费或策略尚未落地。 |
| 6 | `6_unattributed_manual_audit_without_dominant_class` | 未归因/需人工审计 | 当前规则无法稳定给出主导根因，需要结合地图、证据、关系和最终结果继续人工审计。 |

反向归因用于结构分析和优化排序，不等同于绝对根因判定；Road-level 结论需回到归因 CSV/GPKG 与 Step2/Step3 审计明细。

## 后续基线比对字段

- T05 人工消费：`T11_MANUAL input_count / relation_success_count / relation_failure_count`。
- T05 全局结果：`status_0_count`、`status_1_count`、`relation_graph_consumable_count`。
- Step2 relation：`relation_success_count`、`relation_failure_count`。
- Step2 可替换：`rcsd_candidate_count`、`replaceable_count`、`replacement_plan_ready_count`。
- Step2 RCSD 能力：`replaceable_rcsd_road_unique_count`、`replaceable_rcsd_road_unique_length_m`。
- Step3 Segment：`segment_relation_replaced_count`、`segment_relation_mixed_count`、`segment_relation_retained_swsd_count`、`segment_relation_failed_count`。
- 最终 RCSD：`replaced_rcsd_road_count/length_m`、`unreplaced_rcsd_road_count/length_m`。
- 正式归因：`by_final_attribution_class`、`by_final_attribution_subclass`、`by_ppt_attribution_class`。

## 质量与可追溯说明

- CRS 与坐标变换：T05 过程数据使用 `EPSG:3857`，`intersection_match_all` 输出为 `CRS84`；T06 和未替换归因空间计算统一为 `EPSG:3857`。
- 拓扑一致性：未替换归因是只读审计，不执行 silent geometry fix。两套 Step3 状态均为 `completed_with_topology_failures`，`topology_connectivity_fail_count=503`；`surface_topology_fail_count` 从 `314` 变为 `320`，人工标注收益不代表拓扑 QA 已通过。
- 几何语义：SWSD 几何定义候选和归因范围，RCSD 几何用于相交、覆盖和距离判断；最终归因先选择几何主归属 Segment，再应用 5+1 分类。
- 审计可追溯：本页记录两套正式 run root、分母、漏斗、替换率和最终归因；具体 Road/Segment 可回溯到 Step2 summary、Step3 compact summary、归因 CSV/GPKG 和 topology audit。
- 性能可验证：T05 summary 总耗时分别为 `352.877s` 和 `380.255s`。本页只归档用户提供的内网 summary，不代表在当前环境重新执行了内网任务。
