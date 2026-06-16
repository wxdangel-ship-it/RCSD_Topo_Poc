# 2026-06-15 side-group endpoint cross-anchor filter

## 背景

`991176` 反馈迭代中，`509987509_603597212` 的 side-group endpoint candidate 曾把另一端 `509987509` 的 RCSD primary anchor 发布到 `603597212` endpoint 行。T05 按可消费 endpoint candidate 补充 grouping 后，会把同一 SWSD Segment 的两个端点锚点压入同一虚拟聚合关系，导致 T06 继续出现 `rcsd_pair_nodes_not_distinct`。

## 业务变更

- T10 仍保留 segment 级 `t10_upstream_side_group_candidates.csv/json` 审计证据，用于说明该 Segment 需要 T03/T04/T05 或 RCSD 源资料复核。
- T10 在发布 `t10_upstream_side_group_endpoint_candidates.csv/json` 时，按 endpoint 过滤 candidate：
  - 当前 endpoint 的 `candidate_rcsdnode_ids` 可以包含自身 `rcsd_primary_node_id` 与同端新增候选；
  - 若候选 RCSDNode 等于同一 SWSD Segment 另一端的 primary pair node，则不再发布到当前 endpoint；
  - 过滤后没有新增 RCSDNode 的 endpoint 行不输出给 T05。

## 影响范围

- T05 不再消费会造成双端锚点互相吞并的 endpoint 级 side-group candidate。
- 已经由合法同端新增 RCSDNode 支撑的 side-group candidate 不受影响。
- T06 不新增兜底逻辑，仍通过 problem registry 记录未能前置修复的 pair-anchor 问题。

## 验证

- `python -m pytest tests/modules/t10_e2e_orchestration/test_t10_contracts.py::test_t10_side_group_endpoint_candidates_exclude_opposite_primary_anchor -q`
