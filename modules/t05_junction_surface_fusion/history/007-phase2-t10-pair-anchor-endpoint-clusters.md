# 2026-06-15 Phase2 T10 pair-anchor endpoint clusters

## 背景

T06 在 `rcsd_pair_nodes_not_distinct` / `pair_anchor_mismatch` 场景下已能输出 `pair_anchor_endpoint_cluster_nodes`，该字段来自 pair-anchor 诊断的 endpoint 侧短连接簇，不同于普通 `candidate_rcsd_pair_node_sets`。

`991176` 中 `509987509_603597212` 的剩余失败表明：T05 已能消费基础 relation，但 endpoint 侧仍需吸收 T06 诊断出的短连接 RCSDNode 簇，才能让 T06 后续构建正确的 RCSD pair anchor。

## 业务逻辑变更

- T05 Phase2 新增可选输入 `t10_upstream_pair_anchor_endpoint_clusters.csv/json`。
- 仅消费 `auto_consumable_by_t05=true` 的 `T10_PAIR_ANCHOR_CLUSTER` 行。
- 该补充源与 `T10_SIDE_GROUP` 一样只能依附同 target 已有成功 relation 或 T03/T04 road-only split 决策。
- 当存在基础 relation 时，Phase2 将 endpoint cluster 中存在于 `rcsdnode_out` 的 RCSDNode 做 copy-on-write `mainnodeid` grouping。
- 当存在 road-only split 时，Phase2 先执行 split / endpoint reuse，再把新生成或复用的 RCSDNode 与 endpoint cluster 的额外节点归组。

## 边界

- 不从 `candidate_rcsd_pair_node_sets` 反推 endpoint 下标语义。
- 不创建 standalone SWSD-RCSD relation。
- 不修改 RCSD road 方向性，不执行几何 silent fix。
- 不把 T10/T06 feedback 直接转为 T06 Step3 替换白名单。

## 验证

- `python -m pytest tests/modules/t05_junction_surface_fusion/test_phase2_rcsd_junctionization.py::test_t10_pair_anchor_cluster_is_supplemental_decision_only tests/modules/t05_junction_surface_fusion/test_phase2_rcsd_junctionization.py::test_t10_pair_anchor_endpoint_cluster_supplements_existing_relation tests/modules/t05_junction_surface_fusion/test_phase2_rcsd_junctionization.py::test_t10_pair_anchor_endpoint_cluster_is_not_standalone_relation -q`
- `python -m pytest tests/modules/t10_e2e_orchestration/test_t10_contracts.py::test_t10_pair_anchor_endpoint_cluster_marks_safe_rows_consumable_by_t05 tests/modules/t10_e2e_orchestration/test_t10_contracts.py::test_t10_feedback_iteration_passes_pair_anchor_endpoint_clusters -q`
