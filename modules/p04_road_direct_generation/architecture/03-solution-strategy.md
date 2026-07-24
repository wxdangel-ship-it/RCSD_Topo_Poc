# P04 架构：方案策略

## 1. 总体策略

P04采用`Segment-first + Vector-native carrier + deterministic hard gate`：

```text
Input preflight
  → T01 Segment/Junction skeleton
  → upstream accepted JunctionUnit
  → evidence assignment by Segment
  → complete RoadCarrierPlan
  → observed/constrained Road geometry
  → Node/mainnode and RoadNextRoad
  → LaneTopo projection
  → publication / independent QA / QGIS
```

先决定业务结构和完整carrier集合，再生成几何。禁止先从LaneGroup/Patch Road拼Road，最后再贴SWSD/T01标签。

## 2. 输入preflight

- 所有路径、图层和CRS显式参数化。
- 读取T01/T07/T03/T04/T08正式输出，不从review图片或局部文件名猜状态。
- 核对完整RCSD与Patch Vector版本、schema和ID规格。
- 输入hash、数量、CRS、转换和环境写入manifest。
- 未确认字段保持observed-only，不进入强规则。

## 3. Segment skeleton

- 从T01 `segment.gpkg`建立唯一SegmentBuildUnit。
- `roads`只作为SWSD carrier lineage，不是顶层owner。
- `pair_nodes`建立两端Junction关系。
- `junc_nodes`建立THROUGH/辅助Junction关系，禁止optional prune。
- 同一Segment的全部Patch membership统一进入证据范围。

## 4. JunctionUnit策略

### 4.1 普通十字/T型

- T07 accepted surface可独立作为高精物理边界，且高于冲突T03。
- T07缺失时使用T03 accepted。
- 同组T07与T04并存时，T07只决定Road端点落位面，T04继续决定complex拓扑和内部carrier范围。
- Segment Road保持各自高精portal，不把空间分离的端点压到同一中值Node。
- 同一真实物理门户的极近端点可稳定聚类；不同门户保持分布式Node并共享同一mainnodeid。
- 不生成路口中心Node或portal—中心星形Road。默认PhysicalMovement由同一ordinary JunctionUnit内方向兼容的进入—离开Road组合编译，并保留两端物理Node lineage。
- 最终built portal必须进入选定原始surface内部；内缩面用于生成稳定面内目标，原始面`contains(final Node)`用于hard gate。边界、外扩buffer或只有DriveZone支撑均不算入面。
- 存在accepted polygon时，THROUGH只在高精Road实际穿入内缩surface时切分；仅在关系半径内旁侧邻近时拒绝切分，禁止横向吸附制造直角接头。上游只有`swsd_retained`点且同一T01 Segment正式THROUGH access lineage唯一成立时，可在既有Road最近投影处做不改变几何的语义细分；该例外不具备accepted surface入面效力。
- 原始SWSD用于枚举完整的Access方向和应有进入—离开Movement，不用于约束portal坐标或要求输出Road与SWSD Road一一对应；高精Road即使按LaneGroup细分，也必须在归一化方向链上保持这套完整拓扑。

### 4.2 复杂短距离连续分歧/合流

- 以T04 accepted业务逻辑为唯一复杂surface主来源。
- 不使用固定距离搜索，不重新推导Reference Point。
- 内部Road/Node/RoadNextRoad按T04物理范围、Patch LaneTopo和保留关系构建。
- 当Patch/T04内部carrier暂时不足时，只允许把原始SWSD真实shared Node关系中、两侧member lineage匹配且portal都位于accepted surface的关系作为显式Movement fallback；不由mainnode或空间邻近补全其它关系。
- usable LaneTopo已接受但被同Segment局部连接Road承接时，只允许沿“source实际共享Node→已发布local connector→同T04组出口/入口”补充显式关系；出口到目标入口的距离必须受限，直连线至少80%位于T04 accepted surface。该关系不得新增跨Segment功能关系。

### 4.3 环岛

- 按T08/T01整体作为JunctionUnit。
- 各Segment Road到达环岛Access；circulation Road属于JunctionUnit。

### 4.4 附属Junction

- 主业务Segment保持贯穿。
- 物理carrier可拆为JunctionUnit前后多条Segment Road和中间Junction carrier。
- 侧向道路是否独立Segment完全遵循T01。

### 4.5 accepted缺失

```text
verified full RCSD Junction carrier
  → Patch Road/LaneTopo/RoadSurface validation
  → usable candidate

validation fail
  → retain SWSD Junction/mainnode expression
```

不生成unresolved新路口几何。

## 5. Evidence assignment

以Segment、方向和物理走廊为上下文组合证据：

