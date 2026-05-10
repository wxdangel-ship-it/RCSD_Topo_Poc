# P01 v1.0.0 Specification

## 1. 业务目标

P01 的成果目标是生成最终 `F-RCSD:RoadNextRoad.geojson`，并保留可审计、可复现、可人工检查的结构证据链。仓库模块 `p01_arm_build` 承载三段能力：

- `P01-A1`：单源 Arm 构建、特殊转向识别、ArmMovement 与 trunk 修正。
- `P01-A2`：三源 Arm 配准与 LogicalArmGroup 构建。
- `P01-Final`：F-RCSD RoadNextRoad 还原。

P01 不以单点 Node 表示路口，而以语义路口 member node 集合作为 Arm、Movement 和最终 RoadNextRoad 的上下文。

## 2. 输入

### 2.1 A1 / P01-Final

必选输入：

- `--swsd-nodes`
- `--swsd-roads`
- `--rcsd-nodes`
- `--rcsd-roads`
- `--frcsd-nodes`
- `--frcsd-roads`
- `--junction-group <swsd_junction_id>,<rcsd_junction_id>,<frcsd_junction_id>`，可重复。
- `--out-root`

可选输入：

- `--run-id`
- `--right-turn-formway-value`
- `--swsd-road-next-road`
- `--rcsd-road-next-road`
- `--frcsd-road-next-road`

RoadNextRoad 作为 A1 ArmMovement 的 allowed evidence。SWSD 支持 JSON / RoadNodeRoad JSON 形态，RCSD / F-RCSD 支持 GeoJSON 或同类 JSON 结构。F-RCSD RoadNextRoad 输入仅用于同源 evidence 审计；最终 F-RCSD RoadNextRoad 由 P01-Final 生成。

F-RCSD Road 必须读取 `Source`：

- `Source = 1`：来源 RCSD。
- `Source = 2`：来源 SWSD。

Source 缺失、不可解析或超出允许值时，相关 final RoadNextRoad 不生成，并写入 issue。

### 2.2 A2

A2 主输入是 A1 run root：

- `--arm-build-run-root <P01_A1_RUN_ROOT>`
- `--out-root`
- `--run-id`

A2 从 A1 `preflight.json` 读取原始数据路径，从 `cases/<group>/<dataset>/` 读取 A1 JSON 输出。

## 3. A1 规则

### 3.1 语义路口

- 有有效 `mainnodeid`：按 `mainnodeid` 聚合为多节点语义路口。
- `mainnodeid = null / 空字符串 / 0`：Node 自身作为单节点语义路口。
- `mainnode` 只是代表 Node，不等于整个路口。

### 3.2 Arm

Arm 是从当前语义路口出发，沿进入 / 退出当前路口的 Road 进行拓扑追溯，最终到达同一个终端路口或终端边界的一组道路链。Arm 不是几何方向聚类、Port、Family、Movement 或全局 Segment。

### 3.3 特殊转向

`formway` 使用 bit 运算：

- 提前右转：`(formway & 128) != 0`
- 提前左转：`(formway & 256) != 0`

提前右转 road 不进入 Arm `member_road_ids / seed_road_ids / connector_road_ids / trunk_road_ids`，必须进入 `AdvanceRightTurnRelation` 或 issue。提前左转 road 可以进入 Arm member，但必须从 trunk 中排除。

`--right-turn-formway-value` 只用于 legacy 显式右转 / 渠化右转排除兼容；bit7 提前右转优先进入 relation 或 issue。

### 3.4 Through 判断

through 判断发生在语义节点组 / 语义路口层面。允许继续追溯的状态包括 `simple_through` 和 `t_mainline_through`。停止状态包括 `t_side_terminal`、`semantic_boundary`、`ambiguous_boundary`、`dead_end`、`patch_boundary`、`loop_to_current_junction`。

T 型判断必须结合 `kind`、拓扑结构、当前追溯方向、Arm / trunk / RoadNextRoad 证据；`kind` 不能单独裁决。`grade / grade_2` 不进入 P01 主规则。

### 3.5 ArmMovement

ArmMovement 是同源 `from_arm -> to_arm` 的客观动作候选，按全量 `from_arm × to_arm` 输出。RoadNextRoad 在 A1 中只表达 allowed evidence：

- 有映射 evidence：`allowed_supported`
- 无映射 evidence：`no_allowed_evidence`
- 输入未覆盖：`out_of_scope`
- 映射冲突：`mapping_unresolved` 或 `role_conflict`

RoadNextRoad 缺失在 A1 阶段不表示禁止。

`movement_type` 支持 `straight / left / right / uturn / unknown`。判定优先级：

1. `from_arm_id == to_arm_id` -> `uturn`
2. 同一主交通流 / 同一道路走廊连续 -> `straight`
3. 非直行、非调头时，目标 Arm 在进入交通流左侧 -> `left`
4. 非直行、非调头时，目标 Arm 在进入交通流右侧 -> `right`
5. 证据不足 -> `unknown`

RoadNextRoad `turnType / turntype` 只保留在 raw audit 和 turn type summary 中，不得用于 `movement_type` 判定。Y-like、skew-like、diverge-like、merge-like、curved-mainline-like 只能作为后验审计标签，不得作为判定入口。

### 3.6 ReceivingRoadRole 与 corrected trunk

ReceivingRoadRole 统计目标 Arm 内每条 Road 被哪些 movement evidence 接入，角色包括：

- `straight_receiving_road`
- `left_turn_receiving_road`
- `advance_left_receiving_road`
- `right_turn_receiving_road`
- `unknown_receiving_road`

只有 stable straight evidence 非空时，才允许基于 advance-left-only receiving road 排除 trunk candidate。若目标 Arm 无 stable straight receiving evidence，不得排除 trunk，只能输出 `straight_receiving_evidence_missing`。

