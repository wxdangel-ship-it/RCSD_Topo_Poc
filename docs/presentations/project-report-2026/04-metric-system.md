# 汇报指标体系

本文档用于把现有模块产物整理成汇报主线指标。它不是新的业务契约；正式数字必须回到真实 run root、summary、audit CSV/JSON 和人工确认记录。

## 1. 当前指标分层

| 层级 | 指标体系 | 责任模块 | 汇报作用 |
|---|---|---|---|
| L0 总览指标 | RCSD 替换率、拓扑连通率 | T06 | 直接回答“最终融合效果如何”。 |
| L1 漏斗指标 | 路口锚定指标体系 | T05 | 解释 Segment 替换的前置条件是否充分。 |
| L1 漏斗指标 | Segment 替换率指标体系 | T06 | 解释从 SWSD Segment 到 F-RCSD 替换的收益与损失。 |
| 后续讨论 | restriction 恢复指标 | T09 | 后续用于通行能力恢复专题，暂不纳入主要指标体系。 |

`Movement` 只作为 SWSD 道路结构能力，不作为高层展示指标。当前主线先聚焦“路口是否能锚定、Segment 是否能替换、最终 RCSD 骨架替换了多少、拓扑是否连通”。

## 2. L0 总览指标

### 2.1 RCSD 替换率

| 指标 | 建议口径 | 当前满足度 | 现有证据 | 需要完善 |
|---|---|---|---|---|
| RCSD road 替换率 | 被替换为 RCSD 的 SWSD Road 数 / 可替换分母 Road 数 | 部分满足 | T06 Step3 已有 `removed_swsd_road_count`、`added_rcsd_road_count`、`t06_step3_swsd_frcsd_segment_relation.*` | 需要 T06 明确 road 分母，并直接输出 `road_replacement_rate`。 |
| RCSD 里程替换率 | 被替换为 RCSD 的 SWSD 里程 / 可替换分母 SWSD 里程 | 不满足为顶层指标 | T06 Step2 有 RCSD 侧 `rcsd_road_total_length_m / replaceable_rcsd_road_unique_length_m` 契约；Step3 有 `unreplaced_rcsd_road_length_m` | 需要 T06 Step3 汇总 SWSD 分母里程、已替换 SWSD 里程、保留 SWSD 里程、RCSD 承载里程。 |
| RCSD 替换 Segment 数 | `relation_status in {replaced, replaced+retained_swsd}` 的 Segment 数 | 计数满足，替换率待补 | T06 Step3 relation 明细；summary 有 `segment_relation_replaced_count` 与 `segment_relation_mixed_count` | 可选增加 `segment_replacement_success_count` 和总替换率，减少 PPT 二次计算。 |

建议 L0 首屏用 road 和里程替换率作为主指标，Segment 替换率作为辅助解释。road / 里程能更接近业务效果，Segment 更适合解释流程漏斗。

### 2.2 拓扑连通率

| 指标 | 建议口径 | 当前满足度 | 现有证据 | 需要完善 |
|---|---|---|---|---|
| Segment 拓扑连通率 | Step3 relation 中拓扑审计 pass 的 Segment 数 / 参与拓扑审计的 Segment 数 | 部分满足 | `t06_step3_topology_connectivity_audit.*` 和 summary 的 `topology_connectivity_*_count` | 需要 T06 输出按 Segment 去重后的 pass/warn/fail 统计，避免按 audit row 误当 Segment 数。 |
| Road 拓扑连通率 | F-RCSD 中端点完整、source 一致、可连通的 Road 数 / F-RCSD Road 总数 | 部分满足 | topology audit 已有 road-node integrity、source consistency 等审计层 | 需要 T06 定义 road 级连通口径并输出去重 road 统计。 |

拓扑连通率可以作为 L0 第二指标，但需要先确认业务口径：是“无 hard fail 的 Segment 占比”，还是“F-RCSD Road 级端点完整/连通占比”。建议 PPT 第一版先写为“拓扑质量通过率（口径待定）”，等 T06 顶层统计补齐后再定名。

## 3. L1 路口锚定指标体系

责任模块：T05。T05 应提供全量指标数据，T07/T03/T04 只作为来源贡献和根因解释。

