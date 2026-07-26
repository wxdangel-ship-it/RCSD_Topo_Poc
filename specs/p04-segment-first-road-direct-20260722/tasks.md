# Tasks: P04 Segment-first Road 直出

**Input**: `spec.md / research.md / data-model.md / plan.md / contracts/poc-output-contract.md`
**Execution rule**: 按 phase gate顺序执行；实现阶段遵循 `.agents/skills/default-imp/SKILL.md`。
**Roles**: `[PROD]` 产品、`[ARCH]` 架构、`[DEV]` 研发、`[TEST]` 测试、`[QA]` 质量。

**当前执行终态**：Case 1885118 run `p04_segment_first_junction_interior_v75_1885118_20260725T050000` 是本轮10次迭代后的当前综合效果最佳Active POC人工审计候选。V75保持330/330 Segment、831/831 Access、371/371 Junction Movement、0 LaneTopo unresolved、0几何hard failure和独立QA 0 violation；正式输出887 Road、1146 Node、2328 RoadNextRoad，其中470 built、417 retained。三层合同稳定为Baseline 103、Patch资料不足6、RealityChange 1、DirectBuildRequired 96；当前实现86/96，因此`terminal_status=failed`，不得finalize为阶段完成。53层QGIS工程由真实QGIS 3.40.14回读为EPSG:32650、0 invalid、必需层缺失0；470条built Road相对正式道路域覆盖99.463819%。V69/V70保留为Phase 18历史对照，但其59个面外或边界端点不满足后续确认的严格入面合同。

## Phase 1: Source facts 与真实输入 preflight

**Goal**: 在写业务实现前，确认输入事实、数据规格、旧版本保护和源事实迁移。

- [x] T001 [ARCH] 同步 `modules/p04_road_direct_generation/SPEC.md` 为 Segment-first 主口径，同时保留M1/M2/V2/V3历史边界。
- [x] T002 [ARCH] 同步 `modules/p04_road_direct_generation/architecture/01-introduction-and-goals.md` 的目标、范围和非目标。
- [x] T003 [ARCH] 同步 `modules/p04_road_direct_generation/architecture/02-data-and-domain-model.md` 的 Segment/Junction/Road/Node分层。
- [x] T004 [ARCH] 同步 `modules/p04_road_direct_generation/architecture/03-solution-strategy.md` 的上游复用、carrier和fallback流程。
- [x] T005 [ARCH] 同步 `modules/p04_road_direct_generation/architecture/04-evidence-and-audit.md` 的证据优先级、lineage和hard/soft审计。
- [x] T006 [QA] 同步 `modules/p04_road_direct_generation/architecture/05-quality-requirements.md` 的端到端门禁和QGIS验收。
- [x] T007 [ARCH] 同步 `modules/p04_road_direct_generation/architecture/06-risks-and-technical-debt.md` 的现实变化、未知字段和生产边界。
- [x] T008 [ARCH] 同步 `modules/p04_road_direct_generation/INTERFACE_CONTRACT.md`，新增隔离Segment-first callable和输出合同，不改旧callable。
- [x] T009 [PROD] 最小同步项目 `SPEC.md`、`docs/PROJECT_REQUIREMENTS.md` 与必要 `docs/architecture/*` 的P04定位。
- [x] T010 [ARCH] 最小同步 `docs/doc-governance/module-lifecycle.md`、P04模块/文档inventory和status，保持Active POC。
- [x] T011 [QA] 对所有计划修改源码/脚本执行当前字节数precheck，并将新增文件纳入后续code-size audit。
- [x] T012 [DEV] 定位当前完整测试范围的T01/T07/T03/T04/T08/full-RCSD/Patch输入根并生成只读清单。
- [x] T013 [TEST] 编写输入contract测试，核对T01 `id/sgrade/pair_nodes/junc_nodes/roads`和实际图层。
- [x] T014 [TEST] 编写T07/T03/T04 accepted surface contract测试，确保不从review/rejected/relation反推accepted。
- [x] T015 [TEST] 核对RCSD Road/Node/RoadNextRoad正式schema、ID和`source/mainnodeid`字段；缺失正式语义时停机回报。
- [x] T016 [QA] 记录全部输入path/layer/CRS/count/hash与运行环境，形成preflight审计。
- [x] T017 [TEST] 运行现有P04测试并记录旧M1/M2/V2/V3 callable保护基线。

**Gate P1**: source-of-truth一致；输入和schema可消费；旧版本基线可验证；无未知字段被写入强规则。

## Phase 2: 基础类型与配置

**Goal**: 建立隔离版本域模型、配置和稳定工具，不实现具体构图。

- [x] T018 [DEV] 新建 `segment_first_types.py`，定义Segment/Junction/Access/Carrier/Road/Node/Movement数据类和值域。
- [x] T019 [TEST] 新建 `test_segment_first_contract.py`，覆盖枚举、状态组合和非法终态。
- [x] T020 [DEV] 新建 `segment_first_config.py`，定义全部显式输入路径、图层、CRS、输出和参数。
- [x] T021 [TEST] 测试配置拒绝输入输出重叠、缺失必要路径、未知CRS和覆盖历史run。
- [x] T022 [DEV] 复用canonical ID、GeoPackage写出、hash和CRS通用能力；若无兼容接口，只在P04增加adapter。
- [x] T023 [TEST] 测试canonical ID对整数浮点字符串、非整数和业务字符串的稳定处理。
- [x] T024 [QA] 建立结构化reason code registry，hard/soft/quality原因不得混用。

**Gate P2**: 域对象和状态机单测通过；没有新入口；新文件均<100KB。