Corrected trunk 输出：

- `original_trunk_road_ids`
- `movement_excluded_receiving_road_ids`
- `corrected_trunk_road_ids`
- `trunk_correction_status`
- `trunk_correction_reason`

## 4. A2 规则

A2 将 FinalArm 转换为 ArmProfile，生成 FRCSD-SWSD、FRCSD-RCSD、SWSD-RCSD 候选关系，构建跨三源 evidence graph，并形成 LogicalArmGroup。

A2 必须区分：

- 可接受 coverage 差异：`source_missing`、`source_partial`
- 可接受且已解释的分组差异：`source_over_split_resolved`
- 不可接受或需人工审查的分组错误：`source_over_split_unresolved`、`source_over_merged_unresolved`、`conflict`、`uncertain`

后续阶段只能消费 `acceptable_for_downstream = true` 的 LogicalArmGroup。

## 5. P01-Final 规则

### 5.1 Source road mapping

F-RCSD Road 使用 `Source + 几何完全一致` 映射源 Road：

- `Source = 1` 只在 RCSD Road 中查找几何完全一致。
- `Source = 2` 只在 SWSD Road 中查找几何完全一致。

同源多匹配输出 `ambiguous_source_geometry_match`。找不到源 Road 输出 `source_geometry_match_missing`。不得用空间接近替代 exact mapping。

### 5.2 SourceMovementPolicy

SWSD / RCSD SourceMovementPolicy 由源侧 RoadNextRoad evidence 与 role-level road roles 构建。最终生成阶段中：

- 源 RoadNextRoad 存在 -> `permission_status = allowed`
- 源 RoadNextRoad 缺失 -> `permission_status = prohibited`

这里的 `prohibited` 是 final generation 语义，不等同于 A1 ArmMovement 的 `no_allowed_evidence`。

### 5.3 final generation

同源 F-RCSD from/to road pair 直接继承对应源 RoadNextRoad。不同源 pair 以进入 road 的 Source 作为 primary source，使用 primary source 的 SourceMovementPolicy 判断 role pair 是否 allowed。

RCSD -> SWSD fallback 只允许以下场景：

- `from_road.Source = 1`
- `to_road.Source = 2`
- RCSD 中没有对应 to_arm
- SWSD 中存在对应 to_arm
- `RCSD from_arm road count == SWSD from_arm road count`

平行支路数量不一致必须进入 `data_error / manual_review_required`，不得静默生成对应平行支路 RoadNextRoad。trunk -> right Arm 不通且 F-RCSD 缺少 parallel_branch 或提前右转 carrier 时，输出 `data_error_or_missing_right_turn_carrier`。

最终 `frcsd_road_next_road.geojson` 使用 RCSD RoadNextRoad GeoJSON 形态：

- `geometry = null`
- properties 至少包含 `id / road_id / next_road_id / type / source / turntype / city_code`
- `(road_id, next_road_id)` 不重复

`turntype` 是输出编码，不参与 `movement_type` 判定。

## 6. 输出

A1 / P01-Final run root：

- `preflight.json`
- `case_results.json`
- `p01_arm_build_summary.json`
- `p01_arm_build_review_index.csv`
- `cases/<group_id>/case_input.json`
- `cases/<group_id>/case_summary.json`

每个 dataset：

- `junction_context.json`
- `initial_arms.json`
- `final_arms.json`
- `corrected_final_arms.json`
- `advance_right_turn_relations.json`
- `local_arm_candidates.json`
- `arm_traces.json`
- `through_decisions.json`
- `issue_report.json`
- `arm_movements.json`
- `road_movement_evidence.json`
- `arm_receiving_road_roles.json`
- `trunk_corrections.json`
- `review_layers.gpkg`
- `p01_arm_review.png`

P01-Final：

- `cases/<group_id>/FRCSD/frcsd_road_next_road.geojson`
- `cases/<group_id>/FRCSD/frcsd_source_road_map.json`
- `cases/<group_id>/FRCSD/source_movement_policy_swsd.json`
- `cases/<group_id>/FRCSD/source_movement_policy_rcsd.json`
- `cases/<group_id>/FRCSD/frcsd_road_next_road_audit.json`
- `cases/<group_id>/FRCSD/frcsd_road_next_road_issue_report.json`

A2：

- `p01_arm_alignment_summary.json`
- `p01_arm_alignment_review_index.csv`
- `cases/<group_id>/logical_arm_groups.json`
- `cases/<group_id>/arm_build_feedback.json`
- `cases/<group_id>/source_extra_arms.json`
- `cases/<group_id>/arm_alignment_candidates.json`
- `cases/<group_id>/<dataset>/raw_arm_alignment.json`
- `cases/<group_id>/<dataset>/arm_alignment_issue_report.json`
- `cases/<group_id>/<dataset>/arm_alignment_review_layers.gpkg`
- `cases/<group_id>/<dataset>/p01_arm_alignment_review.png`
- `cases/<group_id>/compare/p01_arm_alignment_compare.png`

## 7. 验收

- A1 能读取三源 Node / Road，并处理多个 junction group。
- RoadNextRoad-aware ArmMovement 输出全量候选。
- `turnType / turntype` 不参与 `movement_type` 判定。
- ReceivingRoadRole 与 corrected trunk 可审计。
- A2 输出 LogicalArmGroup、RawArmAlignment、ArmBuildFeedback 与 source_extra。
- P01-Final 能执行 Source + geometry exact mapping、同源继承、跨源 primary source、RCSD -> SWSD fallback 与 final GeoJSON 输出。
- JSON / GeoJSON / PNG / GPKG / summary / review index / audit / issue report 均可定位输入、参数、case、规则与风险。
