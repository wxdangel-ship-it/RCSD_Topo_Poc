# P05-JSG-PTO-P0 数据模型

## JSGCaseTruth

- `schema_version`
- `case_key`
- `source_manifest`
- `source_hashes`
- `crs`
- `junction_units[]`
- `standard_segments[]`
- `junction_segment_relations[]`
- `physical_movements[]`
- `segment_connectors[]`
- `carrier_realization`
- `anomalies[]`
- `content_repair=false`
- `silent_fix=false`

## JunctionUnit

- `junction_id`
- `junction_type`: `NORMAL | ROUNDABOUT | COMPLEX_DIVMERGE | TERMINAL_DEAD_END | TERMINAL_DATA_BOUNDARY | TERMINAL_UNKNOWN`
- `growth_level`
- `evidence_refs[]`
- `state`: `PUBLISHABLE | REVIEW | UNKNOWN`

## StandardSegmentUnit

- `segment_id`
- `endpoint_positions[2]`
- `attached_junctions[]`
- `direction_structure`: `DIRECTED | BIDIRECTIONAL | UNKNOWN`
- `growth_level`
- `road_grade`
- `carrier_road_ids[]`
- `evidence_refs[]`
- `explicit_loop`
- `state`

## JunctionSegmentRelation

- `junction_id`
- `segment_id`
- `structural_role`: `ENDPOINT | THROUGH`
- `direction_role`: `ENTER | EXIT | BOTH | UNKNOWN`
- `access_legs[]`
- `evidence_refs[]`
- `state`

## PhysicalMovement

- `movement_id`
- `junction_id`
- `from_segment_access`
- `to_segment_access`
- `physical_reachable`
- `carrier_road_ids[]`
- `evidence_refs[]`
- `state`

## SegmentConnector

- `connector_id`
- `source_segment_access`
- `target_segment_access`
- `direction=FORWARD`
- `carrier_road_ids[]`
- `evidence_refs[]`
- `state`

## CarrierRealization

- `r2_oracle_run_manifest`
- `r2_case_manifest`
- `road_edits_path`
- `node_edits_path`
- `expected_truth_road`
- `expected_truth_node`
- `artifact_hashes`
- `label_only=true`

`CarrierRealization` 是 P0 编译真值引用，不是未来模型输入。

## Canonical 规则

- 对象按稳定 ID 排序；集合字段排序去重；序列语义字段保持业务顺序。
- JSON 使用 UTF-8、排序键和稳定分隔符。
- signature 只覆盖规范化语义内容，不包含绝对输出目录、运行时间或性能值。
- provenance signature 单独覆盖输入绝对路径、hash 和环境。
