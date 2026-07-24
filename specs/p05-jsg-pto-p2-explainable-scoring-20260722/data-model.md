# P05-JSG-PTO-P2 数据模型

## P2FeatureRow

- `candidate_id`：仅用于 join/audit，不进入 scorer feature。
- `case_key/fold/domain/stage/object_type/group_id`：仅用于 split/group/evaluation，不进入 scorer feature。
- `feature_tokens[]`：ID-free 稀疏 token。
- `truth_equivalent`：label-only，只用于 train/evaluation。
- `sample_weight`：来自 M0 target/context 权重。
- `feature_signature/label_signature`。

## P2LinearModel

- `held_out_fold`
- `train_case_keys[]/held_out_case_keys[]`
- `feature_weights{token: weight}`
- `bias`
- `smoothing`
- `train_weighted_positive/negative`
- `dataset_manifest_sha256`
- `model_signature`

## P2CandidateScore

- `candidate_id/group_id/case_key/domain/stage/object_type`
- `cost`
- `confidence`
- `uncertainty`
- `margin`
- `score_source: V0_EXPLICIT | V1_LINEAR_OOF`
- `fold/model_signature/feature_signature`
- `explanation_reconstructable=true`

## P2SelectionCertificate

- `case_key/scorer`
- `pto_a_status/gap/selection_signature`
- `pto_b_status/gap/selection_signature`
- `selected_jsg_signature/roadgraph_signature`
- `ranking_metrics/compiler_metrics/GIS metrics`
- `relaxation=false/content_repair=false/silent_fix=false`

## Canonical 规则

- feature token 排序去重；禁止任何 ID token。
- model signature 不包含输出目录、时间或 held-out label。
- score signature 覆盖 candidate ID、fold、model signature 和 cost，不覆盖 wall/CPU。
- selection signature 不覆盖绝对路径和运行时间。
