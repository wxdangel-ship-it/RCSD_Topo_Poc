# P01-A2 Arm 配准与 LogicalArmGroup Spec

## 1. Scope

本 SpecKit 任务只覆盖 `P01-A2 / Arm 配准与 LogicalArmGroup 构建`。A2 消费当前 `p01_arm_build` 的 P01-A1 run root，不重新实现 A1 Arm 构建，不静默改写 A1 输出。

本轮业务需求主源为：

```text
/mnt/e/_chatgpt_sync/RCSD_Topo_Poc/P01_1/RCSD_Topo_Poc__P01__REQUIREMENT.md
```

Windows 路径 `E:\_chatgpt_sync\RCSD_Topo_Poc\P01_1\RCSD_Topo_Poc__P01__REQUIREMENT.md` 已按当前 WSL/bash 环境换算确认。

## 2. In Scope

- 读取 P01-A1 run root。
- 读取每个 group 的 SWSD / RCSD / FRCSD A1 JSON 输出。
- 以 `FinalArm` 为配准主对象构建 `ArmProfile`。
- 生成 `FRCSD ↔ SWSD`、`FRCSD ↔ RCSD`、`SWSD ↔ RCSD` 候选证据边。
- 基于 seed role、LocalArmCandidate、trace / terminal、road coverage、geometry 辅助证据进行可审计评分。
- 构建跨三源 evidence graph，并形成以 FRCSD 为承载核心的 `LogicalArmGroup`。
- 输出 `RawArmAlignment`、`LogicalArmGroup`、`ArmBuildFeedback`、candidate matrix、source extra、issue report、summary、review index。
- 输出配准 review PNG、compare PNG、GPKG 图层。
- 区分 `source_missing / source_partial` 与 `source_over_split_* / source_over_merged_* / conflict / uncertain`。
- 为后续 Movement 输出可消费的 `logical_arm_groups.json`，且只允许 `acceptable_for_downstream = true` 的 LogicalArmGroup 被后续阶段消费。

## 3. Out of Scope

- Movement 空间建模。
- SWSD / RCSD 禁行信息提取。
- 禁行证据投影。
- F-RCSD 通行能力裁决。
- P01-B。
- 自动修复 A1 输出。
- 自动拆分 over-merged Arm。
- 基于几何最近原则直接生成 high confidence 配准。
- 使用 `grade / grade_2` 作为 Arm 配准或构建规则。
- 新增 repo CLI 子命令、`scripts/` 常驻脚本、模块 `__main__.py` 或模块 `run.py`。

## 4. Inputs

模块内 callable runner 参数：

```text
--arm-build-run-root <P01_A1_RUN_ROOT>
--out-root <P01_A2_OUT_ROOT>
--run-id <optional>
```

`--arm-build-run-root` 必须包含：

```text
preflight.json
p01_arm_build_summary.json
p01_arm_build_review_index.csv
cases/
```

每个 `cases/<group_id>/` 读取：

```text
case_input.json
case_summary.json
<dataset>/junction_context.json
<dataset>/initial_arms.json
<dataset>/final_arms.json
<dataset>/local_arm_candidates.json
<dataset>/arm_traces.json
<dataset>/through_decisions.json
<dataset>/issue_report.json
```

原始 Node / Road 路径从 A1 `preflight.json` 中读取，仅用于几何辅助证据与 PNG / GPKG 绘制。无 lineage 字段时 A2 仍必须运行。

## 5. Business Objects

### ArmProfile

从 A1 `FinalArm` 归一化得到，至少包含：

- `dataset`
- `junction_group_id`
- `current_junction_id`
- `arm_id`
- `source_final_arm_id`
- `source_initial_arm_ids`
- `member_road_ids`
- `seed_road_ids`
- `connector_road_ids`
- `inbound_seed_road_ids`
- `outbound_seed_road_ids`
- `bidirectional_seed_road_ids`
- `terminal_type`
- `terminal_junction_id`
- `terminal_member_node_ids`
- `build_status`
- `risk_flags`
- `merge_status`
- `merge_reason`
- `local_candidate_ids`
- `trace_ids`
- `through_decision_summary`
- `geometry_summary`
- `lineage_summary`

### ArmAlignmentCandidate

保存所有候选边，不只保存最终结果。至少包含：

