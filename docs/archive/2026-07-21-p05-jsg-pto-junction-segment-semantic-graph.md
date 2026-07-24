# P05-JSG-PTO：路口—路段语义图的分级生长与预测优化生成

## 1. 归档状态

- 中文名称：**P05-JSG-PTO：路口—路段语义图的分级生长与预测优化生成**
- 英文名称：**Junction–Segment Semantic Graph Growth + Predict-Then-Optimize**
- 简称：`P05-JSG-PTO`
- 归档日期：2026-07-21
- 方案状态：业务与总体架构已由用户确认
- 执行状态：**`P05-JSG-PTO-P0/P1/P2/P3` 已完成；P3 正式判定 `P3_MODEL_NO_GO`，后续阶段未授权**
- P0 任务书：`specs/p05-jsg-pto-p0-ontology-oracle-compiler-20260721/`
- P1 任务书：`specs/p05-jsg-pto-p1-candidate-oracle-20260722/`
- 当前角色：已确认方案的历史归档；正式实现范围与门禁以上述 SpecKit 和同步后的项目/P05 source-of-truth 为准

本文继续保存已确认的业务本体、总体架构、验证顺序和历史启动边界。正式执行已建立独立 SpecKit、完成实现和双跑验证，并同步项目与 P05 模块 source-of-truth；本文仍不是实现合同，具体范围、证据和门禁结论以 `specs/p05-jsg-pto-p0-ontology-oracle-compiler-20260721/` 为准。

## 2. 方案目标

P05-JSG-PTO 不把 Road/Node 作为模型首先理解和决定的业务对象。系统首先构建符合现实道路认知的 Junction—Segment—Movement 语义世界，再把复杂 Road/Node 拓扑封闭在独立的 JunctionUnit、SegmentUnit 内部，最终编译为 RCSD/F-RCSD 承载成果。

核心路径为：

```text
多源道路素材
    -> EvidenceGraph
    -> Junction/Segment/Movement/Connector 高召回候选
    -> PTO-A 全局语义结构选择
    -> PTO-B Unit 内部 carrier 选择
    -> JSG 到 Road/Node 编译
    -> RCSD/F-RCSD 与语义、拓扑、几何、审计验收
```

方案需要同时解决：

1. 以 Junction、Segment 还原对现实道路世界的业务认知。
2. 继承 T01 的分级构段逻辑，让高等级 Segment 保持稳定，并沿线生长附属路口和其它 Segment。
3. 用候选、软评分和约束优化替代单一神经网络直接生成完整 RoadGraph。
4. 将 Road/Node 复杂性封闭在 Unit 内部，避免全局拓扑规则持续膨胀。
5. 当前使用 SWSD、RCSD 和已有业务成果，未来可接入点云、BEV、感知要素和轨迹而不改变业务本体。

## 3. 已确认的核心业务口径

### 3.1 StandardSegment

- StandardSegment 一定有两个端点位置。
- 两个端点位置通常引用两个 Junction，也允许引用同一个 Junction，用于显式闭环 Segment。
- 同一 Junction ID 的两端只有在闭环证据明确时成立；错误的端点坍缩不得自动解释为闭环。
- Segment 中间可以包含附属路口。
- 附属路口不自动拆分高等级 Segment。
- Segment 内部不构成其它 Segment 关联关系的拓扑节点属于 Segment 内部实现。

T01 当前对象可映射为：

| T01 对象 | JSG 语义 |
|---|---|
| `pair_nodes` | StandardSegment 的两个端点位置 |
| `junc_nodes` | Segment 沿线仍与其它 Segment 发生关联的附属路口 |
| `inner_nodes` | 不形成外部 Segment 关系的 Segment 内部节点 |
| `roads / sgrade` | Segment carrier、方向和分级构建证据 |

### 3.2 Junction—Segment 关系

Junction 与 Segment 的关系至少包含两个独立维度：

