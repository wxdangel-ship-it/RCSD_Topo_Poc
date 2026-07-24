# P05-JSG-PTO-P1 数据模型

## JSGP1Candidate

- `candidate_id`
- `case_key`
- `stage`: `PTO_A | PTO_B`
- `object_type`
- `object_key`
- `group_id`
- `group_mode`
- `payload`
- `dependencies[]`
- `evidence_refs[]`
- `source_kinds[]`
- `truth_derived=false`
- `label_only=false`

## JSGP1CandidateSet

- `schema_version`
- `case_key/family/business_id`
- `crs`
- `source_manifest/source_hashes`
- `candidates[]`
- `roadgraph_candidate_ref`
- `truth_input_count=0`
- `truth_derived_candidate_count=0`
- `silent_fix=false`

## PTO-A group

- Junction type/state group
- StandardSegment direction/state group
- Relation direction/state group
- Movement select/review group
- Connector outcome group

## PTO-B group

- RoadGraph `FINAL_ROAD/FINAL_NODE/T05_NODE/T05_POINTER` candidate group
- Unit carrier/access feasibility group
- Review/Unknown carrier fallback group

## JSGP1SolveCertificate

- `case_key`
- `candidate_manifest_sha256`
- `truth_manifest_sha256`
- `pto_a_status/objective/lower_bound/gap`
- `pto_b_status/objective/lower_bound/gap`
- `selected_candidate_ids[]`
- `semantic_coverage`
- `carrier_feasibility`
- `compiler_metrics`
- `relaxation=false`
- `content_repair=false`
- `silent_fix=false`

## Canonical 规则

- candidate 按 `candidate_id` 排序，group 按 `group_id` 排序。
- payload 使用 UTF-8、排序键和稳定分隔符。
- candidate signature 不包含 truth、cost、输出目录或运行时间。
- selection signature 覆盖候选 manifest hash、选中 ID 与证书状态，不覆盖 wall/CPU。