## Phase 3: Input adapters 与 Segment/Junction skeleton

**Goal**: 从正式上游产物生成完整业务skeleton。

- [x] T025 [DEV] 新建 `segment_first_inputs.py`，读取并规范化T01/SWSD/T07/T03/T04/full-RCSD/Patch输入。
- [x] T026 [TEST] 测试required/optional字段、schema alias、CRS转换和输入hash。
- [x] T027 [DEV] 新建 `segment_first_skeleton.py`，以T01 Segment为主键构造SegmentBuildUnit。
- [x] T028 [TEST] 测试pair_nodes顺序、junc_nodes、roads、sgrade、跨Patch membership和唯一Segment ID。
- [ ] T029 [DEV] 新建 `segment_first_junctions.py`，实现ordinary/complex/roundabout/auxiliary/retained来源适配。（当前已实现ordinary/complex/retained；本Case无roundabout独立样本，auxiliary以THROUGH access承接，未形成独立kind验证。）
- [ ] T030 [TEST] 测试T07>T03、T04 complex、T08 roundabout、full-RCSD verified和SWSD retained优先级。
- [x] T031 [TEST] 测试T07 review/fail1候选不能冒充accepted、T03/T04 relation成功不等于surface accepted。
- [x] T032 [DEV] 构造ENDPOINT/THROUGH SegmentAccess和JunctionSegmentRelation审计。
- [x] T033 [TEST] 测试junc_nodes/THROUGH保持同一Segment、前后access完整且不optional prune。
- [x] T034 [QA] 输出skeleton/audit GPKG并核对全部T01 Segment、Junction和关系数量守恒。

**Gate P3**: 100%范围内T01 Segment进入skeleton；Junction来源唯一可解释；无Road级顶层owner。

## Phase 4: Patch evidence assignment

**Goal**: 以Segment为语义容器聚合同版本强证据。

- [ ] T035 [DEV] 新建 `segment_first_evidence.py`，按Segment和Junction范围聚合跨Patch Road/Lane/LaneTopo/Boundary/RoadSurface。
- [ ] T036 [DEV] 复用现有Lane/Boundary输入质检但移除旧SWSD Road owner依赖。
- [x] T037 [TEST] 测试EvidenceObservation复合身份、Patch顺序无关和一个Lane不被静默复制到不相容Segment。
- [ ] T038 [TEST] 测试Lane宽度、单侧Boundary、道路面和未知枚举仅影响quality_state，不直接产生结构冲突。
- [x] T039 [DEV] 识别方向中心走廊、主/辅/侧向/局部carrier候选角色。
- [x] T040 [TEST] 覆盖普通两方向、不可分双向、非高速多主辅Road、单向Segment和局部Patch Road。
- [x] T041 [QA] 输出逐对象assignment/rejection/review和跨Patch证据统计，无silent drop。

**Gate P4**: 证据身份、质量与业务状态分层；所有usable证据有唯一或显式候选去向。

## Phase 5: RoadCarrierPlan

**Goal**: 在生成几何前确定每个Segment所需完整carrier集合和四态。

- [x] T042 [DEV] 新建 `segment_first_carriers.py`，生成required carrier roles和built/retained计划。
- [ ] T043 [TEST] 建立普通双向、双单向、一观测一推导、不可分共享、多主辅和单向真值表。（当前已覆盖双向原子接管、单向、局部和多member；“一观测一Surface/Boundary推导”尚未实现。）
- [x] T044 [TEST] 测试禁止新单向Road与原双向retained Road同时发布。
- [x] T045 [TEST] 测试hp_partial仅允许完整Road级built/retained组合，且全部方向/access覆盖。
- [x] T046 [DEV] 实现单Segment hard failure/fallback，不影响其它关联Segment。
- [x] T047 [TEST] 构造Junction单portal/同Segment关系失败，验证仅owner Segment和相关Movement回退；跨Segment被拒Movement不回退两侧Segment。
- [ ] T048 [DEV] 对T01未表达提前右转生成RealityChangeClue，不进入正式Segment。
- [ ] T049 [TEST] 验证无simple Road materialization时RealityChangeClue不能发布Segment。
- [x] T050 [QA] 输出逐Segment carrier plan、四态、replacement_scope和reason codes。

**Gate P5**: 每Segment计划唯一；无Road、方向重复、覆盖不完整均不能进入新carrier接管。

## Phase 6: Vector-native geometry

**Goal**: 生成不以SWSD纵向骨架为reference的完整高精Road。

- [ ] T051 [DEV] 新建 `segment_first_geometry.py`，从Lane/Boundary/Patch Road/RoadSurface派生稳定方向中心走廊。
- [x] T052 [TEST] 测试中心走廊不机械选择最左Lane、局部Lane增减不造成无意义摆动。
- [x] T053 [DEV] 生成hp_observed控制span并保留直接evidence。
- [x] T054 [TEST] 验证observed span具有真实控制证据且不由SWSD采样点伪造。
- [ ] T055 [DEV] 在道路域、切向、Boundary、隔离、相邻Road间距和access约束下生成hp_constrained_completion。
- [ ] T056 [TEST] 测试合法补齐、穿越hard barrier拒绝、跨foreign surface拒绝和接缝连续性。
- [x] T057 [TEST] 对built Road执行source coverage，确认`[0,length]`无缝且值域无`swsd_fallback`。
- [x] T058 [DEV] 完整保留无法构建的既有Road carrier，不把它拼入built Road。
- [x] T059 [TEST] 测试built/retained组合Node接头、方向覆盖和geometry lineage。
- [x] T060 [QA] 复算道路面覆盖、中心偏差、曲率跳变、长度膨胀、valid/simple和人工断裂候选。

