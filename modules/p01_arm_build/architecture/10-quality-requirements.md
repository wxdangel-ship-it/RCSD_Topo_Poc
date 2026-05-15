# 10 质量要求

## 正确性

- 语义路口必须基于 member node 集合。
- internal road 不进入 Arm。
- seed road 不得静默丢失。
- bit7 提前右转 road 必须按路口前 / 路口内区分：路口前不进入普通 Arm member / seed / connector / trunk，必须生成 relation 或 issue；路口内进入 Arm member / seed，但不得进入 trunk 或 relation。
- bit8 提前左转 road 可以进入 Arm member，但不得进入 trunk。
- trunk 状态必须显式输出；`complete_min_loop` 需要可由 trunk road ids 解释。
- 每个 through 判断必须输出业务状态。
- FinalArm 兜底聚合必须输出 validation 状态；`conflict` 不得静默进入下游自动生成，必须在 audit / review index 中暴露。
- ArmCorridorEvidence 必须作为独立审计证据输出；它不得改变 Arm member、seed、connector 或 trunk 结果。
- 同一 Road 不应跨多个 Arm 重复占用，双向 Road 在同一 Arm 内承担双角色除外。

## 可审计性

- preflight 记录输入路径、CRS、字段、feature count、run id。
- case_input 保留原始三套路口 ID。
- arm_traces 记录 seed、路径、节点、decision、stop、issue。
- issue_report 记录异常与风险。
- advance_right_turn_relations 记录提前右转 from Arm、to Arm、trace road/node、状态和风险。
- final_arm_validation 记录兜底 FinalArm 的 validation status、convergence、relaxed trace roads/nodes、terminal、confidence 与 risk。
- arm_corridor_evidence 记录 FinalArm 的 support roads/nodes、corridor angle、terminal、status 与 risk。
- review index 与 summary 记录特殊转向、trunk、formway 缺失 / 不可解析统计。
- P01-Final 记录 ArmSourceProfile、SourceArmPassRule、final generation decision、F-RCSD source map、兼容 source policy、parallel branch alignment、final RoadNextRoad audit、issue report 与 generation metrics。

## GIS QA

- 输出 GPKG 使用输入 CRS。
- retained audit PNG 使用固定局部视野；A2 compare PNG 三栏使用同一视野范围。
- review GPKG 与 retained audit PNG 必须能目视区分 trunk、提前左转、提前右转、Arm corridor support roads 与未解析 relation。
- P01-Final review GPKG 与 pass capability audit PNG 必须能定位 ArmSourceProfile、SourceArmPassRule、final generation decision、generated RoadNextRoad、source map 与 final issue。
- 不进行 silent geometry fix。

## 性能

- summary 记录总 group 数、dataset junction 数和运行耗时。
- 单 Case 使用全量 RoadNextRoad 输入时，完全不相交的 out-of-scope 记录必须只计入 skipped metrics，不得逐条进入 Case issue report。
- synthetic 多组输入应在本地测试中稳定完成。
- A2 summary 记录 LogicalArmGroup、candidate、feedback、source_extra 和耗时。

## 验证

- py_compile。
- 单元测试。
- synthetic single group。
- synthetic multi group。
- FinalArm validation 覆盖 not_required、validated、weak_validated、unvalidated 与 conflict。
- 输出结构、summary、review index、PNG、GPKG 检查。
- 禁止 Grade 源码扫描。
- A2 synthetic 覆盖 stable、missing、partial、over_split、over_merged、conflict / uncertain 和多 group。
- A2 真实 case 至少验证 1019789，或明确记录真实数据未验证。
- P01-Final synthetic 覆盖规则级 full_allowed 投影到全部目标退出 Road、主干 trunk_only 投影、主干 / 平行支路无法解释的部分覆盖报错、advance-left 与 uturn 特例、混源 Arm 规则源选择、alternate source role / corridor ordinal 低置信投影、RCSD 目标 Arm 缺失 fallback、精确源 Road 匹配缺失仍可规则生成、Source + CRS-normalized rounded exact mapping 审计、缺失 / 多匹配 issue 与 duplicate 防护。
