# P04/P05 路口—路段—Road/Node 统一业务认知归档

## 1. 归档状态

- 归档日期：2026-07-22
- 归档对象：`P05-网络模型-预研`、`P04-Road直出-预研（已恢复）`
- 确认状态：本文业务口径已经用户逐项确认
- 当前角色：P04、P05 后续讨论共用的业务认知基线
- 治理边界：本文位于 `docs/archive/`，不替代项目级或模块级 source-of-truth，不自动授权修改 T01-T12、启动 SpecKit、继续模型训练或发布正式 RCSD/F-RCSD

本文解决的问题是：P04 与 P05 虽然使用不同素材和技术路线，但它们面对的是同一个路口—路段—Road/Node 道路世界，不能分别建立互不兼容的业务概念。

## 2. 两条路线的共同前提

### 2.1 当前正式工程

当前项目正式链仍是 relation-first：

```text
T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09
```

- T01 从 SWSD Road/Node 构建当前正式 Segment 骨架。
- T07/T03/T04/T05 建立路口物理证据和 SWSD-RCSD 语义路口关系。
- T06 在冻结 Segment 与 relation 下选择、替换和发布 F-RCSD Road/Node carrier。
- T09 在物理 carrier 上恢复 Restriction、Laneinfo 和其它通行规则。
- T11、T12 只承担审计，不改变业务 carrier。

### 2.2 P04

P04 采用更原始的 `<PatchID>/Vector` 素材，在当前 SWSD/T01 业务骨架下重新组织路口内、路段内以及路口—路段之间的 Road/Node。当前运行期以策略、候选约束和拓扑 hard gate 为主，不依赖神经模型直接决定最终发布。

### 2.3 P05

P05 采用方案 A：保持当前工程已经定义的 Junction/Segment 业务结构和发布合同，用神经模型替换现有策略中的软判断、评分或排序环节。P05 不得自行增加、删除、合并、拆分 T01 Segment，也不得擅自改变 Segment 与 Junction 的已确认关系。

如果模型发现推理证据与先验结构不一致，只能形成现实变更线索并使当前对象进入失败/fallback；它不能在当前 P05 范围内直接改写先验结构。

## 3. 统一业务分层

```text
证据层
  SWSD/T01、T07/T03/T04/T05、RCSD_INPUT_EVIDENCE、Patch Vector、Restriction/Laneinfo
      |
      v
业务语义层
  Junction、Segment、JunctionSegmentRelation、SegmentAccess、PhysicalMovement
      |
      v
物理实现层
  SegmentUnit、JunctionUnit、Portal、CarrierRealization
      |
      v
交付承载层
  Road、Node、mainnodeid、Movement carrier
      |
      v
规则与审计层
  T09 TrafficRule；T11/T12 audit
```

对象存在性、carrier 是否完整、证据是否充分、是否需要 Review 必须分别表达，不能复用一个状态混装多种含义。

## 4. Junction

### 4.1 业务身份

`Junction` 是发生 Segment 关联和通行转换的业务路口身份，不等于以下任一单独载体：

- 某个 SWSD Node；
- 某个 RCSD Node；
- 某个 `mainnodeid` 字段值；
- 某个 `RCSDIntersection`；
- 某个 T03/T04 surface；
- 某个最终 Node。

上述对象分别提供身份、物理范围、映射或 carrier 证据。

### 4.2 JunctionUnit

`JunctionUnit` 是 Junction 在物理 Road/Node 图中的实现边界，负责：

- 路口内部 Road/Node；
- 同一 Junction 内 Segment access 之间的 PhysicalMovement carrier；
- 路口 Node 的物理分组；
- 与各 Segment Road 的逻辑交接。

当前阶段不判断由于替换或重新生成导致的路口内部 Road 端点几何是否最优。当前只要求属于同一业务路口的相关端点被归入同一路口组，并具有相同的 `mainnodeid`。路口内部端点标准化留给后续独立模块或模型升级。

## 5. Segment

### 5.1 正式定义

`Segment` 是道路业务连续单元。正式发布的 Segment 必须满足：

