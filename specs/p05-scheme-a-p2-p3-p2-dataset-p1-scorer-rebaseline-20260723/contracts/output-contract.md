# 输出合同

正式 run 至少包含：

- `dataset_p1_scope_application.jsonl`
- `eligible_scores.jsonl`
- `eligible_decisions.jsonl`
- `eligible_evaluation.jsonl`
- `all_segment_decisions.jsonl`
- `effective_selections.jsonl`
- `roadgraph_index.jsonl`
- `junction_closure.jsonl`
- `fold_index.json`
- `metrics.json`
- `feature_audit.json`
- `scheme_a_p2_p3_p2_summary.json`
- `scheme_a_p2_p3_p2_manifest.json`
- `artifact_manifest.json`
- `validation_report.md`

manifest 必须记录：

- Dataset-P1 manifest和scope hash；
- eligible/context/all Segment分母；
- seeds/folds/模型参数；
- source-role与leakage计数；
- normalized determinism signature；
- RoadGraph 49+2终态；
- geometry、CRS、骨架、repair、silent fix、Movement、T06 model-input审计；
- 阶段decision。
