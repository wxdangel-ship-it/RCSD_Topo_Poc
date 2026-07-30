# P04 - INTERFACE_CONTRACT

## 1. 定位

本文件是`p04_road_direct_generation`当前稳定接口边界。P04保持`Active POC / 成果模块`，当前新增独立Segment-first版本化能力；既有M1/M2、冻结Directional Road V2、High-Precision Road V3保持不变。

Segment-first目标是以T01 Segment为构图/回退原子，使用正式上游Junction surface和Patch强证据，生成数据规格兼容的P04 RCSD候选`Road / Node / RoadNextRoad`，并通过独立发布后QA与QGIS审计。

本契约不发布生产正式RCSD/F-RCSD，不接入T10，不替代T01/T05/T06/T09，不修改T00–T12任何V1接口或入口。

## 2. 版本边界

### 2.1 当前Segment-first版本

- 独立SpecKit：`specs/p04-segment-first-road-direct-20260722/`。
- 独立模块内callable：`run_segment_first_road_direct(SegmentFirstConfig)`与`finalize_segment_first_run(output_dir, acceptance_manifest_path)`。
- 独立Config/Result、状态空间、输出目录和QA。
- 模块callable由第12.1节登记的正式参数化内网入口
  `scripts/p04_run_segment_first_innernet.py`包装；该入口不改变模块业务接口，
  `finalize_segment_first_run(...)`仍按第12.2节独立执行。

### 2.2 历史版本

以下接口保持原行为，不作为当前业务本体：

- `run_milestone_one(MilestoneOneConfig)`；
- `run_milestone_two(MilestoneTwoConfig)`；
- `run_directional_road_v2(DirectionalRoadV2Config)`；
- `run_high_precision_road_v3(HighPrecisionRoadV3Config)`。

冻结V2和V3输出、结果文档、测试与run ID不得被Segment-first覆盖。

## 3. Segment-first输入契约

### 3.1 必需输入族

| 输入 | 最小正式语义 |
|---|---|
| T01 Segment | `id/segmentid`、`sgrade`、`pair_nodes`、`junc_nodes`、`roads` |
| SWSD Road | `id/snodeid/enodeid/direction/patch_id/geometry`及正式别名 |
| SWSD Node | `id/mainnodeid/subnodeid/kind_2/grade_2/geometry`及正式别名 |
| Patch根 | 若干`<patch_id>/Vector/*`，至少可定位Patch Road/Lane/LaneTopo/LaneBoundary/RoadSurface家族 |
| 输出根 | 与全部输入及历史run不重叠的新目录 |

### 3.2 Junction正式输入

| 来源 | 正式可消费成果 | 语义 |
|---|---|---|
| T07 | `t07_rcsdintersection_anchor_surface.gpkg`中正式accepted/可消费surface及relation evidence | ordinary最高优先级 |
| T03 | `virtual_intersection_polygons.gpkg`中`step7_state=accepted` | T07缺失时ordinary补充 |
| T04 | `divmerge_virtual_anchor_surface.gpkg`中`final_state=accepted`及正式audit | complex divmerge |
| T08/T01 | prepared Node/Road和环岛整体Junction事实 | roundabout |

T07/T03冲突采用T07并记录差异。`review_required`、fail1多面候选、rejected、relation-only不得自动提升为accepted。

### 3.3 RCSD输入

- 完整RCSD Road/Node/RoadNextRoad：用于SWSD锚定辅助、Junction fallback候选和全图连续性参考。
- Patch Road：与Lane等同版本的carrier强证据及已有局部结构。

完整RCSD锚定成功只建立语义上下文，不能自动证明Patch Road与SWSD Road一一对应。

### 3.3.1 可选闭域目标输入

