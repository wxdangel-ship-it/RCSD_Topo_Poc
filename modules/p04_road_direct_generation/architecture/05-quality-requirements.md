# P04 架构：质量要求

## 1. 验收原则

P04完成不是“代码运行”“pytest通过”或“QGIS能打开”。必须同时证明：

1. 业务Segment完整；
2. 高精几何真实；
3. Road/Node拓扑自洽；
4. LaneTopo和局部结构可追溯；
5. 跨Patch和重复运行稳定；
6. 发布后独立QA通过；
7. QGIS人工审计完成。

## 2. 业务完整性hard gate

- T01 Segment覆盖率100%。
- 每个Segment四态唯一。
- 每个发布Segment至少一条独立Road。
- `hp_full/hp_partial/swsd_retained/conflict_retained`与replacement scope一致。
- 强证据充分且hard gate通过却无原因retained的对象数为0。
- 低优先级member Surface推导抢占已成立Segment级高精走廊的对象数为0；每轮新增目标相对当前冻结候选的已通过目标丢失数为0。
- 单Segment失败不引发Junction组整体回退。
- 每条正式Segment Road的全部适用Access均实际交接，不能以同Segment其它Road代替。
- RealityChangeClue无simple Road时不进入正式Segment。

## 3. 几何hard gate

- Road几何非空、有效、方向明确。
- 零长度、异常自交、方向/物理重复为0。
- built Road SWSD直接坐标splice为0。
- observed/constrained span无缝完整覆盖built Road。
- constrained completion不越出合法道路域、不穿越hard barrier/foreign surface。
- endpoint surface局部路由在平滑前后均满足正式合法域覆盖门槛；超局部范围、超绕行比例、无法为平滑保留边界余量或需要SWSD坐标时拒绝。
- Movement切分产生的端点面外主干尾段不得形成第三条断裂方向主干；任何抑制必须具备同父carrier唯一贯穿片段和显式审计。
- built/retained接头和Segment内部连接无不可解释断裂。
- Patch边界人工断裂为0。

具体中心偏差、道路面覆盖、曲率接缝、长度膨胀阈值必须先对真实数据和历史基线复算，再作为当前POC参数写入manifest；不得直接升级为生产容差。

## 4. Junction与拓扑hard gate

- 所有Road起终Node存在。
- 同一JunctionUnit mainnode一致率100%。
- `actual_shared_node`型RoadNextRoad均有真实共享Node且方向相容；`ordinary_junction_semantic`型允许source/target物理Node不同，但必须同属一个正确分类ordinary JunctionUnit、mainnode一致、方向相容，并具有完整Junction lineage。
- 无JunctionUnit分类与Node lineage、仅由mainnode字符串机械生成的RoadNextRoad为0。
- actual shared Node型RoadNextRoad共享Node真实性100%；ordinary语义型RoadNextRoad同JunctionUnit/mainnode一致率100%。
- 普通路口应表达的默认物理连接无缺失。
- ordinary空间分离portal整体折叠到单一中值Node的数量为0。
- ordinary中心聚合Node和星形JunctionUnit内部Road数量均为0；未支撑portal在单Segment回退后遗留数量为0。
- 声明与T07/T03/T04 accepted Junction交接的built Road端点严格入面率100%；边界/面外buffer通过数量0。
- 同组存在T07人工面时端点选面采用T07的比例100%，同时不得改写T04 complex拓扑来源。
- THROUGH旁侧邻近但未穿入路口面的虚假切分数量0。
- 闭域目标必要方向主干链端到端连续率100%，链内Road共享实际Node且无断裂、分叉或重复平行主干。
- Road细分点具有LaneGroup/Patch Road、物理Node、`junc_nodes`、Movement或证据边界中的至少一种可追溯原因。
- T04 complex内部连接与其物理范围和证据一致。
- SWSD逐Segment Access方向合同保持率100%；逐Junction Movement合同保持率100%，ordinary全部方向兼容组合无缺失。
- complex SWSD显式fallback关系100%同时满足原始shared Node、两侧member lineage匹配和portal位于accepted surface；裸mainnode推断数量为0。
- 环岛保持整体Junction。
- `junction_geometry_unresolved`正式发布数量0。
- 真实junc_nodes静默丢失数量0。

## 5. LaneTopo hard gate

- 可用LaneTopo去向可追溯率100%。
- confirmed LaneTopo静默丢失0。
- LaneTopo缺失不作为禁止/不存在负证据。
- same-owner反向、跨owner反向和局部connector均进入分类。
- confirmed证据证明主carrier物理不可达时，新carrier不能接管。
- 被拒跨SegmentMovement显式excluded，不能扩大为两个Segment的自动回退。
- 被拒同Segment内部关系若破坏carrier连续性，只回退该Segment和相关Movement。
- 多Road LaneTopo链的每一跳必须是正式有向RoadNextRoad；跨lineage时全部中间Road必须是保留`semantic_carrier`，任意非受限图可达不得判定mapped。

## 6. ID、跨Patch与确定性

