# P12R 输出合同

## 1. `advance_right_realization_truth.jsonl`

每个冻结 `ADVANCE_RIGHT Segment` 一行，包含：

- identity、Case、P12R fold和冻结access；
- 两侧相邻普通Segment及required/realized source；
- truth plan、SWSD/RCSD Road lineage、splice和fallback；
- attachment Segment与动作；
- RealityChangeClue和全部label lineage。

## 2. `advance_right_candidate_ceiling.jsonl`

每个对象一行，包含：

- 仅来自T01/原始RCSD的候选组件；
- candidate role、Road/Node lineage和空间关联证据；
- T06终态候选排除计数；
- truth可组合性、candidate oracle命中和失败原因。

## 3. `advance_right_attachment_audit.jsonl`

记录每个提右的：

- source/target相邻Segment；
- 其它挂接Segment；
- attachment/closure/topology label evidence；
- 独立Road保留、最终引用和硬失败状态。

## 4. `fold_metrics.json`

至少包含：

- 5个P12R Case fold的Case数、对象数；
- eligible对象数；
- candidate oracle hit/count/recall；
- 可比较候选组数量；
- 最差fold召回。

## 5. `metrics.json`

至少包含：

- inventory、lineage、access和两侧来源指标；
- plan type与fallback原因分布；
- attachment、独立Road和拓扑硬失败指标；
- T05提右标签、T06候选泄漏和RealityChangeClue误报指标；
- 总体/分foldcandidate oracle指标；
- training、geometry write、skeleton mutation和T01–T12修改计数。

## 6. `p12r_summary.json`

包含：

- decision、status、counts和gates；
- candidate ceiling、fold和安全结论；
- GIS、性能、隔离、确定性和silent fix；
- content signature和reference run match。

## 7. `p12r_manifest.json`

记录输入/输出path、size、SHA-256、参数、环境、数据角色、正式decision和
content signature。manifest自身不进入递归signature。

## 8. `validation_report.md`

以业务语言说明：

- 提右真值是否重建完成；
- 当前候选是否足以启动P13；
- 若不通过，问题属于标签、候选、数据、拓扑还是lineage；
- 是否需要用户目视审计及其最小对象清单。
