# Research: P04 Segment-first Road 直出

## 1. Brownfield 现状

### 1.1 已有能力

P04 当前已有 Phase 0、M1/M2、冻结 Directional Road V2、High-Precision Road V3：

- Patch Vector profiler、Lane/Boundary质量与 owner候选；
- Road级支持区间与四态；
- 稳定中心 Lane/Boundary、方向走廊、observed/constrained/fallback分段；
- Portal/Arm、跨 owner LaneTopo Movement；
- 独立发布后 QA、DriveZone overlay和 QGIS对比。

这些能力可作为实现组件和对照，但当前 V3的业务主键仍是 `parent_swsd_unit_id`，不具备 SegmentUnit/JunctionUnit统一本体。

### 1.2 不能续改 V3 的原因

- V3按 SWSD Road逐对象决策 split/shared/fallback，不以 T01 Segment为发布和回退原子。
- T01 Segment仅进入只读 skeleton；`junc_nodes` 不参与最终 carrier hard gate。
- T03/T04/T07和完整 RCSD当前只作 comparison，不能提供 JunctionUnit。
- V3允许同一 Road出现 `swsd_fallback` geometry source；新目标禁止 SWSD坐标拼入高精 Road。
- 当前 Movement只完整覆盖既有选定关系，不能证明同 owner反向 LaneTopo、调头口和短 carrier召回。
- 当前输出的 Junction/Arm/Portal是 POC内部 RoadGraph，不是 RCSD数据规格的正式 Road/Node/RoadNextRoad三图层。

结论：新里程碑必须建立独立 SpecKit和版本化 callable；旧结果保持历史事实。

## 2. 正式上游事实映射

| 来源 | P04消费事实 | P04不承担 |
|---|---|---|
| T01 `segment.gpkg` | `id/sgrade/pair_nodes/junc_nodes/roads`；Segment集合与主辅路归属 | 不重算 Segment，不纠正当前功能结构 |
| T01 `nodes.gpkg/roads.gpkg` | SWSD lineage、方向、原 carrier、Node/mainnode | 不把 SWSD几何作为新 Road局部顶点 |
| T07 | `t07_rcsdintersection_anchor_surface.gpkg` accepted surface、relation evidence、mainnode语义组 | 不重跑 T07 Step1-3，不把 review surface冒充 accepted |
| T03 | `virtual_intersection_polygons.gpkg` 中 `step7_state=accepted` 的普通虚拟路口面 | 不由 relation成功反推 surface是否 accepted |
| T04 | `divmerge_virtual_anchor_surface.gpkg` 中 `final_state=accepted` 的复杂分歧/合流面与正式审计 | 不重算 Reference Point或修改 accepted/rejected |
| T08/T01 | 环岛整体 Junction定义、prepared Road/Node | 不把环岛内部 circulation改成 Segment |
| 完整 RCSD | SWSD语义锚定辅助、Junction fallback候选、全图连续性弱证据 | 不作为最终高精真值，不直接覆盖 Patch强证据 |
| Patch Road | 与 Lane/LaneTopo等同版本的 Road carrier强证据、已有局部结构 | 不继承其 LaneGroup分组为业务 Segment真值 |
| Patch Lane/LaneTopo/Boundary/RoadSurface | 高精几何、方向、物理可达和约束补齐主证据 | 缺失不作为道路不存在或禁止通行证据 |

## 3. 决策记录

### D1：Segment-first，而不是 Road-first

T01 Segment是唯一顶层构图 owner。SWSD Road和Patch Road只能作为 Segment内 carrier lineage或证据。

### D2：四态属于 Segment carrier集合

新状态为 `hp_full/hp_partial/swsd_retained/conflict_retained`。Road自身另有 `built/retained` 与 geometry source，不复用旧 Road级四态含义。

### D3：完整 Road原子

一条新建 Road只允许 observed/constrained；一条保留 Road整条保留。禁止在同一 Road中拼接原 SWSD坐标。

### D4：SWSD只提供低权重语义约束

SWSD可约束 Segment走向、方向、Junction归属和完整性；不得作为新 Road纵向 reference或局部顶点来源。

### D5：方向 Road发布规则

- 高精支持两个可区分的方向走廊：两条单方向 Road；
- 一个方向观测、另一方向可由面/Boundary推导：允许两条，推导方向软 Review；
- 上下行不可区分：一条双向 Road；
- 非高速主辅路按 T01允许同一 Segment拥有超过两条 Road；
- 禁止单向新 Road与覆盖双向的 retained Road同时发布。

### D6：Junction surface优先级

- 普通路口：T07 accepted最高；T07缺失时 T03 accepted；冲突采用 T07并审计；
- 复杂短距离连续分歧/合流：T04 accepted；
- 环岛：T08/T01整体 Junction；
- accepted缺失：完整 RCSD候选经 Patch验证，仍失败则 SWSD保留。

### D7：T07 accepted 的判定不得宽化