- 可显式传入冻结T06 Step2 `t06_rcsd_segment_replaceable.csv`作为Case验收/锚定辅助；未传入时不启用闭域高精目标gate。
- 可同时传入独立`target_disposition_manifest.json`，只覆盖闭域目标的DirectBuild资格与审计处置，不改变输入确定的Baseline集合。清单必须逐对象包含`segment_id/direct_build_eligibility/reason_codes/evidence_ids/approval_state`并进入输入hash；实现代码不得硬编码Case或Segment ID。
- 只消费正式字段`swsd_segment_id/replacement_ready/hard_filter_passed/rcsd_road_ids/excluded_advance_right_turn_road_ids`；不由其它样本字段反推业务语义。
- 核心目标要求T06可替换且两个T01 Segment端点终端Road的Patch membership均非空并完全属于本次Patch集合；正式`ADVANCE_RIGHT Segment`按同一闭域条件独立纳入。
- T06/完整RCSD可扩展Patch证据召回和关系锚定，但不得成为正式Road owner或built几何坐标来源。

### 3.4 Patch证据

- Lane/LaneNextLane：方向中心走廊与物理可达；
- LaneBoundary：中心、宽度、方向分离和completion约束；
- DriveZone/DriveZone_fix：合法道路域，同语义证据族，默认fix；
- DivStripZone/DivStripZone_fix：导流带，同语义证据族，不是Patch分区；
- Patch Road：carrier和已有调头/短连接强证据；
- 其它字段：只有正式字典/契约确认后才能进入强规则。

### 3.5 CRS

- 所有源CRS必须可识别或通过显式参数提供。
- 空间计算必须统一到显式米制分析CRS并记录转换。
- 不得隐式混算EPSG:4979、3857或其它CRS。
- 正式输出CRS必须符合当前RCSD数据规格或本次run显式合同。

## 4. 领域状态和值域

### 4.0 闭域目标三层状态

| 层 | 字段 | 值域/语义 |
|---|---|---|
| Baseline | `baseline_target/baseline_target_class` | 输入确定的原始闭域目标及`core/advance_right`分类，后续不得缩小。 |
| DirectBuild | `direct_build_eligibility` | `direct_build_required / patch_data_insufficient / reality_change`；默认必建。 |
| DirectBuild结果 | `direct_build_outcome` | `realized / hard_conflict / partial_evidence_unresolved / not_applicable`。 |
| 发布处置 | `publish_disposition` | `hp_published / swsd_retained_data_insufficient / swsd_retained_reality_change_pending / conflict_retained / swsd_retained_partial_evidence`。 |

`patch_data_insufficient/reality_change`必须来自外部确认清单；`hard_conflict/partial_evidence_unresolved`仍在DirectBuild硬分母内。全部Baseline对象仍进入逐对象审计，全部Segment仍进入正式完整发布。

### 4.1 Segment状态

| 字段 | 值域 |
|---|---|
| `build_state` | `hp_full / hp_partial / swsd_retained / conflict_retained` |
| `segment_publishable` | boolean |
| `carrier_takeover_ready` | boolean |
| `replacement_scope` | `all / subset / none` |

每个范围内T01 Segment必须有唯一build_state和至少一条最终Road。

### 4.2 Road realization

| 字段 | 值域 | 语义 |
|---|---|---|
| `realization` | `built / retained` | 完整新建或完整保留Road |
| `geometry_source` | `hp_observed / hp_constrained_completion / swsd_retained_whole / swsd_retained_partial` | built Road只允许前两类；retained Road只允许后两类 |
| `carrier_role` | P04审计值 | 主/辅/方向/through/local等；正式方向仍沿RCSD规格 |
| `owner_type` | `SEGMENT / JUNCTION_UNIT` | P04关系/审计值；区分业务Segment Road与路口内部Road |
| `junction_group_id` | canonical ID或空 | JunctionUnit Road的lineage；Segment Road为空 |

值域中不存在built Road的`swsd_fallback`。`swsd_retained_whole`完整保留原Road；`swsd_retained_partial`只保留稳定证据边界外的SWSD子串，且必须与同member的built Road互不重叠并共享实际交接Node。

### 4.3 Evidence quality

`usable / review / insufficient / excluded`。输入quality不能直接生成Segment结构冲突。

### 4.4 Movement projection

