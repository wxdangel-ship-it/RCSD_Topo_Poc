# Data Model：Target A

## 1. InferenceFeatureStore

城市级、可复用、无标签缓存：

- `manifest`: 输入路径/hash、schema、CRS、构建版本；
- `objects`: T01/SWSD/RCSD/T07 对象引用；
- `geometry_tensors`: 局部投影坐标、方向、长度、曲率和相对位置；
- `graph_index`: Road/Node/Junction/Segment/access 异构边；
- `candidate_index`: truth-free 锚定、Road 片段、split 和挂接候选；
- `missingness`: 输入缺失、证据完整度和候选检索覆盖。

## 2. TrainingLabelStore

与 InferenceFeatureStore 物理隔离：

- `sample_scope`: source family、case、target object、label weight、context-only；
- `anchor_labels`: acceptable/preferred 锚定候选、状态、break target；
- `ordinary_plan_labels`: acceptable/preferred 完整 plan；
- `advance_right_labels`: 条件化完整 plan；
- `clue_labels`: clue、冲突类型、affected objects、fallback scope；
- `node_recipe_labels`: 由 Road 来源条件化的 T01/proposal/OMIT 与 break/splice；
- `provenance`: artifact hash、replay version、人工裁决和 mask 原因。

## 3. PlanCandidate

一个候选必须是可独立验证的完整业务方案：

- `plan_id`：仅当前样本内稳定引用，不作为学习特征；
- `decision`: `USE_RCSD | KEEP_SWSD | ABSTAIN`；
- `roads[]`：
  - `source_kind`: `SWSD | RCSD`；
  - `source_road_ref`；
  - `piece_ref` 与 split position；
  - `role`: `MAIN | INTERNAL_CONNECTOR | ATTACHED_SWSD | ADVANCE_RIGHT`；
  - `owner_segment_ref` 或合法的 no-owner connectivity；
  - `direction`;
- `source_access` / `target_access`;
- `anchor_requirements[]`;
- `node_recipes[]`;
- `attachments[]`;
- `hard_validity`;
- `unsupported_reason`。

普通 Segment 禁止通用 `HYBRID`。只有 Road role 明确为
`MAIN(RCSD) + ATTACHED_SWSD(SWSD)` 时才是 T06 允许的普通 Segment
混源 carrier。

AdvanceRight `MIXED_SPLICE` 是独立的条件化几何方案，不属于通用
`HYBRID`。它仅在 source/target 相邻普通 Segment 最终 access Road 来源
一侧为 RCSD、另一侧为 SWSD 时成立；模型必须输出 RCSD/SWSD 源 Road、
两侧保留区间、最终方向和 splice 位置。最终 Road role 仍为
`ADVANCE_RIGHT`，所有权仍属于该提右 Segment；缺少任一明确输出时只允许
该 AdvanceRight Segment fallback。

## 4. AnchorDecision

- `swsd_junction_ref`;
- `status`: `SUCCESS | NO_EVIDENCE | AMBIGUOUS | ABSTAIN |
  UNSUPPORTED_COMPOSITE_ANCHOR`;
- `selected_rcsd_junction_refs[]`;
- `selected_rcsd_road_refs[]`;
- `break_recipes[]`;
- `confidence`；
- `clue` 与 `affected_objects[]`。

## 5. DecisionLedger

- 输入 manifest/hash；
- model/checkpoint/config/split；
- 每个 anchor 的最终决定；
- 每个普通 Segment 的候选集、选择、access 和 fallback；
- 每个 AdvanceRight 的条件 access、选择、挂接和 fallback；
- clue 与显式有限 `FallbackDirective`；
- hard validation 结果；
- materialization 指令。

Ledger 是阶段间唯一落盘业务结果；RoadGraph 只在最终物化时写一次。

## 5. FallbackDirective

`FallbackDirective` 是模型输出的业务决定，不是由 decoder 从图连通性推导：

- `directive_id`：不可变审计 ID；
- `scope`：仅 `SEGMENT` 或 `JUNCTION`；
- `junction_id`：仅 Junction 级必填；
- `affected_segment_ids`：模型明确判断受影响的 Segment；
- `reason`：模型判断的业务原因。

Segment 级必须且只能包含一个 Segment。Junction 级的每个 affected Segment
都必须是冻结 T01 中该 Junction 的直接关联对象；确定性层只校验，不补全整个
Junction，也不经这些 Segment 传播到另一端 Junction。多个 directive 重叠时
可以对同一 Segment取更严格的 Junction 级执行结果，但不得合并为新的传递闭包。
