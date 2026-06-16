# 2026-06-15 relation graph bridge side-group feedback

## 背景

`991176` 中，过滤跨端 primary anchor 后，`509987509_603597212` 可以正确替换，但旧成功的 `1026330_54160800` 回退。审计发现 `1026330_54160800` 的 T06 失败属于 `directionality_mismatch_fixable + rcsd_not_bidirectional_for_swsd_dual`，T06 `buffer-only probe` 已找到同一候选走廊，但 T05 中已存在的 `603597212` 多基准 relation graph 还缺少相邻的 RCSD 语义路口锚点，导致双向 RCSD path 构建不完整。

## 业务变更

- T10 在生成 `t10_upstream_side_group_endpoint_candidates.csv/json` 时，新增 relation graph bridge 候选。
- 该候选只从 T06 `t06_rcsd_buffer_only_probe.csv`、T05 `relation_graph_consumability_audit.csv`、`rcsd_junctionization_audit.csv` 和 `rcsdroad_out.gpkg` 中取证，不修改 T06 替换白名单。
- 发布条件同时满足：
  - Segment 问题为 `requires_upstream_side_group_or_rcsd_directionality_review`、`directionality_mismatch_fixable`、`rcsd_not_bidirectional_for_swsd_dual`；
  - T06 probe 已找到 `corridor_found` 的候选走廊；
  - 新增 RCSDNode 是 T05 已消费 relation 的 `base_id`，且不是当前 Segment 两端 primary pair node；
  - 新增 RCSDNode 在 RCSD road graph 中 1 hop 内连接当前 Segment primary pair node；
  - 新增 RCSDNode 在 RCSD road graph 中 3 hop 内连接某个已经由 `T10_SIDE_GROUP` 形成的多基准 relation graph 上下文；
  - 候选只补充该既有 `T10_SIDE_GROUP` target 的 `candidate_rcsdnode_ids`，不单独创建 SWSD-RCSD relation。

## 影响范围

- 对已经可由普通 endpoint candidate 处理的 Segment 无影响。
- 对没有 T05 relation graph、没有 T10_SIDE_GROUP 多基准 relation、没有 T06 corridor probe 或不满足受限 road graph 连接条件的 Segment，不自动发布该候选。
- T05 仍通过 Phase2 junctionization 正式落实 RCSDNode grouping；T06 仍只消费前置模块发布后的正式 relation 和 RCSD road/node 输出。

## 验证

- `python -m py_compile src/rcsd_topo_poc/modules/t10_e2e_orchestration/upstream_feedback.py tests/modules/t10_e2e_orchestration/test_t10_contracts.py`
- `python -m pytest tests/modules/t10_e2e_orchestration/test_t10_contracts.py::test_t10_relation_graph_bridge_candidate_extends_existing_side_group tests/modules/t10_e2e_orchestration/test_t10_contracts.py::test_t10_side_group_endpoint_candidates_exclude_opposite_primary_anchor -q`
- `python -m pytest tests/modules/t10_e2e_orchestration/test_t10_contracts.py -q`
