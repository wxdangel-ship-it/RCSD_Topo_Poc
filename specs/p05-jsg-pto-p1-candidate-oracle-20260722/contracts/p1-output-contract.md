# P05-JSG-PTO-P1 输出合同

## Candidate run

```text
p05_jsg_p1_candidate_manifest.json
p05_jsg_p1_candidate_summary.json
p05_jsg_p1_case_index.csv
p05_jsg_p1_group_index.csv
p05_jsg_p1_lineage.csv
p05_jsg_p1_candidates.jsonl
```

## Solve run

```text
p05_jsg_p1_solve_manifest.json
p05_jsg_p1_summary.json
p05_jsg_p1_case_index.csv
p05_jsg_p1_oracle_costs.jsonl
p05_jsg_p1_pto_a_certificates.jsonl
p05_jsg_p1_pto_b_certificates.jsonl
cases/<case_key>/
  selected_jsg.json
  pto_a_certificate.json
  pto_b_certificate.json
  compiled_road.gpkg
  compiled_node.gpkg
  roadgraph_evaluation.json
  artifact_manifest.json
```

## 必备断言

- candidate manifest 写出前不得打开任何 P0/R2 truth artifact。
- candidate manifest 为 `truth_input_count=0`、`truth_derived_candidate_count=0`。
- solve run 验证 candidate manifest/hash 后才读取 label-only truth。
- candidate 缺失、dependency infeasible、非 OPTIMAL、非零 gap、carrier 缺失或 compiler hard failure 直接失败。
- `relaxation=false`、`content_repair=false`、`silent_fix=false`。
- 第二轮不得覆盖第一轮；candidate 与 selection signature 分别比较。
