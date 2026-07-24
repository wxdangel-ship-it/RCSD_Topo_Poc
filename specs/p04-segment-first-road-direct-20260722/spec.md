# Feature Specification: P04 Segment-first Road 直出端到端里程碑

**Feature Branch**: `codex/p04-road-direct-poc-20260720`
**Created**: 2026-07-22
**Status**: Approved for implementation
**Input**: 用户确认的 P04/P05 统一本体、P04 业务澄清、阶段目标与验收标准；治理授权采用方案 A。

## 1. 目标与边界

本变更在当前 SWSD/T01 Junction—Segment 功能结构未变化的前提下，以 T01 Segment 为构图、实例化、回退和审计原子，使用 Patch 同版本 Road/Lane/LaneTopo/LaneBoundary/RoadSurface 等高精证据，生成数据规格兼容的 P04 RCSD 候选 `Road / Node / RoadNextRoad`。

本变更保持 P04 为 `Active POC / 成果模块`：

- 不修改 T01–T12 的 source-of-truth、公开接口、入口和既有产物；
- 不接入 T10，不替代 relation-first 正式主链，不宣称生产正式化；
- 保留 M1/M2、冻结 Directional Road V2、High-Precision Road V3 的代码和实证为只读历史基线；
- 新能力使用独立 Segment-first 版本化 callable、状态空间、输出包和 QA；
- 不重新实现点云/轨迹感知，不由神经网络直接决定最终 RoadGraph。

本阶段新增 1885118 闭域高精骨架收敛合同：冻结 T06 Step2 `replacement_ready + hard_filter_passed` 只作为“应当具备高精覆盖”的验收先验，不作为 Road owner 或最终几何真值。对当前六 Patch，核心目标由“可替换 Segment 且两个端点终端 Road 的 Patch membership 均非空并完全属于六 Patch”计算；正式 `ADVANCE_RIGHT Segment` 按同一闭域条件独立纳入。目标集合必须由输入实时计算并发布审计，不允许硬编码对象 ID。

## User Scenarios & Testing

### User Story 1 - 以 Segment 发布完整 RCSD carrier (Priority: P1)

作为 Road 直出成果使用者，我希望每个范围内 T01 Segment 都能发布一套完整、可解释的 Road carrier；高精构建失败只影响该 Segment，不造成关联 Junction 或其它 Segment 组回退。

**Why this priority**: 这是从 Road-owner V3 迁移到统一本体的核心价值，也是完整 RC–SD 一体化输出的前提。

**Independent Test**: 在完整测试范围加载 T01 `segment.gpkg`，逐 Segment 核对最终 carrier、发布状态、Road数量、端点 access、`junc_nodes` 和 fallback lineage。

**Acceptance Scenarios**:

1. **Given** 一个具有完整 Patch 高精证据的 T01 Segment，**When** 执行 Segment-first 构建，**Then** 所有必要 carrier 使用新 Road发布，Segment状态为 `hp_full`。
2. **Given** 一个只有部分方向或部分完整 carrier具备高精证据的 Segment，**When** 执行构建，**Then** 可高精构建的完整 Road被替换，其余完整 Road被保留，Segment状态为 `hp_partial`，且没有方向重复。
3. **Given** 一个完全无可用 Patch证据的 Segment，**When** 执行构建，**Then** 原 SWSD carrier完整保留，状态为 `swsd_retained`。
4. **Given** 一个存在可信结构冲突或无法形成完整 carrier集合的 Segment，**When** 执行构建，**Then** 该 Segment保留 SWSD carrier并标记 `conflict_retained`，其它 Segment不回退。
5. **Given** 任一发布 Segment，**When** 检查其 Road集合，**Then** 至少存在一条独立 Road，不存在无 Road Segment。

---

### User Story 2 - 用 Patch 强证据生成平滑高精 Road (Priority: P1)

作为高精地图审计人员，我希望有证据的 Road几何由 Patch原生证据决定，不再以 SWSD折线作为纵向参考骨架，也不在同一条高精 Road中拼接 SWSD坐标。

**Why this priority**: 当前 V3 偏 SWSD、扭曲、断裂和局部结构召回不足的根因是 Road对象与高精几何仍受 SWSD Road reference控制。

