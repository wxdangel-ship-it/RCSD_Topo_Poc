# P04 模块需求：Segment-first Road 直出 POC

## 1. 模块定位

P04 是 `Active POC / 成果模块`。当前主目标是在 SWSD/T01 Junction—Segment 功能结构未变化的场景下，以 T01 Segment 为构图、实例化、回退和审计原子，使用 Patch 同版本 Road/Lane/LaneTopo/LaneBoundary/RoadSurface 等高精证据，直接生成数据规格兼容的 RCSD候选 `Road / Node / RoadNextRoad`。

P04 与 relation-first 正式主链并行验证，不替代或修改 T01–T12，不接入 T10，不把 POC候选宣称为生产 F-RCSD。T01/T07/T03/T04/T08 等既有模块按正式产物和公开契约只读复用；接口不兼容时只在 P04增加版本化适配层。

当前 Segment-first 变更使用独立 SpecKit `specs/p04-segment-first-road-direct-20260722/`。既有 Phase0、M1/M2、冻结 Directional Road V2、High-Precision Road V3 保持历史结果和回归基线，不再作为当前业务本体。

## 2. 业务目标

- 以 T01 `segment.gpkg` 的 `id/sgrade/pair_nodes/junc_nodes/roads` 建立完整 Segment工作图。
- 复用 T07/T03/T04/T08 的 accepted Junction surface，不重新发明路口搜索或固定距离定位。
- 使用完整 RCSD辅助 SWSD语义锚定，使用 Patch Road/Lane/LaneTopo/Boundary/RoadSurface作为同版本强证据。
- 为每个范围内 Segment发布完整 Road carrier集合和唯一状态：`hp_full / hp_partial / swsd_retained / conflict_retained`。
- 新建 Road只允许 `hp_observed + hp_constrained_completion`；禁止把原 SWSD坐标直接拼入高精 Road。
- 生成分布式Node/mainnode和分层RoadNextRoad：Segment内部连续性及复杂路口由实际共享Node/显式物理关系驱动，正确分类的ordinary Junction由同组方向兼容的进入—离开Road组合表达默认PhysicalMovement，最终与LaneTopo物理可达证据一致。
- 输出可重复运行、可机器复算、可通过QGIS逐对象审计的端到端候选成果。

原始 Lane/LaneTopo/Boundary/RoadSurface常见质量问题属于输入质检，只降低证据可用性，不直接产生 Segment结构冲突。所有回退、排除和Review必须有原因与lineage，不得silent fix。

## 3. 当前范围

### 3.1 当前实施目标

- 当前完整真实测试范围内的 T01 Segment、Junction与跨Patch证据。
- ordinary Junction：T07 accepted优先，缺失时使用T03 accepted；二者冲突采用T07并审计。
- complex Junction：短距离连续分歧/合流按T04 accepted业务结果。
- roundabout：按T08/T01整体作为Junction。
- T03/T04缺失时，锚定成功的完整RCSD Junction carrier可作为候选，经Patch强证据验证；仍失败则保留SWSD Junction表达。
- 普通道路高精上下行可分时优先发布两条连续单方向主干链；每条链可按LaneGroup、物理Node、`junc_nodes`、分流合流和证据边界细分为多条Road。不可分时允许一条双向Road链。
- 一个方向观测、另一个方向可由RoadSurface/Boundary可靠推导时，允许发布两条Road并对推导方向加软Review。
- 非高速主辅路按T01允许同一Segment拥有超过两条Road；主辅路出入口属于Segment内部结构。
- `junc_nodes/THROUGH`保持同一业务Segment，允许JunctionUnit前后多条Segment Road和中间Junction carrier。
- Patch Road已有调头口/短连接且同版本证据支持时同步消费；Patch缺失时不主动补建。
- 正式P04候选图层为Road、Node、RoadNextRoad；其它对象按需作为审计层。

### 3.2 当前非目标

