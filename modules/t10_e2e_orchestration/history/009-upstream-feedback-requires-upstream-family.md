# 009 上游反馈收集 requires_upstream 状态族

## 时间

2026-06-15

## 背景

T06 problem registry 不再只有通用 `requires_upstream_iteration`。双向方向性失败需要区分“前置双幅端点侧聚合 / RCSD 方向性复核”，以避免 T10 汇总把不同修复责任混成同一类。

## 业务变更

- T10 上游反馈包收集 `problem_status` 以 `requires_upstream` 开头的所有 Segment。
- 保留原有 `requires_upstream_iteration` 行为。
- 新增状态如 `requires_upstream_side_group_or_rcsd_directionality_review` 会进入 `t10_upstream_feedback_segments.*` 与 summary。

## 边界

- 不收集 `accepted_non_replaceable / covered_by_replacement_plan / resolved_in_step2_plan`。
- 不改变 T06 replacement plan，也不改变 Step3 的替换执行。
