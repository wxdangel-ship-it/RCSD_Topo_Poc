# Data Model: P04 高精骨架优先 Road Direct V3

## 1. HighPrecisionRoadUnit

一个父 SWSD Road下的 V3 发布单元。

| 字段 | 含义 |
|---|---|
| `v3_road_id` | V3 唯一 ID。共享物理 Road沿用父 ID；方向走廊使用版本化后缀。 |
| `parent_swsd_unit_id` | 父 SWSD 语义 ID。 |
| `road_representation` | `shared_physical / directional_carriageway / sd_fallback`。 |
| `travel_side` | `shared / forward / reverse`；不作为主图例。 |
| `direction` | 发布通行方向编码，保持上游已确认语义。 |
| `split_decision` | `split / shared / fallback`。 |
| `split_reason_codes` | 条件拆分或回退原因。 |
| `support_state` | 四态发布状态。 |
| `geometry` | 最终 Road LineString。 |

不变量：每个父 SWSD Road至少一个 HighPrecisionRoadUnit；只有 `split` 父 Road可拥有两个方向单元。

## 2. PhysicalCorridorDecision

| 字段 | 含义 |
|---|---|
| `parent_swsd_unit_id` | 被审计父 Road。 |
| `forward_usable` / `reverse_usable` | 两侧是否有硬几何资格。 |
| `forward_anchor_id` / `reverse_anchor_id` | 稳定方向中心来源。 |
| `shared_longitudinal_coverage_ratio` | 两侧方向走廊共同纵向持续度。 |
| `anchor_median_separation_m` | 对称采样中位间距。 |
| `reference_lane_width_m` | 较窄侧参考 Lane 宽度。 |
| `required_min_separation_m` | 宽度相对门禁。 |
| `separation_gate_pass` | 是否空间可分。 |
| `continuity_gate_pass` | 是否纵向持续。 |
| `decision` | `split / shared / fallback`。 |
| `reason_codes` | 结构化原因。 |

不变量：`decision=split` 必须同时满足双侧 usable、separation 和 continuity 门禁。

## 3. CenterEvidenceObservation

固定纵向站点上的直接中心观测。

| 字段 | 含义 |
|---|---|
| `v3_road_id` | 目标 Road。 |
| `station_index / station_offset_m / station_fraction` | 父 SWSD 局部坐标。 |
| `observation_kind` | `stable_lane / shared_boundary / robust_lane_center`。 |
| `source_lane_ids / source_boundary_ids / source_patch_ids` | 来源 lineage。 |
| `lateral_offset_m` | 相对父 SWSD 的有符号横移。 |
| `observation_quality_state` | `usable / review / insufficient / excluded`。 |
| `lane_envelope_min_m / lane_envelope_max_m` | LaneGroup 横向包络。 |
| `drivezone_contained` | 观测是否落在修正版道路面。 |
| `geometry` | 直接观测点。 |

只有 `usable` 观测可以形成 `hp_observed`。

## 4. HighPrecisionControlSpan

| 字段 | 含义 |
|---|---|
| `v3_road_id` | 目标 Road。 |
| `start_fraction / end_fraction` | 连续控制里程。 |
| `control_kind` | `observed / bounded_interpolation / constrained_extension / fallback`。 |
| `left_anchor_id / right_anchor_id` | 控制锚点；单端延伸允许一侧为空。 |
| `drivezone_gate_pass` | 道路面包络门禁。 |
| `slope_gate_pass / oscillation_gate_pass` | 平滑门禁。 |
| `open_boundary_gate_pass` | 是否未越过开放证据边界。 |
| `decision / reason_codes` | 发布或回退原因。 |

## 5. GeometrySourceSegment

| 字段 | 含义 |
|---|---|
| `segment_id` | 连续片段 ID。 |
| `v3_road_id` | 目标 Road。 |
| `geometry_source` | `hp_observed / hp_constrained_interpolation / swsd_fallback`。 |
| `control_kind` | 更细的 observed/interpolation/extension/fallback 类型。 |
| `source_object_ids` | 支撑对象 lineage。 |
| `start_fraction / end_fraction / length_m` | 里程与长度。 |
| `reason_codes` | 来源或 fallback 原因。 |
| `geometry` | 最终片段。 |

片段必须无重叠覆盖整条 Road；合并后与最终 Road几何长度在容差内守恒。

## 6. HighPrecisionRoadCandidate

在 HighPrecisionRoadUnit 上完成几何与拓扑后的发布对象，除基础 Road 字段外至少包含：

- `support_state`；
- `high_precision_claim_scope`；
- `observed_length_m / constrained_length_m / swsd_fallback_length_m`；
- `high_precision_control_ratio / swsd_fallback_ratio`；
- `anchor_strategy / anchor_source_ids`；
- `geometry_fit_state / geometry_reason_codes`；
- `geometry_valid / geometry_simple`；
- `start_endpoint_source / end_endpoint_source`；
- `parent_swsd_unit_id / source_patch_ids / input_manifest_ref`。

## 7. HighPrecisionRoadGraph

包含：

- HighPrecisionRoadCandidate；
- HighPrecisionPortal；
- HighPrecisionArm；
- HighPrecisionMovement；
- LaneTopoProjectionAudit；
- PhysicalNodeAudit。

每条 Road恰有 `s/e` 两个 Portal/Arm。confirmed 同物理 Node movement 的两侧 Portal共点；复杂语义路口使用显式 Movement。

## 8. FrozenV2RoadComparison

V3 与唯一冻结 V2 的逐 Road 只读形态对照：

- `v3_road_id / parent_swsd_unit_id / v3_travel_side`；
- `frozen_v2_road_id / frozen_v2_travel_side / match_method`；
- `mean_sample_distance_m / p95_sample_distance_m / max_sample_distance_m`；
- `hausdorff_distance_m / length_delta_m`；
- `comparison_state=matched_for_shape_audit` 或显式 unmatched 原因。

匹配先限定同 `parent_swsd_unit_id`，再优先同 `travel_side`；shared/fallback 无同侧对象时才选择同父语义最近 V2。该对象只解释 V3/V2 形态差异，不把 V2 当真值，也不参与 RoadGraph 门禁。

## 9. 状态关系

```text
source evidence quality
  usable ───────────────┐
  review/insufficient ──┼──> CenterEvidenceObservation
  excluded ─────────────┘

CenterEvidenceObservation
  direct usable ─────────────> hp_observed
  constrained gap/extension ─> hp_constrained_interpolation
  gate failed/no evidence ───> swsd_fallback

geometry source coverage
  full controlled ──────> hp_supported
  mixed ────────────────> partial_hp_supported
  all fallback ─────────> sd_only
  trusted conflict ─────> conflict_retained
```

输入质量异常不得直接跳转到 `conflict_retained`。