| 指标 | 建议口径 | 当前满足度 | 现有字段 / 文件 | 需要完善 |
|---|---|---|---|---|
| 有效语义路口数量 | `kind_2 in {4,8,16,64,128,2048}` 的 SWSD 语义路口数，按 `mainnodeid` 优先去重 | 满足 | `t05_junction_anchor_funnel_summary.json` 的 `top_level_funnel.semantic_junction_total` | 无。 |
| 有效语义路口有证据数量 | 上述有效语义路口中，被 T07/T03/T04 任一 relation evidence 覆盖的数量 | 满足 | `top_level_funnel.evidence_junction_total` | 无。 |
| 有证据语义路口 relation 发布成功数量 | 有 evidence 且最终 T05 relation `status=0` 的语义路口数量 | 满足 | `relation_success_total` | 表达 T05 锚定关系生产能力，不直接等价于下游可替换能力。 |
| 有证据语义路口 relation 图可消费数量 | relation 发布成功，且 `base_id` 能被最终 `rcsdnode_out / rcsdroad_out` 的 RCSD road graph 消费的语义路口数量 | 满足 | `graph_consumable_success_total`、`graph_unconsumable_success_total`、`relation_graph_consumability_audit.*` | 作为 T06 可消费锚定数量。与 `relation_success_total` 的差值主要解释为无 RCSD 或 RCSD 节点无法落到最终 road graph 的场景。 |
| 按来源模块统计 | T07/T03/T04 各自输入、成功 evidence、T05 采纳、T05 后成功/失败 | 满足 | `t05_junction_anchor_source_funnel.csv` | 无，但需提示来源模块不是互斥集合，不能直接相加。 |
| 按路口类型统计 | 按 `kind_2` 或业务类型统计有效路口、有证据、成功锚定、1V1 relation | 不满足为顶层汇总 | T05 surface / relation / audit 中保留 `kind_2` 或可从 nodes 反查 | 需要 T05 增加 `kind_2_funnel` 或 `junction_type_funnel`。 |
| 具备 1V1 relation 数量 | 可被 T06 消费的 `status=0 / base_id>0` SWSD-RCSD relation 数量 | 基本满足 | `relation_success_total`、`graph_consumable_success_total`，以及 `intersection_match_all.geojson` | 汇报中建议拆成“relation 发布成功”和“relation 图可消费”两级，避免把无 RCSD 场景误算为 T06 可消费能力。 |
| relation 质量问题 | 基数错误、blocking error、图不可消费 | 满足 | `relation_cardinality_errors.*`、`blocking_errors.*`、`relation_graph_consumability_audit.*` | 无。 |

结论：T05 当前已能支撑路口锚定总漏斗和来源模块漏斗；路口锚定主线应拆成“relation 发布成功”和“relation 图可消费”两级。两级差值主要用于解释无 RCSD 或 RCSD 无法落到最终 road graph 的质量损失。缺口主要是“按不同类型 kind_2 / junction_type 的漏斗统计”。

## 4. L1 Segment 替换率指标体系

责任模块：T06。T06 应提供从 Segment 分母到最终替换成功的全量指标体系。

