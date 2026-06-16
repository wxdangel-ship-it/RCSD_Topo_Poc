# 2026-06-15 Phase2 T04 partial handoff grouping

## 背景

T10 case `991176` 中，T04 将 SWSD 节点 `1013538` 的道路面分歧局部 RCSD node `5396512437306532` 作为 relation handoff base 后，正向 Segment `1013539_1013538` 可以替换，但反向 Segment `1013538_1013539` 从已替换变为 retained。原因是 RCSD 中同一 SWSD 端点需要同时表达：
- 局部 handoff node：`5396512437306532`
- RCSD 语义主点：`5396513947462175`

T04 只负责发布证据和关系候选，不应通过一对多 relation 破坏 cardinality；T06 也不应按双向 Segment 做 case 级兜底。因此责任模块是 T05 Phase2：把 T04 已发布的两个 RCSD node 正式归组为同一 RCSD 语义路口，再向下游发布唯一 relation。

## 业务变更

T05 Phase2 分类器新增 T04 handoff grouping 分支：
- 来源必须是 T04 relation evidence；
- `status_suggested = 0`；
- `swsd_relation_type = partial`；
- `base_id_candidate` 非空；
- `semantic_required_rcsd_node_ids` 非空，且与 `base_id_candidate` 不同。

满足条件时，不按 direct relation 消费，而是进入既有 `group_existing_rcsd_nodes` 路径：
- `base_id_candidate` 作为 preferred primary；
- `base_id_candidate + semantic_required_rcsd_node_ids` 作为 `rcsdnode_ids` 归组集合；
- 输出仍保持一个 SWSD target 只有一条 `intersection_match_all.geojson` relation；
- copy-on-write `rcsdnode_out.gpkg` 中组内 node 的 `mainnodeid` 归一到选定主 node。

## 边界

- 不修改 T04 accepted surface。
- 不新增 RCSDRoad，不打断 road。
- 不修改 T07/T03/T04 原始产物。
- 不放宽 relation cardinality QC。
- 不从几何近邻或 T06 结果反推 RCSD 归属，只消费 T04 显式发布的 `semantic_required_rcsd_node_ids`。

## 验证

- 新增 T05 Phase2 单测覆盖 T04 partial handoff grouping。
- 仅使用 T10 case `991176` 做端到端回归，要求 `1013539_1013538` 被替换，同时 `1013538_1013539` 不从已替换回退。