| 字段 | 值域 |
|---|---|
| `projection_state` | `mapped / soft_review / excluded / blocked` |
| `projection_kind` | `internal_continuity / road_movement / uturn / local_connector` |

PhysicalMovement只表达物理可达，不表达T09合法性。

## 5. 核心业务契约

### 5.1 Segment-first

- T01 Segment是顶层owner；SWSD/Patch Road只作carrier lineage或证据。
- 一个Segment可有一条双向Road链、两条单向方向主干链或多条主辅方向链；链只可在Junction关系范围外的稳定纵向LaneGroup/Patch证据交接处细分为多条Road。
- 细分必须精确保持父Road几何并集、方向角色和Segment状态；只增量生成内部度2 Node，不得再次全局编译Node或改动既有portal/mainnode。
- `junc_nodes/THROUGH`保持同一业务Segment。
- 单Segment失败只回退自身和相关新Movement。
- 每条正式Segment Road都必须独立完成其全部适用SegmentAccess交接；同Segment其它Road已接边不能替代。

### 5.2 部分支持

- 同一built Road仅允许observed+constrained completion。
- Patch Road片段只作为evidence span；跨Patch片段先按Segment/member/方向聚合，再形成正式Road identity。
- 整个方向/完整carrier无证据时可整条retained。
- 禁止同一Road混合新坐标与SWSD坐标。
- 禁止新单向Road和覆盖双向的retained Road并存。
- 不承担DirectBuild完整性硬目标的单方向member可按稳定证据边界拆为独立built Road和互不重叠的`swsd_retained_partial` Road；built部分不得使用SWSD顶点，retained部分不得声明高精，二者共享实际transition Node。该部分表达不计为DirectBuild完成。
- 部分接管不得覆盖既有完整built carrier；候选失败必须恢复进入该步骤前的Road/Node/状态，不得制造新的`conflict_retained`回归。
- 双向member只有在两个方向角色均可完整发布时才允许由两条单向built Road接管；缺一方向且无可审计推导证据时整条retained。
- 接管优先级固定为完整Segment方向走廊、baseline/access恢复、单member缺方向Surface推导；低优先级候选不得覆盖已通过方向与端点门禁的高优先级候选。
- 单member Surface推导必须原子生成两个方向角色；需要endpoint surface救援时，两条Road必须分别到达两端accepted surface/正式端点缓冲，且补齐段满足DriveZone与几何hard gate，否则整条retained。
- `target_access_surface_candidate`只有在冲突占用已释放、DriveZone与最小观测比例通过、两个`accepted surface + junction_endpoint_buffer`保护区互不接触且Road端点分别交接不同保护区时，才可作为surface-to-surface完整carrier；此时不再以包含Junction内部长度的SWSD轴覆盖率否决。重叠保护区、同端归属歧义或推导方向未通过完整hard gate时整条retained。
- endpoint直线补齐失败后，先尝试沿观测端部切线到达accepted surface；切线候选和后续局部RoadSurface路由都必须满足：端点到目标surface未超过既有补齐上限、路径局限于端点—surface局部范围、合法域覆盖达到正式阈值、绕行与总长受限、平滑后仍合法。输出span仍为`hp_constrained_completion`，不得新增SWSD geometry source。Movement切分若产生端点面外主干尾段，只有同父carrier存在唯一贯穿两端面的片段时才抑制并输出显式审计。
- 简单Segment中，built主方向链已连续覆盖两个终端Junction后，可以审计并抑制与其高比例重叠、且不承担THROUGH/局部Movement功能的retained语义carrier；抑制必须增量保持既有Node状态，并在Segment Access、SWSD功能拓扑、RoadNextRoad、LaneTopo复算任一失败时原子回滚。
- fallback后只释放已保留Segment独占且未发布的恢复证据，并重算其它Segment到固定点；与仍有效built carrier冲突的证据不得释放。

### 5.3 Junction/Node

