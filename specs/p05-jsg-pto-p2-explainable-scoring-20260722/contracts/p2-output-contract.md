# P05-JSG-PTO-P2 输出合同

## Dataset run

```text
p05_jsg_p2_dataset_manifest.json
p05_jsg_p2_dataset_summary.json
p05_jsg_p2_case_index.csv
p05_jsg_p2_feature_vocabulary.json
p05_jsg_p2_features.jsonl
p05_jsg_p2_leakage_audit.json
```

## OOF run

```text
p05_jsg_p2_oof_manifest.json
p05_jsg_p2_oof_summary.json
p05_jsg_p2_case_index.csv
p05_jsg_p2_scores.jsonl
p05_jsg_p2_group_metrics.csv
p05_jsg_p2_models/fold_0..4.json
p05_jsg_p2_certificates.jsonl
cases/<case>/<V0|V1>/selected_jsg.json
cases/<case>/<V0|V1>/selected_road.gpkg
cases/<case>/<V0|V1>/selected_node.gpkg
cases/<case>/<V0|V1>/roadgraph_evaluation.json
```

## 必备断言

- dataset manifest 固定 P1 candidate/label 与 M0 split/hash。
- feature artifact 中 forbidden token/字段计数为 0。
- held-out fold label 不参与 fold model 统计。
- 所有候选有 V0/V1 OOF score；所有 V1 score 可从 token+model 重建。
- solver 不读取 truth cost；truth 只在 selection 后评价。
- 任何 infeasible/hard failure 保留，不回退 Oracle 或补图。
- Run B 不覆盖 Run A；score/selection/JSG/RoadGraph signature 分别比较。
