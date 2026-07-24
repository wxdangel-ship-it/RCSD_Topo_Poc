# P04 架构：证据与审计

## 1. 证据分层

### 1.1 业务结构事实

- T01 Segment集合、`pair_nodes/junc_nodes/roads/sgrade`；
- T07/T03/T04/T08正式accepted surface和Junction类型；
- SWSD Road/Node方向、mainnode与原carrier lineage。

这些事实定义当前目标结构，不等于高精几何真值。

### 1.2 高精强证据

- Patch Road与其已有局部结构；
- Lane/LaneTopo；
- LaneBoundary；
- RoadSurface/DriveZone；
- 已确认语义的物理隔离和导流证据。

Patch Road、Lane等同版本生产，优先用于carrier几何和拓扑。它们仍需输入质检，不能因“强证据”跳过hard gate。

Patch Road对象记录为可聚合的evidence span，不作为正式Road identity；跨Patch组装必须保留全部源`patch_id + RoadId`并证明Patch边界没有成为Road断点。

### 1.3 锚定和fallback证据

- 完整RCSD用于SWSD语义锚定、Junction fallback候选和全图连续性参考；
- SWSD用于完整性和最终保留表达。

完整RCSD锚定成功只把对应Patch证据纳入正确语义上下文，不自动证明每条Patch Road与SWSD Road一一对应。

### 1.4 历史对照

P04 M1/M2/V2/V3、T06/T12结果只用于差异、回归和人工理解，不决定当前carrier。

例外仅限显式闭域验收：T06 Step2 `replacement_ready + hard_filter_passed`可作为“该Segment应当存在高精覆盖”的目标先验，`rcsd_road_ids`可辅助把Patch证据召回到正确Segment。它仍不决定Road identity、方向角色或最终坐标；旧T06 Step3是否实际替换也不是目标准入条件。

## 2. 证据身份

每个Patch对象使用：

```text
patch_id + object_type + source_id
```

不得因跨Patch聚合改写源对象ID。一个对象可有多个候选语义上下文，但进入hard geometry前必须有唯一或显式受控角色。

## 3. 输入质量与业务状态分离

输入证据状态：

- `usable`；
- `review`；
- `insufficient`；
- `excluded`。

Lane过窄/过宽、Boundary-gap、宽度不稳定、非机动车道误识别、资料缺失等只进入输入质量层。它们不能直接把Segment标为`conflict_retained`；排除后只降低可用覆盖。

## 4. Junction证据审计

每个JunctionUnit必须记录：

- `junction_id/type/source_module/source_object_ids`；
- surface正式状态与字段；
- T07/T03/T04/T08/RCSD/SWSD优先级路径；
- T07/T03差异；
- Junction拓扑来源、Road端点surface来源及二者分离原因；
- 每个built交接端点的严格入面状态、面内深度、补齐来源和失败原因；
- mainnode、Node集合和默认物理全连接是否适用；
- 高精portal集合、portal物理聚类、mainnode分组及其surface/DriveZone支撑；ordinary中心聚合Node和星形内部Road必须为0；
- rejected portal的owner Segment和原子回退结果；
- fallback/retained原因。

T07 `review_required`/fail1候选、T03/T04 rejected或relation-only不得静默提升为accepted。

## 5. Segment与carrier审计

每个Segment必须发布：

- T01原始字段和source Patch集合；
- 必要carrier角色；
- built/retained Road清单；
- 四态、publishable、takeover ready、replacement scope；
- 方向覆盖和重叠检查；
- pair/junc access交接状态；
- 每条正式Segment Road的逐Road access交接状态；
- hard failure和soft review原因。
- 稳定Road细分的父Road、part顺序、交接里程、左右lineage、accepted/rejected决策和Junction保护原因。

强证据充分但未使用必须单独统计和逐对象解释，不能藏在总fallback率中。

## 6. Road几何审计

built Road逐span记录：

- `hp_observed/hp_constrained_completion`；
- 支撑Lane/Boundary/Patch Road/Surface；
- 起止里程和几何；
- completion边界条件；
- 道路面覆盖、中心偏差、曲率和接缝；
- 是否触发soft Review。

independent QA必须证明span无缝覆盖整条built Road且不存在`swsd_fallback`。

retained Road记录原carrier ID/source，不产生虚假的高精span。

## 7. Node与拓扑审计

- Road起终Node存在性；
- Node ID继承/生成seed；
- 细分只新增度2内部Node；细分前全部既有Node的ID、坐标、mainnode和Junction归属必须逐对象不变；
- JunctionUnit mainnode一致性；
- ordinary共享Node实体；
- ordinary分布式portal Node、统一mainnodeid、语义RoadNextRoad及其source/target物理Node lineage；
- RoadNextRoad实际shared node；
- complex内部Road/Node来源；
- 由mainnode直接生成的关系必须为0。
- SWSD逐Segment Access方向合同：expected/actual方向角色、对应Road链、失败Segment和回退原因；
- SWSD逐Junction Movement合同：ordinary expected/actual进入—离开组合、complex显式关系、source/target SWSD member与物理Node lineage；
- `complex_junction_swsd_explicit`逐关系同时记录原始shared node、member lineage匹配和accepted surface内portal证据。

