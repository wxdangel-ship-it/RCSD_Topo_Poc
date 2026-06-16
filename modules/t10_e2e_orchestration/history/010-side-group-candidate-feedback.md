# 2026-06-15 side-group candidate feedback

## 背景

T06 Step2 已能把双向 SWSD Segment 在 RCSD 全图中只存在单向通路的失败分类为 `requires_upstream_side_group_or_rcsd_directionality_review`。该状态表达的业务顺序是：先评估 T03/T04/T05 是否应把相关 RCSD semantic junction 聚合为同一虚拟路口面；若聚合不成立，再进入 RCSD 方向性或源资料复核。

旧产物只把 `rcsd_pair_nodes / candidate_rcsd_pair_node_sets` 保留在 problem registry 或 T10 segment feedback 中，二次迭代消费方需要重新解析 T06 审计字段。

## 变更

- T10 Case runner 新增 `t10_upstream_side_group_candidates.csv/json`。
- T10 Case runner 新增 `t10_upstream_side_group_endpoint_candidates.csv/json`，按 SWSD Segment 两端拆成 endpoint 级候选，供 T05 Phase2 可选消费。
- segment 级与 endpoint 级候选只收集 `problem_status = requires_upstream_side_group_or_rcsd_directionality_review` 的 Segment。
- 每行规整：
  - `swsd_endpoint_node_ids`
  - `rcsd_primary_pair_node_ids`
  - `candidate_rcsd_pair_node_sets`
  - `candidate_group_rcsdnode_ids`
  - `side_group_action = evaluate_virtual_junction_grouping_before_rcsd_directionality_review`
- endpoint 级每行规整：
  - `target_id`
  - `endpoint_index`
  - `rcsd_primary_node_id`
  - `candidate_rcsdnode_ids`
  - `side_group_action = supplement_existing_relation_with_endpoint_rcsdnode_grouping`
- Run manifest 与 summary 记录 `side_group_candidate_count` 和 CSV/JSON 路径。

## 边界

- 不判断聚合是否成立。
- 不把同一 Segment 两端合并为一个 T05 路口；T05 只消费 endpoint 级候选。
- 不修正 RCSD road 方向性。
- 不改变 T06 Step3 替换计划。
- 不影响 T09 restriction 生成。

该产物是 T06 失败分类向 T03/T04/T05 前置修复闭环的结构化输入，用于后续迭代消费。

## 2026-06-15 guard 结论

- 曾评估把 `requires_upstream_iteration` 中携带 `candidate_rcsd_pair_node_sets` 的 T03/T04/T05 前置问题也转成 endpoint candidate。
- `991176` 回归显示，这类 `candidate_rcsd_pair_node_sets` 在 `buffer_candidate_required_nodes_disconnected` 等场景下不具备稳定的 endpoint 下标语义，直接拆分会把另一端 RCSDNode 误归到当前端点，并触发既有 replaced Segment 回退。
- 因此正式规则保持收敛：只有 `requires_upstream_side_group_or_rcsd_directionality_review` 进入 endpoint candidate；其它问题保留在 problem registry，由后续模块根因分析决定是否新增更明确的反馈结构。

## 2026-06-15 no-op candidate guard

- `991176` feedback pass 后仍有 3 个 `requires_upstream_side_group_or_rcsd_directionality_review` Segment，但它们的 `candidate_rcsd_pair_node_sets` 没有引入 `rcsd_pair_nodes` 之外的新 RCSDNode。
- 这类候选不具备“侧聚合”增量，继续作为 `t10_upstream_side_group_endpoint_candidates` 回灌 T05 只会形成 no-op，不能改善替换率。
- T10 因此收紧自动反馈规则：side-group candidate 与 side-group endpoint candidate 只有在候选集合引入 primary pair 之外的 RCSDNode 时才发布。
- 被过滤的 Segment 仍保留在 `t10_upstream_feedback_segments.csv/json`，用于后续 T03/T04/T05 或 RCSD 源资料方向性根因分析。
