# 004 - Phase2 允许多 SWSD 语义路口对应同一 RCSD 语义路口

## 时间

2026-06-15

## 背景

T10 Case `991176` 在 T07 RCSDIntersection 可消费性门禁修复后，剩余 `missing_pair_relation` 中有一类不是 T03/T04 没有构建关系，而是 T05 Phase2 的 cardinality QC 将 `many_target_to_one_base` 关系从最终 `intersection_match_all.geojson` 中剔除。

样例：

- `1049547` 与 `1019764` 同指向 RCSD base `5395688104730735`
- `39546709` 与 `987957` 同指向 RCSD base `5396513947461734`
- `61704236` 与 `603667457` 同指向 RCSD base `5389752728165570`

这些场景反映 SWSD 与 RCSD 语义路口工艺并不总是严格 1V1。同一 RCSD 语义路口可以服务多个 SWSD 语义路口，T05 若直接删除所有相关 relation，会导致 T06 无法消费本应存在的端点关系。

## 变更

- `many_target_to_one_base` 保留为 relation cardinality 审计行，但不再作为阻断错误。
- 仅 `one_target_to_many_base` 与 `duplicate_target_rows` 继续作为阻断错误，并从 `intersection_match_all.geojson` 中剔除相关 relation。
- `summary.relation_cardinality_blocking_error_count` 记录阻断型 cardinality 错误数。
- `summary.relation_cardinality_passed` 与 `summary.passed` 只受阻断型 cardinality 错误影响。

## 非目标

- 不放宽同一 SWSD target 指向多个 RCSD base 的错误。
- 不修改 T06 对 Segment 端点 distinct、buffer、方向性和拓扑连通性的判定。
- 不修改 RCSD 原始拓扑。

## 验证

- 单元测试覆盖 `many_target_to_one_base` 保留 relation、继续输出审计但不令 T05 失败。
- 回归测试限定为 T10 Case `991176`。