- 无SWSD场景从零构图。
- 已确认现实功能结构变化的全面自动重构。
- Patch缺失调头口、Segment内部短连接和可通车豁口的主动恢复。
- Restriction/Laneinfo、RoadSplit正式语义和完整通行合法性。
- 修改或替代T01/T03/T04/T07/T08内部算法。
- 发布生产正式RCSD/F-RCSD、接入T10或替代T06/T09。
- 新增repo CLI、root script或其它正式执行入口。
- 从局部样本反推未知Vector枚举、RCSD ID或source值域并固化为强规则。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 当前关系 |
|---|---|---|
| 上游 | T08/prepared SWSD | 提供规范Road/Node、环岛等预处理结果和数据规格上下文。 |
| 上游 | T01 | 提供正式Segment集合、`pair_nodes/junc_nodes/roads/sgrade`和主辅路归属。 |
| 上游 | T07 | 提供人工审核优先的普通路口accepted anchor surface和关系证据。 |
| 上游 | T03 | T07缺失时提供普通十字/T型accepted virtual surface。 |
| 上游 | T04 | 提供复杂短距离连续分歧/合流accepted surface和内部物理业务事实。 |
| 输入证据 | 完整RCSD | SWSD语义锚定辅助、Junction fallback候选、全图连续性弱证据。 |
| 输入证据 | Patch Vector | Patch Road/Lane/LaneTopo/Boundary/RoadSurface等同版本强证据。 |
| 历史对照 | P04 M1/M2/V2/V3、T06/T12 | 只读回归和差异审计，不作为当前Segment carrier真值。 |

T06 Step2可替换结果可在显式Case验收配置下作为“闭域内应当具备高精覆盖”的目标先验和完整RCSD锚定辅助；它不改变T01 Segment owner，不提供built Road坐标，也不把旧Step3执行结果当作当前真值。
| 下游 | P04独立QA/QGIS | 复算正式三图层、关系、几何来源、拓扑和人工Review。 |

P04不读取上游review PNG推断正式状态，也不把relation成功等同于surface accepted。

## 5. 输入

| 输入 | 用途 |
|---|---|
| T01 `segment.gpkg` | Segment顶层身份、方向等级、pair/junc nodes和SWSD Road lineage。 |
| SWSD Road/Node | 原carrier、方向、Node/mainnode、Patch membership和fallback。 |
| T07 accepted surface | 普通路口JunctionUnit最高优先级物理边界。 |
| T03 accepted surface | T07缺失时普通路口JunctionUnit边界。 |
| T04 accepted surface | complex divmerge JunctionUnit边界和物理内部关系。 |
| T08/T01环岛事实 | roundabout整体Junction语义。 |
| 完整RCSD Road/Node/RoadNextRoad | 锚定、Junction fallback和弱连续性参考。 |
| Patch Road | 与Lane等同版本的carrier强证据和已有局部结构。 |
| Lane/LaneNextLane | 方向中心走廊和物理可达主证据。 |
| LaneBoundary | 中心/宽度/方向分离和constrained completion约束。 |
| DriveZone/DriveZone_fix | 合法道路域；默认使用T00修正版，raw保留lineage。 |
| DivStripZone/DivStripZone_fix | 导流带证据；不得单独解释为一般硬隔离或Patch分区。 |
| Curb/Fence等 | 仅在字段语义正式确认后进入对应强规则。 |

所有空间计算使用显式米制分析CRS并记录转换；不得在EPSG:4979、3857或其它CRS之间隐式混算。

## 6. 目标输出

### 6.1 正式P04 RCSD候选层

```text
Road
Node
RoadNextRoad
```

- `source`是Road属性，具体值沿用RCSD数据规格。
- `mainnodeid`是Node属性。
- RoadNextRoad分层编译：实际共享Node用于Segment内部连续性和显式物理连接；正确分类的ordinary JunctionUnit按同组方向兼容进入—离开Road组合编译默认PhysicalMovement，并记录source/target物理Node和Junction lineage。T04复杂路口、环岛和聚合异常不得由mainnode机械全连接。
- 非Junction语义范围内的同Segment主干交接必须落为完全相同的实际Node；保留Road的`mainnodeid`只表达lineage，不能替代物理共享Node或自动产生RoadNextRoad。

