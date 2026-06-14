# 009 Step1 self-pair fallback 排除

- 时间：2026-06-12
- 背景：T10 当前漏斗中 `swsd_pair_nodes_not_distinct` 共 34 条，全部来自 T01 `oneway_single_road_fallback`，`sgrade=0-2单`，且 `pair_nodes=A,A`。这些 Road 的两个物理端点归属于同一 SWSD 语义路口，不构成两个语义路口之间的 RCSD Segment 替换主通道。
- 根因：T01 为保留未分段 Road 会生成同一语义路口内部 fallback Segment；T06 Step1 只校验 `pair_nodes` 数量为 2，导致 self-pair fallback 进入 final fusion units，并在 Step2 被计入替换分母后以 `swsd_pair_nodes_not_distinct` rejected。
- 变更：T06 Step1 在 EVD / anchor eligibility 前检查 `pair_nodes` 是否为两个不同 SWSD 语义路口；若两端相同，写入 `t06_swsd_segment_rejected.*`，reason 为 `swsd_pair_nodes_not_distinct`，不进入 final fusion units 和 Step2 替换分母。
- 边界：Step2 仍保留同一 reason 的防御性硬拒绝，防止外部直接传入非法 fusion unit；本变更不修改 T01 输出、不猜测 T01 fallback Road 属性含义、不把 self-pair Road 强行并入其它 Segment。
- 回归：新增 `test_step1_excludes_self_pair_segments_from_step2_fusion_units`，覆盖 self-pair 被 Step1 rejected、合法 Segment 继续进入 Step2 并完成替换的组合 runner 场景。
