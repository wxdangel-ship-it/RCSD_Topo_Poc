# 2026-06-15 road_surface_fork partial relation handoff

## 背景

T10 case `991176` 中，SWSD Segment `1013539_1013538` 在 T06 Step2 失败为 `rcsd_directed_path_missing`。审计发现全 RCSD graph 存在有向路径，但当前 T04/T05 发布给 T06 的端点组合为 `5396527335719654 -> 5396513947462175`，导致 50m buffer candidate graph 缺失局部有向走廊。

T04 Step4 对 SWSD 节点 `1013538` 已经识别：
- `main_evidence_type = road_surface_fork`
- `swsd_junction_present = false`
- `required_rcsd_node = 5396513947462175`
- `local_rcsd_unit_id = event_unit_01:node:5396512437306532`

其中 `required_rcsd_node` 是远端 RCSD 语义主点，`local_rcsd_unit_id` 是道路面分歧局部单元中的 RCSD node。对 downstream Segment 构建而言，局部 node 才是该 partial surface 与 SWSD Segment 端点的 relation handoff base。

## 业务变更

T04 Step7 relation evidence 发布增加一条窄口径规则：
- 当 event-unit 为 `road_surface_fork` 主证据；
- Step7 `swsd_relation_type = partial`；
- `swsd_junction_present = false`；
- `positive_rcsd_consistency_level = A`；
- 且 Step4 同时给出 `required_rcsd_node` 与 `local_rcsd_unit_id = *:node:<rcsdnode_id>`；

则 `t04_swsd_rcsd_relation_evidence.*` 面向 T05/T06 的 `required_rcsd_node_ids` 与 `base_id_candidate` 改用 `local_rcsd_unit_id` 中的 RCSD node。

原 `required_rcsd_node` 不丢弃，改写入新增字段 `semantic_required_rcsd_node_ids`，用于追溯 T04 Step4 识别到的 RCSD 语义主点。

## 边界

- 不改变 T04 accepted surface 几何。
- 不新增 T04 final state。
- 不放宽 `intersection_match_t04.geojson` 的 1:1 cardinality 校验。
- 不基于 case id 特判；规则只依赖 T04 Step4 已发布的结构化业务结果。
- 不修正 RCSD 原始拓扑数据，仅调整 T04 向 T05 发布关系基点的业务口径。

## 验证

- 新增 T04 Step7 单测覆盖 `road_surface_fork + partial` handoff。
- 仅使用 T10 case `991176` 做端到端回归，验证该前置修复是否提升目标 Segment，同时保护已成功替换 Segment 不回退。