- `candidate_id`
- `junction_group_id`
- `left_dataset`
- `right_dataset`
- `left_arm_id`
- `right_arm_id`
- `score`
- `confidence`
- `seed_role_score`
- `local_candidate_score`
- `trace_terminal_score`
- `road_coverage_score`
- `geometry_score`
- `evidence_flags`
- `conflict_flags`
- `rank_for_left_arm`
- `rank_for_right_arm`
- `selected`
- `selection_reason`

### LogicalArmGroup

至少包含：

- `logical_arm_group_id`
- `junction_group_id`
- `frcsd_arm_ids`
- `swsd_arm_ids`
- `rcsd_arm_ids`
- `group_status`
- `acceptable_for_downstream`
- `missing_datasets`
- `partial_datasets`
- `over_split_datasets`
- `over_merged_datasets`
- `evidence_summary`
- `risk_flags`
- `review_priority`

### RawArmAlignment

至少包含：

- `alignment_id`
- `junction_group_id`
- `source_dataset`
- `target_dataset = FRCSD`
- `f_arm_id`
- `source_arm_ids`
- `match_type`
- `coverage_status`
- `confidence`
- `candidate_score`
- `source_initial_arm_ids`
- `f_source_initial_arm_ids`
- `evidence_summary`
- `reason_codes`
- `conflict_flags`
- `review_priority`
- `logical_arm_group_id`

### ArmBuildFeedback

至少包含：

- `feedback_id`
- `junction_group_id`
- `dataset`
- `feedback_type`
- `source_arm_ids`
- `supporting_datasets`
- `supporting_logical_arm_group_ids`
- `reason`
- `confidence`
- `review_priority`
- `evidence_summary`

## 6. Status Rules

可接受进入下游：

- `stable`
- `source_missing`，其中 RCSD missing 通常可接受，SWSD missing 默认高风险
- `source_partial`
- `source_over_split_resolved`

不可静默进入下游：

- `source_over_split_unresolved`
- `source_over_merged_unresolved`
- `conflict`
- `uncertain`

A2 候选选择必须先按 source dataset 做 source Arm 互斥优先分配；当某个 F-RCSD Arm 存在可用替代候选时，不复用已被更优 F-RCSD Arm 占用的 source Arm。`source_over_split_resolved` 必须输出 `recommended_merge` feedback。无法通过可用替代候选解除的 `source_over_merged_unresolved` 不自动拆分，必须输出 `recommended_split` feedback。

## 7. Outputs

输出根目录：

```text
<out-root>/<run-id>/
```

核心产物：

```text
preflight.json
p01_arm_alignment_summary.json
p01_arm_alignment_review_index.csv
cases/<group_id>/alignment_summary.json
cases/<group_id>/logical_arm_groups.json
cases/<group_id>/arm_build_feedback.json
cases/<group_id>/source_extra_arms.json
cases/<group_id>/arm_alignment_candidates.json
cases/<group_id>/SWSD/raw_arm_alignment.json
cases/<group_id>/SWSD/arm_alignment_issue_report.json
cases/<group_id>/SWSD/arm_alignment_review_layers.gpkg
cases/<group_id>/SWSD/p01_arm_alignment_review.png
cases/<group_id>/RCSD/raw_arm_alignment.json
cases/<group_id>/RCSD/arm_alignment_issue_report.json
cases/<group_id>/RCSD/arm_alignment_review_layers.gpkg
cases/<group_id>/RCSD/p01_arm_alignment_review.png
cases/<group_id>/compare/p01_arm_alignment_compare.png
cases/<group_id>/compare/p01_arm_alignment_compare_layers.gpkg
cases/<group_id>/compare/p01_arm_alignment_compare_summary.json
```

## 8. Acceptance Criteria

- 能读取 P01-A1 run root 并处理多个 group。
- 能构建三源 ArmProfile。
- 能生成三类候选边与 evidence graph。
- 能输出 RawArmAlignment、LogicalArmGroup、ArmBuildFeedback、source_extra。
- 能区分 coverage missing 与 grouping error。
- 能输出 `acceptable_for_downstream`。
- 能输出 PNG / GPKG / summary / review index。
- synthetic 覆盖 stable、source_missing、source_partial、over_split_resolved、over_merged_unresolved、conflict / uncertain、多 group。
- P01-A1 既有测试保持通过。