1. 具有明确业务身份和方向结构；
2. 具有可解释的端点或 access 关系；
3. 至少拥有一条独立 Road carrier；
4. Road/Node 引用、方向和拓扑可发布；
5. 关联的真实 `junc_nodes` 得到保留。

一个 Segment 可以拥有一条双向共享 Road，也可以拥有多条方向 Road，但不能在没有独立 Road 的情况下作为有效 Segment 发布。

### 5.2 不允许发布无 Road Segment

当前业务范畴理论上不应出现“有 Segment、无 Road”的正式对象。

P04 后续如果从更原始素材中发现先验未包含的现实变化，应按以下流程处理：

```text
现实变更线索
  -> 生成至少一条简易但可发布的 Road
  -> 形成临时可发布的 Segment 表达
  -> 二次标准化 Segment 生成
  -> 重新发布标准 Road/Node
```

在简易 Road 生成成功之前，该对象只能称为现实变更线索或构建假设，不能作为正式 Segment 发布。`CarrierRealization=NOT_MATERIALIZED` 不属于合法发布终态。

### 5.3 Segment 与 Road 所有权

- 一个 Segment 对应一条或多条 Road。
- 一条 Segment 主体 Road 最多拥有一个 Segment owner。
- JunctionUnit 内部 Road、跨 Segment connectivity Road 不应同时归属多个 Segment；它们属于 JunctionUnit 或显式 connectivity context。
- Road 不得仅因几何邻近被吸附到 Segment。

## 6. 普通 Segment、提右 Segment 与 Junction

### 6.1 普通 Segment

普通 Segment 通常以两个 Junction 端点位置定义。沿线可以存在附属 Junction：

- `pair_nodes`：Segment 两端；
- `junc_nodes`：Segment 沿线真实的小路接入或其它 Segment 关联 Junction；
- `inner_nodes`：不形成外部 Segment 关系的内部节点。

附属 Junction 不自动拆分主体 Segment，可通过 `JunctionSegmentRelation.structural_role=THROUGH` 表达主体 Segment 贯穿。

### 6.2 普通提右 Segment

不经过现有定义的主路口、直接关联两个 Segment 的普通提右，是完整的特殊 Segment：

```text
AdvanceRightSegment
|- segment_type = ADVANCE_RIGHT
|- source_segment_access
|- target_segment_access
|- road_ids[1..n]
|- junc_nodes[]
|- direction_structure
`- evidence/lineage
```

业务规则：

- 它不是独立的 `SegmentConnector` 对象，而是 `segment_type=ADVANCE_RIGHT` 的 Segment。
- 它必须至少拥有一条独立 Road。
- 它绕过现有定义的主路口，直接连接源 Segment 与目标 Segment 的 access。
- 它自身沿线仍可存在 `junc_nodes`，例如小路进入提右路段。
- 沿线 `junc_nodes` 必须按真实 Junction—Segment 关系处理，不得因其是提右 Segment 而忽略。

进入现有定义路口范围的提右不按上述绕行 Segment 处理，而纳入该 Junction 关联的 Segment 结构和 JunctionUnit 内部通行关系。

## 7. JunctionSegmentRelation 与 junc_nodes

Junction 与 Segment 的关系至少包含：

```text
structural_role:
- ENDPOINT
- THROUGH

