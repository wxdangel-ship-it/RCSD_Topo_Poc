# Data Model: P05-R2

## BaseGraphObject

- `sample_id/fold/object_kind/object_id`
- `source_role/artifact_path/artifact_sha256/crs`
- `geometry/properties/snodeid/enodeid`
- 仅来自 raw/T01 推理可用输入。

## RoadEdit

- `edit_id/sample_id/action`
- `base_road_id`：`COPY/UPDATE/SPLIT/DROP` 的输入引用。
- `output_road_ids`：零个、一个或多个输出。
- `output_payloads`：每个输出的 geometry、direction、source、端点和审计属性。
- `lineage_kind`：`same_id/split_parent/create`。
- `label_only=true`：oracle truth payload。

## NodeEdit

- `edit_id/sample_id/action/base_node_id/output_node_id`
- `output_geometry/output_properties`
- `label_only=true`。
- `stage=FINAL/T05`：`FINAL` 物化最终 T06 Node；`T05` 先物化同一推理内 pointer 可引用的 copy-on-write/CREATE 候选 Node。

## T05PointerTarget

- `target_id/candidate_base_ids/selected_base_id/no_match`
- `availability/trust_tier/weight/artifact lineage`
- `selected_base_id` 必须存在于候选集合，除非 `no_match=true`。
- 候选集合来自同次推理的 T05 Node edit 物化结果，键为 Node `id` 或非零 `mainnodeid`；truth T05 Node 仅生成 target。

## R2OracleCase

- `sample_id/fold/base artifacts/truth artifacts`
- `road_edits/node_edits/t05_node_edits/pointer_targets`
- `truth counts/represented counts/action counts`
- `reconstructed Road/Node paths/evaluation/hard failures`

## R2ModelTarget

- edit action/existence/pointer/attributes/endpoints/geometry mask 与权重。
- truth payload 与 target tensor 只用于 loss/evaluation，不进入 input feature schema。
