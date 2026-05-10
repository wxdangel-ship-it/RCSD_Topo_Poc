# P01 Arm Build 模块执行规则

## 模块边界

- 本模块承载 P01 v1.0.0 的 A1 / A2 / Final 成果链路。
- A1 在 SWSD / RCSD / F-RCSD 三套数据内独立构建 Arm、特殊转向、ArmMovement、corrected trunk 与同源审计产物。
- A2 只能消费 A1 run root，不得静默改写 A1 输出；A2 以 F-RCSD FinalArm 为目标承载体输出跨三源 `LogicalArmGroup`、RawArmAlignment 与 ArmBuildFeedback。
- P01-Final 以 F-RCSD Road 为承载体，基于 `Source + 几何完全一致` 源 Road 映射、SWSD / RCSD SourceMovementPolicy、同源继承、跨源 primary source 与 RCSD -> SWSD fallback 生成 `frcsd_road_next_road.geojson`。
- `InitialArm` 保留原始 trace 终端归并事实；`FinalArm` 可在 trace 被局部边界过度切碎且 `LocalArmCandidate` 完整覆盖 InitialArm 时采用局部趋势兜底聚合，并写明 `merge_status / merge_reason`。

## 禁止事项

- 不实现 P01-A3 正式跨源 Movement 空间。
- 不实现 P01-B。
- 不实现禁行迁移或通行能力最终裁决。
- 不使用 `grade / grade_2` 参与 P01 主规则。
- 不使用 RoadNextRoad `turnType / turntype` 判定 `movement_type`。
- 不通过几何形态反推右转专用道 / 渠化右转。
- 不通过空间接近替代 F-RCSD Source + 几何完全一致源 Road 映射。
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

- 输出必须包含输入路径、run id、junction group 原始 ID、trace、through decision、alignment candidate、source map、source policy、final RoadNextRoad audit、issue 和 review priority。
- GIS / 拓扑 / 空间数据任务必须覆盖 CRS、拓扑一致性、几何语义、审计可追溯性与性能可验证性。
