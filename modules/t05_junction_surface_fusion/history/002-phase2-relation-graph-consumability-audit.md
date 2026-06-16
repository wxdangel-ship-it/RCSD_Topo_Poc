# 002 Phase2 Relation Graph Consumability Audit

## 日期
- 2026-06-15

## 背景
- T10 端到端审计发现部分 `intersection_match_all.geojson` 中 `status = 0` 的 T05 relation，后续在 T06 表现为 `pair_anchor_mismatch` 或 `full_rcsd_graph_missing_required_nodes`。
- 典型现象是 relation 的 `base_id` 来自 T07/T03/T04 evidence，但该 id 无法在 T05 最终发布的 `rcsdnode_out.gpkg` 中作为 `id/mainnodeid` 定位，或无法落到 `rcsdroad_out.gpkg` 的端点图上。

## 根因
- T05 原有 relation 发布只校验了 relation cardinality 与 `base_id` 非零，没有补充校验该 `base_id` 是否可被最终 RCSD road graph 消费。
- T06 需要消费的是可通过 `rcsdroad_out.gpkg / rcsdnode_out.gpkg` 建立路径的 RCSD 语义路口端点；T05 若发布不可消费 relation，会把问题延后暴露为 Segment 替换失败。

## 本次边界
- 不改写 `intersection_match_all.geojson`。
- 不以最近点、固定距离或 case 级条件把缺失 `base_id` 强行替换成其他 RCSDNode。
- 不修正 RCSD 原始拓扑方向性或 RCSDRoad 连通性。
- 只新增 T05 Phase2 relation graph consumability 审计，为后续回到 T03/T04/T07 relation evidence 或 T05 junctionization 发布逻辑提供明确问题分类。

## 实际变更
- 新增 `relation_graph_consumability_audit.csv/json`。
- 对每条 relation 记录：
  - `base_id` 是否存在于 `rcsdnode_out.id`。
  - `base_id` 是否存在为 `rcsdnode_out.mainnodeid` group。
  - 匹配到的 RCSDNode 中是否至少一个是 `rcsdroad_out.snodeid/enodeid` 端点。
  - 上游来源模块、case、场景、原因与建议动作。
- `summary.json` 新增 `relation_graph_consumability_*` 统计字段。
- 新增单元测试覆盖 graph 可消费 base 与 `status = 0` 但 base 缺失于 `rcsdnode_out` 的场景。

## 验证
- 待运行 T05 Phase2 单元测试。
- 待运行 T05 模块测试与 `git diff --check`。