```text
structural_role:
- ENDPOINT
- THROUGH

direction_role:
- ENTER
- EXIT
- BOTH
```

- 一个附属路口通常有一个贯穿主体 Segment。
- 其它关联 Segment 以该 Junction 为起点或终点。
- 一个 Junction 自动发布时最多允许一个 `THROUGH` Segment。
- 如果 T01 或后续证据发现多个 Segment 同时贯穿同一 Junction，系统不得自动选择，必须进入人工确认。
- 关系中可以包含用于区分局部方向和两侧的 `access_legs`；它是关系发生位置，不定义新的 Portal 业务实体，也不被解释为固定几何边界。

### 3.3 Junction 截断规则

- 环岛一定截断所有相关 StandardSegment，环岛内部道路结构属于 JunctionUnit。
- 复杂路口不一定截断 Segment。
- 复杂路口本质上是分歧、合流关系的复杂表达；是否截断依据 T01 的走廊连续性和分歧/合流判定。
- 复杂路口内部 carrier 属于 JunctionUnit；如果某个 Segment 语义上贯穿该 Junction，其 Segment 身份仍可保持连续，物理穿越由 JunctionUnit 内部 Movement/carrier 实现。

### 3.4 特殊终端

dead-end、数据边界和未知终点作为特殊终端路口，保证 StandardSegment 保持两个端点位置：

```text
TerminalJunction
- DEAD_END
- DATA_BOUNDARY
- UNKNOWN_END
```

特殊终端承担 Segment 端点职责，不要求其为传统道路交叉口。

### 3.5 提前右转

提前右转分为两类：

1. 辅路提前右转：本质上是 Segment 内部道路，经过 Junction，属于 SegmentUnit 内部 carrier，不形成 SegmentConnector。
2. 普通提前右转：本质上是 Segment 与 Segment 之间不经过 Junction 的有向分流连接，定义为特殊 Segment `SegmentConnector`。

SegmentConnector 的默认合同为：

- 一个源 Segment access；
- 一个目标 Segment access；
- 有向；
- 不经过 Junction；
- 中间不允许第三个 Segment 接入；
- 一旦出现独立分支或路口，升级为正常 Junction—Segment 结构。

### 3.6 PhysicalMovement 与 TrafficRule

JunctionUnit 正式输出 Segment 间的物理通行关系：

```text
PhysicalMovement:
from_segment_access -> to_segment_access
```

物理可达不等于交通规则允许。禁转、限时、车种限制以及有提前右转时的合法通行要求，由 T09/TrafficRule 层独立叠加，不得反向删除物理 Movement。

### 3.7 业务验收层级

主要业务真值和等价验收对象为：

- Junction 身份、类型和层级；
- StandardSegment 的两个端点位置；
- Segment 附属路口及沿线顺序；
- Junction—Segment 的 `ENDPOINT/THROUGH` 关系；
- Segment 方向；
- Junction 内 PhysicalMovement；
- SegmentConnector；
- TerminalJunction 和闭环；
- 对象分级、身份和变更血缘。

Road/Node 是编译和交付载体，不要求与某份人工成果逐对象、逐切分一致，但必须完整承载上述业务语义，并通过 CRS、ID、引用、方向、有向拓扑、几何和审计 hard gate。

## 4. 核心数据对象

### 4.1 JunctionUnit

```text
JunctionUnit
|- junction_id
|- junction_type
|- growth_level
|- segment_relations
|- physical_movements
|- carrier_options
|- evidence_refs
|- confidence
`- state
```

`junction_type` 首版至少覆盖：

- `NORMAL`
- `ROUNDABOUT`
- `COMPLEX_DIVMERGE`
- `TERMINAL_DEAD_END`
- `TERMINAL_DATA_BOUNDARY`
- `TERMINAL_UNKNOWN`

### 4.2 StandardSegmentUnit

```text
StandardSegmentUnit
|- segment_id
|- growth_level
|- road_grade
|- endpoint_positions[2]
|- attached_junctions[]
|- direction_structure
|- carrier_options
|- evidence_refs
|- confidence
`- state
```