- Patch Road：同版本carrier强证据与已有局部结构；
- Lane：方向中心走廊主证据；
- LaneBoundary：中心、宽度和方向分离约束；
- RoadSurface：合法道路域与不可越界约束；
- DivStrip/Curb/Fence：仅按已确认语义提供隔离/导流证据；
- LaneTopo：纵向、转向、调头、局部连接的物理可达证据。

LaneGroup和Patch Road分组不能直接决定Segment或Road数量；局部Lane增减、导流带形态和无意义先分后合必须由连续走廊约束消化。

Patch Road的输入对象是观测片段而不是正式Road identity。属于同一Segment、同一SWSD member语义和同一方向的跨Patch片段先按纵向顺序聚合为中心走廊；只有完成carrier角色规划后才分配稳定Road ID。

SWSD member Road另按T01 Node/mainnode和Road方向枚举Segment正反向路径。该结果用于核对“一个Segment可由多条方向Road串联”的完整语义，不把SWSD坐标带入built几何。唯一解和歧义解均发布审计；fallback后的证据占用重协调已形成固定点，唯一解可以驱动正式member Road角色，歧义解仍不得猜测或进入发布决策。

## 6. Carrier planning

### 6.1 普通双向道路

- 两个高精方向走廊可区分：两条单方向主干链；
- 一个方向观测、另一个方向可由Surface/Boundary推导：两条方向主干链，推导方向soft Review；
- 不可区分：一条双向Road链。

主干链不是固定一条Road。LaneGroup/Patch Road证据归属、物理Node、`junc_nodes`、分流合流或证据边界发生变化时允许细分Road；细分后链内必须共享实际Node并保留逐Road Lane/Patch lineage。

细分只接受纵向顺序稳定、两侧有效长度满足门槛且不存在第三条lineage跨越的证据交接。全部accepted JunctionUnit surface本体及正式`junction_endpoint_buffer`形成保护区；不得借用通用relation端点搜索半径扩大保护区。落入保护区的交接只记录为`junction_relation_scope_protected`，不得把Segment内部证据边界误作Junction portal或SegmentAccess。

细分在Road高精几何、平滑和路口端点协调完成后执行，使用父Road的精确里程子串，不重新拟合几何。每个accepted边界只增量插入一个稳定度2 Node；既有Road外端Node、Junction portal、mainnode和坐标全部保留，禁止再次对全图Node编译以免二次收敛误聚合物理门户。

### 6.2 多主辅道路

非高速主辅路按T01属于同一Segment时，一个Segment可拥有两条以上Road。主辅出入口属于Segment内部Node/PhysicalMovement；存在独立侧向Segment时保留T01 Junction关系。

### 6.3 部分支持

- 同一built Road内部资料缺口使用constrained completion；
- 整个必要Road无证据时整条retained；
- `hp_partial`描述完整Road级组合，不描述raw SWSD splice；
- 不承担DirectBuild完整性硬目标的单方向member可在稳定证据边界拆成独立built Road和互不重叠的`swsd_retained_partial` Road；两条Road共享实际transition Node，部分表达不满足DirectBuild完整性。
- 部分member候选不得覆盖既有完整built carrier；候选失败时恢复进入该步骤前的Road/Node/状态。
- 原只有一条双向Road且只构建一个方向时，不能发布单向built+双向retained，必须同时构建两个方向或全部保留。
- 双向member的两个方向角色执行原子接管；若另一方向只能由Surface/Boundary推导，则必须保留推导证据和soft Review，否则不得局部接管。
- 完整Segment方向走廊优先于baseline/access恢复；前两者均失败后，才允许单member按“一方向观测 + RoadSurface推导另一方向”恢复。推导不能抢占已经成立的Segment级走廊。
- 单member恢复若处于endpoint surface救援范围，两个方向都必须到达两端accepted surface/正式端点缓冲；补齐段必须满足DriveZone覆盖和几何hard gate，否则整条保留。
- 当SWSD参考轴把Junction内部长度计入Segment、导致短Patch走廊无法达到常规轴覆盖率时，只允许已认证的access-surface候选按两个互不接触的`accepted surface + junction_endpoint_buffer`之间的实际桥接验收。观测方向须以`hp_observed + hp_constrained_completion`分别交接不同保护区，另一方向由RoadSurface约束原子推导；保护区相交或任一端无法区分时不进入接管。
- endpoint直线补齐离开合法域时，先保持既有证据链和端点归属不变，尝试沿观测端部切线到达accepted surface；切线候选不成立时，再在端点—目标surface的局部RoadSurface内做受约束最短路。两类候选都受最大补齐距离、绕行比例、顶点规模、合法域覆盖和平滑后覆盖共同门禁；路径中间拐点向合法域内部留出POC安全余量，避免平滑切角越界。该余量属于当前真实数据标定参数，不提升为生产真值。
- Segment hard fallback后，重新释放该Segment独占且未发布的恢复证据，再对其它Segment规划；仍与有效built carrier冲突的证据继续保留冲突。证据占用、规划和fallback迭代到固定点后，唯一SWSD方向路径才驱动member角色。