- Road端点物理选面：同组T07人工accepted优先，其次为对应T03/T04 accepted；T07与T04同组时只覆盖端点落位几何，不覆盖T04 complex拓扑模式和内部carrier范围。
- ordinary拓扑：T07 accepted>T03 accepted>verified full RCSD>SWSD retained。
- complex拓扑：T04 accepted>verified full RCSD>SWSD retained。
- roundabout：T08/T01整体Junction。
- 同JunctionUnit所有Node共享mainnodeid，但保留分布式物理nodeid。
- 实际共享nodeid编译Segment内部连续性和显式物理RoadNextRoad。
- 非Junction语义范围内，同Segment前后主干Road必须以完全相同的实际Node完成物理交接；`mainnodeid`只提供分组lineage，不得替代共享Node。
- ordinary默认PhysicalMovement由同一正确分类JunctionUnit内方向兼容的进入—离开Road组合编译；每条关系必须记录source/target物理Node、junction_group_id和mainnodeid，不得只按mainnode字符串无上下文笛卡尔连接。
- SWSD提供完整拓扑验收合同而非built几何：逐Segment保留全部Access进出方向，逐ordinary Junction保留全部方向兼容的进入—离开组合；Road可按稳定LaneGroup交接细分，验收按方向Road链归一，不要求与SWSD Road一一对应。
- ordinary不发布中心聚合Node或星形`JUNCTION_UNIT`内部Road；空间分离portal保持原高精位置。同一真实门户的极近端点可稳定聚类，不得跨门户snap。
- ordinary内的built方向portal不得经同一SWSD source Node或保留`semantic_carrier`重新聚合到中心坐标；保留Road可以参与语义RoadNextRoad，但不替代built Road的物理Node。
- T04复杂路口、环岛和聚合异常只按实际共享Node或显式物理关系编译，不使用ordinary默认全连接。T04证据暂缺时，原始SWSD关系只有在真实共享Node、member lineage匹配、两侧portal位于accepted surface三项同时成立时，才可按`complex_junction_swsd_explicit`保守实例化。若usable LaneTopo已被Node交接证据接受，但source到target之间由已发布`local_connector`承接，则仅在source到该connector已实际共享Node、connector出口与target入口属于同一T04组、二者距离受限且连线至少80%位于该accepted surface时，才可按`complex_junction_lane_topo_explicit`补充显式关系；该关系只补足Segment内部物理carrier，不新增跨Segment功能关系。
- built Road的Junction portal最终Node必须被选定原始accepted surface严格包含；边界、面外`junction_endpoint_buffer`和仅DriveZone支撑均不成立。无法平滑入面是hard failure，只回退该portal所属的built Segment。
- `junction_endpoint_buffer`只承担候选检索、细分保护和生成面内目标，不得作为发布验收容差。存在T07/T03/T04 accepted polygon时，THROUGH Road只有实际穿入面内才允许切分，旁侧邻近不得形成Junction端点；若上游只有`swsd_retained`点，且该点由同一T01 Segment的正式THROUGH access lineage唯一支持，可在既有Road最近投影处细分，但不得移动Road几何或将其解释为accepted surface入面证明。
- 不发布`junction_geometry_unresolved`。

### 5.4 LaneTopo与局部结构

- 可用LaneTopo必须mapped/review/excluded/blocked之一。
- LaneTopo缺失不是负证据。
- 对实际PhysicalMovement，LaneTopo优先于Patch RoadNextRoad；冲突不得用后者覆盖前者。
- Road内部LaneTopo锚点可触发Road切分和共享Node实例化，但业务Segment保持不变。
- LaneTopo跨细Road时可沿同一稳定父Roadpart链，或沿中间Road全部为保留`semantic_carrier`的有限实际RoadNextRoad链映射；必须发布完整`carrier_path_road_ids`，不得接受任意可达路径。
- ordinary跨SegmentMovement可直接映射到ordinary语义RoadNextRoad；被物理证据拒绝时显式excluded，不回退两侧Segment。
- retained语义连接只允许在source/target Road或Lane证据命中同一原始LaneTopo关系时发布为`explicit_lane_topo_retained_semantic`，不得由共享mainnode扩展。
- T01正式`ADVANCE_RIGHT Segment`与相邻主干Road被同一原始LaneTopo关系命中时，可发布`explicit_lane_topo_advance_right_semantic`；端点必须具备ordinary/retained Junction lineage，且关系不得新增或改写T01业务骨架。
- 反向/U-turn关系不得由几何、mainnode或邻近自动生成，必须具有原始LaneTopo或局部连接Road显式证据。
- 同Segment内部关系被拒且破坏carrier连续性时，只阻断该Segment及相关Movement。
- Patch已有调头/短连接按需同步；缺失不主动恢复。
- T01未表达提前右转先输出RealityChangeClue；无simple Road不得发布临时Segment。

