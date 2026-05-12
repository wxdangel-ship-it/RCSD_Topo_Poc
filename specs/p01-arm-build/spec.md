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

提前右转 road 分两类处理：路口内且按 `direction` 进入当前语义路口的 bit7 road 是 Arm 组成部分，进入 `member_road_ids / seed_road_ids`，但必须从 `trunk_road_ids` 中排除；路口前、不进入当前语义路口的 bit7 road 不进入 Arm `member_road_ids / seed_road_ids / connector_road_ids / trunk_road_ids`，必须进入 `AdvanceRightTurnRelation` 或 issue。提前左转 road 可以进入 Arm member，但必须从 trunk 中排除。

`--right-turn-formway-value` 只用于 legacy 显式右转 / 渠化右转排除兼容；不进入当前路口的 bit7 提前右转优先进入 relation 或 issue。

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

### 3.7 FinalArm 兜底验证

LocalArmCandidate 兜底聚合形成的 FinalArm 必须在 A1 内部执行 relaxed reverse / supplemental trace validation。该验证只新增证据，不覆盖原始 InitialArm、ArmTrace、ThroughDecisionAudit、LocalArmCandidate 或 FinalArm merge fact。

验证对象为 `merge_status = local_candidate_fallback`、`source_initial_arm_ids` 数量大于 1，或等价表示由多个 InitialArm 兜底合并得到的 FinalArm。单 source FinalArm 输出 `validation_status = not_required`。

validation 状态包括：

- `not_required`
- `validated`
- `weak_validated`
- `unvalidated`
- `conflict`

收敛状态包括 `same_semantic_junction / same_terminal_boundary / partial_same_corridor / no_convergence / conflicting_terminals / not_evaluated`。`conflict` 进入 P0，`weak_validated / unvalidated` 至少进入 P1。validation risk 必须保留到 corrected_final_arms 与 P01-Final audit，不得静默使用 conflict FinalArm。

## 4. A2 规则

A2 将 FinalArm 转换为 ArmProfile，生成 FRCSD-SWSD、FRCSD-RCSD、SWSD-RCSD 候选关系，构建跨三源 evidence graph，并形成 LogicalArmGroup。

A2 必须区分：

- 可接受 coverage 差异：`source_missing`、`source_partial`
- 可接受且已解释的分组差异：`source_over_split_resolved`
- 不可接受或需人工审查的分组错误：`source_over_split_unresolved`、`source_over_merged_unresolved`、`conflict`、`uncertain`

后续阶段只能消费 `acceptable_for_downstream = true` 的 LogicalArmGroup。

## 5. P01-Final 规则

### 5.1 Source road mapping audit

F-RCSD Road 使用 `Source + CRS 归一化后的 rounded exact geometry` 尝试映射源 Road，但该映射只作为 audit / confidence evidence，不作为 final generation 前提：

- `Source = 1` 只在 RCSD Road 中查找 CRS 归一化后的 rounded exact geometry。
- `Source = 2` 只在 SWSD Road 中查找 CRS 归一化后的 rounded exact geometry。
- 当前 F-RCSD 没有可作为权威依据的 source road id；`baseroadid` 在验证 case 中为空，不进入来源映射规则。

同源多匹配输出 `ambiguous_source_geometry_match`。找不到源 Road 输出 `source_geometry_match_missing`。不得用空间接近或最近邻替代 rounded exact mapping。

### 5.2 SourceArmPassRule

SWSD / RCSD RoadNextRoad evidence 先抽象为 SourceArmPassRule。规则维度为：

- source dataset
- from Arm
- to Arm
- movement type
- from road role
- rule status
- generation scope

`rule_status` 至少支持：

- `full_allowed`
- `prohibited`
- `trunk_only_allowed`
- `left_receiving_only_allowed`
- `data_error_partial_target_coverage`
- `insufficient`
- `conflict`