**Gate P6**: built Road直接SWSD splice=0；所有几何有效且来源完整；失败转到完整carrier保留。

## Phase 7: Node、mainnode、RoadNextRoad 与 LaneTopo

**Goal**: 将完整carrier编译成正式RCSD物理图。

- [x] T061 [DEV] 新建 `segment_first_nodes.py`，实现Node继承、稳定新建和Junction mainnode统一。
- [x] T062 [TEST] 测试ID不受Patch顺序/并行顺序影响，同Junction mainnode一致，不同物理Node不强合并。
- [ ] T063 [DEV] 实例化普通平交、T04复杂内部Node、环岛和辅助Junction carrier。（旧ordinary“中心shared Node + 星形内部Road”实现已被后续业务审计否决并由Phase11替换；T04走显式物理pair，roundabout/独立auxiliary缺少本Case样本，故不把组合任务整体标完成。）
- [x] T064 [TEST] 测试ordinary默认物理全连接先实体化Node，错误mainnode聚合不全连接。
- [x] T065 [DEV] 新建 `segment_first_topology.py`，初版从方向正确的实际共享Node编译RoadNextRoad；Phase 11扩展为`actual_shared_node / ordinary_junction_semantic`分层编译。
- [x] T066 [TEST] 验证`actual_shared_node`型RoadNextRoad的shared node同时是source Road出口和target Road入口；ordinary语义型合同由Phase 11覆盖。
- [x] T067 [DEV] 投影LaneTopo到Road/Node/RoadNextRoad，生成PhysicalMovementAudit。
- [ ] T068 [TEST] 覆盖mapped/review/excluded/blocked、缺失非负证据、same-owner反向和局部connector。
- [ ] T069 [DEV] 同步消费Patch已有调头口/短连接；缺失时不生成。（已发布2条显式local connector；尚未建立调头/短连接细分类策略。）
- [x] T070 [TEST] 验证Patch已有局部Road被保留，未提供对象不会由邻近关系凭空创建。
- [x] T071 [QA] 核对junc_nodes、confirmed LaneTopo、Road/Node/RoadNextRoad数量和逐对象去向。

**Gate P7**: Node引用100%；actual shared Node型RoadNextRoad共享Node真实性100%；ordinary语义型RoadNextRoad同JunctionUnit/mainnode一致且无机械mainnode连接；LaneTopo去向100%；无junc_nodes静默丢失。

## Phase 8: Publication、independent QA 与 QGIS

**Goal**: 写出正式候选三图层和可独立验收的运行包。

- [x] T072 [DEV] 新建 `segment_first_outputs.py`，写出正式Road/Node/RoadNextRoad与审计/关系层。
- [x] T073 [TEST] 测试正式三图层schema、source/mainnode归属、CRS、GPKG回读和字段截断。
- [x] T074 [DEV] 新建 `segment_first_quality.py`，实现core gate和只读发布文件的independent QA。
- [ ] T075 [TEST] 对每个hard gate构造失败样本，验证Review不能绕过。
- [x] T076 [TEST] 验证soft review可以随passed carrier发布且逐对象可追溯。
- [x] T077 [DEV] 新建 `segment_first_qgis.py`，构建相对路径分组QGIS工程。
- [x] T078 [QA] PyQGIS独立回读工程，核对图层、CRS、数据源、默认可见和comparison role。
- [x] T079 [DEV] 新建 `segment_first_pipeline.py`，编排preflight→skeleton→evidence→carrier→geometry→topology→publish→QA→QGIS→finalize。
- [x] T080 [TEST] 测试finalizer缺任一必要证据或gate失败时不得写`passed`。
- [x] T081 [DEV] 在P04 `__init__.py`导出版本化Config/Result/callable，不改变旧导出行为。
- [x] T082 [TEST] 运行legacy regression，确认M1/M2/V2/V3 callable和输出合同不变。

**Gate P8**: 正式GPKG可读；independent QA通过；QGIS可读；旧版本无回归。

## Phase 9: 完整真实数据、人工审计与收口

**Goal**: 用端到端效果而非代码完成证明阶段目标。

- [x] T083 [DEV] 在当前完整测试范围执行参数化Segment-first run，记录run ID、输入hash和性能。
- [x] T084 [QA] 复算100% Segment四态、Road数、replacement_scope、strong-evidence未使用和hard violation。
- [x] T085 [QA] 审计普通十字/T型accepted surface/DriveZone支撑、portal/内部carrier和默认物理全连接；未支撑portal按单Segment回退。
- [ ] T086 [QA] 审计T04复杂分歧/合流内部Road/Node/RoadNextRoad。
- [ ] T087 [QA] 审计环岛、非高速主辅多Road和附属Junction THROUGH。
- [x] T088 [QA] 审计hp_full/hp_partial/swsd_retained/conflict_retained分层样本。
- [x] T089 [QA] 审计跨Patch Segment、Patch已有调头/短连接和RealityChangeClue。（本Case跨Patchbuilt Road为2、显式local connector为2；无RealityChangeClue触发样本。）
- [x] T090 [QA] 对比SWSD、完整RCSD、Patch Road、冻结P04和新结果的中心、平滑、断裂、路口接头。
- [ ] T091 [TEST] 以相同输入重复运行并扰动Patch读取顺序，比较归一化Road/Node/RoadNextRoad与ID。（两次完整run的正式/审计/关系28层已一致；loader稳定排序已覆盖，但尚未做外部注入乱序replay。）
- [x] T092 [QA] 执行CRS、拓扑、几何语义、审计追溯、性能和文件体量五类治理审计。
- [x] T093 [PROD] 输出业务报告，区分已改善、保留、软Review、范围外局部结构和未解决问题。
- [x] T094 [ARCH] 完成SpecKit cross-document analyze和source-of-truth最终一致性复核。
- [x] T095 [QA] 逐SC-001~SC-015建立证据矩阵，只有全部有权威证据时标记阶段完成。