只消费 T07正式 accepted/可消费 surface。`review_required`、fail1多面候选或 relation成功但无 accepted surface不得自动提升为 JunctionUnit高精边界。

### D8：mainnode与物理 Node分层

同JunctionUnit Node共享mainnode并保持分布式物理位置。原始SWSD与一张图RCSD审计表明，绝大多数多Node语义路口没有中心Node或内部星形Road；因此普通路口保留各Segment Road高精portal，不再补造JunctionUnit内部Road。RoadNextRoad分层编译：Segment内部与复杂路口使用实际共享nodeid/显式物理关系；ordinary使用同一正确分类JunctionUnit内方向兼容的进入—离开Road组合，并记录source/target物理Node和Junction lineage。不能仅由mainnode字符串脱离Junction分类机械笛卡尔连接。

### D9：单 Segment回退

任何 carrier或逐Road交接 hard failure只使该 Segment保留 SWSD及取消相关新 Movement，不回退其它 Segment；如果整个 Junction surface不可用，则每个相邻 Segment分别判断能否与保留 Junction carrier交接。ordinary某portal缺少surface/DriveZone支撑时只回退该portal owner Segment。

### D10：LaneTopo三去向

每条可用 LaneTopo必须映射、软 Review或显式排除。ordinary跨Segment关系可经JunctionUnit内部carrier路径映射；被拒关系作为Movement级excluded，不回退两侧Segment。同Segment内部关系被拒且破坏carrier连续性时只回退该Segment。缺失不作负证据；T09合法性不在本轮。

### D11：局部结构按需消费

Patch已有调头口/短连接且证据支持时同步构建；Patch缺失不主动恢复。它们默认是 Segment内部 Road/Node/PhysicalMovement，不是新 Segment。

### D12：提前右转与现实变化

T01已有提前右转则作为 `ADVANCE_RIGHT Segment`。T01没有时，当前只输出 RealityChangeClue；生成简易 Road后才允许临时 Segment，随后二次标准化。

### D13：跨 Patch统一构建

先按 T01 Segment聚合 Patch证据，Patch membership仅作 lineage/ownership，不能成为几何切分边界。

### D14：正式成果与审计分层

正式 P04 RCSD候选图层为 Road/Node/RoadNextRoad；Segment、JunctionUnit、关系、Movement和Review按需审计。

### D15：ID稳定而不抢占数据规格

新 Road不继承 SWSD Road ID。Node/RCSD身份能继承则继承；新 ID按现有 RCSD数据规格构造。具体数值编码在实现前通过输入规格/样本核对，不从局部样本反推字段语义。

### D16：独立 QA决定终态

生成器完成不等于 passed。独立 QA必须只读发布 GPKG复算硬门禁，QGIS只承担可视审计，不能替代机器 gate。

### D17：保持旧版本与入口不变

新能力仅增加模块内 callable；不改旧 callable，不新增 CLI/root script，不修改入口 registry。

## 4. 被否决方案

| 方案 | 否决原因 |
|---|---|
| 在 V3上增加 Segment字段 | 决策和fallback仍按 parent SWSD Road，无法得到 Segment原子性 |
| 继续使用 SWSD reference横移 | 结果仍偏 SWSD，无法证明 Vector-native几何 |
| Road内 observed + raw SWSD splice | 容易产生接缝折角、扭曲和伪连续 |
| 脱离Junction分类、仅按mainnode字符串全连接RoadNextRoad | 会把聚合异常或复杂物理结构伪造成可达；ordinary语义连接必须同时满足JunctionUnit类型和Node lineage |
| T03/T04/T07重新做一套搜索 | 重复上游业务逻辑并重现固定距离误差 |
| 资料缺失时自动补高精 Road | 把语义存在伪装为高精支持 |
| 所有问题均用 Review发布 | 会绕过无 Road、错误 mainnode、拓扑不成立等 hard gate |

## 5. 实现前仍需核对的技术事实

这些不是业务未决项，不阻断 SpecKit，但必须在对应任务中以数据/契约证据收口：

1. 1885118当前 T01/T07/T03/T04/T08 run root及实际图层字段。
2. 完整 RCSD Road/Node/RoadNextRoad数据规格中的 ID、`source`和值域。
3. Patch Road与 Lane/LaneTopo的稳定主键、方向字段和已有局部结构关联。
4. T07 surface accepted与 review候选在实际 GPKG中的可判别字段。
5. 新 Road几何的中心走廊派生和 constrained completion数值阈值；阈值必须来自真实数据分析，不固化单样本猜测。
6. 当前测试范围的 CRS链及最终发布 CRS；空间计算统一米制并记录转换。

## 6. 研究结论

业务本体、输入角色、发布状态、Junction优先级、正式输出和验收目标已经稳定，可进入 `plan / data-model / contracts / tasks / analyze`。实现必须先通过旧版本保护、source-of-truth同步和输入契约 preflight。
