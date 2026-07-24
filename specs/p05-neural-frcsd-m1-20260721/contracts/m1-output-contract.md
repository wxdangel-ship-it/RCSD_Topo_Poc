# Contract: P05 M1 输出

M1 使用互相引用 hash 的不可变分阶段 run，而不是覆盖同一目录。

dataset run 至少包含：

- `p05_m1_dataset_manifest.json`
- `p05_m1_input_artifacts.csv`
- `p05_m1_candidate_roads.csv`
- `p05_m1_operation_labels.csv`
- `p05_m1_graph_index.json`
- `p05_m1_entity_leakage_audit.csv`
- `p05_m1_anomalies.csv`
- `p05_m1_normalization.json`
- `p05_m1_dataset_summary.json`

baseline run 至少包含 `p05_m1_baseline_manifest.json` 与 `p05_m1_baselines.json`。training run 至少包含：

- `p05_m1_training_manifest.json`
- `p05_m1_training_history.json`
- `p05_m1_development_metrics.json`
- `p05_m1_model_config.json`
- `p05_m1_model.pt`

evaluation run 至少包含：

- `p05_m1_evaluation_manifest.json`
- `p05_m1_evaluation_summary.json`
- `p05_m1_case_metrics.json`
- `p05_m1_predictions.csv`
- `cases/<model>/<case-hash>/predicted_road.gpkg`
- `cases/<model>/<case-hash>/predicted_node.gpkg`
- `cases/<model>/<case-hash>/metrics.json`

## 必需审计字段

- M0 manifest path/hash 与全部消费 output hash；
- 输入 artifact path/hash、CRS、schema 和 feature count；
- candidate/label schema version、split、权重和 entity guard decision；
- 模型配置、参数量、seed、checkpoint hash 和阈值冻结时间；
- Python/PyTorch/CUDA/GPU、CPU、RAM/VRAM、wall time；
- 每个预测 GPKG hash、M0 evaluator 原始结果和 hard failures；
- `silent_fix=false`。

manifest 最后写入，包含以上正式输出的 SHA-256 与字节数。run root 已存在时必须阻断，禁止覆盖。
