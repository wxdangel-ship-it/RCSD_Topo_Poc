# P05-Scheme-A-P1 输出合同

## Candidate run

```text
<candidate_run>/
  scheme_a_p1_candidate_manifest.json
  scheme_a_p1_candidate_summary.json
  candidate_groups.jsonl
  candidate_features.jsonl
  case_index.csv
  lineage.csv
  artifact_manifest.json
```

candidate run 不接受 label/truth path；manifest 必须记录 `truth_input_count=0`、`truth_derived_candidate_count=0`、`absolute_coordinate_feature_count=0`。

## Dataset run

```text
<dataset_run>/
  scheme_a_p1_dataset_manifest.json
  scheme_a_p1_dataset_summary.json
  feature_rows.jsonl
  labels.jsonl
  grouped_folds.csv
  leakage_audit.json
  reachability_audit.json
  artifact_manifest.json
```

dataset 必须固定引用 candidate manifest SHA-256 后才允许读取 Scheme A label。所有可用 label exact reachability 必须为 100%。

## OOF run

```text
<oof_run>/
  scheme_a_p1_oof_manifest.json
  scheme_a_p1_oof_summary.json
  checkpoints/<seed>/<fold>/...
  scores/<seed>/<fold>.jsonl
  predictions/<seed>.jsonl
  fallbacks/<seed>.jsonl
  cases/<seed>/<case_token>/roadgraph.json
  metrics/<seed>.json
  non_neural_baselines.json
  determinism_audit.json
  resource_audit.json
  qgis_gis_audit.json
  artifact_manifest.json
  validation_report.md
```

硬约束：

- 不覆盖既有 run；全部正式输出 SHA-256/size 可定位。
- OOF score 必须来自未训练目标 Case 的 checkpoint。
- `skeleton_mutation_count=0`、`truth_feature_count=0`、`relaxation=false`、`content_repair=false`、`silent_fix=false`。
- RoadGraph hard failure 不得通过补点、吸附、重连、改 ID 或择近合并消除。