## 8. LaneTopo审计

每条可用LaneTopo最终为：

- `mapped`；
- `soft_review`；
- `excluded`；
- `blocked`。

记录source/target Lane、Road、Node、Junction/Segment、projection kind和reason。缺失LaneTopo不进入负向统计。

同owner反向、跨owner反向、调头/局部connector必须纳入同一分类，不得因owner相同静默忽略。

LaneTopo与Patch RoadNextRoad表达冲突时，前者作为PhysicalMovement直接证据优先；冲突记录必须保留。LaneTopo触发的Road内部切分需同时审计anchor距离、切分前后Road lineage、共享Node和最终RoadNextRoad。

LaneTopo跨越同一父Road的多个细分part时，审计必须记录实际RoadNextRoad链`carrier_path_road_ids`；单跳投影器不得把合法多Road链误报为shared-node缺失。

跨Segment关系被物理证据拒绝时，审计为Movement级显式excluded，不回退两侧Segment；同Segment内部关系被拒且破坏carrier连续性时，记录其owner Segment原子回退。两类阻断范围不得混用。

证据占用固定点审计至少记录：恢复候选总数、仍冲突数、因owner Segment已fallback而释放的冲突数、最终接管Segment、Segment级走廊/baseline/access/member Surface的实际优先级分支。单member Surface推导还必须记录观测方向、推导方向、RoadSurface约束、endpoint surface补齐及soft Review；被DriveZone覆盖或几何hard gate拒绝的尝试不得进入正式Road。

access-surface短桥接还必须记录两个端点保护区的距离/重叠状态、观测与补齐比例、观测方向source key、推导方向和最终两端Junction归属。两个保护区接触或重叠时记录为端点归属歧义并拒绝接管，不能把同时落入两个surface的短线解释为完整Segment。

局部endpoint surface路由至少审计：观测端点、目标surface、直线失败原因、局部support范围、最终路径长度/绕行比例、平滑前后合法域覆盖、最终转角和completion比例。由该路由触发的LaneTopo切分还须保留原Movement审计；端点面外兄弟尾段被抑制时记录父carrier、尾段长度、两个端点Access及`segment_main_tail_outside_endpoint_corridor_suppressed`，不得silent drop。

## 9. hard与soft分层

hard failure包括：无Road、必要方向主干链断裂/分叉/终端Access缺失、built终端Node未被选定原始accepted surface严格包含、THROUGH因旁侧邻近而虚假切分、方向/覆盖不完整、SWSD splice、错误Junction/mainnode、逐Road Access未实现、SWSD Access方向或Junction Movement合同不完整、ordinary中心聚合Node/星形内部Road、junc_nodes丢失、RoadNextRoad证据类型不成立、细分Road缺少Lane/Patch lineage、细分侵入Junction关系范围或改变既有Node/Segment级连通关系、constrained越界、confirmed同Segment主carrier冲突、CRS错误、independent QA失败。边界、面外buffer或仅有DriveZone支撑不得替代严格入面。

soft Review包括：推导方向、completion跨度/曲率偏高、中心走廊置信较低但合法、RCSD/Patch可解释差异、输入质量异常已隔离、局部Movement证据不足。

soft Review不影响完整carrier发布；hard failure不能由Review豁免。

## 10. 运行与性能审计

manifest必须记录：

- 输入绝对路径、layer、hash、CRS、count；
- 参数、阈值及其数据依据；
- 代码版本和运行环境；
- 各阶段耗时、吞吐和可获得的峰值内存；
- 输出相对路径、hash、schema和count；
- core/independent/QGIS/manual状态；
- 旧版本保护结果。

## 11. QGIS人工审计

QGIS至少显式比较：

- SWSD；
- 完整RCSD；
- Patch Road/Lane/LaneBoundary/RoadSurface；
- 冻结P04历史成果；
- 新Road/Node/RoadNextRoad；
- Segment/Junction/Access；
- ordinary Junction内部carrier和LaneTopo connection exclusion；
- geometry source、carrier状态；
- LaneTopo/PhysicalMovement；
- Road lineage split accepted/rejected、父Road part顺序和LaneTopo carrier path；
- soft Review和hard violation。

人工检查按普通路口、复杂分歧合流、环岛、主辅路、部分/无证据、冲突、跨Patch和Patch已有局部结构分层记录，不以少量截图替代全量机器门禁。
