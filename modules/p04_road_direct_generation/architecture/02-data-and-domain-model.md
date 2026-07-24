# P04 架构：数据与领域模型

## 1. 分层模型

### 1.1 业务语义层

- **Junction**：业务路口身份，不等于surface、Node或mainnode字段。
- **Segment**：T01定义的路口—路段业务连续单元，是P04顶层构图和回退原子。
- **JunctionSegmentRelation**：`ENDPOINT/THROUGH`与`ENTER/EXIT/BOTH`。
- **SegmentAccess**：Segment进出Junction的业务位置。
- **PhysicalMovement**：物理可达，不等于T09合法通行规则。

### 1.2 物理实现层

- **SegmentBuildUnit**：T01 Segment在P04中的工作对象，保留`pair_nodes/junc_nodes/roads/sgrade`。
- **JunctionUnit**：Junction在Road/Node图中的物理边界和内部carrier。
- **RoadCarrierPlan**：一个Segment完整发布所需的Road集合。
- **RoadBuildCandidate**：一条完整built或retained Road。
- **NodeBuildCandidate**：可继承或稳定生成的Node/mainnode。
- **PhysicalMovementAudit**：LaneTopo到正式图的投影审计。

### 1.3 发布层

- **Road**：RCSD正式候选Road，`source`为属性。
- **Node**：RCSD正式候选Node，`mainnodeid`为属性。
- **RoadNextRoad**：分层编译。Segment内部和复杂路口使用方向正确的实际共享Node/显式物理关系；ordinary Junction使用同一正确分类JunctionUnit内方向兼容的进入—离开Road组合。

## 2. Segment不变量

- T01 Segment集合和Junction关系在当前路径中冻结。
- 每个正式发布Segment至少拥有一条独立Road。
- 一个Segment可拥有一条双向Road链、两条单方向主干链或多条主辅方向链；每条链可由多条细粒度Road组成。
- `junc_nodes/THROUGH`不拆业务Segment；物理上可由前后Segment Road和中间Junction carrier贯通。
- 单Segment失败只回退自身及相关新Movement。

Segment状态：

| 状态 | 业务含义 |
|---|---|
| `hp_full` | 必要carrier全部高精重建。 |
| `hp_partial` | 完整Road级built/retained组合，或built Road由observed/constrained完整覆盖。 |
| `swsd_retained` | 无可接管高精carrier，保留原表达。 |
| `conflict_retained` | 可信冲突或carrier不完整，保留原表达并Review。 |

状态之外同时记录`segment_publishable/carrier_takeover_ready/replacement_scope`，防止把直出失败误写成Segment消失。

### 2.1 闭域目标三层合同

| 层 | 字段/值域 | 不变量 |
|---|---|---|
| `BaselineCohort` | `baseline_target/baseline_target_class` | 只由输入确定性计算；一经形成不得因后续处置缩小。 |
| `DirectBuildEligibility` | `direct_build_required / patch_data_insufficient / reality_change` | 默认必建；例外只能来自外部确认、逐对象有证据且可哈希的清单。 |
| `PublishDisposition` | `hp_published / swsd_retained_data_insufficient / swsd_retained_reality_change_pending / conflict_retained / swsd_retained_partial_evidence` | 独立于硬分母，所有Segment仍须完整发布。 |

`hard_conflict`和`partial_evidence_unresolved`仍属于`direct_build_required`，不能借人工Review退出硬分母。每次运行同时发布Baseline实现、DirectBuild实现和全量发布指标。

## 3. JunctionUnit模型

| 类型 | 正式来源 |
|---|---|
| ordinary | T07 accepted优先；缺失时T03 accepted；RCSD验证；SWSD保留 |
| complex_divmerge | T04 accepted；RCSD验证；SWSD保留 |
| roundabout | T08/T01整体Junction |
| auxiliary | T01 junc relation加适用surface/RCSD/Patch证据 |

规则：

- T07/T03冲突采用T07并审计。
- Road端点物理面与Junction拓扑来源分开记录：同组存在T07人工accepted时端点使用T07；T04仍可保留`complex_divmerge/explicit_physical`拓扑和内部carrier范围。
- review/rejected surface不等于accepted。
- 同一JunctionUnit内所有Node共享mainnodeid，但可保持多个实际nodeid。
- built Road声明Junction交接时，最终Node必须被端点选用的原始surface严格包含；`junction_endpoint_buffer`不是发布容差。
- ordinary默认物理全连接由分布式高精portal Node、统一mainnodeid和方向兼容进入—离开RoadNextRoad实体化；空间分离portal不得压到单一中值Node，不发布中心聚合Node或星形内部Road。
- `JUNCTION_UNIT`内部Road仅用于T04复杂、环岛或有显式原始carrier证据的场景，不是ordinary默认构造物。
- 每条Segment Road必须在其适用Access处与portal Node实际共享；同Segment其它Road的交接不能代替。
- 内部Road必须由accepted surface或DriveZone完全支撑；未支撑portal只触发owner Segment原子回退。
- 上下层道路误聚合同mainnode属于输入异常，不是合法Junction类型。
- 不发布`junction_geometry_unresolved`。