`road_grade` 表示道路业务等级，`growth_level` 表示模型构图顺序。两者有关但不得混为同一个字段。

### 4.3 SegmentConnector

```text
SegmentConnector
|- connector_id
|- source_segment_access
|- target_segment_access
|- direction
|- carrier_options
`- evidence_refs
```

### 4.4 PhysicalMovement

```text
PhysicalMovement
|- junction_id
|- from_segment_access
|- to_segment_access
|- physical_reachable
|- carrier_option
`- evidence_refs
```

## 5. 多源 EvidenceGraph

本文中的“原始素材”是相对于 JSG 世界模型而言，不仅指传感器原始数据，也包括已有道路成果。

### 5.1 当前成果级素材

- SWSD Road/Node/Segment；
- RCSD Road/Node/RoadNextRoad/Intersection；
- 现有 F-RCSD；
- T01 Segment 与构段审计；
- T03/T04/T05/T07 surface、relation 和锚定证据；
- T06 carrier、替换和 Road/Node 成果；
- T09 交通规则证据；
- 道路面、导流带及其它已有道路素材。

### 5.2 未来感知级素材

- 点云；
- BEV；
- 车道线、道路边界和感知道路要素；
- 轨迹；
- 其它可定位、可追溯的道路观测证据。

### 5.3 RCSD 的双重角色

RCSD 同时可以是：

- `RCSD_INPUT_EVIDENCE`：构建 JSG 的原始证据和 carrier 候选来源；
- `RCSD_OUTPUT_CARRIER`：JSG 编译后的 Road/Node 承载成果。

两种角色必须使用不同 lineage。输入 RCSD 不是不可修改真值，最终输出也不得反向泄漏到推理候选层。

未来路线不是“用感知素材彻底替换现有先验”，而是多源素材逐步接入和融合，同时保持 Junction—Segment—Movement 本体与输出合同稳定。

## 6. 分级生长

### 6.1 高等级骨架

1. 生成高等级 Junction 候选。
2. 环岛形成强制截断 Junction 候选。
3. 在两个端点 Junction 之间生成连续 Segment 候选。
4. 联合选择高等级 Junction、Segment 和方向。
5. 保留近等价假设，不在候选层唯一决定。

当前可以继承 T01 的 `grade_2/kind_2/sgrade` 和多阶段构段证据，未来可以由多源 EvidenceGraph 产生等价候选。

### 6.2 附属路口与其它 Segment

1. 沿已选择的高等级 Segment 搜索附属 Junction。
2. 验证是否存在唯一贯穿主体。
3. 将其它道路生长为以该 Junction 为端点的 Segment。
4. 在 JunctionUnit 内建立 PhysicalMovement。
5. 不因附属路口自动拆分高等级 Segment。

核心生长动作是：

```text
ATTACH_JUNCTION_TO_SEGMENT
```

而不是默认执行：

```text
SPLIT_HIGH_GRADE_SEGMENT
```

### 6.3 低等级与残余结构

- 在 residual evidence 上继续构建低等级 Segment；
- 识别 TerminalJunction；
- 识别闭环 Segment；
- 识别 SegmentConnector；
- 对证据不足、多个贯穿或无法确定的结构输出 `UNKNOWN/REVIEW`。

## 7. 双层 PTO

### 7.1 PTO-A：全局语义结构选择

PTO-A 选择：

- Junction 候选；
- StandardSegment 候选；
- Junction—Segment relation；
- PhysicalMovement；
- SegmentConnector；
- `UNKNOWN/REVIEW`。

示意变量：

```text
x_j: Junction candidate
x_s: StandardSegment candidate
x_r: JunctionSegmentRelation candidate
x_m: PhysicalMovement candidate
x_c: SegmentConnector candidate
x_u: Review/Unknown decision
```

