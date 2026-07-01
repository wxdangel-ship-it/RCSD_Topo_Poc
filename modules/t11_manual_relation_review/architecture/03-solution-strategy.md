# 03 Solution Strategy

## 1. 证据优先

T11 不参与上游生产链，只读取已完成 T10 Case root。输入探测顺序为：

1. T10 manifest / 常规 layout 下的 T05 Phase2 输出。
2. T06 Step1 final fusion units。
3. T06 Step2 problem registry、rejected、buffer rejected、replacement plan 和 repair candidates。
4. T01 Segment build table、Segment 几何与 final SWSD nodes。

## 2. 聚合策略

T06 的 Segment 证据是主线。T11 先把 T06 行映射到 `swsd_segment_id`，再通过 pair/junc/failed/pair-anchor 字段和 Step1 final fusion units 聚合到 SWSD `target_id`。

每个 `target_id` 聚合：

- 影响 Segment 集合与总长度。
- T06 reject reasons 和 root cause categories。
- T05 relation / graph consumability 状态。
- RCSDNode / RCSDRoad 机器候选 ID。
- final nodes 上的 `kind_2 / has_evd / is_anchor`。

Segment anchor 审计另建一条精简聚合链路：

- 以 T06/T01 可追溯的 Segment 为 scope。
- 从 Segment `pair node` 与 `junc node` 生成候选 target。
- 用 T01 Segment build table 补齐 pair/junc 节点角色，用 T06 Step1/Step2 行补齐 reject 语义与机器候选。
- 对 `junc_node` 复算 `t01/roads.gpkg` 的非提右 incident road 数，剔除 `formway` bit 128 的提前右转 Road 后若只剩不超过 2 条 Road，则视为非路口锚点，不进入候选。
- 排除已正确建立 1v1 anchor 且 relation graph 可消费的 target。
- 对同一 target 聚合所有受影响 Segment，并记录最高优先级 Segment。

Segment 全 1V1 成功但未替换审计另建 Segment 级链路：

- 以 T06 Step1 final fusion units 为 Segment 集合。
- 校验 Segment 的所有 `semantic_node_set` 节点均已形成 T05 可消费 1v1 relation。
- 再与 T06 Step3 `t06_step3_swsd_frcsd_segment_relation` 对齐，只保留 `relation_status != replaced` 或缺失 Step3 relation 的 Segment。
- 聚合 Step2 plan / reject / problem registry 的状态、原因和 root cause，便于快速区分 corridor、方向性、RCSD 质量或执行问题。

## 3. 分类策略

分类来自现有证据字段，不反推新字段语义：

- `invalid_pair_relation_status`、`relation_mapping` 等进入 `relation_missing_or_invalid`。
- `graph_consumable=0` 进入 `relation_graph_unconsumable`。
- `pair_anchor`、`required_nodes_disconnected`、`not_connected` 等进入 `required_nodes_disconnected_or_pair_anchor_issue`。
- `has_evd` 为空或否，且 Segment 范围存在 RCSD 候选，进入 `no_evidence_but_rcsd_present_in_segment_scope`。
- 其余保留为 `uncertain_upstream_or_data_issue`。

同一候选可以拥有多个分类。

## 4. 排序策略

候选按以下规则排序：

1. `affected_segment_count` 降序。
2. `affected_segment_total_length_m` 降序。
3. `has_rcsd_in_segment_scope=1` 优先。
4. `has_machine_candidate=1` 优先。

`priority_score` 只服务于同一排序口径的快速查看，不作为业务阈值。

Segment anchor 人工审计按以下规则排序：

1. 未人工填写的候选优先。
2. Segment scope 内存在 RCSD 数据的候选优先。
3. `highest_priority_segment_length_m` 降序。
4. `affected_segment_count` 降序。
5. anchor gap 严重程度与 `target_id`。

因此未人工填写且无 RCSD 上下文的路口不再进入新审计表，避免挤占可立即依据现有 RCSD 信息判断的候选。已人工填写的行，包括 `selected_ids=NULL` 或人工新增行，继续保留并排在后部。

## 5. 输出策略

CSV 是人工审计主入口；GPKG 用于 QGIS 叠加；summary 用于复核输入路径、统计和质量检查。T11 输出不写入 `outputs/baselines/`，默认落在 `outputs/_work/` 下。

`t11_segment_anchor_manual_audit.csv` 输出全量候选，不做 Top 截断。调用方提供既有人工 CSV 时，T11 只带入 `manual_relation_type / selected_ids / comment` 三列，未填写行保持空值，便于人工分批标注。

`t11_unreplaced_segment_junctions_without_1v1_relation_success.csv/gpkg/xlsx` 固定输出以 T06 Step3 未替换 Segment 为分母的 relation 缺口审计结果。该表只列有效 `pair node` / `junc node` 中未成功建立可消费 1V1 relation 的节点，排序按 Segment 长度优先，适合作为人工标注入口。

`t11_segments_all_1v1_relation_success_but_not_replaced.csv/gpkg/xlsx` 固定输出 Segment 级审计结果。该表不承担 relation 人工回填，只为定位“relation 已成功但替换仍失败”的下游问题；`.xlsx` 以文本单元格写出，避免长 ID 被表格软件自动改格式。

上述两张 Segment 级表在 Step3 relation 输出完整时互补：按 `swsd_segment_id` 合并后应等于全量 `relation_status != replaced` Segment，不应混入已替换 Segment。

三表拆分输出进一步把未替换 Segment 固定拆为：

1. 所有有效路口均有可消费 1V1 relation。
2. 所有有效路口均存在证据，但至少一个有证据路口未成功 1V1 relation。
3. 至少一个有效路口无证据。

表 2/3 使用完全一致的字段，均按 `Segment + target_id` 出行；同一 target 在前序 Segment 已出现时，后序重复行保留以维持 Segment 完整性，但标记 `manual_row_consumable=0` 和 `duplicate_target_policy`，后续消费不应读取该重复行。

T03/T04 场景只作为人工参考提示写入 `t03_scene_hint / t04_scene_hint / upstream_no_rcsd_reference_hint`，不固化为 T11 强判定。无证据节点的 50m RCSD 查询基于输出 CRS 中的几何距离，写入 `rcsd_50m_*` 字段；T11 只读几何，不做 snap、repair 或拓扑修改。

## 6. 人工 Excel 重跑策略

`scripts/t11_run_manual_rerun.py` 是 T11 人工结果消费的编排入口，不新增 T05/T06 业务规则。它先读取三张 Segment 审计 Excel，把可执行人工 relation 行合并为 `t11_manual_relation_merged.csv`，再把该 CSV 交给既有 T05 `--t11-manual-relation` 参数，随后串联 T06 Step1/2 与 Step3 并输出修复前后指标对比。

导入策略：

- 表 1/2/3 都会被扫描，允许人工只填写局部行。
- 只消费 `1v1_rcsd_junction / 1vN_rcsd_junction / 1v1_rcsd_road / 1vN_rcsd_road`。
- `NULL`、空白、`no_valid_relation`、`uncertain` 仅作为人工审计标记，不进入 T05。
- `manual_row_consumable=0` 的重复路口行不进入 T05。
- 同一 `target_id` 只消费首个可执行人工行，避免同一语义路口被多个 Segment 重复回灌。
- 输出全部写入新的 `_work` run root；输入 T10 Case root 与 T11 审计目录只读。
