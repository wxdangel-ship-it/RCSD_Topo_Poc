# 数据模型

## DatasetP1ScopeApplication

- `group_id`
- `case_key`
- `fold`
- `object_id`
- `label_eligible`
- `scorer_metric_eligible`
- `label_weight`
- `context_input_eligible`
- `context_input_weight`
- `object_failure_localized`
- `scope_class`

## EligibleTrainingExample

复用 P2-P3-P0 `HierarchicalTrainingExample`，但其 `group.sample_weight` 必须被
Dataset-P1 `label_weight`覆盖。只有 `label_eligible=true` 的对象可以进入
训练、inner validation、threshold和held-out metric。

## AllSegmentDecision

- eligible scorer decision：来自当前 held-out model；
- localized failure：`accepted=false`、`KEEP_SWSD`、
  `dataset_p1_localized_expected_failure`；
- context-only：`accepted=false`、`KEEP_SWSD`、
  `dataset_p1_context_only_fallback`。

## MetricScope

- scorer metric：6,275 eligible Segment；
- RoadGraph/effective selection：8,863 Segment；
- clue-only：13个历史对象中仅5个Dataset-P1 eligible对象；
- expected failure：2 Case × 3 seeds，各1个局部 failure group。
