# 02 数据与领域模型

- `RawManualRelation`：用户原始 SWSD target 与 RCSDNode/RCSDRoad 关系。
- `CanonicalManualRelation`：Tool5 后使用最终 `mainnodeid` 转换的 T11 关系。
- `TransformAudit`：raw target 到 canonical target、selected ID 和状态 lineage。
- `InputIntegrityAudit`：分别记录 Tool1 原始转换结果与 P02 工作副本的 Road/Node 数量、ID 集合、缺失端点引用、CRS 与 hash。
- `ConfirmedEndpointOverride`：用户逐项确认的临时 `SNodeId/ENodeId` 覆盖；以 `road_id + endpoint_field + expected_old_node_id + replacement_node_id` 唯一约束，不承载推断规则。
- `P02RunManifest`：T08/T01/T05/T06 跨阶段运行事实。
