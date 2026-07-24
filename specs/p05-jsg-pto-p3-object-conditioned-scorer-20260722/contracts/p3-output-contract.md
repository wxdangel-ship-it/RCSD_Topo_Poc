# P05-JSG-PTO-P3 输出合同

## Dataset run

- `p05_jsg_p3_group_context.jsonl`
- `p05_jsg_p3_context_vocabulary.json`
- `p05_jsg_p3_case_index.csv`
- `p05_jsg_p3_leakage_audit.json`
- `p05_jsg_p3_dataset_summary.json`
- `p05_jsg_p3_dataset_manifest.json`

## Fold/seed model

- `model.pt`
- `model_contract.json`
- `fold_vocabulary.json`
- `training_history.csv`
- `training_summary.json`

## OOF/seed run

- `p05_jsg_p3_scores.jsonl`
- `p05_jsg_p3_group_metrics.csv`
- `p05_jsg_p3_case_index.csv`
- `p05_jsg_p3_certificates.jsonl`
- `p05_jsg_p3_seed_summary.json`
- `p05_jsg_p3_oof_manifest.json`

## Final validation

- `seed_comparison.json`
- `determinism_audit.json`
- `gis_audit.json`
- `resource_audit.json`
- `test_audit.json`
- `validation_summary.md`

所有 JSON/CSV/JSONL 使用稳定字段顺序或 canonical hash。模型二进制必须有 SHA-256 和对应 JSON contract；任何输出不得省略输入 manifest/hash、fold/seed、运行环境、`relaxation/content_repair/silent_fix` 状态。
