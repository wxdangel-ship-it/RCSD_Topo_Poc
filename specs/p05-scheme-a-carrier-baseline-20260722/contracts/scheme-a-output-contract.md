# 方案 A 输出合同

正式不可变 run root：

```text
<run_root>/
  scheme_a_manifest.json
  scheme_a_summary.json
  case_inventory.csv
  segment_inventory.csv
  strategy_baseline.csv
  carrier_labels.jsonl
  reality_change_clues.jsonl
  fallback_plans.jsonl
  cases/<case_token>/frozen_skeleton.json
  artifact_manifest.json
  validation_report.md
```

硬约束：

- 目标目录不得已存在；
- 输入 P0/M0 manifest 和声明输出必须验证 SHA-256；
- 每个 Case 的历史 `jsg_truth.json` 必须通过其 `artifact_manifest.json`；
- `segment_inventory.csv` 必须逐条覆盖 T01 Segment；
- 当前输出不得出现 `SegmentConnector` object type；
- labels 只能是 carrier/anomaly 软目标，不能包含骨架增删改目标；
- clue/fallback 不得修改输入或输出 GPKG；
- 所有 JSON/JSONL 使用稳定键序和 canonical hash；
- manifest 必须记录 `skeleton_mutation_count=0`、`content_repair=false`、`silent_fix=false`；
- artifact manifest 覆盖除自身以外的全部正式输出并记录 SHA-256/size。
