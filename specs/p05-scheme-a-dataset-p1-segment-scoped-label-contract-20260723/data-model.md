# P05-Scheme-A-Dataset-P1 数据模型

## `DatasetP1Config`

- Dataset-P0 run root
- Scheme A baseline run root
- P2-P3-P0 run root
- POC data root
- output root / run ID
- approved exclusions
- strict hash/scope/count/resource gates

## `SegmentPackageLineage`

- `case_key`
- `target_segment_id`
- `target_road_ids`
- `current_segment_ids`
- `current_segment_road_ids`
- `mapping_method`
- `mapping_status`
- `road_drift_observed`
- `manifest_path/sha256`
- `missing/duplicate/extra_road_ids`

## `SegmentLabelScope`

- `case_key/object_id/group_id`
- `family/fold`
- `scope_class`
- `label_eligible`
- `label_weight`
- `scorer_metric_eligible`
- `context_input_eligible/context_input_weight`
- `package_target_segment_id`
- `lineage_method`
- `case_terminal_state`
- `object_failure_localized`
- `reason`

## `ExpectedFailureScope`

- `case_key/seed`
- `terminal_state/publish`
- `failure_group_ids`
- `case_segment_count`
- `localized_failure_segment_count`
- `case_cascade_mask_count`

## `HistoricalMetricInvalidation`

- `stage`
- `artifact_status`
- `preserved_facts`
- `invalidated_metrics`
- `reason`
- `required_next_action`

## `DatasetP1Summary`

- Gate 0–5
- label/context/mapping denominators
- expected-failure double-layer audit
- GIS/resource/determinism audit
- decision/signature

所有输出只属于 P05 实验标签合同，不构成 T01–T12 source-of-truth 或生产输入。