**Independent Test**: 对每条新建 Road复算 geometry source、中心走廊偏差、道路面覆盖、平滑性和 observed/constrained 接缝，并与 SWSD、完整 RCSD、Patch Road、冻结成果比较。

**Acceptance Scenarios**:

1. **Given** 一个方向具有连续 Lane/LaneBoundary/RoadSurface证据，**When** 生成 Road，**Then** Road使用 `hp_observed` 与必要的 `hp_constrained_completion`，不存在 SWSD顶点直接拼接。
2. **Given** 一个方向存在局部资料缺口但两侧高精约束充分，**When** 补齐缺口，**Then** 补齐结果受观测切向、道路面、Boundary、隔离和 SegmentAccess约束，并标记为 `hp_constrained_completion`。
3. **Given** 只有一个方向被观测、另一方向可由 RoadSurface/Boundary可靠推导，**When** 构建普通双向物理道路，**Then** 允许发布两条单方向 Road，推导方向保留约束来源和软 Review。
4. **Given** 上下行高精物理走廊可区分，**When** 发布 Road，**Then** 发布两条连续的单方向主干链；每条链允许按LaneGroup、物理Node、`junc_nodes`、分流合流和证据边界细分为多条Road。
5. **Given** 道路面存在但上下行中心走廊不可可靠区分，**When** 发布 Road，**Then** 优先发布一条双向共享 Road。
6. **Given** 非高速主辅路被 T01定义为同一 Segment，**When** Patch证据支持多条物理走廊，**Then** 允许该 Segment拥有超过两条 Road。

---

### User Story 3 - 复用上游 Junction 事实并正确编译 Node (Priority: P1)

作为拓扑使用者，我希望 P04直接消费 T07/T03/T04/T08 的正式路口成果，在不重新实现上游路口算法的前提下生成一致 Node/mainnode和 RoadNextRoad。

**Why this priority**: SWSD Node精度不足、分歧合流误差可超过 100m；固定距离搜索和重新推断会重复制造接边错误。

**Independent Test**: 按普通路口、T04复杂路口、环岛、附属 Junction分层核对 surface来源、Node分组、mainnode、实际共享 Node和 RoadNextRoad。

**Acceptance Scenarios**:

1. **Given** T07 accepted surface，**When** 构建普通十字/T型 JunctionUnit，**Then** T07 surface独立作为高精物理边界并优先于冲突的 T03 surface。
2. **Given** T07缺失且 T03 accepted，**When** 构建普通 JunctionUnit，**Then** 使用 T03 accepted surface。
3. **Given** T04 accepted复杂分歧/合流 surface，**When** 构建 JunctionUnit，**Then** 以 T04正式业务结果确定范围和内部物理连接，不使用固定距离搜索。
4. **Given** T08/T01已将环岛定义为 Junction，**When** 构建，**Then** 环岛整体保持 JunctionUnit，内部 circulation Road不改写为新 Segment。
5. **Given** T03/T04缺失，**When** 存在锚定成功的完整 RCSD Junction carrier，**Then** 允许其作为候选并由 Patch强证据验证；验证失败则保留 SWSD Junction表达。
6. **Given** 同一 JunctionUnit 内多个 Node，**When** 发布 Node，**Then** 所有 Node共享同一 `mainnodeid`并保留分布式物理位置；Segment内部和复杂路口RoadNextRoad使用实际共享`nodeid`或显式物理关系。
7. **Given** 正确分类的非复杂平交路口且无物理负证据，**When** 编译内部拓扑，**Then** 保留各Segment Road高精portal，不生成中心聚合Node或星形JunctionUnit内部Road；方向兼容的进入—离开Road按同一JunctionUnit/mainnode编译默认PhysicalMovement，并记录两端物理Node lineage。Restriction/Laneinfo合法性不在本变更中判断。
8. **Given** 上下层道路被错误聚合到同一 mainnode，**When** 输入审计发现该情况，**Then** 作为上游聚合异常进入 Review/fallback，不把它当合法 JunctionUnit全连接。
9. **Given** 同一Segment有多条正式Road到达同一Junction，**When** 验证SegmentAccess，**Then** 每条Road都必须完成自身交接，不能由同Segment其它Road代替。
10. **Given** 某ordinary portal缺少accepted surface和DriveZone支撑，**When** Junction carrier hard gate失败，**Then** 只保留该portal的owner Segment，其它相邻Segment继续构建。

