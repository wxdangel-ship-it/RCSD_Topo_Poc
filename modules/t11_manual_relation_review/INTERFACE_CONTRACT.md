# T11 - INTERFACE_CONTRACT

## 定位

本文件是 `t11_manual_relation_review` 的稳定接口契约。T11 消费既有 T10 Case root，输出人工 relation / anchor 修复候选，不改变上游产物。

## 1. Callable

```python
extract_t11_relation_repair_candidates(
    *,
    t10_case_root: Path,
    out_root: Path,
    case_id: str = "605415675",
    existing_manual_csv_path: Path | None = None,
) -> T11RelationRepairArtifacts
```

### 输入

| 参数 | 含义 |
|---|---|
| `t10_case_root` | 已冻结或已完成的 T10 Case 目录，例如 `<run_root>/cases/605415675`。 |
| `out_root` | T11 输出根目录。callable 会在其下创建 `<run_id>/`。 |
| `case_id` | CaseID，默认 `605415675`。 |
| `existing_manual_csv_path` | 可选，既有人工审计 CSV。T11 仅按 `target_id` 带入 `manual_relation_type / selected_ids / comment`，不解释为空行。 |

T11 按文件名和常规 T10 layout 探测输入，不要求调用方传入 T05/T06 子目录。缺失输入按空证据处理；`t10_case_root` 不存在时直接失败。

### 输出

目录：

```text
<out_root>/<run_id>/
```

文件：

| 文件 | 用途 |
|---|---|
| `t11_relation_repair_candidates.csv` | 候选主表，面向审计和排序。 |
| `t11_relation_repair_candidates.gpkg` | 候选空间图层，几何为 SWSD final node 点。 |
| `t11_manual_relation_template.csv` | 人工填写模板。 |
| `t11_segment_anchor_manual_audit.csv` | 全量 Segment anchor 人工审计主表，字段精简并保留既有人工填写。 |
| `t11_segment_anchor_manual_template.csv` | 与主表同候选集的空白人工填写模板。 |
| `t11_unreplaced_segment_junctions_without_1v1_relation_success.csv` | Segment 级人工审计表；仅从 T06 Step3 未替换 Segment 中列出未成功建立可消费 1V1 relation 的有效路口节点。 |
| `t11_unreplaced_segment_junctions_without_1v1_relation_success.gpkg` | 上述 relation 缺口审计表的空间图层，几何为 SWSD Segment。 |
| `t11_unreplaced_segment_junctions_without_1v1_relation_success.xlsx` | 上述 relation 缺口审计表的 Excel 文本格式版本；所有单元格按文本写入，避免长 ID 被表格软件改格式。 |
| `t11_segments_all_1v1_relation_success_but_not_replaced.csv` | Segment 级审计表；列出所有语义路口已 1v1 relation 成功且可消费，但 T06 Step3 仍未替换成功的 Segment。 |
| `t11_segments_all_1v1_relation_success_but_not_replaced.gpkg` | 上述 Segment 审计表的空间图层，几何为 SWSD Segment。 |
| `t11_segments_all_1v1_relation_success_but_not_replaced.xlsx` | 上述 Segment 审计表的 Excel 文本格式版本；所有单元格按文本写入，避免长 ID 被表格软件改格式。 |
| `t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.csv` | 三表拆分中的表 2；未替换 Segment 中所有有效路口均有证据，但存在有证据路口未成功 1V1 relation。 |
| `t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.gpkg` | 表 2 的空间图层，几何为 SWSD Segment。 |
| `t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.xlsx` | 表 2 的 Excel 文本格式版本，`manual_relation_type` 带下拉选项。 |
| `t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.csv` | 三表拆分中的表 3；未替换 Segment 中存在无证据有效路口，字段与表 2 完全相同。 |
| `t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.gpkg` | 表 3 的空间图层，几何为 SWSD Segment。 |
| `t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.xlsx` | 表 3 的 Excel 文本格式版本，`manual_relation_type` 带下拉选项。 |
| `t11_relation_repair_candidate_summary.json` | 输入路径、参数、数量统计、Top 候选和质量检查摘要。 |

## 2. 脚本入口

```bash
.venv/bin/python scripts/t11_extract_relation_repair_candidates.py \
  --t10-case-root <T10_CASE_ROOT> \
  --out-root outputs/_work/t11_minimal_relation_candidates_605415675 \
  --case-id 605415675 \
  --existing-manual-csv <EXISTING_MANUAL_CSV>
```

该脚本只包装 callable，不新增业务规则。

## 3. 候选主表字段