direction_role:
- ENTER
- EXIT
- BOTH
```

`junc_nodes` 表达真实小路接入或其它 Segment 关联时，采用以下正式业务规则：

1. 必须具有可消费 relation；
2. 必须在最终 Road/Node 拓扑中保留该关联；
3. 不能仅因 RCSD corridor 没有覆盖该节点，就自动降为 optional 或脱挂；
4. 只有被显式认定为 `detached/exempt`，且有证据证明它不再是业务连接时，才允许脱挂；
5. 脱挂决定必须有原因、证据和 lineage，不能 silent fix。

因此，`junc_nodes` 的默认口径是 relation 与最终拓扑全程 hard required；`detached/exempt` 是显式、可审计例外。

## 8. SegmentAccess、Portal 与路口交接

`SegmentAccess` 是业务上的 Segment 进出位置；`Portal` 是它在 Road/Node 图中的逻辑交接点。

当前阶段：

- Segment 的独立 Road负责到达所属 Junction 组；
- JunctionUnit 负责同组 `mainnodeid` 下的路口内部 Road/Node 和 Movement carrier；
- 不新增 `SegmentApproachAdapter` 作为独立业务对象；
- Segment Road 的端部延伸、调整或保留属于 Segment Road自身的 carrier 实现与审计；
- 当前不评价路口内部生成/替换 Road端点的几何合理性，只保证同一路口组与相同 `mainnodeid`。

如果一个 Junction 关联四个 Segment，其中三个可完成交接、一个不能：

- 只阻断失败 Segment 及其相关 Movement；
- 其它三个 Segment 可以继续发布；
- 不因一个 Segment 失败自动回退整个 Junction；
- 不允许为失败 Segment伪造连通。

## 9. PhysicalMovement、carrier 与 TrafficRule

三层必须独立：

1. `PhysicalMovement`：两个 Segment access 在物理上是否可达；
2. `MovementCarrierRealization`：使用哪些 Road/Node 实现该物理可达；
3. T09 `TrafficRule`：该通行是否被禁止、限时、限车型或受其它现场规则约束。

物理可达不等于交通规则允许；TrafficRule 不得反向删除 PhysicalMovement 的物理事实。

## 10. P04 决策边界

P04 当前共享 T01/SWSD Junction—Segment 先验，使用 Patch Vector 生成或保留 Road/Node carrier。

### 10.1 当前失败与 fallback

- 单个 Segment 生成失败时，该 Segment 保持 SWSD 现状。
- 与失败 Segment 直接相关的新 Movement 不发布。
- 其它可成功生成的 Segment 和 Movement 可继续发布。
- 不允许无 Road Segment发布，不允许几何近邻 silent snap。

### 10.2 后续现实变更

P04 后续可以发现先验之外的现实道路变化，但必须先作为现实变更线索输出。只有生成简易可发布 Road 后，才能形成临时 Segment，并在二次标准化后重新发布。

## 11. P05 方案 A 决策边界

P05 保持业务本体、T01 Segment 集合、Junction关系、Road/Node输出合同和硬约束不变。神经模型可以用于：

- 候选评分和排序；
- carrier 方案选择；
- 异常与证据冲突识别；
- Review/失败概率估计。

神经模型不得在当前范围内：

- 新增、删除、拆分或合并 Segment；
- 改变 Segment 的 Junction 归属；
- 以没有独立 Road 的 Segment作为有效输出；
- 绕过拓扑、方向、引用、CRS和 lineage hard gate；
- 直接把现实变更线索改写为正式业务结构。

### 11.1 证据与先验冲突

如果证据与先验结构不一致：

- 形成 `RealityChangeClue` 或等价审计线索；
- 当前 P05 判定失败，不在本轮自动改结构；
- 如果冲突对象是 Junction，该 Junction 关联的全部 Segment保持 SWSD 现状；
- 如果冲突对象是单个 Segment，只将该 Segment保持 SWSD 现状；
- 线索交给 P04 后续现实变更能力、人工 Review 或独立正式任务处理。

### 11.2 PTO 收缩

原 P05-JSG-PTO 中允许重新选择 Junction/Segment 结构的 PTO-A 不再作为当前 P05 范围。当前 PTO/约束求解只能在冻结业务结构下选择 carrier、Movement实现、Road/Node编译方案与失败/fallback，不得改写业务骨架。

## 12. T01、T07、T03、T04、T05、T06、T09、T11、T12 映射

| 模块 | 在统一本体中的职责 | 不承担的职责 |
|---|---|---|
| T01 | 从 SWSD 构建当前正式 Segment 骨架，提供 `pair_nodes/junc_nodes/inner_nodes/roads/sgrade` | 不提供高精 Road/Node，不等于全部现实变更真值 |
| T07 | existing surface 锚定证据 | 不处理 Segment |
| T03 | 常规路口 accepted surface 与 relation evidence | surface accepted 不自动等于 relation 成功 |
| T04 | 复杂路口物理面、Reference Point 和 relation evidence | 不得无主证据伪造 Reference Point |
| T05 | 唯一 SWSD-RCSD Junction relation 与 RCSD junctionization | 不创造业务 Junction/Segment |
| T06 | 当前策略方案下的 Segment carrier选择、替换、fallback 和 F-RCSD发布 | 不得自动丢失真实 junc 关联 |
| T09 | PhysicalMovement 上的 Restriction/Laneinfo/TrafficRule恢复 | 不产生 RoadNextRoad，不用规则反删物理可达 |
| T11 | relation修复候选和人工审计 | 候选不是真值，不是替换白名单 |
| T12 | 原始 1V1 F-RCSD carrier等价性审计 | 不修图，不重新定义业务本体 |

## 13. 已知实现与文档差异

### 13.1 T07 Step1 evidence

当前暂时保留 `DriveZone-only`：

- 当前代码 Step1 虽读取 `RCSDIntersection`，但 `has_evd` evidence surface 只由 DriveZone 构造。
- 当前 `SPEC.md`、`INTERFACE_CONTRACT.md` 与测试也以 DriveZone-only 为稳定口径。
- 部分架构文档写为 `DriveZone ∪ RCSDIntersection`，与当前代码/契约不一致。
- 本轮不修改 T07；将“是否改为 `DriveZone ∪ RCSDIntersection`”登记为后续 Review 项。

### 13.2 T06 junc_nodes

当前代码在 relation mapping 阶段会硬拒绝缺失/无效 junc relation，但在后续 RCSD corridor 选择中存在把 junc 记为 `dropped_junc_nodes / isolated_optional_junc_pruned`、同时仍允许 Segment replaceable 的路径。

该行为与本文确认的业务规则不一致。后续若正式修改 T06，必须走独立授权和 SpecKit，统一 `SPEC.md`、architecture、接口、代码、测试与回归证据。本归档不构成该改动授权。

### 13.3 P04/P05 历史对象

- P04 当前文档和 V3 实现仍以 SWSD Road owner 和 Road级支持状态为主，不能视为 SegmentUnit/JunctionUnit统一本体已经落地。
- P05 历史归档和已完成实验中的 `SegmentConnector` 应按本文改为 `ADVANCE_RIGHT Segment`；历史 Connector、Review/Unknown指标不能继续作为有效业务指标。
- 历史 RoadGraph编译、候选基础设施和技术 hard gate证据可以保留，但必须在本文本体下重新解释。

## 14. 两个任务重新开始时的共同约束

P04、P05 恢复讨论时必须先引用本文，并遵守：

1. 不再分别定义 Junction、Segment、AdvanceRightSegment、Road、Node 或 PhysicalMovement。
2. P04 讨论从“冻结先验下如何用 Vector 构建独立 Road carrier，以及未来如何报告/处理现实变更”继续。
3. P05 讨论从方案 A 继续：冻结 T01 Junction—Segment 结构，只研究模型评分、carrier选择、异常线索和失败/fallback。
4. 未经新授权，不修改 T01-T12、不启动新的模型训练或生产接入。
5. 发现本文与当前 source-of-truth冲突时，必须显式区分“已确认业务目标”和“当前正式实现”，不能 silent merge。

## 15. 已确认决策摘要

| 主题 | 确认结论 |
|---|---|
| 业务本体 | Junction/Segment独立于具体Road/Node载体，但正式Segment必须有独立Road |
| 无Road Segment | 不允许发布；P04未来现实变更先生成简易Road，再二次标准化 |
| P05范围 | 方案A；不改变T01 Segment集合和Junction关系 |
| P05现实变更 | 只报线索并失败/fallback；Junction冲突则关联Segment全部保留SWSD，Segment冲突则仅该Segment保留SWSD |
| 普通提右 | `ADVANCE_RIGHT Segment`，直接连接两个Segment access，必须有独立Road，可有junc_nodes |
| PhysicalMovement | 与Movement carrier、T09 TrafficRule分层 |
| 单Segment Portal失败 | 只阻断该Segment和相关Movement，其它Segment继续发布 |
| 当前路口端点门禁 | 只保证同一路口组和相同mainnode；几何合理性后续处理 |
| T07 | 暂时保持DriveZone-only，union差异登记Review |
| T06 junc_nodes | 默认relation与最终拓扑hard required；仅显式detached/exempt例外 |