## 6. 正式输出契约

### 6.1 正式P04 RCSD候选

单一GeoPackage或等价发布包必须包含：

- `Road`；
- `Node`；
- `RoadNextRoad`。

具体schema、ID和枚举沿用正式RCSD数据规格；实现preflight必须核对，不得由局部样本猜测。

属性职责：

- `source`属于Road；
- `mainnodeid`属于Node；
- `segment_id/source_patch_ids/Lane/evidence`可通过关系审计恢复，避免污染正式schema。
- `owner_type/junction_group_id`属于P04关系/审计语义；正式RCSD schema不允许扩展时必须从`segment_road_relation`恢复。

### 6.2 审计输出

按需发布：

- SegmentBuildUnit/JunctionUnit/SegmentAccess/RoadCarrierPlan；
- Segment-Road/Road-Lane/Junction-Node/source lineage；
- `swsd_segment_directional_paths`：按T01 Node/mainnode和Road方向枚举的Segment正反向SWSD member路径、唯一/歧义状态及候选数；当前仅审计，不直接驱动正式Road角色；
- `road_lineage_split_audit`：accepted稳定交接与`junction_relation_scope_protected`拒绝候选；
- geometry source/PhysicalMovement/RealityChangeClue；
- Baseline/DirectBuildEligibility/PublishDisposition逐对象合同、外部分类证据及manifest hash；
- input quality/soft Review/hard violation；
- manifest/summary/report/independent QA/QGIS。

## 7. ID合同

- 输入IDcanonical化。
- 新Road不继承SWSD Road ID。
- Node/RCSD/Patch身份能继承则继承，不能继承时按RCSD ID规范稳定生成。
- ID必须对Patch输入顺序、并行顺序和重复运行稳定。
- 具体编码未核对正式规格前不得实现猜测规则。

## 8. hard gate

以下任一存在时，新carrier不得接管：

1. Segment无独立Road；
2. 必要方向缺失、方向重复或双向/单向重叠；
3. built Road含SWSD直接坐标；
4. Road无有效Node引用；
5. SegmentAccess错误Junction组或mainnode不一致；
6. 任一正式Segment Road未实现其适用Access交接；
7. ordinary Junction portal缺少accepted surface/DriveZone支撑，或出现中心聚合Node/星形内部Road；
8. 真实junc_nodes静默丢失；
9. 实际共享Node型RoadNextRoad无真实shared node，或ordinary语义型RoadNextRoad的source/target Node不属于同一正确分类JunctionUnit；
10. constrained completion越界/穿隔离/无法解释；
11. confirmed LaneTopo证明同Segment主carrier物理拓扑错误；
12. CRS或schema失败；
13. independent QA缺失或失败。
14. 必要方向主干链断裂、分叉、缺少终端JunctionAccess，细分Road缺少LaneGroup/Lane/Patch lineage，或细分改变既有Junction portal/Segment级有向连通关系。
15. SWSD逐Segment Access方向合同或逐Junction Movement合同存在缺失；complex SWSD显式关系不满足共享Node、member lineage或accepted surface约束；complex LaneTopo显式关系缺少accepted LaneTopo、已发布local connector、同组T04 portal或accepted surface覆盖。

hard failure按单Segment回退；Review不得豁免。

## 9. soft Review

在hard gate通过时，推导方向、completion风险、低置信中心但合法、T07/T03差异、RCSD/Patch可解释差异、已隔离输入异常、局部Movement不足可带Review发布。必须逐对象输出reason和QGIS层。

