# P05-Scheme-A-P2-P0 输出合同

## Candidate run

- `scheme_a_p2_candidate_manifest.json`
- `scheme_a_p2_candidate_summary.json`
- `segment_candidate_index.jsonl`
- `node_carrier_options.jsonl`
- `case_index.csv`
- `artifact_manifest.json`

Candidate run 必须 `truth_input_count=0`、`truth_derived_candidate_count=0`、`movement_candidate_count=0`。

## Oracle run

- `scheme_a_p2_oracle_manifest.json`
- `scheme_a_p2_oracle_summary.json`
- `segment_joint_truth.jsonl`
- `junction_node_selection.jsonl`
- `reality_change_clues.jsonl`
- `case_results.csv`
- `cases/<token>/roadgraph.json`
- `artifact_manifest.json`
- `validation_report.md`

所有记录必须包含 `case_key`、对象 ID、candidate/source、fallback/clue、lineage 和 stable signature。Oracle payload 为 `label_only=true`；不得成为 future scorer feature。
