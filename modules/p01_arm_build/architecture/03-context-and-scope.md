# 03 上下文与范围

## 上下文

P01 的成果目标是为 F-RCSD 重建路口级 RoadNextRoad。P01-A1 提供单源 Arm、特殊转向、movement 与 corrected trunk；P01-A2 提供跨三源 LogicalArmGroup；P01-Final 使用 F-RCSD Road、Source 映射与源 RoadNextRoad evidence 生成最终 F-RCSD RoadNextRoad。

## 范围

- 基础数据读取。
- 多 junction group 批处理。
- 语义路口组装。
- seed road 识别。
- 显式右转专用道 / 渠化右转排除。
- `formway` bit7 / bit8 特殊转向识别。
- Arm trace。
- InitialArm / FinalArm / corrected_final_arms 输出。
- ThroughDecisionAudit。
- IssueReport。
- Review PNG / compare PNG / review GPKG。
- Summary / review index。
- RoadNextRoad-aware ArmMovement。
- RoadMovementEvidence。
- ReceivingRoadRole。
- Movement-aware trunk correction。
- F-RCSD Source + CRS-normalized rounded exact source road mapping。
- SourceMovementPolicy。
- 同源继承、跨源 primary source 与 RCSD -> SWSD fallback。
- `frcsd_road_next_road.geojson`、final audit、issue report、review GPKG / PNG。
- A2 ArmProfile、candidate edge、RawArmAlignment、LogicalArmGroup、ArmBuildFeedback 与 source_extra。
- A2 配准 review PNG / compare PNG / review GPKG / summary / review index。

## 范围外

- P01-A3 正式跨源 Movement 空间建模。
- 禁行信息迁移。
- F-RCSD 通行能力最终裁决。
- P01-B。
- Lane 级能力。
- 未在 P01 v1.0.0 定义的 RoadNextRoad 推理规则。