### 6.2 审计与关系层

按需发布：

- SegmentBuildUnit、JunctionUnit、SegmentAccess、RoadCarrierPlan；
- Segment-Road、Road-Lane、Junction-Node、source lineage关系；
- geometry source、PhysicalMovement、RealityChangeClue；
- input quality、soft Review、hard violation；
- manifest、summary、report、independent QA、QGIS工程。

## 7. 核心业务步骤

| 步骤 | 业务说明 |
|---|---|
| Step1 Input preflight | 定位正式输入，核对schema/CRS/hash/数据规格和旧版本保护。 |
| Step2 Segment/Junction skeleton | 以T01 Segment为主键，复用T07/T03/T04/T08建立JunctionUnit与Access。 |
| Step3 Evidence assignment | 按Segment统一聚合跨Patch强证据，不继承旧Road owner。 |
| Step4 Carrier planning | 先确定必要方向/主辅/局部完整Road角色，再决定built/retained和四态。 |
| Step5 Road geometry | 用Patch原生中心走廊生成observed和constrained completion；不拼SWSD坐标。 |
| Step6 Junction/Node/topology | Segment Road保持分布式高精portal；ordinary JunctionUnit不生成中心点或星形内部Road，由共享mainnodeid的portal Node组编译方向兼容RoadNextRoad；复杂路口继续按实际共享Node和显式物理关系编译。 |
| Step7 LaneTopo projection | 每条可用LaneTopo映射、软Review或显式排除；同Segment内部冲突阻断该Segment，跨Segment被拒Movement不反向回退两侧Segment。 |
| Step8 Publish/QA/QGIS | 写正式三图层，独立复算hard gate，构建QGIS并完成人工审计。 |

## 8. Segment发布状态

| 状态 | 含义 |
|---|---|
| `hp_full` | 所有必要Road carrier均由高精证据重建。 |
| `hp_partial` | 至少一条完整Road重建，其余完整Road保留；或built Road内部由observed/constrained完整覆盖。 |
| `swsd_retained` | 无可接管的高精carrier，完整保留SWSD表达。 |
| `conflict_retained` | 可信冲突或carrier集合不完整，保留SWSD并发布Review。 |

同时区分：

- `segment_publishable`：最终是否有完整可发布carrier；
- `carrier_takeover_ready`：新/混合carrier是否可接管；
- `replacement_scope=all/subset/none`。

直出失败不等于Segment不发布；当前功能结构未变化时，通过原carrier保持完整发布。

## 9. Junction与Node规则

