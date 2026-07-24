# Data Model: P05-PTO-P0

## StrategyReplayDescriptor

- `family/code_commit/worktree/input_root/output_root`
- `case_ids/excluded_case_ids/command/stop_after`
- `input_manifest_paths/input_hashes/output_manifest_path/output_hashes`
- `status/environment/duration_seconds`
- 不包含 truth path 或 oracle artifact。

## PTOCandidate

- `candidate_id/sample_id/stage/object_kind/group_id/action`
- `base_object_id/output_payloads/pointer_value`
- `canonical_payload_sha256`
- `sources[]`：`BASE_IDENTITY` 或 `STRATEGY_REPLAY`，含 commit/run/artifact hash。
- `label_only=false/truth_derived=false`

## CandidateManifest

- `schema_version/run_id/case_scope/exclusion`
- `base_lineage/strategy_replay_lineage`
- `candidate_artifacts/output_hashes`
- `candidate/variable/constraint counts`
- `truth_input_count=0/truth_derived_candidate_count=0`
- `silent_fix=false`

## OracleCostRecord

- `candidate_manifest_sha256/candidate_id`
- `cost/truth_equivalent/match_reason`
- `truth_artifact_path/truth_artifact_sha256`
- `label_only=true`

## PTOSolveCertificate

- `sample_id/status/objective/lower_bound/optimality_gap`
- `selected_candidate_ids/selection_sha256`
- `constraint_counts/hard_failures`
- `relaxation=false/content_repair=false/silent_fix=false`

## PTOCaseResult

- candidate/variable/constraint/action/coverage counts。
- reconstructed Road/Node paths 与 output hash。
- M0 evaluation 与归一化 RoadGraph signature。
- replay/build/solve/materialize/evaluate/peak RAM 性能。
