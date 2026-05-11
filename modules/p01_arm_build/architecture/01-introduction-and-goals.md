# 01 引言与目标

## 模块定位

`p01_arm_build` 是 P01 v1.0.0 的结构构建、跨源 Arm 配准与 F-RCSD RoadNextRoad 还原模块。模块覆盖：

- `P01-A1`：单源 Arm 构建、特殊转向识别、ArmMovement 与 trunk 修正。
- `P01-A2`：三源 Arm 配准与 `LogicalArmGroup` 构建。
- `P01-Final`：最终 `F-RCSD:RoadNextRoad.geojson` 生成。

P01 的最终成果是面向 F-RCSD Road 的路口级允许通行关系。模块必须同时输出机器可消费结果、审计链路、GIS 图层与目视检查材料。

## 目标

- 从 SWSD / RCSD / F-RCSD Node、Road 与可选 RoadNextRoad 中构建语义路口 Arm。
- 用 `formway` bit7 / bit8 识别提前右转、提前左转，并输出 `AdvanceRightTurnRelation`。
- 基于 RoadNextRoad allowed evidence 生成同源 ArmMovement、ReceivingRoadRole 与 corrected trunk。
- 基于 A1 输出构建跨三源 LogicalArmGroup，并区分 coverage missing 与 grouping error。
- 基于 SWSD / RCSD 源侧 ArmMovement 通行规则抽象、F-RCSD 道路角色投影与 ArmSourceProfile 审计生成最终 F-RCSD RoadNextRoad；精确源 Road 映射仅作为审计 / 置信增强证据。
- 输出 JSON / GeoJSON / PNG / GPKG / summary / review index / audit / issue report。

## 成功标准

- 多组路口输入可批处理。
- A1 每套数据输出 Arm、trace、through decision、特殊转向、movement、corrected trunk 与 issue。
- A2 每个 FRCSD FinalArm 进入 LogicalArmGroup 或输出明确不可用原因。
- P01-Final 输出去重后的 `frcsd_road_next_road.geojson`、ArmSourceProfile、SourceArmPassRule、final generation decision、source map、兼容 source policy、audit 与 issue report。
- RoadNextRoad `turnType / turntype` 不参与 `movement_type` 判定。
- `grade / grade_2` 不进入 P01 主规则。
- review PNG / compare PNG / review GPKG 可用于人工判断。
- summary / review index 可支持批量筛查和优先级排序。