| 指标 | 建议口径 | 当前满足度 | 现有字段 / 文件 | 需要完善 |
|---|---|---|---|---|
| Segment 总体数量 | T01 `segment.gpkg` 输入 T06 的 Segment 数 | 满足 | T06 Step1 `input_segment_count` | 无。 |
| Segment 所有路口具有证据数量 | eligibility 集合内全部语义路口 `has_evd=yes` 的 Segment 数 | 基本满足 | T06 Step1 `evd_candidate_count / swsd_candidate_count` | 需要在命名上明确它是“全部 required eligibility 节点有证据”，其中部分 junc 可按规则豁免或脱挂。 |
| Segment 所有路口均锚定数量 | 具备进入 T06 Step2 替换审查资格的 Segment 数 | 满足 | T06 Step1 `final_fusion_unit_count / swsd_final_fusion_unit_count` | 无，但需说明这使用 T04 downstream `final_swsd_nodes.is_anchor`，不是直接读取 T05 relation。 |
| Segment 两端具备可用 relation 数 | pair required nodes 在 T05 中 `status=0 / base_id>0` 的 Segment 数 | 满足 | T06 Step2 `relation_success_count` | 建议把该指标纳入正式漏斗命名，因为它比 Step1 anchor 更贴近 T06 可消费 relation。 |
| RCSD 符合替换要求数量 | 通过 Step2 硬审计、特殊组门控、replacement plan 的 Segment 数 | 满足 | T06 Step2 `replaceable_count`、`replacement_plan_ready_count` | 无。 |
| 最终替换成功 Segment 数 | Step3 relation 中 `replaced` 与 `replaced+retained_swsd` | 计数满足，替换率待补 | `t06_step3_swsd_frcsd_segment_relation.*`；summary 有 `segment_relation_replaced_count` 与 `segment_relation_mixed_count` | 可选增加最终替换成功率顶层字段。 |
| 最终保留 / 失败数量 | Step3 relation 中 `retained_swsd / failed` | 满足 | `segment_relation_retained_swsd_count`、`segment_relation_failed_count` | 无。 |
| 损失原因 | Step1 / Step2 拒绝原因、problem registry、failure business audit | 满足 | `reject_reason_counts`、`buffer_reject_reason_counts`、`problem_registry_status_counts`、`t06_rcsd_segment_failure_business_audit.*` | 无。 |

结论：T06 当前已经能支撑 Segment 漏斗主链；`segment_relation_mixed_count` 已能呈现混合替换数量，剩余缺口主要是“最终成功替换率”和“road / 里程替换率的顶层汇总”。

## 5. 需要模块完善的内容

### 5.1 T05 需要完善

| 优先级 | 完善项 | 目的 |
|---|---|---|
| P0 | 将路口锚定指标拆为 `relation_success_total` 和 `graph_consumable_success_total` 两级 | 同时表达 T05 relation 生产能力和 T06 可消费能力，并将差值解释为无 RCSD / RCSD 无法落到最终 road graph 的质量损失。 |
| P1 | 新增按 `kind_2` / `junction_type` 的漏斗汇总 | 支撑“不同类型的数量”展示。 |
| P1 | 在 `t05_junction_anchor_funnel_summary.json` 中直接输出 `one_to_one_relation_total` / `t06_consumable_relation_total` 等业务命名字段 | 减少 PPT 二次解释成本。 |

### 5.2 T06 需要完善

| 优先级 | 完善项 | 目的 |
|---|---|---|
| P0 | Step3 summary 增加 `segment_replacement_success_count`、`segment_replacement_success_rate` | 让“最终替换成功 Segment 数 / 率”成为顶层字段；混合替换数量已由 `segment_relation_mixed_count` 暴露。 |
| P0 | 新增 L0 road 替换率汇总：road 分母、已替换 SWSD road 数、保留 SWSD road 数、RCSD 承载 road 数、替换率 | 支撑高层总览指标。 |
| P0 | 新增 L0 里程替换率汇总：SWSD 分母里程、已替换 SWSD 里程、保留 SWSD 里程、RCSD 承载里程、替换率 | 支撑高层总览指标。 |
| P1 | 新增按 Segment 去重的拓扑通过率：Segment pass/warn/fail 和 hard fail reason | 避免用 audit row count 误代表 Segment 连通率。 |
| P1 | 如需 road 级拓扑连通率，新增 F-RCSD road 去重 pass/warn/fail 统计 | 支撑“拓扑连通率（road）”。 |
| P1 | 在 Step1 summary 中把 `evd_candidate_count` 重命名或补充别名为 `all_required_junctions_have_evidence_segment_count` | 与汇报口径对齐，减少误读。 |

## 6. 暂缓纳入主指标体系

restriction 恢复后续单独讨论。当前可保留 T09 证据项，但不进入 L0 / L1 主线。

| 指标 | 现有证据 | 暂缓原因 |
|---|---|---|
| restored rule 数 | T09 `t09_swsd_field_rule_restoration_summary.json` | 不是当前主线。 |
| F-RCSD restriction 数 | T09 `t09_step3_frcsd_restriction_summary.json` | 后续作为通行能力专题。 |
| 投影跳过原因 | T09 `skipped_counts` | 后续用于质量问题闭环。 |
