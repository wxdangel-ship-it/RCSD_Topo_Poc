# Output Contract: P05 M0

## 1. 不可变运行根

```text
<out-root>/<run-id>/
├── p05_m0_manifest.json
├── p05_training_samples.csv
├── p05_label_artifacts.csv
├── p05_grouped_split.csv
├── p05_data_anomalies.csv
├── p05_oracle_evaluation.json
├── p05_m0_summary.json
└── p05_m0_report.md
```

运行根启动前必须不存在；空表仍写稳定 header，不用缺文件表达空结果。

## 2. Summary 最小字段

- `schema_version/run_id/status`
- `scope.poc_data_root/allowed_source_families`
- `counts.discovered/usable/unusable/by_scope/by_weight/by_split/by_task`
- `quality.scope_violation/missing_manifest/missing_label/duplicate_group/cross_split_leakage/crs_issue`
- `oracle.status/road_f1/node_f1/attribute_accuracy/hard_fail_count`
- `runtime.stage_elapsed_seconds/object_counts/environment`
- `outputs.*`
- `silent_fix=false`
- `approved_exclusions[]`，包含 family、business ID、reason 与 decision source

## 3. 样本表

每行一个 package/sample，字段至少包含 data-model 的 TrainingSample 全部字段。list 字段使用稳定 JSON 字符串。

## 4. 标签表

每行一个 label role；缺失或 masked 仍保留行和原因。T10 Road/Node 主标签必须同时 available 才可开启 `road_graph` task。

## 5. 异常表

所有排除、降级和人工复核项必须进入异常表；禁止只在日志打印。

用户确认排除使用 `info:approved_sample_exclusion`，与仍需复评的 integrity error 分层；排除关闭全部训练 task mask，但不得删除样本、split assignment、label artifact 或 integrity evidence。
