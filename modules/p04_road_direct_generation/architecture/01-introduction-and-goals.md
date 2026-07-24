# P04 架构：引言与目标

## 1. 背景

既有RCSD生产由细碎Patch Road/LaneGroup预处理和接边形成，容易继承Road断裂、LaneGroup误分、接边错误及SWSD偏移。P04不再从旧RCSD Road结构反推目标图，而是使用T01已经定义的Junction—Segment业务骨架，在每个Segment内部用Patch原生高精证据重新实例化Road/Node carrier。

点云/轨迹到Patch Vector的感知链已是正式上游，本模块不重新训练感知模型。当前使用规则、约束构图和hard gate；学习模型未来最多提供候选评分或异常线索，不直接决定正式RoadGraph。

## 2. 当前目标

```text
T01 Junction—Segment skeleton
  → T07/T03/T04/T08 JunctionUnit
  → full RCSD semantic anchoring
  → Patch evidence aggregation by Segment
  → complete Road carrier realization
  → high-precision portal + JunctionUnit internal carrier
  → Node/mainnode + RoadNextRoad compilation
  → Road/Node/RoadNextRoad POC candidate
  → independent QA + QGIS + human audit
```

目标成果必须：

- 完整覆盖范围内全部T01 Segment；
- 有高精证据处由Patch证据决定几何，不沿用SWSD纵向折线；
- 资料不足时保留完整carrier，不把SD伪装成高精；
- 与LaneTopo物理可达关系一致，且不以缺失作负证据；
- Junction/Segment/Road/Node各层语义清晰；
- 可在QGIS中与SWSD、完整RCSD、Patch证据和历史P04逐对象比较。

## 3. 关键质量目标

1. **业务完整性**：每个发布Segment至少一条独立Road，四态唯一。
2. **高精真实性**：built Road只含observed/constrained completion，SWSD splice为0。
3. **拓扑正确性**：Node引用完整；Segment内部和复杂路口RoadNextRoad来自实际共享Node/显式物理关系，ordinary语义RoadNextRoad来自同一正确分类JunctionUnit的方向兼容进入—离开Road组合。
4. **路口一致性**：Segment Road保持分布式高精portal；ordinary共享mainnodeid但不生成中心聚合点或星形内部Road。
5. **主干连续性**：双向Segment以两条方向主干链验收，链可按LaneGroup等物理边界细分Road，但必须端到端连续。
5. **证据守恒**：junc_nodes、LaneTopo和Patch已有局部Road无静默丢失。
6. **跨Patch一致性**：先聚合Segment证据，Patch边界断裂为0。
7. **可审计性**：输入、参数、CRS、lineage、性能、机器gate和人工结论完整。

## 4. 范围

当前主体是“有SWSD/T01，功能性Junction—Segment结构未变化”。无SWSD构图和已确认现实结构变化保留架构扩展点，但不进入本轮实现。

Patch已有调头/短连接按需消费；缺失局部结构恢复、Restriction/Laneinfo、RoadSplit正式语义留待后续。

## 5. 治理定位

P04保持`Active POC / 成果模块`，不改变relation-first正式主链，不修改T01–T12。正式P04候选层采用RCSD数据规格的Road/Node/RoadNextRoad，但不接入T10或宣称生产F-RCSD。

M1/M2、冻结Directional Road V2、High-Precision Road V3均为历史基线；当前Segment-first设计以`specs/p04-segment-first-road-direct-20260722/`为变更工件。
