# P01 v1.0.0 Coverage Tasks

## 1. 文档与契约

- [x] 模块 README 覆盖 A1 / A2 / P01-Final。
- [x] 模块接口契约覆盖输入、输出、业务对象、final generation 与审计规则。
- [x] architecture 文档覆盖 v1.0.0 成果链路。
- [x] SpecKit spec / plan / tasks 与 v1.0.0 口径一致。
- [x] 建立 v1.0.0 覆盖审计文档。

## 2. P01-A1

- [x] 读取 SWSD / RCSD / F-RCSD Node 和 Road。
- [x] 多 `--junction-group` 批处理。
- [x] 语义路口按 `mainnodeid` 聚合。
- [x] seed road、internal road 与 trace 构建。
- [x] kind-aware through / stop 判断。
- [x] `formway` bit7 / bit8 位运算识别。
- [x] 提前左转 road 标记并排除出 trunk。
- [x] 提前右转 road 排除出 Arm member / seed / connector / trunk。
- [x] `AdvanceRightTurnRelation` 输出与 issue 审计。
- [x] InitialArm / FinalArm / LocalArmCandidate / ArmTrace / ThroughDecisionAudit / IssueReport 输出。
- [x] trunk_road_ids / trunk_status / trunk_reason 输出。
- [x] RoadNextRoad 读取与归一化。
- [x] RoadMovementEvidence 映射与 issue 审计。
- [x] 全量 ArmMovement 候选。
- [x] `movement_type` 不使用 `turnType / turntype`。
- [x] ReceivingRoadRole 统计。
- [x] advance-left-only receiving road trunk correction。
- [x] corrected_final_arms 输出。
- [x] A1 PNG / GPKG / summary / review index。

## 3. P01-A2

- [x] A1 run root 读取。
- [x] ArmProfile 构建。
- [x] candidate matrix 与 evidence graph。
- [x] RawArmAlignment。
- [x] LogicalArmGroup。
- [x] coverage missing / partial 与 grouping error 区分。
- [x] ArmBuildFeedback。
- [x] source_extra 输出。
- [x] A2 PNG / GPKG / summary / review index。

## 4. P01-Final

- [x] F-RCSD Road `Source` 读取与校验。
- [x] Source + geometry exact source road mapping。
- [x] missing / ambiguous source geometry mapping issue。
- [x] SWSD / RCSD SourceMovementPolicy。
- [x] 同源继承源 RoadNextRoad。
- [x] 跨源 primary source generation。
- [x] RCSD -> SWSD fallback。
- [x] entering arm road count mismatch manual review。
- [x] parallel_branch count mismatch data error。
- [x] source parallel branch missing in F-RCSD audit。
- [x] missing right-turn carrier issue。
- [x] final `frcsd_road_next_road.geojson`。
- [x] final source map、audit、issue report。
- [x] duplicate `(road_id, next_road_id)` 防护。

## 5. 验证

- [x] py_compile。
- [x] A1 regression tests。
- [x] A2 regression tests。
- [x] P01-Final synthetic tests。
- [x] Grade / grade_2 源码扫描。
- [x] turnType / turntype movement_type 禁用检查。
- [x] 文档过程性措辞扫描。
- [ ] 真实 1019789 RoadNextRoad case 本地执行；依赖可访问的真实 RoadNextRoad 与内网数据路径。