- T07 accepted可独立作为JunctionUnit的人工审核高精物理边界，Road端点选面高于同组T03/T04；若同组T04定义complex拓扑，仍保留T04的拓扑模式和内部carrier范围，只把Road端点落位几何切换到T07。
- T04负责complex短距离连续分歧/合流，不使用固定距离另行搜索。
- 环岛整体为JunctionUnit。
- 同一JunctionUnit所有Node共享mainnodeid，但可保留多个实际nodeid。
- 正确聚合的普通非复杂平交路口通过“分布式Segment Road portal Node + 统一mainnodeid + 方向兼容进入—离开RoadNextRoad”表达默认物理全连接；不得把空间分离的portal压到单一中值Node，也不得补造中心点或星形内部Road。
- 原始SWSD在当前“功能结构未变化”场景中提供完整拓扑合同而非几何模板：逐Segment校验全部Access的进出方向，逐Junction校验应有Movement，不要求新Road与SWSD Road一一对应。
- ordinary Junction的应有Movement为该正确分类JunctionUnit内方向兼容的全部“进入Road × 离开Road”组合；最终Road可因LaneGroup更细碎，但这些组合不得因Road细分、ID变化或portal分布式表达而丢失。
- T04 complex不执行ordinary全连接。Patch/T04物理证据不足时，只允许把原始SWSD中真实共享Node、两侧member lineage匹配且portal均落入T04 accepted surface的关系作为显式弱fallback Movement；其余关系不得由mainnode推断。
- 每条正式Segment Road都必须完成自身Access交接，不能用同Segment的另一条Road已接边替代。
- built Road凡声明与accepted JunctionUnit交接，其最终Node必须被选定原始路口面严格包含；落在边界、外部`junction_endpoint_buffer`或只有DriveZone支撑均不算完成交接。同一真实物理门户的极近端点可稳定聚类，但不得跨门户或向中心点拉扯。
- `junction_endpoint_buffer`只用于候选检索、Road细分保护和生成时构造面内目标，不是最终端点验收容差。无法沿观测切向或合法RoadSurface平滑进入路口面的Road必须阻断对应Segment/Access，禁止横向吸附或用Review绕过。
- 有accepted polygon的`junc_nodes/THROUGH`只有在Road实际穿入其面内时才允许细分。若上游只提供`swsd_retained`点，且该点可由同一T01 Segment的正式THROUGH access lineage唯一证明，则可在既有Road最近投影处建立语义细分；该例外不得移动Road几何、不得作为accepted surface入面证明，也不得扩展到关系半径内的旁侧邻近Road。
- 某portal无法得到物理支撑时，只阻断并保留其owner Segment；不得扩大为Junction关联Segment组回退，也不得用Review绕过。
- 上下层道路被错误聚合为同一mainnode属于输入异常，不作为合法多子图路口。
- 不发布`junction_geometry_unresolved`。

## 10. Road几何与部分支持