### 7.2 PTO-B：Unit 内部 carrier 选择

PTO-B 在已选择的语义结构下，分别为每个 Unit 选择内部 Road/Node/几何实现：

- JunctionUnit 内部环岛、复杂分歧合流和 Movement carrier；
- SegmentUnit 内部上下行、单向/双向、内部节点、辅路提前右转和几何；
- SegmentConnector 的有向 carrier；
- Unit 连接处的明确 access 对齐。

全局只交换 Unit 合同，不展开每个 Unit 内部全部 Road/Node，从而把复杂性封闭在独立构图单元内。

## 8. 候选、硬约束和软代价

### 8.1 候选生成

候选生成只负责高召回，不拥有最终决定权：

- Junction 候选来自多源路口、分歧合流、道路面和锚定证据；
- Segment 候选必须有两个端点、连续 corridor、方向、附属 Junction 序列和 carrier 方案；
- Movement 只在同一 JunctionUnit 内生成；
- Connector 只在明确存在绕过 Junction 的 Segment-to-Segment 分流证据时生成；
- 按 Junction 邻域、Segment corridor 或连通分量局部分解，禁止全城任意对象全连接；
- 候选规范化去重并保存全部非 truth 来源。

### 8.2 已确认硬约束

1. StandardSegment 有两个端点位置。
2. 闭环必须有显式闭环候选和证据。
3. Segment 引用的 Junction 必须存在。
4. 环岛截断所有相关 StandardSegment。
5. 复杂路口不按类型自动截断。
6. 自动发布 Junction 最多一个 `THROUGH` Segment。
7. 附属路口的其它关联 Segment 为 `ENDPOINT`。
8. 多贯穿结构进入人工确认。
9. SegmentConnector 为一对一有向连接。
10. Movement 的输入输出 access 必须存在。
11. PhysicalMovement 不受交通规则合法性过滤。
12. 每个自动发布语义对象至少有一个可行 carrier 实现。
13. CRS、ID、引用、状态和 lineage 合法。
14. `silent_fix=false`。

### 8.3 软代价

以下证据进入候选代价或评分，不直接升级为全局硬规则：

- 道路和方向连续性；
- road grade、surface、corridor 和轨迹支持；
- SWSD、RCSD、感知证据一致性；
- 端点、几何、距离和形状证据；
- 候选复杂度、编辑风险和证据缺失；
- 模型、历史策略和人工确认的一致性。

目标函数可以组合学习代价、证据不一致代价、结构复杂度代价、不确定性代价和人工确认代价。人工确认代价不得无限大，避免系统为了降低 Review 比例而强制输出错误结构。

## 9. 评分模型为可选组件

P05-JSG-PTO 不依赖小模型成立。PTO 只消费统一评分合同：

```text
candidate_id
cost
confidence
uncertainty
score_source
```

评分器按阶段可替换：

```text
V0: 明确、可解释的证据代价
V1: 线性模型或 GBDT
V2: 对象条件小模型
V3: 大模型教师蒸馏的小模型
```

已确认的路线为：

- JSG-P0/P1 不训练小模型；
- JSG-P2 先验证明确代价或可解释学习基线；
- 只有正确候选已经存在、约束正确、固定代价仍无法排序时，才在 JSG-P3 启动对象条件小模型或大模型蒸馏；
- 如果失败原因是候选缺失、业务合同错误、编译器错误或证据不足，不得通过训练模型掩盖。

未来点云/BEV 接入可能需要专用感知神经网络提取 EvidenceGraph，但感知模型不直接决定最终 Junction—Segment 拓扑。

大模型只作为条件性增强：离线规则教师、结构化理由和软标签来源、困难样本生成器或疑难 Case 复核助手。自动生产主链不默认逐 Case 调用大模型；如果未来在线使用，其输出也只能作为可审计软证据，不得绕过 PTO 成为最终决定。

