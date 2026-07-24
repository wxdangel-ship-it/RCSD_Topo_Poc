# P11 输出合同

## 必需输出

- `stable_clue_fp_ledger.jsonl`
- `manual_review_queue.csv`
- `manual_review_guide.md`
- `metrics.json`
- `scheme_a_p2_p3_p11_summary.json`
- `validation_report.md`
- `scheme_a_p2_p3_p11_manifest.json`
- `artifact_manifest.json`

## `stable_clue_fp_ledger.jsonl`

每个稳定对象一行，至少包含：

- `group_id/case_key/object_id/fold`
- `truth_basis/label_weight/lineage_method`
- `truth_target/selected_targets`
- `control/treatment`三个seed的Clue probability、threshold与prediction
- `source_applicable/source_modules`
- `segment_type/swsd_road_ids`
- `source_segment_access/target_segment_access/access_valid`
- `locator_method/locator_layer/locator_expression`
- `manual_adjudicated`
- `attribution`
- `risk_tags`
- `manual_review_priority`
- `qgis_project_path`

正式输入必须为50行，`group_id`唯一。

## `manual_review_queue.csv`

只包含未被P10对象级人工确认、且命中Spec第4节风险规则的对象。必须包含：

- Case、Segment对象ID与Segment类型；
- QGIS工程绝对路径；
- 普通Segment的T01 Segment过滤表达式，或`ADVANCE_RIGHT`的SWSD Road过滤表达式
  与source/target access；
- 当前Case级真值、carrier真值/选择；
- 风险标签与三seed Clue概率；
- 待用户填写的`reviewed_clue_target`、`reviewed_allowed_targets`、
  `reviewed_preferred_target`与`review_reason`空列。

## 隔离字段

所有输出必须声明：

- `training_count=0`
- `threshold_tuning_count=0`
- `model_weight_change_count=0`
- `movement_decision_count=0`
- `geometry_read_count=0`
- `geometry_write_count=0`
- `t01_t12_modification_count=0`

P11不得输出或应用新的模型决策、fallback plan或RoadGraph。

## 人工裁决接受合同

人工填写CSV必须与原始队列的非填写列逐值一致，且：

- 19行全部填写；
- `reviewed_clue_target`只能为`true/false`；
- `reviewed_allowed_targets`为非空、唯一的已知carrier集合；
- `reviewed_preferred_target`必须属于allowed集合；
- `review_reason`非空；
- `USE_RCSD`裁决承载“两侧路口正确锚定且替换连接正确”的用户确认。

接受工件必须保存原始/填写CSV hash、逐对象1.0真值和合并后的P10人工真值manifest。