**Gate P9 / Definition of Done**:

- 完整真实测试范围运行成功；
- 正式Road/Node/RoadNextRoad发布；
- 所有hard gate通过；
- soft review完整；
- QGIS机器回读和人工审计完成；
- 重复运行确定性通过；
- 旧版本、T01–T12、入口和code-size治理通过；
- SC-001~SC-015全部有直接证据。

## Phase 10: 闭域高精骨架收敛

**Goal**: 将已证明应有高精覆盖的闭域目标从回归样本升级为硬验收合同，并在不牺牲330个Segment完整发布的前提下收敛主干和正式提右。

- [ ] T096 [ARCH] 同步SpecKit与P04模块source-of-truth，明确T06只作闭域覆盖/锚定先验，不作owner和最终几何。
- [ ] T097 [TEST] 先写目标覆盖合同测试，覆盖严格闭域、开放边界、Step2可替换、Step3非必要和正式ADVANCE_RIGHT。
- [ ] T098 [DEV] 实现参数化TargetCoverageContract，发布逐Segment membership、目标类型、当前状态和reason。
- [ ] T099 [QA] 在1885118真实输入复算83核心+20提右；10个混合缺失Patch对象单列边界审计。
- [ ] T100 [DEV] 使用完整RCSD/T06关系只扩展Segment证据召回，最终built Road坐标仍100%来自Patch observed/constrained。
- [ ] T101 [DEV] 将目标主干完整性从逐SWSD member接管提升为Segment必要方向角色，允许非必要semantic carrier保留。
- [ ] T102 [TEST] 覆盖目标Segment双向/单向/多member主干组装、无SWSD坐标splice和非必要carrier保留。
- [ ] T103 [DEV] 审计并修正目标Segment交接fallback范围，跨SegmentMovement拒绝不得回退正确主干。
- [ ] T104 [TEST] 覆盖目标主干、正式提右、Access、LaneTopo和实际共享Node hard gate。
- [ ] T105 [QA] 完整真实范围复跑，验证83/83核心主干、20/20提右、330/330完整发布。
- [ ] T106 [QA] 生成QGIS目标/边界/达标/失败分层、逐Segment人工审计与新旧差异报告。
- [ ] T107 [TEST] 重复运行、Patch顺序、CRS、拓扑、几何、性能和code-size最终审计。

**Gate P10 / 当前Definition of Done**：SC-001~SC-016全部有直接证据；83核心主干和20正式提右均高精；目标必要角色 retained/conflict 为0；330范围完整；QGIS与人工逐Segment审计完成。

## Phase 11: SWSD原生分布式路口与方向主干链

**Goal**: 以原始SWSD/一张图RCSD两级路口结构替换中心星形实现，并把闭域目标从“角色名称出现”提升为端到端方向主干链。

- [x] T108 [ARCH] 同步P04模块级、最小项目级和SpecKit source-of-truth：ordinary分布式portal、语义RoadNextRoad、方向主干链和可追溯Road细分。
- [x] T109 [TEST] 先写ordinary四门户分布式Node、统一mainnode、无中心Node/星形Road和语义RoadNextRoad合同测试。
- [x] T110 [TEST] 覆盖T04 complex/聚合异常不得使用ordinary mainnode默认全连接，actual shared Node合同保持。
- [x] T111 [DEV] 将ordinary Junction realization改为portal支撑审计，不再生成中心Node或`JUNCTION_UNIT`星形Road。
- [x] T112 [DEV] 修改Node编译，保留分布式portal；仅同一真实物理门户极近端点共享nodeid，同JunctionUnit统一mainnodeid。
- [x] T113 [DEV] 分层编译RoadNextRoad，发布`actual_shared_node / ordinary_junction_semantic`证据及source/target Node/Junction lineage。
- [x] T114 [QA] 独立QA复算两类RoadNextRoad证据，hard fail无上下文mainnode机械连接、中心聚合Node和ordinary星形Road。
- [x] T115 [TEST] 先写方向主干链连续、断裂、分叉、终端Access错配和多Road合法细分测试。
- [x] T116 [DEV] 实现DirectionalTrunkChain审计与闭域目标hard gate，替换仅检查`main_*`角色出现的弱门禁。
- [x] T117 [DEV] 在Junction关系范围外的稳定纵向LaneGroup/Patch Road证据交接处细分Road；精确保持父Road几何并集，增量插入内部度2 Node，保留链顺序、Road-Lane/Patch lineage和稳定ID。
- [ ] T118 [QA] 在1885118完整真实范围复跑，验证330 Segment完整、103闭域目标、ordinary中心/星形对象为0和方向主干链端到端连续。（V46已验证330完整、ordinary星形Road为0、3个及以上Segment接入路口的built portal单点聚合由V35的10组降为0、严格目标86/103；剩余17个核心目标尚未完成。）
- [x] T119 [QA] 更新QGIS：SWSD/完整RCSD/Patch/新Road与Node对比、mainnode分组、两类RoadNextRoad、方向链和Road-LaneGroup关系。
- [ ] T120 [TEST] 执行重复运行、Patch顺序扰动、CRS、拓扑、几何、性能、旧版本和code-size最终审计。（V46已通过CRS、拓扑、几何、P04 212项回归、QGIS 42层回读和code-size；重复运行与外部Patch顺序扰动仍未完成。）
- [x] T121 [TEST] 覆盖Junction保护区拒绝、父Road几何并集不变、既有Node不重编译、内部Node度2和可选lineage字段空值语义。
- [x] T122 [DEV] 支持LaneTopo沿同一父Road细分part的实际RoadNextRoad链投影并发布`carrier_path_road_ids`。
- [x] T123 [QA] V20真实数据复算：46个accepted/40个Junction保护拒绝边界；431个语义骨架组与V12b等价；Segment级有向关系新增/丢失均为0；QGIS 38层回读和99.5954%道路域覆盖通过。

