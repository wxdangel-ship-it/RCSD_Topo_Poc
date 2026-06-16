# 2026-06-15 Step2 problem registry pair-anchor diagnostics

## 背景

T06 failure business audit 已能输出 `pair_anchor_endpoint_cluster_nodes`、`pair_anchor_error_*`、bridge road 与诊断来源，但 `t06_segment_replacement_problem_registry` 只保留 `candidate_rcsd_pair_node_sets`。在 `991176` 回归中，直接把 `candidate_rcsd_pair_node_sets` 按 endpoint 下标拆给 T05 会造成已替换 Segment 回退，说明该字段不能承担 endpoint 归属语义。

## 变更

- `t06_segment_replacement_problem_registry` 新增并透传 pair-anchor 诊断字段：
  - `pair_anchor_error_swsd_nodes`
  - `pair_anchor_error_original_rcsd_nodes`
  - `pair_anchor_error_candidate_rcsd_nodes`
  - `pair_anchor_endpoint_cluster_nodes`
  - `pair_anchor_bridge_road_ids`
  - `pair_anchor_bridge_length_m`
  - `pair_anchor_diagnostic_source`
  - `pair_anchor_diagnostic_reason`
- T10 upstream feedback segment 表同步保留这些字段，供 T03/T04/T05 后续前置迭代读取。

## 边界

- 这些字段是诊断证据，不是 T06 Step3 替换白名单。
- 不改变 `problem_status` 判定，不新增自动替换。
- 不根据 `candidate_rcsd_pair_node_sets` 反推 endpoint 归属；需要前置模块消费时应优先使用 `pair_anchor_endpoint_cluster_nodes` 并继续通过 no-regression guard 验证。