- built Road只允许`hp_observed/hp_constrained_completion`。
- SWSD可以提供语义走向、方向和access弱约束，不提供built Road局部顶点。
- 同一条Road不得混合新坐标与原SWSD坐标。
- Patch Road是可跨Patch聚合的观测span，不直接等同于正式Road身份；必须先按Segment、SWSD member语义和方向组装完整carrier。
- 整个方向或完整carrier无证据时，可以整条保留既有Road。
- 禁止“新单方向Road + 覆盖双向的retained Road”同时发布。
- 对不承担当前DirectBuild完整性硬目标的单方向member，若只有一段连续高精观测满足独立Road门禁，可以在稳定证据边界发布一条built Road和互不重叠的`swsd_retained_partial`补集Road；两条Road必须共享实际交接Node，built Road只含高精观测/受约束补全，retained部分只含原SWSD子串。该表达不得降低既有完整built carrier，也不把部分Road计作DirectBuild完成。
- 部分member接管失败时必须保持进入该步骤前的完整built或完整retained表达；不得因尝试部分接管，把已有高精结果降级为冲突保留。
- 原双向member接管具有方向原子性：两个单方向角色均可完整实例化时才同时接管；否则整条保留，除非另一方向已有Surface/Boundary可审计推导证据。
- 候选仲裁顺序为：完整Segment方向走廊优先，baseline/access恢复次之，单member缺方向的Surface推导最后；后置推导不得替换已经满足方向、端点和Movement门禁的Segment级高精走廊。
- 单member缺方向推导必须同时形成两个必要方向角色；若该Segment已进入endpoint surface救援，则两个方向还必须分别进入两端选定accepted surface内部。补齐线段DriveZone覆盖或几何hard gate不成立时整条保留，不得用Review绕过。
- 对已认证的`target_access_surface_candidate`，若SWSD轴覆盖率不足只是因为参考轴包含较长Junction内部几何，可按两个不同`accepted surface + junction_endpoint_buffer`之间的实际物理桥接长度验收。候选必须已通过证据占用冲突、DriveZone覆盖和最小观测比例门禁；两个端点保护区必须互不接触，观测Road的两个端点必须分别完成到不同保护区，缺失方向原子推导后仍满足同一端点、几何和拓扑hard gate。保护区相交或端点归属不可区分时不得接管。
- constrained completion必须由直接观测边界条件、合法道路域、Boundary/隔离、相邻Road间距和access支撑。
- endpoint直线completion覆盖不足时，优先按观测中心线端部切线求与目标accepted surface的合法交点；切线路径必须满足最大距离、绕行、道路域覆盖和几何hard gate，且不得改写内部观测几何。切线候选不成立时，才可在观测端点、目标surface与既有最大补齐距离限定的局部范围内，沿`DriveZone/RoadSurface + completion buffer ∪ accepted endpoint surface`搜索最短可解释路径。路径必须限制顶点数、绕行比例和总长，中间拐点需向合法域内部留出平滑余量；平滑后仍须满足合法域覆盖。两类搜索都不得使用SWSD坐标、跨远端连通道路绕行或改变候选证据排序。
- Movement切分后，若同一父主干carrier的唯一片段已贯穿该Segment两个端点面，位于该走廊之外的兄弟尾段不得继续作为Segment Road发布；必须记录`segment_main_tail_outside_endpoint_corridor_suppressed`。该规则以accepted surface和正式`junction_endpoint_buffer`判定，不要求尾段一定由某一种endpoint路由触发，也不得改写无关Segment。
- 对简单Segment，若built主方向链已通过实际共享Node连续覆盖两个终端Junction，且某retained语义carrier与built走廊构成高比例冗余、不是受保护的THROUGH/局部Movement载体，则可以抑制该retained Road及其孤立Node。抑制后必须重新通过Segment Access、SWSD功能拓扑、RoadNextRoad和LaneTopo门禁；任一失败即原子回滚，并输出逐Road抑制审计。
- 为平滑可以忽略Lane局部拓宽/变窄，但不能抹除真实弯道、物理分离或分歧合流。
- 对已发布主干Road允许执行端点固定、切向受控的局部正则化，但必须同时通过几何有效、长度变化、最大偏离和弯折改善门禁；正则化不得移动已接受Junction端点、改变Node身份或将真实弯道拉直。
- 双向Segment的高精验收单位是`main_forward/main_reverse`方向主干链。每条链允许多Road，但必须从一个终端JunctionAccess连续到另一个终端JunctionAccess，链内相邻Road共享实际Node且不得分叉、断裂或形成多套平行主干。
- 对T03/T07/T04 accepted Junction，方向主干链的两个终端物理Node必须分别被选定原始accepted surface严格包含；边界点和面外buffer点均失败。仅写入正确`junction_group_id/mainnodeid`不得替代几何到达；超出surface的补齐只有在沿观测切向或局部RoadSurface平滑进入面内、且全程满足合法域门禁时才能发布为`hp_constrained_completion`。
- 端点补齐上限由最小观测覆盖率允许的缺失比例、DriveZone覆盖和几何hard gate共同约束，不得把通用relation搜索半径当作唯一补齐上限；但扩大补齐上限不得反向扩大候选路径选择范围或改变证据链排序。
- Road只可在Segment内部稳定、纵向连续的LaneGroup/Patch Road证据交接处细分；平行重叠、短时横向换Lane和Junction关系范围内的候选不得形成正式Road边界。
- JunctionUnit accepted surface本体及正式`junction_endpoint_buffer`属于Road细分保护区；不得借用通用relation搜索半径扩大保护区。保护区内候选必须保留父Road并发布`junction_relation_scope_protected`审计，不得与SegmentAccess/portal竞争解释。
- 细分发生在高精几何、平滑和路口端点协调完成之后，只对既有Road做精确子串切分并增量插入度2内部Node；禁止为细分再次全局编译Node或移动既有Road/Node/mainnode。
- 细分后的每条Road必须有独立Road—Lane/LaneGroup/Patch lineage，父Road各part的几何并集必须与细分前逐语义carrier完全相同。
- SWSD member Road可按T01 Node/mainnode和Road方向枚举为Segment正反向路径合同；唯一解与歧义解都必须进入审计。唯一解在fallback后证据占用重协调固定点完成后可驱动正式Road角色，歧义解仍只进入审计，不得猜测发布方向。
- Segment hard fallback后，只有该Segment独占且未被任何有效built carrier发布的恢复证据可被释放并重新参与其它Segment候选；仍存在有效carrier重叠冲突的证据继续阻断。规划、fallback和证据释放必须迭代到固定点。

