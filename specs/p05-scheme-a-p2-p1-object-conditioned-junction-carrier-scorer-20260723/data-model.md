# P05-Scheme-A-P2-P1 数据模型

## `P2P1Candidate`

- `case_key/group_id/candidate_id`：仅join、split和审计，不进入feature。
- `object_type`：`SEGMENT`或`NODE`。
- `candidate_target/action/source_kinds`：推理可用候选语义。
- `candidate_tokens/object_tokens/context_tokens/numeric_features`：ID-free模型输入。
- `output_object_ids/output_payload`：只供执行器物化和引用验证，不直接进入feature。
- `truth_derived=false/feature_uses_truth=false`。

## `P2P1Label`

- `truth_candidate_id`：candidate manifest冻结后label-only join。
- `carrier_target`：Segment使用有效carrier label；Node在候选冻结后按Segment真值Road来源选择`T01_NODE / PROPOSAL_NODE / OMIT`。
- `label_weight/fold/anomaly_target/mask_reason`。
- `label_only=true`。

## `P2P1Group`

- Segment group：一个冻结Segment及其Road candidate集合。
- Node group：一个Road endpoint/JunctionUnit Node ID及其来自PTO全量FINAL_NODE payload的T01/proposal carrier option与OMIT option。
- 每个可训练group恰有一个truth candidate；多truth等价项必须按稳定payload signature折叠后唯一。

## `JunctionCompatibilityRecord`

- `junction_id/related_segment_group_ids/required_node_group_ids`只用于约束和审计。
- `compatible_candidate_edges`由candidate payload端点、mainnode和冻结Junction relation生成，不读取truth。
- Oracle和模型选择共用同一兼容图；Oracle只提供label-only cost。

## `P2P1Score`

- `candidate_id/score/confidence/uncertainty/anomaly_probability`。
- `seed/fold/model_signature/context_signature`。
- 不含truth或Oracle cost。

## `P2P1Selection`

- `selected_candidate_id/decision/accepted/fallback_unit/reason`。
- `accepted=true`只允许高置信、低异常且兼容图hard gate通过。
- fallback后保留SWSD并记录`RealityChangeClue`，不得修改candidate payload。
