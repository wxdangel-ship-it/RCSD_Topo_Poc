# P13-P0 输出合同

正式run至少输出：

- `feature_schema.json`
- `candidate_features.jsonl`
- `candidate_labels.jsonl`
- `fold_inventory.json`
- `model_checkpoints/seed_<seed>_fold_<fold>.npz`
- `training_summaries.jsonl`
- `candidate_scores.jsonl`
- `object_decisions.jsonl`
- `fold_metrics.json`
- `metrics.json`
- `p13_p0_summary.json`
- `p13_p0_manifest.json`
- `artifact_manifest.json`
- `validation_report.md`

`candidate_features.jsonl`必须在label读取前冻结并记录signature。
checkpoint必须记录seed、held-out/inner/train Case、feature transform、参数量、
best epoch和state signature；NPZ成员名、时间戳与JSON顺序固定，正式双跑必须
逐字节一致。score/decision必须能够追溯到候选、checkpoint、阈值和fallback原因。
