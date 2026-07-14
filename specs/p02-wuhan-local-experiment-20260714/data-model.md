# P02 数据模型

## 1. RawManualRelation

用户提供的不可变原始关系：

- `case_id`
- `swsd_segment_id`：初始为空；T01 后可补充影响 Segment 审计，不作为消费前提。
- `target_id`：原始 SWSD 语义路口 ID。
- `manual_relation_type`
- `selected_ids`：RCSDNode semantic ID 或 RCSDRoad ID。
- `comment`
- `source_manual_table`
- `source_manual_xlsx`

## 2. CanonicalManualRelation

Tool5 后交给 T05 的 T11 可消费关系。字段与 RawManualRelation 相同，但 `target_id` 已转换为最终 SWSD canonical semantic node ID。

## 3. ManualRelationTransformAudit

- `raw_target_id`
- `canonical_target_id`
- `raw_manual_relation_type`
- `raw_selected_ids`
- `canonical_source_node_id`
- `transform_status`：`unchanged / remapped / merged_to_1vN / deduplicated / conflict / missing_target`
- `conflict_reason`
- `source_row_number`

## 4. InputIntegrityAudit

- `dataset`
- `source_path / sha256 / crs`
- `road_count / node_count`
- `road_ids / node_ids` 或对应稳定 hash
- `missing_endpoint_road_ids / missing_endpoint_ids`
- `input_preserved`：完整 Road/Node 是否原样进入下一阶段
- `action`：原始输入为 `audit_only_no_clip`；用户确认覆盖为 `user_confirmed_copy_on_write_endpoint_override`

## 4.1 ConfirmedEndpointOverrideAudit

- `road_id / endpoint_field`
- `expected_old_node_id / replacement_node_id`
- `confirmation_source`
- `input_sha256 / output_sha256`
- `road_count_unchanged / road_id_set_unchanged / geometry_unchanged`
- `crosslid_used / nodelid_used / geometry_inference_used`：必须均为 `false`

## 5. P02RunManifest

- 输入绝对路径、大小、SHA256、CRS、要素数。
- git commit、分支、Python/GDAL/GEOS 运行环境。
- T08/T01/T05/T06 阶段输入输出路径、参数、开始/结束时间、退出状态。
- T03/T04/T07 未运行原因。
- 原始关系、转换关系、T05 发布关系和 T06 输出 lineage 路径。