**Gate P11 / 当前Definition of Done**：SC-001~SC-018全部有直接证据；ordinary路口与SWSD/完整RCSD原生分布式结构一致；中心聚合Node和默认星形内部Road为0；闭域目标必要方向主干链端到端连续且可按LaneGroup追溯细分；330范围完整发布；QGIS与人工逐对象审计完成。

## Phase 12: SWSD完整拓扑合同与LaneGroup细粒度Road

**Goal**: 用原始SWSD定义完备的Segment Access和Junction Movement结构，同时允许高精Road按稳定LaneGroup交接细分，避免“几何高精但路口关系缺失”或“为了拓扑完整而回到SWSD几何”。

- [x] T124 [ARCH] 固化SWSD只作完整拓扑合同、不作built几何模板；输出Road与SWSD Road不要求一一对应。
- [x] T125 [TEST] 覆盖逐Segment Access方向合同，裸`mainnodeid`不得替代明确Junction lineage和accepted surface到达。
- [x] T126 [DEV] 实现ordinary进入Road×离开Road完整Movement审计及缺失hard gate。
- [x] T127 [DEV] 实现T04 complex的SWSD显式弱fallback，仅接受shared Node、member lineage和accepted surface三证俱全关系。
- [x] T128 [QA] V24真实数据复算831/831 Access、371/371 Junction、2181/2181 Movement；4个不受支撑portal只触发各自单Segment回退。
- [x] T129 [QA] 保持5个LaneGroup交接细分几何精确不变，QGIS增加SWSD Movement合同层并完成人工路口审计。
- [ ] T130 [QA] 继续收敛17个闭域核心目标；V46保持LaneTopo unresolved/Review为0，但闭域目标通过前不得宣布阶段完成。
- [x] T131 [DEV] 目标主干端点按accepted surface本体裁切，不再用额外1m缓冲推迟物理portal。
- [x] T132 [DEV] ordinary built方向portal与保留`semantic_carrier`中心Node分离；二者共享mainnodeid但不共享物理nodeid。
- [x] T133 [DEV] LaneTopo支持经过有限保留`semantic_carrier`的实际有向多Road链，并拒绝任意跨lineage可达。
- [x] T134 [QA] V46复跑：Road/Node/RoadNextRoad为876/1129/2494，built/retained为449/427，831/831 Access和371/371 Junction合同保持，独立QA通过。

**Gate P12 / 当前Definition of Done**：SC-001~SC-019全部有直接证据；SWSD Access/Movement完整拓扑合同100%保持；Road可按LaneGroup细分且不改变几何、Junction portal或Segment级连通关系；闭域目标和LaneTopo hard gate继续独立成立。

## Phase 13: accepted surface保护域与部分证据端点补全

**Goal**: 固化`accepted surface + junction_endpoint_buffer`的Road细分保护口径，并在不改变证据链选择和既有目标的前提下，用DriveZone受约束补全恢复部分资料缺失Segment。

- [x] T135 [ARCH] 固化Road细分保护区只由accepted JunctionUnit surface和正式`junction_endpoint_buffer`组成；relation搜索半径不得扩大保护区。
- [x] T136 [TEST] 覆盖补全距离不得反向改变候选路径排序、超过20m但满足观测覆盖率/DriveZone的端点补全、同member语义RoadNextRoad不得制造方向链分叉。
- [x] T137 [DEV] 将端点补全上限改为最小观测覆盖率允许的缺失比例，并保持候选路径选择仍使用原正式关系范围。
- [x] T138 [QA] V49真实复跑：目标87/103，较冻结V46新增`1921620_620559468`且旧目标丢失0；330/330 Segment、Access/Junction合同和独立QA保持通过。
- [x] T139 [QA] QGIS 43层真实回读，项目/图层CRS均为EPSG:32650；454条built Road道路面内长度99.481951%，overlay gate通过。
- [x] T140 [DEV] 输出SWSD方向Road路径合同及唯一/歧义审计；正式发布暂不消费路径角色。
- [x] T141 [DEV] 构建fallback后证据占用重协调固定点；只释放已fallback Segment独占且未发布的恢复证据，保留有效built carrier冲突，并在无目标回归后启用唯一SWSD方向路径角色。V54相对V49新增`1914979_506231207`、既有目标丢失0。
- [ ] T142 [QA] 继续收敛剩余15个核心目标；5个`Patch data insufficient`和`1882067_520668482` RealityChangeClue仍保留显式分类，不静默绕过当前103目标门禁。

**Gate P13 / 当前Definition of Done**：方案A保护域无歧义；fallback证据占用固定点和唯一SWSD方向路径发布已完成；V54相对V49目标单调新增1、丢失0；CRS、拓扑、几何、审计、独立QA和QGIS门禁全部通过。P04整体阶段仍需继续处理15个未达标目标，当前不得finalize。