```text
case_id
target_id
kind_2
has_evd
is_anchor
candidate_category
candidate_reason
source_modules
t05_status
t05_reason
graph_consumable
graph_consumability_status
has_rcsd_in_segment_scope
machine_candidate_rcsdnode_ids
machine_candidate_rcsdroad_ids
affected_segment_count
affected_segment_total_length_m
affected_segment_ids
rejected_segment_count
t06_reject_reasons
root_cause_categories
priority_rank
priority_score
recommended_manual_relation_types
```

## 4. 人工模板字段

```csv
case_id,target_id,manual_relation_type,selected_ids,comment
```

`manual_relation_type` 允许值：

```text
1v1_rcsd_junction
1vN_rcsd_junction
1v1_rcsd_road
1vN_rcsd_road
no_valid_relation
uncertain
```

模板不预填 `manual_relation_type`、`selected_ids` 或 `comment`。

## 5. Segment Anchor 人工审计字段

`t11_segment_anchor_manual_audit.csv` 是当前人工审计主入口，输出全量候选而不是 Top 截断。人工可只填写局部行；未填写行保持空值。

```text
anchor_priority_rank
case_id
target_id
anchor_gap_category
review_focus
highest_priority_segment_id
highest_priority_segment_length_m
affected_segment_count
affected_segment_total_length_m
affected_segment_ids
node_roles
segment_pair_nodes
segment_junc_nodes
kind_2
has_evd
is_anchor
t05_status
t05_reason
graph_consumable
graph_consumability_status
has_rcsd_in_segment_scope
machine_candidate_rcsdnode_ids
machine_candidate_rcsdroad_ids
t06_reject_reasons
review_hint
recommended_manual_relation_types
manual_relation_type
selected_ids
comment
```

候选集来自 Segment 的 `pair node` 与 `junc node`，排除已正确建立 1v1 anchor 且 relation graph 可消费的路口。`junc node` 还会基于 `t01/roads.gpkg` 复算非提右 incident road 数：剔除 `formway` bit 128 的提前右转 Road 后，若 incident road 数不超过 2，则不作为路口锚点候选。未人工填写且 `has_rcsd_in_segment_scope=0` 的行不进入新表；已人工填写的行，包括 `selected_ids=NULL` 或人工新增行，继续保留。排序优先考虑：

1. 未人工填写。
2. `has_rcsd_in_segment_scope=1`。
3. `highest_priority_segment_length_m` 降序。
4. `affected_segment_count` 降序。
5. anchor 失败等级与 target id。

## 6. 未替换 Segment 的 Relation 缺口审计字段

`t11_unreplaced_segment_junctions_without_1v1_relation_success.csv` 是面向人工填写的 Segment 顺序审计表。它不再从全局 relation 缺口节点出发，而是以 T06 Step3 `relation_status != replaced` 的 Segment 为分母；只列出这些未替换 Segment 中没有成功建立可消费 1V1 relation 的有效 `pair node` / `junc node`。

有效节点口径：

- `pair node` 始终参与审计。
- `junc node` 会按 `t01/roads.gpkg` 复算非提右 incident road 数；剔除 `formway` bit 128 的提前右转 Road 后，若 incident road 数不超过 2，则不作为路口锚点。

字段：

```text
segment_rank_by_length
case_id
swsd_segment_id
segment_length_m
sgrade
segment_pair_nodes
segment_junc_nodes
node_role
target_id
relation_gap_category
relation_gap_reason
t05_status
t05_base_id
graph_consumable
graph_consumability_status
has_rcsd_in_segment_scope
machine_candidate_rcsdnode_ids
machine_candidate_rcsdroad_ids
t06_step2_plan_status
t06_step2_reject_reasons
t06_root_cause_categories
t06_step3_relation_status
t06_step3_relation_reason
manual_relation_type
selected_ids
comment
```

排序按 `segment_length_m desc, swsd_segment_id asc, node_role asc, target_id asc`。调用方提供既有人工 CSV 时，T11 按 `target_id` 带入 `manual_relation_type / selected_ids / comment`，便于保留局部人工标注。

该表与 `t11_segments_all_1v1_relation_success_but_not_replaced.csv` 互补：在 Step3 输出完整的前提下，二者按 `swsd_segment_id` 合并后应等于全量 `relation_status != replaced` Segment 集合，且不应包含 `relation_status=replaced` 的 Segment。

## 7. 三表拆分的 Segment 审计输出

T11 固定输出三张 Segment 级表：

