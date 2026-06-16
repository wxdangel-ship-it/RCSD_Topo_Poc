# 2026-06-16 T10 feedback regression guard 展开 replacement plan 组级覆盖

## 背景

T06 Step2 引入 `path_corridor_group` 后，合法结果可能从 baseline 的单段 `standard_segment` plan 变成 final 的组级 plan，原 Segment 进入 `group_segment_ids`。此前 T10 feedback regression guard 只按 plan 行 `swsd_segment_id` 对比，会把这种“单段升级为组级 action 成员”的变化误判为 replacement plan 回退。

## 业务变更

- T10 replacement plan 防回退集合改为“plan 覆盖 Segment 集合”。
- 普通 plan 行继续读取 `swsd_segment_id`。
- 组级 plan 行额外展开 `group_segment_ids`，用于判断 baseline 已有 Segment 是否仍被 final plan 覆盖。
- 防回退语义不变：若 baseline 已覆盖 Segment 在 final 的 plan 覆盖集合中消失，仍判定 `feedback_regression_guard_passed=false`。

## 审计影响

`feedback_comparison.baseline_replacement_plan_segment_count / final_replacement_plan_segment_count` 现在表示被 plan 覆盖的 SWSD Segment 数量，而不是 CSV plan 行数。
