# 025 Step2 同一 RCSD 语义路口折叠不可替换审计

## 时间

2026-06-15

## 背景

T05 Phase2 放开 SWSD 多个语义路口映射到同一个 RCSD 语义路口后，T06 可以消费更多正式 relation，但会出现部分 SWSD Segment 的 pair 两端在 relation 后归并到同一个 RCSD 语义路口。该场景无法构建具有两个端点的可替换 RCSDSegment。

## 业务变更

- T06 Step2 对 `reject_reason=rcsd_pair_nodes_not_distinct` 且 `rcsd_pair_nodes` 去重后只有一个 RCSD 语义路口的失败 Segment，登记为 `problem_status=accepted_non_replaceable`。
- 该状态表示 T06 已审计确认：当前 relation 表达的是同一个 RCSD 路口内部关系，不应再要求 T03/T04/T05 重跑，也不允许 Step3 兜底替换。
- `feedback_action` 固定为 `record_as_t06_non_replaceable_no_upstream_rerun`，`replan_trigger` 固定为 `no_current_rerun_required`。

## 不变项

- 不修改 T05 relation。
- 不修正 RCSD 原始拓扑或方向性。
- 不把该 Segment 纳入 replacement plan。
- 其他缺失 relation、方向性不通、buffer 内不连通等失败类型仍按原有上游迭代逻辑处理。

## 验证要求

- T06 replacement plan 单测覆盖该状态。
- 端到端回归只使用 Case `991176`，确认上游反馈减少且最终替换结果不回退。