## Phase 14: accepted endpoint surface短桥接与V57单调恢复

**Goal**: 对SWSD轴包含较长Junction内部几何的短Segment，用互不接触的accepted endpoint surface定义实际Road范围；只接受已认证的Patch access-surface候选，不放宽任意raw component。

- [x] T143 [TEST] 覆盖短观测不足SWSD轴60%但可完成到两个不同endpoint surface的双向原子恢复、未通过`recovery_eligible`拒绝、端点保护区相交拒绝。
- [x] T144 [DEV] 新建`segment_first_surface_bridge.py`承接surface-to-surface证据识别；carrier只保留恢复编排，不继续回填大文件职责。
- [x] T145 [QA] V56发现`51811143_506668044`两个端点保护区重叠约247.5㎡却被短线同时命中，触发SWSD方向合同回退；将重叠保护区设为硬拒绝并复跑V57。
- [x] T146 [QA] V57相对V54仅`600658673_608658375`由`swsd_retained`变为`hp_full`，旧88条目标丢失0，其余329条Segment终态不变；目标89/103。
- [x] T147 [QA] V57正式输出882 Road/1142 Node/2516 RoadNextRoad，831/831 Access、371/371 Junction Movement、LaneTopo unresolved 0、几何hard failure 0、independent QA 0 violation；QGIS主工程43层、完整业务审计工程46层、局部工程16层真实回读均为0 invalid，457条built Road的DriveZone覆盖99.433853%。
- [ ] T148 [QA] 继续处理剩余14个核心目标；当前`mandatory_target_high_precision_complete=false`，不得finalize。

**Gate P14 / 当前Definition of Done**：V57只恢复一个可区分端点保护区的真实短高精走廊；不改变其他Segment终态，不新增fallback、hard failure或Review。P04整体阶段仍有14个未达标目标，继续保持Active POC。

## Phase 15: 局部RoadSurface端点路由与V61单调恢复

**Goal**: 对双向高精主走廊已观测、但到accepted endpoint surface的直线completion离开道路域的Segment，使用局部RoadSurface受约束路径完成端点；不得改写无关Segment或把LaneTopo切分尾段发布为断裂主干。

- [x] T149 [TEST] 覆盖弯折RoadSurface可路由、道路域断开拒绝、超绕行拒绝、平滑后合法域覆盖和SWSD geometry source为0。
- [x] T150 [DEV] 新建`segment_first_surface_routing.py`，实现局部可见性最短路、顶点规模/绕行门禁和边界拐点内缩保护；直线completion仍保持优先。
- [x] T151 [TEST] 覆盖新路由引出的Movement切分尾段：仅当同父carrier有唯一片段贯穿两个endpoint surface时抑制，并保留Movement与tail suppression审计。
- [x] T152 [QA] V58首次恢复`508668645_608667653`但使`1881842_608667653`方向链断裂，按单调门禁否决；根因是端点面外切分尾段被继续发布。
- [x] T153 [QA] V61相对V57新增`508668645_608667653`、既有89条目标丢失0；其余329条Segment正式Road属性与WKB签名不变。目标90/103。
- [x] T154 [QA] V61输出883 Road/1146 Node/2518 RoadNextRoad，831/831 Access、371/371 Junction Movement、LaneTopo unresolved 0、几何hard failure 0、independent QA 0 violation；P04专项回归230 passed。
- [x] T155 [QA] PyQGIS主工程44层、局部工程13层均0 invalid且EPSG:32650；459条built Road原始DriveZone总体覆盖99.281357%，新增两条Road对正式`DriveZone+1m ∪ accepted surface+1m`覆盖100%，局部人工审计确认与Patch Lane/完整RCSD走廊一致。
- [ ] T156 [QA] 继续处理剩余13个核心目标；当前`mandatory_target_high_precision_complete=false`，不得finalize。

**Gate P15 / 当前Definition of Done**：局部RoadSurface路径只恢复一个具有双向高精观测和可解释端点道路域的Segment；正式Road变更限定为该Segment，既有目标零损失，拓扑、LaneTopo、几何、QGIS与人工审计通过。P04整体仍有13个未达标目标，继续保持Active POC。

## Phase 16: V61剩余13条原始证据复核

**Goal**: 证明哪些剩余目标是Node/编译问题，哪些是实际高精证据不足或hard conflict；不得为追求目标数继续放宽Phase15。

- [x] T157 [QA] 从V61逐Segment提取13条未达标目标，分类为5条Patch资料不足、1条RealityChangeClue、4条hard conflict、3条部分证据未闭合。
- [x] T158 [QA] 证明`1882067_1898182`只有南侧成员具备两条built Road，北侧183.437m成员无高精carrier，终点错配不是Node编译错误。
- [x] T159 [QA] 复核`1885108_608669457`双向观测投影覆盖0.295/0.413，均低于0.50最小门槛。
- [x] T160 [QA] 修正`30899951_30956454`旧诊断：双向观测投影覆盖0.910/0.765，但关键缺口直连DriveZone覆盖仅0.336/0.209，局部RoadSurface路由均失败。
- [x] T161 [QA] 生成14层剩余13条QGIS审计工程，EPSG:32650、invalid layer 0，并输出全局和`30899951_30956454`局部渲染。
- [x] T162 [PRODUCT/ARCH] 用户确认三层合同：103条Baseline不变；5条Patch资料不足和1条RealityChange退出DirectBuild硬分母；97条必须直接高精构建，4条hard conflict与3条部分证据未闭合仍在硬分母。

