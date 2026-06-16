# 2026-06-15 feedback iteration no-regression guard

## 背景

T06 Step2 已能把部分 Segment 失败分类为需要 T03/T04/T05 前置处理，并由 T10 发布 endpoint 级 side-group candidate。此前需要人工执行 baseline run，再手工把 `t10_upstream_side_group_endpoint_candidates.csv` 回灌给 T05 运行下一轮，缺少统一编排与不回退检查。

## 变更

- T10 Case runner 新增可选 `feedback_iterations` 参数；`scripts/t10_run_e2e_cases.sh` 通过环境变量 `T10_FEEDBACK_ITERATIONS` 暴露该能力。
- 当 `feedback_iterations > 0` 时，T10 在同一 `<run_id>` 下写入 `iterations/iteration_00_baseline/` 与后续 `iterations/iteration_<NN>_feedback_<NN>/`。
- 每一轮完整执行 `T01 -> T07 -> T03 -> T04 -> T05 -> T07 Step3 -> T06 Step1/2 -> T06 Step3 -> T09`，上一轮累积后的 `t10_upstream_side_group_endpoint_candidates.csv` 与 `auto_consumable_by_t05=true` 的 `t10_upstream_pair_anchor_endpoint_clusters.csv` 只作为下一轮 T05 Phase2 的可选 endpoint 级补充输入。
- 顶层 `t10_e2e_run_summary.json` 写入 `feedback_comparison`，比较 baseline 与最终 pass 的 replacement plan Segment 集合和 Step3 replaced Segment 集合。
- 若最终 pass 移除了 baseline 已经 replaced 的 Segment，或移除了 baseline 已在 replacement plan 中的 Segment，`feedback_regression_guard_passed = false`，该 run 不通过。
- feedback pass 之间的 side-group endpoint candidate 与 `auto_consumable_by_t05=true` 的 pair-anchor endpoint cluster 按业务字段去重累积，分别写入 `feedback_candidates/iteration_<NN>_cumulative_side_group_endpoint_candidates.csv` 与 `feedback_candidates/iteration_<NN>_cumulative_pair_anchor_endpoint_clusters.csv`，下一 pass 消费累积候选，而不是只消费上一 pass 新产物，避免第一轮新增替换在第二轮因候选不再重复发布而回退。
- 当当前 pass 新产出的 feedback candidate 与本 pass 输入候选在业务字段上完全一致时，T10 记录 `feedback_stop_reason = feedback_candidates_converged` 并提前停止后续 feedback pass，避免多轮重复消费无变化候选；收敛比较忽略 `problem_registry_path` 等来源路径字段，只比较业务字段。

## 边界

- 该迭代不新增执行入口，只扩展现有 T10 Case runner。
- 不把 T06 problem registry 直接作为替换白名单；仍由 T03/T04/T05 relation/junctionization 与 T06 Step2/Step3 判定最终替换。
- 不修改 RCSD road 方向性，不进行几何 silent fix，不反推未授权字段语义。
- 默认 `T10_FEEDBACK_ITERATIONS=0`，保持既有单 pass 行为。