`full_allowed` 表示该进入道路角色可通向目标 Arm 的所有退出 Road。目标 Arm 退出 Road 包括 outbound、bidirectional 与具备退出能力的 trunk road，不包括只进入 road、路口前 bit7 提前右转 relation road、当前路口 internal road 或被排除的非通行承载 road。

主干道路 / 平行支路只覆盖部分目标退出 Road 时，规则必须进入 `data_error_partial_target_coverage`，不得作为正常 partial rule 自动投影。advance-left left-receiving only、advance-left trunk only 与 uturn trunk only 是合法特殊范围。

### 5.3 final generation

F-RCSD final generation 以 ArmMovement、进入道路角色、目标 Arm 退出 Road 集合和 SourceArmPassRule 为依据。F-RCSD Arm 可以混源，`Source` 只在 Road 级解释。

规则源选择：

- 进入 Arm 参与通行道路全部 `Source = 1` 时优先 RCSD 规则。
- 进入 Arm 参与通行道路全部 `Source = 2` 时优先 SWSD 规则。
- 混源进入 Arm 先匹配 SWSD 结构，再匹配 RCSD 结构；结构包括道路总数、主干数量、提前左转数量、平行支路数量与进入方向道路数量。
- SWSD / RCSD 都不吻合时，使用 SWSD basic rule 并记录低置信审计；SWSD basic rule 只包含稳定基础能力，不包含多平行支路细节、局部 partial 规则或 F-RCSD 中无承载道路的规则。
- 参考 RCSD 但 RCSD 目标 Arm 缺失时，fallback 到 SWSD basic rule，并记录 `fallback_reason = rcsd_target_arm_missing`。

生成范围：

- `full_allowed`：进入道路角色下全部 F-RCSD from road 生成到目标 Arm 全部退出 Road。
- `trunk_only_allowed`：仅生成到目标 Arm trunk road，用于 uturn 等明确特例。
- `left_receiving_only_allowed`：生成到目标 Arm left receiving road；目标 Arm 缺失 left receiving road 时回退到目标 Arm trunk road。
- `prohibited / insufficient / conflict / data_error_partial_target_coverage`：不自动生成 RoadNextRoad，并输出 final generation decision 与 issue。

平行支路数量不一致必须进入 `data_error / manual_review_required`，不得静默生成对应平行支路 RoadNextRoad。source 有平行支路而 F-RCSD 没有时，不生成平行支路关系，以主路逻辑为主，并输出 `source_parallel_branch_missing_in_frcsd`。trunk -> right Arm 不通且 F-RCSD 缺少 parallel_branch、路口内提前右转 Arm member 或提前右转 relation carrier 时，输出 `data_error_or_missing_right_turn_carrier`。

`source_movement_policy_swsd.json` / `source_movement_policy_rcsd.json` 可继续输出为兼容审计对象，但不得作为唯一生成前提。

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
- `final_arm_validation.json`
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
- `cases/<group_id>/FRCSD/arm_source_profiles.json`
- `cases/<group_id>/FRCSD/source_arm_pass_rules_swsd.json`
- `cases/<group_id>/FRCSD/source_arm_pass_rules_rcsd.json`
- `cases/<group_id>/FRCSD/final_generation_decisions.json`
- `cases/<group_id>/FRCSD/frcsd_source_road_map.json`
- `cases/<group_id>/FRCSD/source_movement_policy_swsd.json`
- `cases/<group_id>/FRCSD/source_movement_policy_rcsd.json`
- `cases/<group_id>/FRCSD/parallel_branch_alignment.json`
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
- P01-Final 能执行规则级通行能力抽象、ArmSourceProfile、SourceArmPassRule、混源规则源选择、SWSD basic fallback、全通投影到全部目标退出 Road、部分覆盖报错、精确匹配缺失仍可规则生成与 final GeoJSON 输出。
- JSON / GeoJSON / PNG / GPKG / summary / review index / audit / issue report 均可定位输入、参数、case、规则与风险。