## 10. 独立QA与终态

独立QA只读取发布文件，至少复算：

- schema/CRS；
- Segment覆盖、四态、Road数和replacement scope；
- geometry source、无SWSD splice、Road有效性/道路面/平滑；
- Node/mainnode/RoadNextRoad；
- junc_nodes/LaneTopo；
- 跨Patch、ID稳定和重复运行；
- 输入/参数/output hash与性能；
- 旧M1/M2/V2/V3保护。
- 显式闭域目标合同、目标必要主干/正式提右覆盖率和边界排除原因。
- Baseline实现率、DirectBuild实现率和全量完整发布率必须并列复算；Baseline历史分母不得被例外清单改写。

生成callable最多写`technical_passed`；`terminal_status=passed`必须由finalizer在core、发布回读、independent QA、QGIS道路面覆盖、真实PyQGIS回读、完整真实范围确定性和人工审计证据齐全后晋级。任一证据缺失不得passed。

## 11. QGIS合同

工程使用相对路径，至少分组显示：

1. 正式Road/Node/RoadNextRoad；
2. SWSD；
3. 完整RCSD；
4. Patch Road/Lane/LaneBoundary/RoadSurface；
5. 历史P04成果；
6. Segment/Junction/Access；
7. geometry source/carrier状态；
8. LaneTopo/PhysicalMovement；
9. soft Review；
10. hard violation。
11. Road证据边界切分的accepted/rejected候选及其Junction保护原因。
12. SWSD Access方向合同、Junction Movement合同及complex显式fallback关系。
13. SWSD方向Road路径合同；唯一/歧义均可下钻，当前审计层与正式Road发布层分离。
14. 路口面审计组：P04最终JunctionUnit、T07人工确认面、Patch原始`Intersection`、T03 accepted面和T04 accepted分歧合流面，必须使用可独立开关的显式样式。
15. retained冗余候选的accepted/rollback逐Road审计，以及`swsd_retained_partial`与对应built Road的交接Node。

QGIS工程和全部空间图层必须显式序列化分析CRS。PyQGIS构建和独立回读都必须通过，并分别核对项目CRS、图层CRS、数据源、图层数量和必需比较角色。

## 12. 入口契约

### 12.1 repo CLI/root scripts

正式内网入口：

```text
.venv/bin/python scripts/p04_run_segment_first_innernet.py <explicit arguments>
```

输入参数合同：

- 唯一目录型业务输入：`--patch-root`，其下为`<PatchID>/Vector/*`；
- 必填文件型输入：`--swsd-road / --swsd-node / --t01-road / --t01-node / --t01-segment / --t07-surface / --t03-surface / --t04-surface / --full-rcsd-road / --full-rcsd-node`；
- 可选文件型输入：`--target-replaceability / --target-disposition`；
- 运行参数：`--output-dir / --run-id / --analysis-crs`；
- 禁止在脚本内硬编码本地或内网业务路径，禁止复制Segment-first业务算法；
- 输出目录必须为新目录或空目录，且不能与任何输入目录重叠；
- 默认进程完成即返回0，`terminal_status/core_gate_pass`必须在stdout JSON显式报告；`--require-core-pass`启用时core gate失败返回2。

### 12.2 模块callable

当前支持：

```text
SegmentFirstConfig -> run_segment_first_road_direct(...) -> SegmentFirstResult
technical_passed output + acceptance manifest -> finalize_segment_first_run(...) -> SegmentFirstResult(passed)
```

Result至少包含`run_id/output_root/summary/report/independent_quality/qgis_project/core_gate/terminal_status`。

两个callable仍为P04模块接口；`run_segment_first_road_direct(...)`由`p04_run_segment_first_innernet.py`正式参数化包装，`finalize_segment_first_run(...)`不在本入口自动调用，仍需外部验收证据。

## 13. 历史输出

M1/M2、冻结V2、V3的文件名、字段、阈值、run ID和结果文档保持历史事实。本版本不覆盖其输出，不把旧Road级四态转换为当前Segment四态。
