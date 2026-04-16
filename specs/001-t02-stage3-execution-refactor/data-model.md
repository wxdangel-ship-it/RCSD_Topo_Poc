# Data Model: T02 Stage3 Execution-Layer Refactor

## Stage3Context

统一只读上下文，供 Step3~Step7 顺序消费。

建议字段：

- `representative_node`
- `semantic_junction_set`
- `analysis_member_node_ids`
- `group_nodes`
- `local_nodes`
- `local_roads`
- `local_rc_nodes`
- `local_rc_roads`
- `drivezone_union`
- `road_branches`
- `analysis_center`
- `kind_2`
- `normalized_mainnodeid`

约束：

- 一旦构建完成，不允许在 Step3~7 内原地改写上下文语义

## Step3LegalSpaceResult

定义 Stage3 的合法活动空间。

建议字段：

- `template_class`
- `legal_activity_space_geometry`
- `must_cover_group_node_ids`
- `allowed_drivezone_geometry`
- `hard_boundary_road_ids`
- `single_sided_corridor_road_ids`
- `step3_blockers`

约束：

- Step4~7 只能读取，不能扩大

## Step4RCSemanticsResult

定义 RC 语义分类。

建议字段：

- `required_rc_node_ids`
- `required_rc_road_ids`
- `support_rc_node_ids`
- `support_rc_road_ids`
- `excluded_rc_node_ids`
- `excluded_rc_road_ids`
- `selected_rc_endpoint_node_ids`
- `stage3_rc_gap_records`
- `step4_audit_facts`

约束：

- 只能分类 RC 语义，不得反向扩大 Step3 legal space

## Step5ForeignModelResult

定义 foreign 硬排除模型。

建议字段：

- `foreign_semantic_node_ids`
- `foreign_road_arm_corridor_ids`
- `foreign_rc_context_ids`
- `foreign_trim_geometry`
- `foreign_tail_records`
- `foreign_overlap_records`
- `step5_audit_facts`

约束：

- foreign 必须先建模，再进入 Step6

## Step6GeometrySolveResult

定义受约束几何求解结果。

建议字段：

- `seed_geometry`
- `primary_solved_geometry`
- `bounded_optimizer_geometry`
- `optimizer_events`
- `must_cover_validation`
- `foreign_exclusion_validation`
- `geometry_problem_flags`
- `step6_audit_facts`

约束：

- `bounded_optimizer_geometry` 只能在不改变 Step3/4/5 核心语义的前提下优化

## Step7AcceptanceResult

定义最终准出。

建议字段：

- `status`
- `success`
- `acceptance_class`
- `acceptance_reason`
- `root_cause_layer`
- `root_cause_type`
- `visual_review_class`
- `step7_audit_facts`

约束：

- Step7 是唯一终裁
- Step7 之后不得再改写几何和 foreign 语义

## Stage3AuditRecord

聚合所有 Step result 的原生审计事实。

建议字段：

- `mainnodeid`
- `step3`
- `step4`
- `step5`
- `step6`
- `step7`
- `final_root_cause_layer`
- `final_root_cause_type`
- `final_visual_review_class`

## Stage3ReviewIndexEntry

正式审查包索引条目。

建议字段：

- `case_id`
- `test_case_name`
- `source_test_file`
- `input_mode`
- `input_paths`
- `output_dir`
- `run_id`
- `official_review_eligible`
- `status`
- `root_cause_layer`
- `root_cause_type`
- `visual_review_class`
