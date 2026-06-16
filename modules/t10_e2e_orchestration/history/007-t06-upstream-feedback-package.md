# 007 T06 上游反馈包

## 背景

T10 4-case 端到端审计中，T06 Step2 已能输出 `t06_segment_replacement_problem_registry.*`，但 run 级结果只提供 Case 内漏斗，无法直接按 `T01/T03/T04/T05/T08/T06` 归属查看仍需根因模块迭代的 Segment。

## 业务变更

1. T10 Case runner 在 run root 新增 `t10_upstream_feedback_segments.csv/json`。
2. 该逐 Segment 反馈只收集 `problem_status = requires_upstream_iteration` 的问题，保留推荐模块、上游归属、失败业务分类、拒绝原因、根因分类、回流动作、证据产物与来源 registry 路径。
3. T10 Case runner 在 run root 新增 `t10_upstream_feedback_summary.csv/json`，按 `recommended_module + upstream_issue_owner + failure_business_category + reject_reason + root_cause_category` 聚合计数，并保留样例 Case / Segment。
4. `t10_e2e_run_manifest.json` 与 `t10_e2e_run_summary.json` 记录反馈包路径与计数。

## 边界

- 不改变 T06 Step2 / Step3 的替换判定。
- 不改变 T09 限制生成。
- 不把反馈包解释为 Step3 替换白名单。
- 不执行几何变换、拓扑修复或字段语义反推。

## 验证

- 新增 T10 单元测试覆盖 requires-upstream 行过滤、摘要聚合与来源 registry 路径保留。
