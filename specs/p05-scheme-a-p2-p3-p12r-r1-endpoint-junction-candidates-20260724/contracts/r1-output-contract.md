# P12R-R1 输出合同

## 1. `advance_right_endpoint_candidates.jsonl`

逐候选记录Control/Treatment来源、component/bundle、两端incident、owner匹配、orientation、
距离、hop、歧义和冻结状态。

## 2. `advance_right_candidate_delta.jsonl`

逐对象记录Control/Treatment Road集合、新增/移除数、truth component hit、
Oracle变化、候选规模和fallback状态。

## 3. `endpoint_evidence_audit.jsonl`

记录两侧T01 owner context、原始RCSD endpoint图、trace结果、未加入原因和
label-free证据。

## 4. `fold_metrics.json`

记录Control/Treatment五个Case-grouped fold的对象、eligible、hit、recall、
候选规模和差值。

## 5. `metrics.json`

记录范围、来源、泄漏、endpoint语义、召回、规模、安全、GIS、资源和体量指标。

## 6. `r1_summary.json`

记录decision、Gate、Control/Treatment关键指标、signature和资源。

## 7. `r1_manifest.json`与`artifact_manifest.json`

记录配置、输入/输出path、size、SHA-256、data role、P12R引用、环境和双跑引用。

## 8. `validation_report.md`

以业务语言说明候选补强是否通过、剩余失败原因及是否具备P13技术启动理由。
