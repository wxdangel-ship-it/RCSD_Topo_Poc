# Dataset-P1 标签范围输出合同

正式 run 必须输出：

- `segment_package_lineage.jsonl`
- `segment_label_scope.jsonl`
- `expected_failure_scope.jsonl`
- `historical_metric_invalidation.jsonl`
- `dataset_p1_summary.json`
- `dataset_p1_manifest.json`
- `artifact_manifest.json`
- `validation_report.md`

`segment_label_scope.jsonl` 对 8,863 个当前 Segment每个只允许一行。
`label_eligible=true` 与 `scope_class=CONTEXT_ONLY_MASKED` 互斥。
`context_input_weight=0.3` 不得复制到 `label_weight`。

正式 signature 排除路径和运行时间，只覆盖规范化业务内容。Run B 必须匹配 Run A。
