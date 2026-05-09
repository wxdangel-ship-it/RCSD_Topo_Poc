# 01 引言与目标

## 状态

- 当前状态：P01-A 模块源事实
- 模块：`p01_arm_build`
- 阶段：`P01-A1 / Arm 构建`、`P01-A2 / Arm 配准` 与 `P01-Final / F-RCSD RoadNextRoad 还原`

## 目标

本模块为 P01 POC 验证链路提供 Arm 结构基础与最终 F-RCSD RoadNextRoad 还原能力：A1 在已知 SWSD / RCSD / F-RCSD 对应路口 ID 的前提下分别构建当前语义路口 Arm；A2 读取 A1 run root，以 F-RCSD FinalArm 为目标承载体，构建跨三源 LogicalArmGroup；P01-Final 基于 A1 RoadNextRoad-aware 输出、F-RCSD Road.Source 与源 RoadNextRoad evidence 生成最终 F-RCSD RoadNextRoad。

## 成功标准

- 多组路口输入可批处理。
- 三套数据各自输出 Arm 构建结果。
- 每条 seed road 有归属或 issue。
- through 判断输出业务状态。
- review PNG / compare PNG / review GPKG 可用于人工判断。
- summary / review index 可支持批量筛查。
- A2 每个 FRCSD FinalArm 进入 LogicalArmGroup 或输出明确不可用原因。
- A2 后续 Movement 只消费 `acceptable_for_downstream = true` 的 LogicalArmGroup。
- P01-Final 输出 `frcsd_road_next_road.geojson`、source map、source policy、audit 与 issue report。
