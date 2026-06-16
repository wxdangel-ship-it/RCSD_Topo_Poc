# 008 T05 Relation Graph Feedback

## 日期
- 2026-06-15

## 背景
- T05 Phase2 新增 `relation_graph_consumability_audit.csv/json` 后，可以识别 `intersection_match_all.geojson` 中 `status = 0` 但 `base_id` 不能被最终 `rcsdroad_out.gpkg / rcsdnode_out.gpkg` 消费的 relation。
- 这类问题会在 T06 表现为 `pair_anchor_mismatch`、`full_rcsd_graph_missing_required_nodes` 或类似 Segment 替换失败，但根因位于 relation evidence handoff 或 T05 junctionization 消费阶段。

## 根因定位
- 原 T10 run 级反馈只收集 T06 `t06_segment_replacement_problem_registry.csv` 中的 Segment 级问题。
- T05 已能发现 relation 级质量问题，但 T10 不聚合该审计时，前置模块无法直接看到需要回到 T07/T03/T04/T05 处理的 relation handoff 缺口。

## 实际变更
- T10 run root 新增 `t10_upstream_feedback_relations.csv/json`。
- T10 run root 新增 `t10_upstream_feedback_relation_summary.csv/json`。
- Relation 级反馈只收集 T05 `relation_graph_consumability_audit.csv` 中 `relation_status = 0` 且 `graph_consumable != 1` 的记录。
- 每条记录保留 `case_id / target_id / base_id / graph_consumability_status / source_modules / scenes / reasons / affected_problem_segment_ids / relation_graph_consumability_audit_path`，并标记 `problem_status = requires_upstream_iteration`。
- `affected_problem_segment_ids` 只通过 T06 problem registry 中 `swsd_segment_id` 的端点 ID 与 relation `target_id` 做属性匹配，不做空间推断。

## 本次边界
- 不改变 `intersection_match_all.geojson`。
- 不改变 T06 Step2/Step3 替换关系。
- 不基于最近点或 case 级条件自动修正 `base_id`。
- 新增反馈只用于后续回到 T07/T03/T04/T05 的根因模块迭代。

## 验证
- 待运行 T10 feedback 单元测试。
- 待运行 T10 模块测试与 4-case 端到端回归，确认已成功替换 Segment 不回退。