- 同一Segment跨Patch只发布一套carrier。
- Patch读取顺序变化不改变Road/Node ID和拓扑。
- 相同输入、参数、代码版本两次运行的归一化Road/Node/RoadNextRoad一致。
- 生成ID可由稳定seed和正式数据规格复算。
- Patch ownership沿用现有Road记录方式并在lineage中可见。

## 7. CRS与schema

- 输入CRS可识别并记录。
- 所有空间运算在显式米制分析CRS完成。
- 正式输出CRS符合RCSD数据规格或明确的POC合同。
- 正式Road/Node/RoadNextRoad schema回读一致；字段截断、类型漂移和空必填字段为0。

## 8. soft Review

允许带Review发布：

- 一方向依赖Surface/Boundary推导；
- constrained completion跨度/接缝风险；
- 中心走廊置信较低但hard gate成立；
- T07/T03差异；
- 完整RCSD/Patch可解释差异；
- 输入质量异常已隔离；
- 局部Movement证据不足但主carrier成立。

Review必须有逐对象图层和reason，不得只给聚合数量。

## 9. 独立QA

独立QA必须是发布后只读流程，至少复算：

- schema/CRS；
- Segment覆盖和四态；
- geometry source与无SWSD splice；
- Road有效性、道路面和平滑指标；
- Node/mainnode/RoadNextRoad；
- built Road端点相对选定原始Junction surface的严格包含关系及选面优先级；
- SWSD Access方向和Junction Movement完整拓扑合同；
- access-surface短桥接的两个端点保护区必须互不接触，观测/推导Road分别到达不同保护区；相交保护区恢复数量必须为0；
- junc_nodes/LaneTopo；
- 跨Patch、ID稳定和重复运行；
- 输入/参数/output hash与性能；
- 旧P04版本保护。

生成callable最多写`technical_passed`。independent QA缺失、不可读或`gate_pass=false`，或QGIS道路面覆盖、真实PyQGIS回读、确定性、人工审计任一缺失时，finalizer不得晋级`passed`。

## 10. QGIS与人工验收

- 工程使用相对路径。
- PyQGIS构建和独立回读通过。
- 项目CRS与全部空间图层CRS均显式有效；不得只依赖provider隐式CRS而让项目CRS为空。
- 正式三图层和核心比较层默认可见。
- hard violation层默认可见或一键定位；soft Review独立分组。
- 对普通十字/T型、T04复杂、环岛、主辅路、四态、跨Patch和已有局部结构形成分层人工结论。
- 人工结论区分已改善、保留、soft Review、范围外和未解决问题。

## 11. 性能与治理

- 记录阶段耗时、吞吐和峰值内存（可获得时）。
- 对比历史可重复运行时间，不允许无解释数量级劣化。
- 所有新增/修改源码和脚本写入前检查字节数，最终均<100KB。
- 不新增CLI/root script，不改变入口registry。
- 不修改T01–T12或旧P04 callable。

## 12. 完成定义

启用闭域目标合同的Case还必须同时满足：

- 目标集合由输入确定性计算，硬编码Segment ID数量为0；
- 原始`BaselineCohort`对象及其分类、实现状态100%保留并逐对象发布；
- `DirectBuildEligibility`默认`direct_build_required`；只有外部确认且带证据、审批和manifest hash的`patch_data_insufficient/reality_change`可退出硬分母；
- `direct_build_required`核心Segment必要主干高精覆盖率100%；
- `direct_build_required`正式`ADVANCE_RIGHT Segment`高精覆盖率100%；
- `direct_build_required`必要角色`swsd_retained/conflict_retained`数量为0；
- 报告同时披露Baseline实现率、DirectBuild实现率和完整发布率，不得只展示缩小后的硬分母；
- 混合关联未提供Patch的开放边界对象不计入硬分母，并逐对象审计；
- 全范围Segment完整发布、原有CRS/拓扑/几何/审计/性能门禁继续全部通过。

只有完整真实测试范围、全部hard gate、soft Review清单、independent QA、QGIS回读、人工审计、确定性、旧版本保护、CRS/审计/性能和逐成功标准证据矩阵均完成，才能宣布本阶段目标完成。

## 13. Case 1885118当前审计候选（V75）

`p04_segment_first_junction_interior_v75_1885118_20260725T050000`是本轮最多10轮迭代后的当前综合最佳候选。它不代表阶段完成，但必须作为后续目视审计与回归比较基线：

- 330/330 Segment、831/831 Access、371/371 Junction Movement；
- Road/Node/RoadNextRoad为887/1146/2328，built/retained为470/417；
- T07人工accepted surface优先于同组T03/T04端点面；T04 complex拓扑范围不被覆盖；
- built Road全部适用端点均被选定原始accepted surface严格包含，面外buffer验收数量0；
- LaneTopo unresolved 0、几何hard failure 0、独立QA 0 violation；
- QGIS工程53层、EPSG:32650、invalid layer 0；470条built Road在正式道路域内覆盖99.463819%；
- DirectBuild为86/96，仍有10条硬目标未完成，故`terminal_status=failed`且不得finalize。
