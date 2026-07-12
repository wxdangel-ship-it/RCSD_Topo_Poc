# RCSD Road Ownership 输出契约草案

本契约是本轮 SpecKit 变更目标，不替代当前模块源事实；实现完成并通过回归后，必须同步写入 T01/T06 `INTERFACE_CONTRACT.md`。

## 1. T01 `segment.gpkg`

新增字段：

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `segment_type` | string | 是 | `normal / advance_right` |
| `segment_build_source` | string | 是 | 保留现有来源；提右使用稳定新来源值 |

### normal

- 保持现有 `pair_nodes / junc_nodes / roads / sgrade` 语义。

### advance_right

- `roads` 非空，且全部 Road 满足正式提右属性规则；
- `pair_nodes=[]`；
- `junc_nodes=[]`；
- 不进入 T06 普通锚定与 Step2 replaceable 分母；
- 不允许与 normal Road 混合。

## 2. `t06_rcsd_road_ownership.*`

稳定载体：GPKG/CSV；JSON feature dump 继续遵守现有输出开关。

每个原始 T05 `rcsdroad_out.id` 恰好一行：

```text
rcsd_road_id
owner_type
owner_key
owner_segment_id
owner_segment_type
connectivity_group_id
related_segment_ids
candidate_segment_ids
ownership_status
ownership_confidence
ownership_evidence_types
ownership_reason
replacement_status
replacement_action
final_road_ids
risk_flags
```

约束：

- `rcsd_road_id` 唯一；
- `owner_type=single_segment` 时 `owner_segment_id` 必须唯一且非空；
- `owner_type=multi_segment_connectivity` 时 `connectivity_group_id` 必须非空，`related_segment_ids` 至少两个；
- `owner_type=reality_change` 时必须有现实变更证据；
- `owner_type=unresolved_exception` 时必须有证据耗尽字段和人工复核标记；
- `final_road_ids` 只引用最终存在的 F-RCSD Road。

## 3. `t06_multi_segment_connectivity_group.*`

每个 group 一行：

```text
connectivity_group_id
connectivity_kind
rcsd_road_ids
final_road_ids
terminal_node_ids
related_segment_ids
terminal_attachment_evidence
connectivity_status
replacement_status
blocked_reason
risk_flags
```

约束：

- 同一原始 RCSD Road 只能属于一个 connectivity group；
- `attachable + used` 计入 RCSD Road 替换指标；
- 所有 connectivity group 固定不计 Segment 替换指标；

## Final F-RCSD Topology 指标

- `topology_connectivity_fail_count`：兼容审计 fail 行数，不作为最终成果错误数；
- `topology_audit_fail_row_count`：与上述兼容字段同值的显式名称；
- `final_frcsd_topology_fail_count`：按 `final_topology_object_key` 去重后的正式最终 topology fail；
- `final_frcsd_segment_transition_fail_count`：SWSD Segment 内及 Segment-Segment 通行关系未在最终 F-RCSD 保持；
- `final_frcsd_independent_attachment_fail_count`：最终 Road、patch 或提右对象形成独立/单侧挂接。

正式指标不得消费 relation failed、coverage、source consistency 或仅映射证据缺失；这些审计行继续保留，但 `counts_in_final_frcsd_topology_fail=false`。
- `unattachable` 仍保留 group 归属；
- 无法确定 `related_segment_ids` 时不得生成正式 group，应转 unresolved。

## 4. `t06_segment_construction_audit.*`

普通 Segment 每个 id 一行：

```text
swsd_segment_id
pair_anchor_status
junc_anchor_status
main_corridor_status
side_road_status
construction_class
step2_replaceable
segment_replacement_status
root_cause
```

`construction_class`：

- `2a_complete`；
- `2b_main_complete_side_missing`；
- `2c_not_replaceable`；
- `pair_only`；
- `pair_incomplete`。

## 5. `t06_step3_swsd_frcsd_segment_relation.*`

兼容现有 T09 carrier 消费，不把 carrier 引用等同于 ownership。

新增或明确字段：

```text
owned_frcsd_road_ids
connectivity_group_ids
related_connectivity_road_ids
```

- `owned_frcsd_road_ids` 只包含该 Segment 单独 owner 的最终 Road；
- `related_connectivity_road_ids` 可在多个 Segment relation 中重复引用，但 ownership 只存在于 connectivity group；
- 现有 `frcsd_road_ids` 可在兼容期继续表达所有可消费 carrier；
- 正式 ownership 指标只读取 `t06_rcsd_road_ownership.*`，不得从重复 carrier 引用反推 owner。

## 6. replacement plan

`execution_action` 扩展或重解释为：

```text
replace_segment
replace_main_retain_side
include_connectivity
hold
include_context
```

- `replace_segment` 只允许 Step2 formal replaceable normal Segment；
- `replace_main_retain_side` 只允许主干完整、附属侧路缺失；
- `include_connectivity` 只作用于 connectivity group，不改变 Segment replaced 状态；
- `group_probe_status=passed` 不能单独产生 `replace_segment`。

## 7. summary 指标

必须同时输出：

```text
normal_segment_replaceable_count
normal_segment_replaced_count
advance_right_segment_count
advance_right_segment_used_count
rcsd_road_total_count
rcsd_road_used_count
rcsd_road_used_length_m
connectivity_group_count
connectivity_group_used_count
connectivity_rcsd_road_used_count
reality_change_rcsd_road_count
unresolved_exception_rcsd_road_count
ownership_duplicate_count
ownership_missing_count
```

指标约束：

- multi-segment connectivity 只进入 RCSD Road used 指标；
- 普通 Segment 历史分母不因新增提右 Segment 改写；
- 提右 Segment 初期单列；
- summary 必须与最终 GPKG/CSV 回算一致。

## 8. GIS 与审计

- 所有输出 CRS 与输入分析 CRS 一致并记录；
- 不得 silent geometry/topology fix；
- ownership 记录必须可追溯到输入 RCSD Road、Segment、relation、plan、参数和最终 Road；
- copy-on-write split 必须保留原始 Road 到 final Road 的映射。
