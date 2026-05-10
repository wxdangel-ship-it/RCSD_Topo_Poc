# 10 质量要求

## 正确性

- 语义路口必须基于 member node 集合。
- internal road 不进入 Arm。
- seed road 不得静默丢失。
- bit7 提前右转 road 不得进入 Arm member / seed / connector / trunk，必须生成 relation 或 issue。
- bit8 提前左转 road 可以进入 Arm member，但不得进入 trunk。
- trunk 状态必须显式输出；`complete_min_loop` 需要可由 trunk road ids 解释。
- 每个 through 判断必须输出业务状态。
- 同一 Road 不应跨多个 Arm 重复占用，双向 Road 在同一 Arm 内承担双角色除外。

## 可审计性

- preflight 记录输入路径、CRS、字段、feature count、run id。
- case_input 保留原始三套路口 ID。
- arm_traces 记录 seed、路径、节点、decision、stop、issue。
- issue_report 记录异常与风险。
- advance_right_turn_relations 记录提前右转 from Arm、to Arm、trace road/node、状态和风险。
- review index 与 summary 记录特殊转向、trunk、formway 缺失 / 不可解析统计。
- P01-Final 记录 F-RCSD source map、source policy、parallel branch alignment、final RoadNextRoad audit、issue report 与 generation metrics。

## GIS QA

- 输出 GPKG 使用输入 CRS。
- PNG 使用同一数据集 bounds；compare PNG 三栏使用同一视野范围。
- review GPKG / PNG 必须能目视区分 trunk、提前左转、提前右转与未解析 relation。
- P01-Final review GPKG / PNG 必须能定位 generated RoadNextRoad、source map 与 final issue。
- 不进行 silent geometry fix。

## 性能

- summary 记录总 group 数、dataset junction 数和运行耗时。
- synthetic 多组输入应在本地测试中稳定完成。
- A2 summary 记录 LogicalArmGroup、candidate、feedback、source_extra 和耗时。

## 验证

- py_compile。
- 单元测试。
- synthetic single group。
- synthetic multi group。
- 输出结构、summary、review index、PNG、GPKG 检查。
- 禁止 Grade 源码扫描。
- A2 synthetic 覆盖 stable、missing、partial、over_split、over_merged、conflict / uncertain 和多 group。
- A2 真实 case 至少验证 1019789，或明确记录真实数据未验证。
- P01-Final synthetic 覆盖 Source + CRS-normalized rounded exact mapping、同源继承、跨源 primary source、RCSD -> SWSD fallback、缺失 / 多匹配 issue 与 duplicate 防护。