---

### User Story 4 - 保持 LaneTopo、局部结构与跨 Patch一致 (Priority: P1)

作为 RCSD RoadGraph 使用者，我希望 LaneTopo、Patch已有调头口/短连接、真实 `junc_nodes` 和跨 Patch Segment都能在最终 Road/Node拓扑中得到可追溯表达。

**Why this priority**: 既有 V3只显式处理跨 owner Movement，导致同 owner反向关系、调头口和局部短 carrier静默缺失。

**Independent Test**: 对全部可用 LaneTopo、T01 `junc_nodes`、跨 Patch Segment和 Patch已有局部 Road逐对象核对输出去向。

**Acceptance Scenarios**:

1. **Given** 一条可用 LaneTopo，**When** 构建完成，**Then** 它映射到正式 Road/Node/RoadNextRoad、进入明确软 Review，或以输入质量原因显式排除，去向可追溯率为 100%。
2. **Given** LaneTopo缺失，**When** 评估物理可达，**Then** 不把缺失解释为禁止通行或道路不存在。
3. **Given** T01 Segment包含真实 `junc_nodes/THROUGH`，**When** 构建 carrier，**Then** 业务 Segment不拆分，允许由 JunctionUnit前后多条 Segment Road和中间 Junction carrier贯通。
4. **Given** Patch Road已经包含调头口或短连接且同版本证据支持，**When** 构建，**Then** 同步保留对应局部 Road/Node/PhysicalMovement；Patch中缺失时不主动推断。
5. **Given** T01没有普通提前右转 Segment但 Patch证据发现提右，**When** 处理当前范围，**Then** 只发布 RealityChangeClue；必须先生成简易可发布 Road，之后才能形成临时 `ADVANCE_RIGHT Segment` 并二次标准化。
6. **Given** 一个 Segment横跨多个 Patch，**When** 构建，**Then** 先聚合全部 Patch证据再统一生成，不在 Patch边界切断 Road，且 ID不受 Patch读取顺序影响。
7. **Given** 一条跨Segment LaneTopo物理关系被证据拒绝，**When** 投影Movement，**Then** 显式排除该Movement，不因此回退两侧Segment；同Segment内部关系被拒且破坏carrier连续性时只回退该Segment。

---

### User Story 5 - 发布数据规格兼容成果与可复核证据 (Priority: P2)

作为验收人员，我希望正式 POC候选成果只包含数据规格约定的 Road、Node、RoadNextRoad，并通过关系表、QGIS和机器报告解释所有构图决定。

**Why this priority**: 只有端到端正式形态和完整审计同时存在，才能区分“代码运行成功”“技术自洽”和“业务效果可接受”。

**Independent Test**: 从发布后的 GPKG重新读取三类正式图层和审计包，独立复算 schema、CRS、拓扑、几何来源、LaneTopo守恒、QGIS数据源和运行 provenance。

**Acceptance Scenarios**:

1. **Given** 一次成功运行，**When** 检查正式成果，**Then** 只将 Road、Node、RoadNextRoad标记为正式 P04 RCSD候选图层。
2. **Given** 新建 Road，**When** 检查属性，**Then** `source`符合 RCSD数据规格，保留 `segment_id/source_patch_ids` 或可由审计关系恢复，并通过独立 Road-Lane关系表关联证据。
3. **Given** 新建 Node，**When** 检查 ID和 mainnode，**Then** 可继承的身份被继承，不能继承的按 RCSD ID规范稳定生成，同一 JunctionUnit `mainnodeid`一致。
4. **Given** 任一软质量问题，**When** 发布成果，**Then** 可以带 Review发布；任一 hard gate失败不得被 Review绕过。
5. **Given** QGIS工程，**When** 打开，**Then** 能显式比较 SWSD、完整 RCSD、Patch Road/Lane/Boundary/RoadSurface、既有 P04成果和新成果，并按 carrier状态、Junction来源、geometry source和 Review定位对象。

