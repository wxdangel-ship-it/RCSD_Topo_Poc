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
- [x] 提前右转 road 按路口前 / 路口内分流：路口前不进入普通 Arm member / seed / connector / trunk，进入 AdvanceRightTurnRelation 或 issue；路口内进入 Arm member / seed，排除出 trunk。
- [x] `AdvanceRightTurnRelation` 输出与 issue 审计。
- [x] InitialArm / FinalArm / LocalArmCandidate / ArmTrace / ThroughDecisionAudit / IssueReport 输出。
- [x] LocalArmCandidate 使用方向性 seed corridor 兜底分组，综合进入 / 退出角色、局部趋势和远端道路一致性，避免 InitialArm 复用。
- [x] FinalArm fallback validation 输出 `final_arm_validation.json`，并将 validation 状态写入 FinalArm / corrected_final_arms / summary / review index。
- [x] FinalArm 输出 `arm_corridor_evidence.json`，以非 member 远端走廊证据增强 A2 配准和 Movement 方向判断。
- [x] trunk_road_ids / trunk_status / trunk_reason 输出。
- [x] RoadNextRoad 读取与归一化。
- [x] 单 Case 默认按语义道路拓扑 BFS=8 子图加载 Node / Road，并按 selected road ids 流式过滤 RoadNextRoad。
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
- [x] ArmSourceProfile 混源审计。
- [x] SourceArmPassRule 源侧规则抽象。
- [x] Source + CRS-normalized rounded exact source road mapping 审计。
- [x] missing / ambiguous source geometry mapping issue。
- [x] SWSD / RCSD SourceMovementPolicy 兼容审计。
- [x] 规则级 full_allowed 生成到目标 Arm 所有退出 Road。
- [x] 主干目标 trunk 完整覆盖时 trunk_only 投影；其它无法解释的主干 / 平行支路部分目标覆盖报错。
- [x] advance-left / uturn 特殊合法范围。
- [x] 混源 Arm SWSD 优先、RCSD 次之、SWSD basic rule 兜底。
- [x] primary source 无可生成规则时 alternate source role / corridor ordinal 低置信投影。
- [x] RCSD 目标 Arm 缺失时 SWSD basic fallback。
- [x] 精确源 Road 匹配缺失仍可规则生成。
- [x] entering arm road count mismatch manual review。
- [x] parallel_branch count mismatch data error。
- [x] source parallel branch missing in F-RCSD audit。
- [x] parallel_branch alignment 独立审计对象。
- [x] missing right-turn carrier issue。
- [x] final `frcsd_road_next_road.geojson`。
- [x] final source map、ArmSourceProfile、SourceArmPassRule、final generation decision、audit、issue report。
- [x] duplicate `(road_id, next_road_id)` 防护。

## 5. 验证

- [x] py_compile。
- [x] A1 regression tests。
- [x] FinalArm validation not_required / validated / weak_validated / unvalidated / conflict tests。
- [x] A2 regression tests。
- [x] P01-Final synthetic tests。
- [x] Grade / grade_2 源码扫描。
- [x] turnType / turntype movement_type 禁用检查。
- [x] 文档过程性措辞扫描。
- [ ] 真实 1019789 RoadNextRoad case 本地执行；依赖可访问的真实 RoadNextRoad 与内网数据路径。
- [ ] 真实 RCSD `turntype` 输出编码规范确认；仓库已按模块契约映射输出。
- [x] `950044` A2 source Arm 复用误绑定修复；通过 source Arm 互斥优先分配回归覆盖。