## 10. JSG 到 Road/Node 编译

### 10.1 语义展开

将选择后的语义对象展开为局部 carrier realization：

```text
JunctionUnit -> Junction carrier graph
SegmentUnit -> Segment carrier graph
SegmentConnector -> directed carrier graph
```

### 10.2 Unit 对齐

根据 Junction—Segment relation 和 access 关系对齐 Unit，不通过空间最近点 silent snap。

### 10.3 R2 Edit IR

现有 R2 Road/Node edit-set 不删除，而是调整为 JSG 编译器的中间表示：

```text
Road: COPY / UPDATE / SPLIT / CREATE / DROP
Node: COPY / UPDATE / CREATE / DROP
```

JSG 是业务设计图，carrier 是 Unit 内部实现，R2 edit-set 是具体 Road/Node 施工清单，现有 materializer 执行该清单。

因此 R2 edit-set 不再作为主模型直接预测目标，而作为 `JSG -> carrier -> Road/Node` 编译后端和物化合同继续复用。

如果已选择 JSG 无法编译为合法 Road/Node，必须报告 carrier 不可行或进入 Review，编译器不得自行补路、吸附、重连或执行内容修复。

## 11. 当前真值和证据映射

首版 51 Case 可以使用以下材料构建 canonical JSG truth 和编译真值：

| JSG 内容 | 当前来源 |
|---|---|
| Segment 两端 | T01 `pair_nodes` |
| Segment 附属路口 | T01 `junc_nodes` |
| Segment 内部节点 | T01 `inner_nodes` |
| Segment carrier、方向和等级 | T01 `roads/sgrade` |
| Junction 类型 | T01/T03/T04/T07 |
| Junction—RCSD 锚定证据 | T05 |
| Junction 物理 Movement | SWSD/F-RCSD 物理 carrier topology |
| 交通规则 | T09，单独 overlay |
| Road/Node 编译真值 | T06 F-RCSD |
| Connector | T01 特殊 Segment/提前右转逻辑 |
| Terminal/闭环 | T01 dead-end、fallback 和 pair 结构 |

自动转换结果必须经过 JSG Oracle 审计。字段可转换不等于业务真值已经确认；无法解释、冲突或特殊 Case 必须进入异常清单和人工确认。

## 12. 建议里程碑

### 12.1 P05-JSG-PTO-P0：本体、Oracle 与编译证明

- 固化 JSG 对象和关系合同；
- 将 51 Case 转换为 canonical JSG truth；
- 建立 JSG evaluator；
- 建立 `JSG truth -> Road/Node` 编译器；
- 验证业务语义和 Road/Node hard gate。

P0 不训练模型，不接入生产主链，不正式接入点云/BEV，不修改 T01-T09 接口。

### 12.2 P05-JSG-PTO-P1：候选可达与 Oracle PTO

- 从推理时可用输入生成高召回候选；
- truth 不进入候选层；
- PTO-A/PTO-B 使用 Oracle cost 选择；
- 输出候选覆盖、最优性、物化和确定性证书。

### 12.3 P05-JSG-PTO-P2：可解释评分基线

- 冻结一版明确证据代价或 GBDT/线性基线；
- 与现有规则重放、R2/PTO RoadGraph 基线比较；
- 输出逐候选代价贡献、最优/次优差距和 Review 原因。

### 12.4 P05-JSG-PTO-P3：条件性模型增强

只有 P2 证明正确候选已存在、约束正确、评分仍是主要瓶颈时，才允许：

- 对象条件小模型；
- 大模型离线教师；
- 蒸馏；
- grouped OOF 学习验证。

小模型与大模型蒸馏不是主方案必选项。

### 12.5 后续 Shadow 与原始感知素材

- 先在现有 SWSD/T01/RCSD 输入上 shadow；
- 再增加点云、BEV、轨迹 Evidence Adapter；
- 比较有/无现有成果先验；
- 不改变 JSG 本体、PTO 和编译合同。