### 6.4 冲突和失败

不能形成完整方向/access/Node拓扑的carrier集合不得接管。该Segment保留SWSD并发布原因，其他Segment不回退。

## 7. Road geometry

### 7.1 observed

从稳定中心Lane、共享Boundary、Patch Road中心证据和RoadSurface约束生成直接控制段。中心证据必须具有方向、覆盖和物理走廊一致性，不能机械选择最左Lane。

### 7.2 constrained completion

缺口补齐使用：

- observed两端位置与切向；
- RoadSurface合法域；
- Boundary/隔离；
- 相邻方向或主辅Road间距；
- SegmentAccess/Portal；
- SWSD低权重全局走向。

任何补齐穿越hard barrier、foreign surface或形成不可解释曲率/拓扑时失败，转为完整carrier保留。

端点补齐长度不以通用relation搜索半径作为唯一上限，而由既有最小观测覆盖率允许的缺失比例、DriveZone完整覆盖和几何hard gate共同约束。该放宽只作用于已选中证据链到accepted endpoint surface的补齐；候选路径排序仍使用原正式关系范围，不能因补齐距离增加而换选另一条证据链。

直线completion覆盖不足但局部道路域连通时，可使用可见性最短路绕过道路面凹部；不得沿同一巨型RoadSurface的远端连接绕行。路径必须先通过局部范围与绕行门禁，再对边界拐点做内缩保护，最后由现有平滑流程生成发布几何并复核合法域覆盖。

### 7.3 平滑

允许忽略Lane局部拓宽/变窄和短时中心锚点切换，但不能抹除真实弯道、物理分离、分歧合流。阈值由真实数据复算后配置，不固化为生产真值。

## 8. Node与RoadNextRoad

LaneTopo在同版本物理Movement判定中高于Patch RoadNextRoad。若LaneTopo锚点落在已组装Road内部，可先切分物理Road并实体化共享Node，再编译RoadNextRoad；该操作只改变Road carrier，不切分T01 Segment。

- Road/Node ID按正式RCSD规范继承或稳定生成。
- 同一JunctionUnit mainnode一致。
- 每条正式Segment Road都必须完成自身Access交接；正确Junction组/mainnode是必要条件而非充分条件。
- ordinary物理全连接通过分布式portal Node、统一mainnode和语义RoadNextRoad表达，不生成中心点或星形内部Road。
- complex通过内部Road/Node表达。
- Segment内部和complex RoadNextRoad从方向正确的实际共享Node/显式物理关系生成；ordinary语义RoadNextRoad只在正确分类JunctionUnit内生成。
- Road细分后重新编译RoadNextRoad，但既有Node图不重建；投影到细分父Road的LaneTopo允许沿同一lineage的实际有向part链到达目标Road，并发布完整`carrier_path_road_ids`。
- 发布前先以SWSD逐Segment Access方向合同复核所有Road链，再以SWSD逐Junction Movement合同复核ordinary全部组合和complex显式关系；任一缺失触发所属单Segment回退后重编译，不允许用Review或裸`mainnodeid`补边。

## 9. LaneTopo和局部结构

- 每条usable LaneTopo进入mapped/review/excluded/blocked之一。
- 缺失不作负证据。
- ordinary跨Segment关系可直接映射到ordinary语义RoadNextRoad；被拒关系显式excluded且不回退两侧Segment。
- 同Segment内部关系被拒并破坏carrier连续性时，回退范围仅为该Segment和相关Movement。
- Patch已有调头口/短连接且证据支持时同步为Segment内部Road/Node/PhysicalMovement。
- 缺失局部结构恢复不在当前主流程。
- T01未表达提前右转只输出RealityChangeClue；Road materialization后再进入临时Segment流程。

## 10. 发布与终态

生成器写正式三图层、关系层、审计层和manifest。独立QA从发布文件复算：

- Segment覆盖和四态；
- geometry source和无SWSD splice；
- Road有效性/道路面/平滑；
- Node/mainnode/RoadNextRoad；
- junc_nodes/LaneTopo；
- 跨Patch和ID稳定；
- CRS、性能和旧版本保护。

QGIS构建和回读通过后还需人工分层审计。只有所有必要证据齐全时finalizer才允许`passed`。

## 11. 版本隔离

新实现使用`segment_first_*`模块内文件和独立callable。旧M1/M2/V2/V3 callable、输出名、tests和历史run保持不变；不新增CLI/root script或入口登记。