1. `t11_segments_all_1v1_relation_success_but_not_replaced.*`：未被替换 Segment，所有有效路口均有可消费 1V1 relation。
2. `t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.*`：未被替换 Segment，所有有效路口均存在证据；每个有证据但未成功 1V1 relation 的路口一行，是人工审计重点表。
3. `t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.*`：未被替换 Segment，至少一个有效路口无证据；字段与表 2 完全相同，但人工审计价值按 50m RCSD 上下文排序。

表 2 与表 3 字段完全相同：

```text
segment_priority_rank
case_id
swsd_segment_id
segment_length_m
segment_priority_bucket
sgrade
segment_pair_nodes
segment_junc_nodes
segment_relation_success_node_ids
segment_relation_gap_node_ids
segment_no_evidence_node_ids
node_role
target_id
has_evd
is_anchor
relation_gap_category
relation_gap_reason
t05_status
t05_base_id
graph_consumable
graph_consumability_status
t05_source_modules
t05_scenes
t05_reasons
t03_scene_hint
t04_scene_hint
upstream_no_rcsd_reference_hint
rcsd_50m_hint
rcsd_50m_feature_count
rcsd_50m_nearest_ids
rcsd_50m_nearest_distance_m
has_rcsd_in_segment_scope
machine_candidate_rcsdnode_ids
machine_candidate_rcsdroad_ids
t06_step2_plan_status
t06_step2_reject_reasons
t06_root_cause_categories
t06_step3_relation_status
t06_step3_relation_reason
duplicate_target_first_segment_id
duplicate_target_policy
manual_row_consumable
manual_relation_type
selected_ids
comment
```

表 2 排序按 Segment 长度降序。表 3 先按 `segment_priority_bucket` 排序，再按 Segment 长度降序：

- `0_no_evidence_but_all_nodes_have_context`：Segment 下所有有效路口均满足有证据、有 relation，或无证据但 50m 内存在 RCSD。
- `1_no_evidence_with_partial_context`：存在无证据且 50m 内无 RCSD 的路口，但 Segment 内仍有有证据路口或 50m 内有 RCSD 的路口。
- `2_no_evidence_no_rcsd_50m_low_priority`：无证据路口周围 50m 内缺少 RCSD 上下文，优先级较低。

表 2/3 会保留重复路口行以保证 Segment 完整性。若同一 `target_id` 在前序 Segment 已出现，后序 Segment 行会设置 `duplicate_target_policy=duplicate_of_segment:<segment>;do_not_consume_duplicate_row`、`manual_row_consumable=0`，并在 `comment` 填入提示；后续消费应忽略该重复行。

`manual_relation_type` 在 Excel 中提供下拉选项：

```text
1v1_rcsd_junction
1vN_rcsd_junction
1v1_rcsd_road
1vN_rcsd_road
no_valid_relation
uncertain
NULL
```

其中 `NULL` 表示人工认为该行事实无 RCSD 可关联，或数据复杂到无法标注；该值是审计标记，不等同于可直接消费的正式 relation 类型。

## 8. Segment 全 1V1 成功但未替换审计字段

`t11_segments_all_1v1_relation_success_but_not_replaced.csv` 用于快速审计“relation 看起来已经对，但 Segment 仍 retained_swsd / 未替换”的问题。入选条件：

- Segment 的所有有效 `pair node` / `junc node` 均满足 T05 `relation_status=0`、`base_id` 非 0、`graph_consumable=1`、`graph_consumability_status=base_node_graph_incident`。
- T05 junctionization audit 中 `multi_base_relation != 1`。
- T06 Step3 `relation_status != replaced` 或缺失 Step3 relation 行。

字段：

```text
segment_rank_by_length
case_id
swsd_segment_id
segment_length_m
sgrade
segment_pair_nodes
segment_junc_nodes
relation_target_ids
relation_base_ids
all_junction_relation_success_1v1_consumable
segment_has_t06_rcsd_scope
t06_step2_plan_status
t06_step2_reject_reasons
t06_root_cause_categories
t06_step3_relation_status
t06_step3_relation_reason
audit_comment
```

排序按 `segment_length_m desc, swsd_segment_id asc`。该表不要求人工填写 relation，只保留 `audit_comment` 作为快速问题备注。`.xlsx` 与 `.csv` 行列一致，但所有单元格均按文本写入。

## 9. 质量边界

- CRS：输出 GPKG 沿用 final nodes CRS，summary 记录 final nodes 与 Segment CRS。
- 拓扑：T11 不修改几何，不执行 silent fix。
- 几何语义：候选点表示待人工判断的 SWSD 语义路口；RCSD 候选以 ID 字段追溯。
- 审计：每行保留 source modules、T05 状态、T06 reject reasons、root cause 和 affected Segment。
- 性能：summary 记录输入规模和耗时。