### Edge Cases

- 原 SWSD仅有一条双向 Road，而 Patch只支持一个方向时，不得同时发布新单向 Road和原双向 Road；能推导两个方向则发布两条，否则保留原双向 carrier。
- 一个 Segment的部分 Road可重建、部分 Road需保留时，必须保证完整方向覆盖且无空间/方向重复。
- T07与 T03同时 accepted但 surface冲突时，T07优先，T03差异进入审计。
- T07 surface为 `review_required` 而非 accepted 时，不得冒充 accepted高精边界。
- T04 rejected或无合法 surface时，不得发布 `junction_geometry_unresolved`；使用已确认 fallback链。
- 非复杂路口默认物理全连接只适用于正确 mainnode聚合，不得由 mainnode相等机械推导。
- ordinary不得把空间分离的portal折叠为中值Node，也不得生成中心点或星形内部Road；只有同一真实物理门户的极近端点可以稳定聚类。
- 跨Segment被拒Movement是显式排除，不是两个Segment的联合fallback触发器。
- Segment内调头口/短连接只在 Patch Road已包含且强证据验证时同步；缺失恢复留给后续策略。
- `junc_nodes` 只有显式、可审计 `detached/exempt` 证据时才允许不进入最终拓扑。
- 资料异常只降低 evidence可用性，不能直接产生业务结构冲突。
- 任一 source CRS未知、坐标转换失败或跨 CRS隐式计算都必须 hard fail。

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 以 T01 `segment.gpkg` 的 `id/sgrade/pair_nodes/junc_nodes/roads` 建立 SegmentBuildUnit；不得以 SWSD Road作为顶层构图 owner。
- **FR-002**: 系统 MUST 复用 T01正式 Segment集合和 Junction关系，不在当前主路径中自行增删、合并或拆分 T01 Segment。
- **FR-003**: 系统 MUST 聚合同一 Segment跨全部 Patch的证据后再生成 Road。
- **FR-004**: 系统 MUST 为每个范围内 Segment发布 `hp_full/hp_partial/swsd_retained/conflict_retained` 之一。
- **FR-005**: 系统 MUST 保证每个发布 Segment至少拥有一条独立 Road。
- **FR-006**: 系统 MUST 区分 `segment_publishable`、`carrier_takeover_ready` 与 `replacement_scope=all/subset/none`。
- **FR-007**: 系统 MUST 支持一个 Segment拥有一条双向Road链、两条单方向主干链或多条主辅方向链；每条链可以由多条细粒度Road组成。
- **FR-008**: 系统 MUST 在高精方向走廊可区分时优先生成两条连续单方向主干链，在不可区分时允许双向共享Road链。
- **FR-009**: 系统 MUST 允许一个观测方向和一个受 RoadSurface/Boundary约束推导方向共同形成两条 Road，并保留软 Review。
- **FR-010**: 新建 Road MUST 只由 `hp_observed` 与 `hp_constrained_completion` 组成，不得直接拼接 SWSD坐标。
- **FR-011**: SWSD几何 MAY 作为低权重语义走廊、方向和 access参考，但不得作为新建 Road局部顶点来源。
- **FR-012**: 完整缺失的 Road carrier MAY 整条保留；同一条 Road不得混合新高精坐标与原 SWSD坐标。
- **FR-013**: 系统 MUST 检测新建、保留 carrier间的方向重复、覆盖重复和不一致 Node拓扑。
- **FR-014**: 系统 MUST 按优先级消费 Junction surface：普通路口 T07 accepted优先，T07缺失时 T03 accepted；复杂分歧/合流使用 T04；环岛使用 T08/T01。
- **FR-015**: T07与 T03 accepted冲突时系统 MUST 使用 T07，并发布差异审计。
- **FR-016**: T03/T04缺失时系统 MAY 使用锚定成功的完整 RCSD Junction carrier候选，但 MUST 由 Patch强证据验证；否则保留 SWSD Junction表达。
- **FR-017**: 系统 MUST 将 Segment Road边界放在 JunctionUnit的稳定高精SegmentAccess/Portal，不使用 SWSD Node固定距离搜索；每条正式Segment Road必须独立实现其适用Access。
- **FR-018**: 同一 JunctionUnit内所有 Node MUST 共享相同 `mainnodeid`。
- **FR-019**: RoadNextRoad MUST 分层编译：Segment内部连续性和复杂路口使用实际共享`nodeid`或显式物理关系；ordinary语义关系必须由同一正确分类JunctionUnit内方向兼容的进入—离开Road组合生成，并记录source/target物理Node、junction_group_id和mainnodeid。不得只比较mainnode字符串。
- **FR-020**: 正确分类的非复杂平交 Junction MUST 以分布式高精portal Node、统一mainnodeid和ordinary语义RoadNextRoad表达默认PhysicalMovement；不得生成中心聚合Node或星形JunctionUnit内部Road，T09合法性不在本变更处理。
- **FR-021**: 系统 MUST 按 T04内部物理关系处理复杂分歧/合流，不得对 T04 accepted/rejected业务结果另起算法。
- **FR-022**: 系统 MUST 保持环岛整体为 JunctionUnit。
- **FR-023**: `junc_nodes/THROUGH` MUST 保持同一业务 Segment，并由前后 Segment Road和中间 Junction carrier表达。
- **FR-024**: 单 Segment交接或其ordinary portal carrier失败 MUST 只阻断该 Segment及其相关新 Movement，其他 Segment可继续发布；跨Segment被拒Movement MUST 显式excluded且不得同时回退两侧Segment。
- **FR-025**: 系统 MUST 对全部可用 LaneTopo提供正式映射、软 Review或显式排除去向。
- **FR-026**: LaneTopo缺失 MUST NOT 被解释为禁止通行或不存在。
- **FR-027**: Patch已有调头口/短连接 MAY 在强证据验证后同步构建；Patch缺失时本变更 MUST NOT 主动补建。
- **FR-028**: T01未表达的普通提前右转 MUST 先作为 RealityChangeClue；无简易可发布 Road时不得发布正式 Segment。
- **FR-029**: 新 Road MUST 不继承 SWSD Road ID；可继承的 RCSD/Patch身份按数据规格处理，不能继承时稳定生成。
- **FR-030**: Node ID MUST 能继承则继承，不能继承时按 RCSD ID规范稳定生成；跨 Patch顺序和重复运行不变。
- **FR-031**: 正式 POC候选图层 MUST 为 Road、Node、RoadNextRoad；`source`属于 Road，`mainnodeid`属于 Node。
- **FR-032**: Segment/JunctionUnit/PhysicalMovement/evidence/review MUST 作为内部或按需审计层，不得误列为正式 RCSD图层。
- **FR-033**: 系统 MUST 输出 Road-Lane、Segment-Road、Junction-Node等关系审计，使 `segment_id/source_patch_ids/evidence_ids` 可追溯。
- **FR-034**: 所有 hard gate MUST 阻断新 carrier接管；软质量问题 MAY 带 Review发布。
- **FR-035**: 系统 MUST 发布输入、参数、hash、CRS、转换、环境、版本、耗时与逐阶段性能。
- **FR-036**: 系统 MUST 使用显式米制分析 CRS，不得隐式混算 EPSG:4979/3857或其它 CRS。
- **FR-037**: 系统 MUST 提供独立发布后 QA，从发布 GPKG重新读取并复算业务完整性、几何来源、Node/RoadNextRoad、LaneTopo和跨 Patch门禁。
- **FR-038**: 系统 MUST 构建相对路径 QGIS工程，显式展示输入、基线、新结果、关系与 Review。
- **FR-039**: 系统 MUST 保持旧 M1/M2/V2/V3 callable、输出名、测试和基线不变。
- **FR-040**: 系统 MUST 仅新增模块内研究 callable，不新增 repo CLI、root script或入口登记项。
- **FR-041**: 双向Segment的`main_forward/main_reverse`和单向Segment的`main_oneway` MUST 分别形成从一个终端JunctionAccess到另一个终端JunctionAccess的连续方向主干链；链内Road MUST 共享实际Node且不得断裂、分叉或形成重复平行主干。对accepted Junction，两个终端物理Node MUST 分别落入对应surface或正式端点缓冲，仅有正确`junction_group_id/mainnodeid`不得判定为到达。
- **FR-042**: 系统 MAY 在LaneGroup/Patch Road证据归属、物理Node、`junc_nodes`、分流合流或证据边界处细分Road；每个细分Road MUST 通过关系层恢复Lane/LaneGroup/Patch lineage和细分原因。
- **FR-043**: 在“有SWSD且功能结构未变化”场景中，系统 MUST 将原始SWSD作为完整拓扑合同而非built几何模板：逐Segment保持全部Access进出方向，逐ordinary Junction保持全部方向兼容的进入—离开Movement；输出Road可更细，但归一化方向链不得丢失原拓扑。
- **FR-044**: T04 complex不得使用ordinary全连接。Patch/T04内部carrier不足时，原始SWSD关系只有在真实共享Node、两侧member lineage匹配且portal均位于T04 accepted surface时，才 MAY 以`complex_junction_swsd_explicit`保守实例化；不得由裸`mainnodeid`或邻近关系生成。
- **FR-045**: 闭域验收 MUST 把输入确定的`BaselineCohort`、外部确认的`DirectBuildEligibility`和最终`PublishDisposition`分层；Baseline集合不得被后续例外清单缩小。
- **FR-046**: `DirectBuildEligibility` MUST 默认`direct_build_required`；只有逐对象包含原因、证据、审批状态并纳入输入hash的外部清单才可标记`patch_data_insufficient/reality_change`。代码 MUST NOT 硬编码Case或Segment ID。
- **FR-047**: `hard_conflict/partial_evidence_unresolved` MUST 保留在DirectBuild硬分母；退出硬分母的对象仍 MUST 完整发布Road/Node/RoadNextRoad并进入Baseline审计。
- **FR-048**: Summary、Report、独立QA和QGIS MUST 同时披露Baseline实现、DirectBuild实现、完整发布及全部例外对象，不得只报告缩小后的DirectBuild分母。