## 13. 建议 P0/P1 门禁

### P0

- 51 Case 的 Junction、Segment、Relation、PhysicalMovement、Connector、Terminal、闭环可表达率 `100%`；
- truth-derived JSG Oracle 语义重建 `51/51` 完全一致；
- `JSG truth -> Road/Node` 编译 `51/51` 成功；
- Road/Node CRS、ID、引用和有向拓扑 hard failure 为 `0`；
- `content_repair=false`；
- `silent_fix=false`。

### P1

- 推理候选层不得读取 truth；
- Oracle 候选可达率 `100%`；
- PTO-A/PTO-B Oracle solve `51/51` 可行并给出确定性证书；
- `relaxation=false`；
- 编译 hard failure 为 `0`；
- 无法表达或候选缺失直接形成 no-go，不增加 Case 特判掩盖。

P2/P3 的学习门槛在 P0/P1 完成后另行冻结，本归档不提前承诺模型指标。

## 14. 与当前 P05 的关系

| 当前 P05 资产 | P05-JSG-PTO 中的未来角色 |
|---|---|
| M0 数据、lineage、group split、审计 | 继续复用 |
| M1/M2R/R2 实验 | 保留为历史实验和失败基线 |
| R2 ordinal slot-query 模型 | 不继续作为主路线扩量 |
| R2 edit/pointer/materializer | 作为编译中间表示、物化和兼容底座 |
| 当前 PTO-P0 候选、去重、solver、certificate | 作为未来 JSG 候选和求解基础设施参考 |
| 当前 Road/Node PTOCandidate | 不作为 JSG 最高层业务候选 |
| M0 Road/Node evaluator | 继续作为编译 hard gate |
| T01 | 当前 JSG 真值、构段逻辑和分级生长教师 |
| T03/T04/T05/T06/T07/T09 | 当前证据、候选、锚定、编译真值和规则 overlay 来源 |

RoadGraph R2/PTO-P0 的既有结论继续按原 source-of-truth 和证据保留，不因 JSG-P0 启动而重写。当前 JSG-P0 只按新 SpecKit 和同步后的 source-of-truth 执行。

## 15. 已启动 P0 与后续阶段边界

本方案原先确认但暂缓；用户已在 2026-07-21 另行明确授权启动 P0。以下禁令对 P0 已由新任务书替代，对 P1 及之后阶段仍然有效：

- 越过已建立的 `P05-JSG-PTO-P0` SpecKit 范围扩展实现；
- 未经同步擅自修改其它模块 source-of-truth；
- 修改 T01-T09 代码或接口以适配 JSG；
- 训练新的 JSG scorer；
- 提前修改当前 P05 任务的验收结论；
- 把本文登记为当前正式执行入口或生产路线。

P0 已按以下顺序启动：

1. 重新核对当前 P05 最终事实与可复用资产。
2. 新建独立 `P05-JSG-PTO-P0` SpecKit。
3. 在 `specify / plan / tasks` 中覆盖产品、架构、研发、测试、QA 五类视角。
4. 明确授权后同步项目/P05 source-of-truth 和接口合同。
5. 只实施 P0 本体、Oracle、evaluator 和编译证明，不越级训练模型。

P1 已于 2026-07-22 完成无 truth candidate、PTO-A/PTO-B Oracle、物化和确定性证明。P2 已完成 V0/V1 可解释评分与 grouped OOF：候选、PTO 和 compiler 门禁通过，但 JSG ranking gate 失败。P3 也已完成正式 3 seeds × 5 folds：object-conditioned context 显著提升总体排序，但 Connector 与 Review/Unknown 未过门槛，判定 `P3_MODEL_NO_GO`；RoadGraph safety gate 完整通过。后续 carrier evidence/proposal 阶段、online proposal 和生产接入仍未授权。