**Gate P16**：当前没有可由`accepted surface + junction_endpoint_buffer + local RoadSurface routing`继续安全补齐的Segment。下一次实现必须引入已确认的新业务分流或新增原始证据，不得通过继承SWSD坐标、跨道路域空洞直连或Review绕过hard gate。

## Phase 17: 三层目标合同与DirectBuild硬分母

**Goal**: 不改写103条历史Baseline、不改变全量发布的前提下，用外部可哈希确认清单将DirectBuild硬分母稳定为97，并显式发布6条例外与7条未完成硬目标。

- [x] T163 [ARCH] 同步P04模块级、最小项目级source-of-truth和SpecKit，固化`BaselineCohort / DirectBuildEligibility / PublishDisposition`三层合同。
- [x] T164 [TEST] 覆盖默认全量必建、外部例外清单、非Baseline/重复/无证据拒绝、Baseline与DirectBuild双分母及完整发布处置。
- [x] T165 [DEV] 新增独立`segment_first_target_disposition.py`，把确认清单纳入输入hash；现有构图代码只消费通用资格字段，不硬编码Case或Segment ID。
- [x] T166 [QA] V62真实复跑：Baseline 103、DirectBuild 97、实现90、未实现7；330/330 Segment完整发布，正式三图层与V61归一化属性/WKB完全一致，独立QA PASS。
- [x] T167 [QA] V63发布4条`hard_conflict`和3条`partial_evidence_unresolved`；459条built Road的DriveZone覆盖99.281357%并通过QGIS门禁，47层工程由真实PyQGIS回读为EPSG:32650、0 invalid、5类样式完整，人工目视审计完成。
- [ ] T168 [DEV/QA] 在不放宽hard gate且保持已有90条零回归的前提下，继续为7条DirectBuild硬目标引入专项冲突/部分证据策略；达到97/97前不得finalize。

**Gate P17 / 历史Definition of Done**：三层合同本身可重复计算并保持当时确认的103/97/6分类稳定，正式图层未因分类合同改变；该口径已被Phase 18用户确认的103/96/7合同替代，V63/V65仍保留为历史回归证据。

## Phase 18: 目视审计驱动的最佳版本迭代

**Goal**: 在不改变103条Baseline和330范围完整发布的前提下，使用新版外部清单固定6条Patch资料不足、1条RealityChange与96条DirectBuild硬目标；结合V65目视审计修正高精骨架、路口端点、部分证据和提前右转，最多连续迭代10轮并交付综合效果最佳的QGIS工程。

- [x] T169 [PRODUCT/ARCH] 用户确认`1885137_74295305`因没有独立Patch主走廊、唯一证据属于父Segment而重分类为`patch_data_insufficient`；合同更新为Baseline 103、Patch资料不足6、RealityChange 1、DirectBuildRequired 96。
- [x] T170 [TEST] 建立`621954521 / 7895886509995543 / 7860057501137708 / 517389206 / 627387389 / 15640676`逐对象回归合同，覆盖冗余Road、路口面内部尾段、路口端平滑、部分证据接管和提前右转端点连接。
- [x] T171 [DEV] 消除同Segment高精Road与保留SWSD Road的重叠发布；Segment Road进入accepted surface后停止，只有真实PhysicalMovement支持的面内Road可作为JunctionUnit carrier发布。
- [x] T172 [DEV] 对非硬目标Segment同样执行`hp_observed + constrained_completion`部分支持策略，补充路口端切线/曲率门禁和质量Review向正式Road传播；提前右转必须同时满足高精走廊与两端Junction连接。
- [x] T173 [QA] 以V65为起点执行V66–V70版本化端到端迭代；逐轮记录DirectBuild、6个目视样本、CRS、拓扑、LaneTopo、几何、性能和回归结果，选择V69并保留全部历史版本。V70只作确定性重放，不替代V69审计候选。
- [x] T174 [QA] 最佳版本QGIS工程显式加入T07人工审核路口面、Patch原始`Intersection`、T03锚定面、T04分歧合流锚定面及P04最终JunctionUnit；真实PyQGIS回读52层0 invalid，built Road道路面overlay为99.829608%并通过门禁。

**Gate P18 / 当前Definition of Done**：外部清单稳定复算103/96/7；96条DirectBuild必要方向主干链100%高精；330范围完整发布；6个目视样本逐对象通过或有不绕过hard gate的明确审计处置；正式Road/Node/RoadNextRoad、LaneTopo、路口端点和平滑性全部通过；最佳QGIS工程包含五类路口面对比且0 invalid layer。

## Phase 19: Road端点严格入面与V75最佳候选

**Goal**: Road端点至少延伸进入选定原始路口面；端点物理选面按T07人工accepted优先、T03/T04 accepted次选，且不让T07覆盖T04 complex拓扑语义。最多完成10轮后停止，以hard gate、LaneTopo、几何和人工可解释性选择最佳版本。