### Responsibility Views

#### 产品视角

- 保证完整 Segment覆盖、四态发布、正式三图层和可人工理解的差异说明。
- 不以高精替换率代替正确性；强证据充分但未使用必须逐对象解释。

#### 架构视角

- 保持 Junction/Segment/PhysicalMovement 与 Road/Node carrier分层。
- 保持 T01–T12只读依赖、P04版本隔离和 RealityChangeClue扩展点。

#### 研发视角

- 新代码按 input/skeleton/junction/evidence/carrier/geometry/node/topology/output/quality职责拆分。
- 单个源码/脚本文件不得达到 100KB；写入前必须执行体量自检。

#### 测试视角

- 单元测试覆盖状态机、方向 carrier组合、geometry source、Junction优先级、ID稳定性和 RoadNextRoad编译。
- 集成测试覆盖完整真实测试范围、跨 Patch聚合、旧版本不回归和重复运行确定性。

#### QA视角

- 独立进程只读发布 GPKG复算硬门禁。
- QGIS按路口/Segment/证据状态分层人工审计；soft Review与hard failure严格分开。

### Key Entities

- **SegmentBuildUnit**: T01 Segment在 P04构图中的唯一顶层工作单元。
- **JunctionUnitCandidate**: 由 T07/T03/T04/T08/RCSD/SWSD来源形成的物理 Junction候选及优先级决策。
- **RoadCarrierPlan**: 一个 Segment发布所需的完整 Road carrier集合、方向结构和替换范围。
- **RoadBuildCandidate**: 完整新建或完整保留的一条 Road；新建 Road只含 observed/constrained来源。
- **SegmentAccess**: Segment Road与 JunctionUnit之间的业务进出位置及物理 Portal实现。
- **NodeBuildCandidate**: 可继承或稳定新建的 RCSD Node及 mainnode分组。
- **PhysicalMovementAudit**: LaneTopo到 Road/Node/RoadNextRoad的物理可达映射和审计，不等于 T09合法性。
- **RealityChangeClue**: 先验之外现实结构线索；在简易 Road materialized之前不能成为正式 Segment。