## 4. RoadCarrierPlan模型

先确定必要carrier角色，再生成几何：

```text
T01 direction/main-aux semantics
  + Patch direction/corridor evidence
  + Junction accesses
      → required carrier roles
      → built/retained choice
      → complete topology gate
```

典型角色包括`main_forward/main_reverse/shared_bidirectional/aux_*/through_part/local_connector`。角色是P04审计语义，正式方向值仍沿用RCSD数据规格。

禁止组合：

- 新单向Road与覆盖双向的retained Road并存；
- 必要方向缺失；
- built与retained几何/方向重复；
- 同一条Road内新高精坐标与SWSD坐标拼接。

## 5. 几何来源模型

built Road的唯一来源：

- `hp_observed`：直接由Patch中心走廊证据控制；
- `hp_constrained_completion`：由观测端点/切向、RoadSurface、Boundary、隔离、相邻Road和Access共同约束补齐。

SWSD只提供业务走向、方向、完整性和Access弱约束，不提供built Road局部顶点。

每条正式Road identity仍保持原子：built Road不含SWSD顶点，retained Road不声明高精，也不作为built Road的几何span。无高精接管时使用`swsd_retained_whole`完整保留原Road；不承担DirectBuild完整性硬目标的单方向member可在稳定证据边界生成独立built Road和互不重叠的`swsd_retained_partial`补集Road，二者以实际transition Node交接。这是两个独立Road identity，不是同一Road内raw SWSD拼接。

## 6. Evidence模型

每个原始对象使用`patch_id + object_type + source_id`复合身份。输入quality state为：

- `usable`；
- `review`；
- `insufficient`；
- `excluded`。

quality state只决定证据能否进入强构图，不直接决定Segment结构冲突。

Road-Lane、Segment-Road、Junction-Node和source lineage使用关系表表达，不把多对多列表强塞进Road正式属性。

Road owner分为：

- `SEGMENT`：正式业务Segment的独立Road，必须有`segment_id`；
- `JUNCTION_UNIT`：仅复杂路口、环岛或显式局部carrier使用，必须有`junction_group_id`，`segment_id`为空；ordinary不得为表达默认全连接补造该类Road。

## 7. LaneTopo与RoadNextRoad

每条可用LaneTopo最终必须：

- 映射到Road/Node/RoadNextRoad；或
- 进入明确soft Review；或
- 因输入质量显式排除。

RoadNextRoad有四类可审计证据：

- `actual_shared_node`：source出口与target入口使用同一物理nodeid；
- `ordinary_junction_semantic`：source出口Node与target入口Node不同，但二者属于同一正确分类ordinary JunctionUnit、共享mainnodeid，且方向角色兼容。
- `complex_junction_swsd_explicit`：T04复杂路口资料不足时，原始SWSD shared Node、member lineage和两侧accepted surface portal三证俱全的保守关系；
- `complex_junction_lane_topo_explicit`：usable LaneTopo已接受，且已发布local connector的出口与目标入口属于同一T04组、距离受限、连线位于accepted surface内时，用于补足Segment内部物理carrier的显式关系。

只有JunctionUnit分类和Node lineage同时成立时才能使用第二类；不能仅比较mainnode字段。第三、四类必须保留原始关系证据和source/target物理Node，且不得改变跨Segment功能关系。T04复杂路口、环岛和聚合异常禁止使用ordinary语义全连接。

ordinary跨Segment LaneTopo可沿JunctionUnit内部Road路径映射；若该物理关系被证据拒绝，记录为Movement级显式排除，不反向回退两个Segment。同Segment内部关系被拒且破坏carrier连续性时，只阻断该Segment及相关Movement。

方向主干链是Segment高精验收单位。`main_forward/main_reverse/main_oneway`可分别由多条Road组成，但每条链必须从一个终端JunctionAccess连续到另一个终端JunctionAccess，链内相邻Road共享实际Node且无断裂、分叉或重复平行主干。Road可在LaneGroup/Patch Road证据归属改变处细分，并通过关系层保留逐Road lineage。

PhysicalMovement不包含Restriction/Laneinfo合法性。

## 8. ID与lineage

- 输入ID先canonical化。
- 新Road不继承SWSD Road ID。
- Node或Patch/RCSD身份能继承则继承；否则按正式RCSD ID规范稳定生成。
- 生成seed不得包含Patch读取顺序或并行顺序。
- 具体数值编码必须通过正式数据规格核对，不能由样本反推。

## 9. RealityChangeClue

T01未表达但Patch发现的普通提前右转或新结构先输出RealityChangeClue：

```text
clue_only
  → simple publishable Road
  → temporary Segment
  → second-stage normalization
  → standard Road/Node republish
```

没有简易可发布Road时，不允许发布正式Segment。

## 10. 详细变更模型

字段、关系和状态机详见`specs/p04-segment-first-road-direct-20260722/data-model.md`。
