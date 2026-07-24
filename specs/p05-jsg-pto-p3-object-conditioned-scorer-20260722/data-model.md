# P05-JSG-PTO-P3 数据模型

## P3GroupContext

- `case_key/fold/group_id/object_type/domain`：只用于 join、split 与 audit。
- `context_tokens`：ID-free self/dependency/reverse/case-profile token。
- `context_signature`：canonical token signature。
- `feature_uses_truth=false`。

## P3FoldVocabulary

- candidate/context token 映射与 unknown index。
- `train_case_keys/inner_validation_case_keys/held_out_case_keys`。
- token 来源计数、held-out unknown audit、dataset manifest hash。

## P3ContextScorer

- candidate/context embedding。
- candidate/context encoder。
- gated interaction MLP 与 object-type embedding。
- 参数量、初始化 seed、训练超参数、checkpoint/model signature。

## P3CandidateScore

- `candidate_id/case_key/fold/seed/domain/group_id`。
- `cost/confidence/uncertainty/selected`。
- `model_signature/context_signature/score_source`。
- candidate/context unknown-token count。

## P3SeedSummary

- JSG overall/macro/per-type、Review precision/recall、ECE。
- PTO-A/PTO-B、RoadGraph/GIS、资源与 hard failure。
- checkpoint/score/selection/JSG/RoadGraph signature。

## P3ValidationSummary

- 3-seed all-pass 判定。
- V1 与 candidate-only ablation 比较。
- `P3_SCORER_GO/P3_MODEL_NO_GO/P3_UPSTREAM_OR_IMPLEMENTATION_BLOCKED`。
- online/production 状态固定为 NO-GO。