## 11. LaneTopo与局部结构

- 每条可用LaneTopo必须映射到正式Road/Node/RoadNextRoad、进入软Review或显式排除。
- 同版本LaneTopo与Patch RoadNextRoad冲突时，LaneTopo是物理Movement的更强直接证据；Patch RoadNextRoad保留为次级连续性证据并记录差异。
- LaneTopo证明正式Road内部存在跨carrier锚点时，可以切分物理Road并共享Node，但不得因此切分T01业务Segment。
- LaneTopo跨越同一稳定父Road的多个细分part时，必须投影为实际RoadNextRoad有向链并记录`carrier_path_road_ids`；不得因不再是单跳关系而新增Review、回并Road或伪造共享Node。
- LaneTopo在两个高精Road之间经过保留的短`semantic_carrier`时，只允许沿实际有向RoadNextRoad、有限跳数且全部中间Road均为`realization=retained / carrier_role=semantic_carrier`的链映射，并发布完整`carrier_path_road_ids`；不得把任意图可达当作物理关系。
- 普通JunctionUnit内的跨Segment LaneTopo可经Junction内部carrier路径映射；若物理关系证据被拒，必须显式排除该Movement，但不得据此同时回退两个独立Segment。
- ordinary之外的保留局部结构不得由共享`mainnodeid`自动全连接。只有source/target Road或其Lane证据能追溯到同一条原始LaneTopo关系时，才可发布`explicit_lane_topo_retained_semantic`，且不得扩展为同组Road笛卡尔积。
- 正式T01 `ADVANCE_RIGHT Segment`可在其Road/Lane证据与相邻主干Road被同一原始LaneTopo关系命中、且端点属于ordinary或retained Junction lineage时，发布`explicit_lane_topo_advance_right_semantic`；该关系可以跨不同mainnode lineage，但不能反向新增业务Segment或其它功能关系。
- 几何方向相反、同组mainnode或空间邻近均不能自动产生掉头/反向RoadNextRoad；调头必须具有LaneTopo、Patch局部连接Road或后续专门策略的显式物理证据。
- 同一Segment内部LaneTopo关系被拒且破坏其carrier连续性时，只回退该Segment及相关Movement。
- LaneTopo缺失不解释为道路不存在或禁止通行。
- `junc_nodes`默认relation与最终拓扑hard required；只有显式、可审计`detached/exempt`才例外。
- Patch已有调头口/短连接按需同步，缺失恢复由后续独立策略承担。
- T01已有普通提右按`ADVANCE_RIGHT Segment`处理；T01未表达时先输出RealityChangeClue，简易Road materialized后才允许临时Segment并二次标准化。

## 12. 什么是对

- 100%范围内T01 Segment都有四态和至少一条独立Road。
- 同一Segment跨Patch证据统一聚合，Patch边界不成为Road断点。
- 强证据充分且hard gate通过的carrier得到使用，未使用有逐对象原因。
- 新建Road不偏向SWSD参考折线，geometry source可复算。
- Road/Node/RoadNextRoad符合数据规格，Node/mainnode和LaneTopo可解释。
- hard failure阻断新carrier，soft issue可带Review发布。
- 输入、参数、CRS、决策、环境、性能和输出hash可追溯。

## 13. 什么是错

