# P12 输出合同

## 1. `anchor_eligibility_ledger.jsonl`

每个 P11 人工对象一行，至少包含：

- 对象：`case_key/group_id/object_id/segment_type`
- 人工真值：`preferred_target/allowed_targets/clue_target/target_weight`
- 两侧：`side_a_target_id/side_b_target_id/side_source`
- T05：每侧的 `relation_present/status/base_id/anchor_pass/block_reason`
- carrier：`candidate_id/target_payload/carrier_available/carrier_anchor_compatible`
- 决策：`current_release_eligible/release_block_code`
- lineage：T01/T05/candidate/P11 输入 path、SHA-256

## 2. `t05_lineage_repair_queue.csv`

只包含人工 `USE_RCSD` 且当前因 T05 正式关系缺失或失败而不能发布的对象。不得包含：

- 仅因 RCSD carrier 缺失而 `KEEP_SWSD` 的对象；
- 已完成 T05 正式锚定的对象；
- 自动推断的新人工标签。

## 3. `metrics.json`

至少包含：

- `manual_object_count`
- `manual_use_count`
- `manual_keep_count`
- `use_t05_anchor_complete_count`
- `use_carrier_compatible_count`
- `use_release_eligible_count`
- `t05_lineage_repair_count`
- `keep_rcsd_unavailable_count`
- `clue_false_preserved_count`
- `t01_only_anchor_accept_count`
- `training_count`
- `geometry_write_count`
- `skeleton_mutation_count`
- `t01_t12_modification_count`

## 4. `p12_summary.json`

包含：

- `decision`
- `status`
- `counts`
- `gates`
- `lineage`
- `gis_audit`
- `performance`
- `determinism_signature`
- `silent_fix`

## 5. `p12_manifest.json`

记录输入与输出 path、size、SHA-256、运行参数、环境、正式 decision 和 content
signature。manifest 自身不进入 signature 递归计算。

## 6. 决策语义

- `ANCHOR_ELIGIBILITY_GO`：全部人工 USE 已完成 T05 与 carrier 闭环；
- `T05_LINEAGE_REPAIR_REQUIRED`：审计可信，但存在人工 USE 缺少 T05 正式 lineage；
- `AUDIT_NO_GO`：输入、join、权威性、确定性或隔离合同失败。
