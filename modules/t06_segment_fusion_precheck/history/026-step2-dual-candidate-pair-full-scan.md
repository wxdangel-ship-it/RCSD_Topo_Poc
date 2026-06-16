# 026 Step2 双向高等级候选 Pair 全量正式试算

## 时间

2026-06-15

## 背景

T10/991176 回归中发现部分 `swsd_directionality=dual` 高等级 Segment 的 T05 原始 pair relation 在 RCSD 全图上仅单向可达，但 buffer-only probe 输出的候选 pair 集合中存在可双向消费的候选。旧逻辑只尝试 probe 排名第一的候选 pair，若第一候选仍无法通过双向硬审计，后续候选不会进入正式重试，导致可替换 Segment 继续落入 `directionality_mismatch_fixable`。

## 业务变更

- `pair_anchor_formal_retry` 对 `directionality_mismatch_fixable + rcsd_not_bidirectional_for_swsd_dual` 的高等级双向场景，不再只试算第一组候选 pair。
- 在保持“不回写 T05 relation”的前提下，遍历 buffer-only probe 输出的候选 pair，并分别执行正式双向 extractor、adaptive buffer、必要时的 `dual_graph_first_bidirectional_retry`。
- 只有恰好一个候选 pair 通过正式硬审计时，才允许在当前 Segment 内消费该 effective relation 并进入 replaceable。
- 多个候选 pair 均可通过、无候选通过、候选不满足高置信门槛或后续方向 / 几何 / 特殊组硬审计失败时，继续保持 rejected / 人工复核。

## 边界

- 不修改 RCSD 原始拓扑方向，不伪造双向可达。
- 不回写 T05 relation，不改变 T03/T04/T05 的正式路口聚合产物。
- 单向 Segment 的 `multi_anchor_ambiguous` 既有受限消歧规则不变。

## 审计

通过后仍写入 candidates / replaceable / failure business audit，并保留原始 pair、候选 pair、重审距离和来源失败原因，便于追溯本次替换是由 T06 当前 Segment effective relation 重试产生。
