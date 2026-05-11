# P01 Arm Build 模块执行规则

## 模块边界

- 本模块承载 P01 v1.0.0 的 A1 / A2 / Final 成果链路。
- A1 在 SWSD / RCSD / F-RCSD 三套数据内独立构建 Arm、特殊转向、ArmMovement、corrected trunk 与同源审计产物。
- A2 只能消费 A1 run root，不得静默改写 A1 输出；A2 以 F-RCSD FinalArm 为目标承载体输出跨三源 `LogicalArmGroup`、RawArmAlignment 与 ArmBuildFeedback。
- P01-Final 以 F-RCSD Road 为承载体，基于 SWSD / RCSD 源侧 ArmMovement 通行规则抽象、F-RCSD 道路角色投影、ArmSourceProfile 与 final generation decision 生成 `frcsd_road_next_road.geojson`；`Source` 只在 Road 级解释，精确源 Road 映射只作为审计 / 置信增强证据，不作为生成前提。
- `InitialArm` 保留原始 trace 终端归并事实；`FinalArm` 可在 trace 被局部边界过度切碎且 `LocalArmCandidate` 完整覆盖 InitialArm 时采用局部趋势兜底聚合，并写明 `merge_status / merge_reason`。
- 兜底聚合或多 source InitialArm 的 `FinalArm` 必须保留 `FinalArmValidation` 证据；该证据只用于健壮性审计和下游 risk gate，不改写原始 trace / through decision。

## 禁止事项

- 不实现 P01-A3 正式跨源 Movement 空间。
- 不实现 P01-B。
- 不实现禁行迁移或通行能力最终裁决。
- 不使用 `grade / grade_2` 参与 P01 主规则。
- 不使用 RoadNextRoad `turnType / turntype` 判定 `movement_type`。
- 不通过几何形态反推右转专用道 / 渠化右转。
- 不把 F-RCSD Source + CRS 归一化 rounded exact geometry 源 Road 映射作为唯一生成前提；也不通过空间接近或最近邻替代该审计证据。
- 不把主干道路或平行支路的部分目标退出 Road 覆盖静默投影为正常通行规则。
- 不仅凭几何最近输出 high confidence 配准。
- 不静默穿越 `ambiguous_boundary`。
- 不静默丢弃 seed road、RoadNextRoad、FRCSD FinalArm 或 source_extra Arm。
- 不自动拆分 over-merged Arm。
- 模块根目录不放 `SKILL.md`。

## 入口边界

- 仓库不提供 P01 repo 官方 CLI 子命令。
- 仓库不提供 P01 `scripts/` 常驻命令。
- 模块不提供 `__main__.py` 或 `run.py`。
- 稳定调用方式为模块内 callable runner；dev helper 仅用于取证、复现和开发验收，不登记为正式入口。

## 审计要求

- 输出必须包含输入路径、run id、junction group 原始 ID、trace、through decision、alignment candidate、ArmSourceProfile、SourceArmPassRule、final generation decision、source map、source policy 兼容审计、final RoadNextRoad audit、issue 和 review priority。
- GIS / 拓扑 / 空间数据任务必须覆盖 CRS、拓扑一致性、几何语义、审计可追溯性与性能可验证性。
