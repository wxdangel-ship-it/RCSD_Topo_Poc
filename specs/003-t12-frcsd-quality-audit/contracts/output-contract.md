# Output Contract: T12 FRCSD 质量审计

## 1. 运行根

```text
<out-root>/<run-id>/
├── t12_frcsd_quality_audit_manifest.json
├── t12_frcsd_quality_audit_summary.json
├── t12_frcsd_quality_candidates.csv
├── t12_frcsd_quality_candidates.gpkg
├── t12_frcsd_carrier_evidence.gpkg
├── t12_frcsd_confirmed_quality_issues.csv
├── t12_frcsd_confirmed_quality_issues.gpkg
├── t12_frcsd_quality_review_exclusions.csv
├── t12_frcsd_quality_manual_review_required.csv
└── t12_frcsd_quality_report.md
```

即使计数为 0，契约文件也必须存在；空空间图层使用稳定 schema，不用缺文件表达空结果。

运行根必须在启动时不存在；系统不得覆盖、追加或清理同名历史运行。

## 2. Summary 最小字段

- `schema_version / run_id / status`
- `target.frcsd_*_sha256 / target.evidence_relation / target.t05_run_identity`
- `counts.segment_total / audited_segment_count / candidate_count`
- `counts.confirmed_quality_issue_count / review_exclusion_count / manual_review_required_count`
- `counts.by_issue_type / counts.by_review_status`
- `crs.input_crs / crs.processing_crs / crs.transform_applied`
- `quality.invalid_geometry_count / endpoint_missing_count / t07_truth_audit`
- `runtime.elapsed_seconds / stage_elapsed_seconds / object_counts`
- `outputs.*`
- `silent_fix=false`

## 3. Candidate CSV 最小字段

`candidate_id,segment_id,candidate_status,suggested_issue_type,required_directions,failed_directions,anchor_modules,base_nodes,portal_equivalent,drivezone_in_road_ratio,local_directed_status,local_undirected_status,full_directed_status,t06_reject_reason,t06_root_cause,review_status,review_reason`

禁止 `confidence/probability/high/medium`。

## 4. Review 输出

- confirmed CSV/GPKG：只含 `confirmed_frcsd_quality_issue`。
- exclusions CSV：只含 `excluded_false_positive`。
- manual CSV：未提供决定、决定为 manual 或证据不完整的候选。
- 三者 candidate ID 必须互斥，合计等于 candidate count。

## 5. Carrier Evidence GPKG

至少包含图层：

- `candidate_segments`
- `anchor_portals`
- `swsd_required_carriers`
- `frcsd_carrier_paths`

所有图层 CRS 必须等于 processing CRS；字段保留源对象 ID 和 path kind。