- [x] T175 [PRODUCT/ARCH] 固化端点选面优先级和严格`surface.contains(Node)`合同；`junction_endpoint_buffer`只用于检索、保护和生成面内目标。
- [x] T176 [TEST] 覆盖T07端点面与T04 topology解耦、边界点拒绝、旁侧THROUGH拒绝、精确T01 retained lineage细分和局部平滑补齐；P04专项回归253 passed。
- [x] T177 [DEV] 端点按观测切向或局部RoadSurface平滑进入面内；补齐仍只发布为`hp_constrained_completion`，不拼接SWSD坐标。
- [x] T178 [DEV] 有accepted polygon的THROUGH只在Road实际穿面时切分；只有`swsd_retained`点且同一T01 Segment正式THROUGH lineage唯一时，允许不移动Road几何的最近投影细分。
- [x] T179 [QA] 执行V71–V75版本化端到端迭代并停止；V75实现accepted端点面外数量0、LaneTopo unresolved 0、几何hard 0和独立QA 0 violation。
- [x] T180 [QA] V75 QGIS真实回读53层、EPSG:32650、0 invalid；470条built Road道路域overlay为99.463819%，并完成`1898312`、`7860057501137708`、`517389206/627387389`、`15640676`和LaneTopo retained-through chain人工审计。

**Gate P19 / 当前Definition of Done**：端点严格入面、路口面优先级、LaneTopo、几何、拓扑、独立QA和QGIS门禁均通过。DirectBuild仍为86/96，10条硬目标未完成，因此V75仅作为当前最佳人工审计候选，P04整体继续保持Active POC，不得finalize。

## Phase 20: 主干物理交接、局部平滑与显式LaneTopo关系

**Goal**: 针对V75人工审计发现的主干Road断裂、路口端局部扭曲和无证据关系问题，在不改变冻结Segment/Junction骨架、470条built Road及86/96 DirectBuild事实的前提下，最多迭代10轮，交付综合效果最佳的人工审视工程。

- [x] T181 [PRODUCT/ARCH] 固化“路段主干必须共享实际Node、mainnode只作lineage、无证据反向/U-turn不发布、retained/ADVANCE_RIGHT显式关系必须命中原始LaneTopo”的业务合同。
- [x] T182 [TEST] 新增物理handoff、端点固定平滑、反向关系排除、retained显式证据和ADVANCE_RIGHT跨lineage证据回归；P04专项回归258 passed。
- [x] T183 [DEV] 在独立`segment_first_physical_handoff.py`实现受限主干handoff和Hermite局部正则化，不向已超体量的pipeline/nodes回填职责。
- [x] T184 [DEV] 重构RoadNextRoad关系来源：ordinary方向兼容默认关系、retained显式LaneTopo、正式ADVANCE_RIGHT显式LaneTopo和complex显式关系分别编译、审计与QA。
- [x] T185 [QA] 执行V76 Iteration 1–6并停止，选择Iteration 6：Road/Node/RoadNextRoad 887/1134/1933，built/retained 470/417，LaneTopo unresolved 0，Junction contract failure 0，独立QA 0 violation。
- [x] T186 [QA] 构建57层人工重点审视QGIS工程；470条built Road道路域覆盖97.319384%并通过overlay门禁，重点5条Road及端点Node、19条相关RoadNextRoad和27条显式LaneTopo关系置顶。

**Gate P20 / 当前Definition of Done**：本轮主干物理交接、局部平滑、LaneTopo去向、Junction合同、独立QA和QGIS工程均通过；全流程性能较V75增加17.4%，需作为后续优化项。DirectBuild仍为86/96且两项core gate失败，故Iteration 6只是当前最佳人工审计候选，P04保持Active POC，不得finalize。

## Phase 21: P04参数化内网执行入口

**Goal**: 在不复制业务算法、不硬编码内网路径和不自动finalize的前提下，为Segment-first生成提供唯一正式内网执行脚本；Patch按目录传入，其余业务输入均按文件路径传入。

- [x] T187 [PRODUCT/ARCH] 用户确认方案A，授权以唯一repo script替代原“无正式入口”合同，并同步模块级source-of-truth、SpecKit和入口注册表。
- [x] T188 [TEST] 新增显式参数映射、Patch目录前检、默认完成状态和可选core gate非零退出合同测试。
- [x] T189 [DEV] 新增`scripts/p04_run_segment_first_innernet.py`，只构造`SegmentFirstConfig`并调用`run_segment_first_road_direct(...)`。
- [x] T190 [QA] 使用Case 1885118本地真实文件路径通过新入口完成端到端运行：438个manifest文件、330 Segment、887/1134/1933 Road/Node/RoadNextRoad、独立QA 0 violation、QGIS 52层0 invalid且EPSG:32650；忽略`run_id`后正式三图层与V76 Iteration 6逐要素一致。
- [x] T191 [QA] P04专项回归261 passed；`--help`、compileall、入口数量/登记一致性、文件体量和`git diff --check`通过。

**Gate P21 / Definition of Done**：Patch以唯一目录参数输入，其余业务输入均为显式文件参数；无硬编码路径；新入口真实运行可定位；原输入未修改；入口登记、模块合同、SpecKit和体量审计一致；不把P04现有业务gate失败误报为脚本执行失败或阶段完成。

## Dependencies & Execution Order

```text
P1 source/input
  → P2 types/config
  → P3 skeleton
  → P4 evidence
  → P5 carrier plan
  → P6 geometry
  → P7 topology
  → P8 publish/QA/QGIS
  → P9 real-data acceptance
```

- P3前不得实现carrier算法。
- P5完成前不得先生成最终Road。
- P8 independent QA完成前不得宣布技术passed。
- P9人工审计与证据矩阵完成前不得宣布阶段目标完成。

## Parallel Opportunities

- 同一Phase中标记不同职责文件的`[TEST]`可与对应设计准备并行，但测试必须先失败再实现。
- QGIS工程实现可在正式输出schema稳定后与independent QA并行。
- 真实数据不同场景审计可并行，但必须消费同一冻结run。
- source-of-truth和实现不可并行漂移：任何业务合同变化必须先回到SpecKit和模块文档。