- 继续以SWSD Road或LaneGroup作为顶层owner，再附加Segment字段。
- 在V3上调参并把Road级fallback称为Segment-first。
- 在built Road中直接拼接SWSD坐标。
- 对T04复杂路口、环岛、聚合异常或未分类Junction仅凭mainnodeid生成RoadNextRoad。
- 把正确ordinary Junction的分布式portal补造为中心点和星形JunctionUnit Road。
- 重做T03/T04固定距离路口搜索或覆盖上游accepted/rejected事实。
- 丢失真实junc_nodes、same-owner反向LaneTopo或Patch已有局部Road而不审计。
- 用Review绕过无Road、错误Node/mainnode、拓扑不成立或CRS错误。
- 仅凭代码测试/QGIS构建宣布端到端业务完成。

## 14. 验收口径

- Segment覆盖率100%，每Segment至少一Road，四态唯一。
- built Road SWSD直接坐标splice数量0，geometry source完整覆盖。
- Road几何非空、有效、方向明确，无不可解释断裂或方向重复。
- Road端点Node引用100%存在；实际共享Node型RoadNextRoad真实性100%；ordinary语义型RoadNextRoad的source/target Node同属一个正确分类JunctionUnit且mainnode一致率100%；显式retained/ADVANCE_RIGHT语义关系的原始LaneTopo证据可追溯率100%，无证据反向/U-turn自动关系数量0。
- 同一JunctionUnit mainnode一致率100%，`junction_geometry_unresolved`数量0。
- ordinary Junction的portal有accepted surface或DriveZone支撑，中心聚合Node和星形内部Road数量均为0；未支撑portal经单Segment回退后遗留数量0。
- 原始SWSD逐Segment Access方向合同和逐Junction Movement合同保持率均为100%；ordinary应有组合无缺失，complex显式SWSD fallback逐关系满足共享Node、member lineage和accepted surface三项约束。
- 每条正式Segment Road的SegmentAccess交接实现率100%。
- junc_nodes静默丢失0；可用LaneTopo去向可追溯率100%。
- Patch边界人工断裂0；ID对Patch顺序和重复运行稳定。
- 独立发布后QA全部hard gate通过；soft Review逐对象可见。
- QGIS显式比较SWSD、完整RCSD、Patch证据、历史P04和新结果，并完成分类型人工审计。
- 目标双向Segment的两条方向主干链端到端连续率100%；允许的Road细分均具有LaneGroup/Lane/Patch lineage、链内共享实际度2 Node，且细分前后Segment级有向连通关系与既有Junction portal保持不变。
- 显式闭域目标启用时采用三层合同：`BaselineCohort`由输入确定并永久保留；`DirectBuildEligibility`默认`direct_build_required`，只允许外部确认、逐对象有证据且可哈希的清单标记`patch_data_insufficient/reality_change`；`PublishDisposition`独立表达最终完整发布。只有`direct_build_required`对象的必要主干和正式`ADVANCE_RIGHT Segment`必须100%高精且不得为`swsd_retained/conflict_retained`；退出硬分母的对象仍须完整发布并保留原Baseline审计。报告必须同时披露Baseline、DirectBuild和完整发布三套分母。
- 只有完整真实范围、机器审计、QGIS回读、人工审计和可重复性均通过才可宣布阶段完成。

## 15. 历史实证边界

以下结果保留为历史基线，不自动证明当前Segment-first目标：

- M2：571 Road级四态和混合几何；
- 唯一冻结Directional Road V2：`p04_directional_v2_1885118_20260721T154712`，638 Road；
- High-Precision Road V3：`p04_hp_v3_1885118_20260721T180655`，603 Road、39.817% fallback。

历史结果文档位于`architecture/1885118-*.md`，只用于回归和差异审计。

## 16. 当前治理缺口

- RCSD Road/Node/RoadNextRoad ID与`source`正式规格需在实现preflight中核对。
- Vector未知枚举不进入强规则。
- RoadSplit、Restriction/Laneinfo和缺失局部结构恢复留待后续。
- `docs/repository-metadata/path-conventions.md`尚未建立；当前使用与PowerShell一致的Windows路径。
