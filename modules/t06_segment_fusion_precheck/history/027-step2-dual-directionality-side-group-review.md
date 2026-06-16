# 027 Step2 双向方向性失败的侧聚合 / RCSD 方向性复核分流

## 时间

2026-06-15

## 背景

T10/991176 中存在 `swsd_directionality=dual` 的 Segment：T05 当前 pair relation 在 RCSD 全图上只支持单向可达；buffer-only probe 可能发现另一组候选端点，但正式双向 extractor、adaptive buffer 或 dual graph-first 仍无法通过硬审计。典型现象是反向 path 远离当前 Segment 或长度比明显超限，T06 不能把这类绕行当作合法反向通道。

## 业务变更

- `t06_segment_replacement_problem_registry.problem_status` 新增 `requires_upstream_side_group_or_rcsd_directionality_review`。
- 该状态仅用于 `rcsd_not_bidirectional_for_swsd_dual + directionality_mismatch_fixable + full_rcsd_graph_one_direction_only` 且未被 replacement plan 覆盖的 Segment。
- 反馈 owner 调整为 `T03/T04/T05_or_RCSD_directionality_review`，recommended module 为 `T03/T04/T05_or_RCSD_source_review`。
- 反馈动作明确为：先评估 T03/T04/T05 是否能形成双幅端点侧聚合；若侧聚合无法成立，再进入 RCSD 方向性或源资料复核。

## 边界

- 不放宽 T06 Step2 的双向可达、50m core、长度比、额外 mapped semantic node 或几何覆盖硬审计。
- 不把该状态视为 `accepted_non_replaceable`；它仍进入 T10 上游反馈包，供前置模块或资料复核队列消费。
- 不改变已有 replacement plan 覆盖的 Segment，保证已成功替换结果不回退。

## 审计

该状态会保留 `root_cause_category / reject_reason / candidate_rcsd_pair_node_sets / evidence_artifacts`，并通过 T10 `t10_upstream_feedback_segments.*` 汇总。
