# 2026-06-15 pair-anchor endpoint cluster feedback

## 背景

在 `991176` 回归中，直接把普通 `requires_upstream_iteration` 行里的 `candidate_rcsd_pair_node_sets` 扩大成 T05 endpoint candidate 会导致已替换 Segment 回退，说明该字段在 `buffer_candidate_required_nodes_disconnected` 等失败类型中不具备稳定的端点下标语义。

但 T06 problem registry 新增的 `pair_anchor_endpoint_cluster_nodes` 是 pair-anchor 诊断阶段按 SWSD Segment endpoint 输出的端点簇证据，适合向 T03/T04/T05 的后续根因分析暴露。

## 业务逻辑变更

- T10 上游反馈包新增 `t10_upstream_pair_anchor_endpoint_clusters.csv/json`。
- 该产物只从 `problem_status` 以 `requires_upstream` 开头且携带 `pair_anchor_endpoint_cluster_nodes` 的 Segment 生成。
- 产物按 endpoint 拆行，保留 `target_id / rcsd_primary_node_id / endpoint_cluster_rcsdnode_ids / pair_anchor_bridge_road_ids / pair_anchor_bridge_length_m / pair_anchor_diagnostic_source / pair_anchor_diagnostic_reason` 与来源 registry 路径。
- `auto_consumable_by_t05` 默认 `false`；只有 T06 已诊断为 `buffer_only_endpoint_cluster / short_connected_endpoint_cluster`，且问题为 `pair_anchor_mismatch + rcsd_pair_nodes_not_distinct`、cluster 包含 `rcsd_primary_node_id` 之外的新增 RCSDNode 时，才标记为 `true`。
- 标记为 `true` 的行可被 T10 feedback iteration 回灌给 T05 Phase2，但 T05 只能将其作为同 target 已有 relation / road-only split 的 RCSDNode grouping 补充，不能 standalone 创建 relation。
- T10 run manifest 与 summary 记录该产物路径和行数，便于后续审计和人工复核。

## 边界

- 不扩大 `t10_upstream_side_group_endpoint_candidates.csv/json` 的生成范围。
- 不把 `candidate_rcsd_pair_node_sets` 直接解释成 endpoint-index 稳定语义。
- 不自动创建 SWSD-RCSD relation，不发布虚拟路口面，不作为 T06 Step3 替换白名单；自动消费仅限 T05 对已有 relation / road-only split 的 endpoint RCSDNode grouping。
- 不修改 RCSD road 方向性，不进行几何 silent fix，不反推未授权字段语义。

## 验证

- `python -m py_compile src/rcsd_topo_poc/modules/t10_e2e_orchestration/upstream_feedback.py src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner.py`
- `python -m pytest tests/modules/t10_e2e_orchestration/test_t10_contracts.py::test_t10_upstream_feedback_aggregates_problem_registry -q`
- 仅使用 `991176` 做 T10 feedback iteration 回归，确认新增审计产物不改变自动回灌输入，不造成已替换 Segment 回退。