## Success Criteria

### Measurable Outcomes

- **SC-001**: 范围内 T01 Segment覆盖率为 100%，每个 Segment均有唯一四态和至少一条独立 Road。
- **SC-002**: 强证据充分且 hard gate通过但无原因 `swsd_retained` 的 Segment数量为 0。
- **SC-003**: 新建 Road直接拼接 SWSD坐标的区间数量为 0。
- **SC-004**: 新建/保留 carrier方向重复、双向 Road与单向 Road重叠发布数量为 0。
- **SC-005**: Road几何非空、有效、方向明确；零长度、异常自交和不可解释断裂数量为 0。
- **SC-006**: 所有Road的snode/enode均存在；actual shared Node型RoadNextRoad共享Node真实性100%；ordinary语义型RoadNextRoad的source/target Node同属一个正确分类JunctionUnit且mainnode一致率100%；无上下文mainnode机械连接数量为0。
- **SC-007**: 同一JunctionUnit内Node的mainnode一致率为100%；ordinary中心聚合Node和星形JunctionUnit内部Road数量均为0；portal支撑完整，未支撑portal在单Segment回退后遗留数量为0；`junction_geometry_unresolved`正式发布数量为0。
- **SC-008**: T01真实 `junc_nodes` 静默丢失数量为 0，全部正式Segment Road的适用Access交接实现率为100%。
- **SC-009**: 可用 LaneTopo去向可追溯率为 100%，confirmed LaneTopo静默丢失数量为 0。
- **SC-010**: Patch边界引入的 Road断裂数量为 0；同一 Segment不因 Patch输入顺序产生不同 Road/Node ID。
- **SC-011**: 同输入、参数、版本重复运行的归一化 Road/Node/RoadNextRoad属性与几何一致。
- **SC-012**: 发布后独立 QA全部 hard gate通过；soft Review逐对象列出且不伪装为 hard pass。
- **SC-013**: QGIS工程可独立打开，所有数据源相对路径有效，正式三图层、至少四类输入/基线及全部 hard violation层可见。
- **SC-014**: 完整真实测试范围完成机器审计和按类型人工审计，报告明确区分已改善、保留、软 Review和未在范围内恢复的局部结构。
- **SC-015**: 输入hash、参数、CRS、运行环境、代码版本和阶段性能可定位率为 100%。
- **SC-016**: Case 1885118 的`BaselineCohort`稳定为83个核心Segment和20个正式`ADVANCE_RIGHT Segment`，合计103且永久保留；经已确认清单，6个`patch_data_insufficient`和1个`reality_change`退出DirectBuild硬分母，`DirectBuildRequired`为96。96个必要主干/提右必须100%高精且`swsd_retained/conflict_retained`为0；103条Baseline逐对象审计、330范围完整发布。旧冻结run只作回归基线。
- **SC-017**: 闭域目标的必要方向主干链端到端连续率为100%；链内Road实际共享Node、无断裂/分叉/重复平行主干，且两个终端物理Node分别落入T01声明两端的accepted Junction surface或正式端点缓冲；属性身份不能替代物理到达。
- **SC-018**: ordinary Junction中心聚合Node和默认星形内部Road均为0；QGIS逐路口可见分布式portal、统一mainnode和ordinary语义RoadNextRoad。
- **SC-019**: 原始SWSD逐Segment Access方向合同保持率100%，逐Junction Movement合同保持率100%；ordinary expected/actual组合完全一致，所有complex SWSD显式fallback关系均具备shared Node、member lineage和accepted surface证据。

## 2. 明确非目标

- 无 SWSD场景的从零构图。
- 已确认现实功能结构变化的全面自动重构。
- Patch中缺失的调头口、Segment内部短连接和可通车豁口主动恢复。
- Restriction/Laneinfo、RoadSplit正式语义和完整通行合法性。
- 修改或重跑 T01/T03/T04/T07/T08内部算法以迎合 P04。
- 把 P04候选直接接入 T10或发布为生产 F-RCSD。
- 为提高替换率而放宽 hard gate、静默 snap或伪造 Node/RoadNextRoad。
