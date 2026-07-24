# Feature Specification: P04 SWSD-first Road 直出 POC

**Feature Branch**: `codex/p04-road-direct-poc-20260720`
**Created**: 2026-07-20
**Status**: Directional Road V2 Independently Validated - 第一、第二里程碑及方向级 V2 的无证据不外推、全物理节点闭合、Road 平滑和 Movement 切向接入已在 1885118 通过独立发布后终验
**Input**: 用户要求启动 P04，基于 `1885118/Patch_Test` 理解 Patch Vector 表与字段价值，并以 `SWSD Road.patch_id` 建立 Patch 级关系，探索 SWSD-first Road 直出。

## User Scenarios & Testing

### User Story 1 - 建立可信的 Patch Vector 数据理解基线 (Priority: P1)

作为 Road 直出方案设计者，我需要知道所有有实际数据的 Vector 表表达什么、哪些字段可作为证据、哪些字段只是旧 Road 分组的派生产物，避免把局部样本或旧 RCSD 结果误当生产真值。

**Why this priority**: P04 的任何强规则都依赖输入语义；字段含义不清时直接编码会违反项目字段治理和 no-silent-fix 边界。

**Independent Test**: 对 6 个 Patch 的 70 类 GeoJSON 做全量盘点，能够逐项说明 29 个非空表的数量、结构含义、价值字段、CRS/几何形态和已知限制，并明确 41 个空表不进入当前输入契约。

**Acceptance Scenarios**:

1. **Given** 6 个 Patch Vector 目录，**When** 完成结构与引用分析，**Then** 29 个非空表全部被登记且没有遗漏。
2. **Given** 未提供枚举字典的字段，**When** 形成业务说明，**Then** 只记录观测值和值分布，不固化枚举含义。
3. **Given** 旧 `Road/RoadNextRoad`，**When** 分析其来源，**Then** 能用 Lane 分组和 LaneTopo 证明其派生关系或明确反例。

---

### User Story 2 - 从 SWSD 预生成语义骨架 (Priority: P1)

作为 P04 使用者，我需要先获得由 SWSD Road/Node、方向、路口和通行规则构成的稳定语义骨架，再让 Patch Vector 证据去拟合骨架，而不是从零散 Lane 拼出目标 RoadGraph。

**Why this priority**: 这是 P04 与现有 RCSD 替换融合链的本质区别，也是消除 Patch 接边猜测的前提。

**Independent Test**: 输入 prepared SWSD Road/Node 后，可以为每条目标有向道路和语义路口建立唯一骨架单元，并将逗号分隔的 `patch_id` 解析为 Patch membership 集合。

**Acceptance Scenarios**:

1. **Given** 单 Patch `patch_id`，**When** 建立骨架，**Then** 该 Patch 仅作为该 SWSD Road 的证据提供方。
2. **Given** 双 Patch `patch_id`，**When** 建立骨架，**Then** 两个 Patch 共同指向同一 SWSD Road 单元，不创建两个待端点接边的目标 Road。
3. **Given** `segment_id` 为空，**When** 需要 Segment 语义，**Then** 复用 T01 构段语义，不把空字段当已有 Segment。

---

### User Story 3 - 以高精证据实例化完整四态 RoadGraph (Priority: P2)

作为质量负责人，我需要 571 条 SWSD Road 全部进入结果，并依据沿 Road 的可信 Lane 几何覆盖分为 `hp_supported / partial_hp_supported / sd_only / conflict_retained`；原始 Lane/LaneTopo/Boundary 质量异常必须进入独立质检层，不能直接制造 Road 冲突。

**Why this priority**: 最终成果需要同时保持 SD 语义完整性和高精 LaneTopo 一致性，不能用其中一层静默覆盖另一层。

**Independent Test**: 对每条 SWSD Road 生成可复算的支持/缺口里程区间和一种发布状态，验证四态数量守恒、区间长度守恒、几何来源可解释以及输入质检与 Road 冲突解耦。

**Acceptance Scenarios**:

1. **Given** 一条可信 Lane，**When** 形成 Road 支持区间，**Then** 原始 Lane 身份保持不变，每个连续 LaneEvidenceSegment 只能投影到唯一 SWSD Road owner；同一原始 Lane 可以按 SWSD 语义节点切成多个相邻 Road 证据片段，来源 Lane/Patch、源里程、目标里程和区间合并原因均可追溯。
2. **Given** Road 仅部分里程有可信 Lane 几何，**When** 发布 Road 候选，**Then** 状态为 `partial_hp_supported`，支持区间使用高精拟合，缺口区间保留 SWSD 参考几何并显式标识来源。
3. **Given** Road 没有可用高精证据，**When** 发布 Road 候选，**Then** 状态为 `sd_only`，Road 仍完整存在。
4. **Given** Lane 宽度、Boundary-gap、方向复核或 Boundary 资料不足，**When** 发布输入质检，**Then** 只形成 `evidence_quality_state/reason_codes`，不得自动将 Road 标记为 `conflict_retained`。
5. **Given** 经过输入质检后仍可信的高精证据与 SWSD Road 结构矛盾，**When** 无法形成自洽拟合，**Then** Road 以 `conflict_retained` 保留 SWSD 语义并输出冲突证据，不得 silent fix。

---

### User Story 4 - 对现有融合链做独立 POC 对照 (Priority: P3)

作为项目负责人，我需要 P04 与 `T08 -> T01 -> T07/T03/T04/T05 -> T06 -> T09` 并行验证，不修改主链正式输入输出，也不把 POC 结论直接升级为生产规则。

**Independent Test**: P04 没有修改现有模块接口、CLI 或脚本；P04 结果可以与现有 RCSD/T06/T12 结果比较，但不成为其输入真值。

---

### User Story 5 - 生成方向自洽且位于 LaneGroup 中心的 Road V2 (Priority: P1)

作为 Road 直出成果检查者，我需要非纯 SWSD 的双向道路按两个单方向 RCSD Road 发布，并让每个方向的几何由同方向 LaneGroup 的稳定中心 Lane/LaneBoundary 决定，避免对向 Lane 混合、逐站换线和回拉 SWSD 中心门户造成扭曲。

**Independent Test**: 对 1885118 重新运行方向级 V2，能够证明非 `sd_only` 的 SWSD 双向父 Road 不再以 `direction=1` 单对象发布；正反向证据不混用；每个高精方向 Road 只有一个可追溯中心锚点；几何闭合到自身方向级 Portal/Arm，并通过平滑性、长度膨胀、LaneGroup 包络和 QGIS A/B 对比门禁。

**Acceptance Scenarios**:

1. **Given** `direction in {0,1}` 的 SWSD 父 Road 至少一侧存在 `usable` Lane 证据，**When** 发布 Directional Road V2，**Then** 生成 forward/reverse 两个单方向子 Road；缺证据的一侧显式为 `sd_only`，不得伪造高精几何。
2. **Given** 同一父 Road 同时存在正反向 Lane，**When** 选择几何证据，**Then** 每个方向子 Road 只消费同向证据，且 `review/insufficient/excluded` 不得成为硬几何锚点。
3. **Given** 一个方向 LaneGroup 含奇数条 Lane，**When** 选择中心基准，**Then** 优先使用覆盖连续、曲率稳定且横向排序居中的单一 Lane；偶数 Lane 优先使用中间两 Lane 的共享 LaneBoundary，无法可靠使用 Boundary 时退回稳定中心 Lane。
4. **Given** 临时拓宽、变窄或局部 Lane 缺失，**When** 生成 Road 几何，**Then** 不得逐站无审计切换锚点；中心锚点只作为形态基准，输出需平滑并保持在有证据站点的 LaneGroup 横向包络内。
5. **Given** Directional Road 已生成，**When** 构建拓扑，**Then** 首尾点闭合到自身 DirectionalPortal/Arm；SWSD 父 Road/Junction 仅作为语义 lineage，不再要求高精方向 Road 回到父 SWSD 中心门户。
6. **Given** 现有 M2、旧 Patch Road 和输入 RCSD，**When** 执行 QA，**Then** QGIS 工程可同时对比旧扭曲结果、V2 方向 Road、中心锚点、LaneGroup、SWSD、旧 Patch Road 和输入 RCSD，机器审计输出方向拆分、平滑度、长度膨胀、包络和 Portal 闭合指标。
7. **Given** `partial_hp_supported` 方向 Road 存在无证据里程或端点，**When** 生成几何，**Then** 无证据站点保持 SWSD 几何且横移为 0；高精拟合不得跨缺口全局插值，SD—高精过渡必须位于有证据范围并显式标识。
8. **Given** 跨 Road LaneTopo 投影到同一物理 Node，**When** 生成最终 RoadGraph，**Then** 来源 Road 终点与目标 Road 起点协调为同一 Portal 坐标，物理 movement 端点间距和 movement—Road Portal 偏差均为 0。
9. **Given** LaneTopo 连接位于同一语义路口但不同物理 Node，**When** 生成最终 RoadGraph，**Then** 保留各 Road 的方向 Portal，并发布连接两 Portal 的显式 movement；方向复核、语义不连通和方向 Road 端点冲突不得 silent fix，必须原样进入 review 层。
10. **Given** 同一双向父 Road 的正反向稳定中心锚点中位间距低于 `max(0.5 m, 0.5 × 较窄侧 Lane 宽度)`，**When** 发布 V2，**Then** 不得用人工横移制造两个方向中心线；该父 Road回退为纯 SWSD 表达，相关 Lane 仅保留 LaneTopo lineage 与塌缩审计。
11. **Given** `partial_hp_supported` Road 的最长无证据区间达到 100 m，**When** 发布与检查，**Then** Road 仍完整存在，`high_precision_claim_scope=supported_intervals_only` 且 `sd_gap_risk_state=long_sd_gap_review`，QGIS 必须区分 HP、过渡和 SD gap。

## Edge Cases

- 同一 SWSD Road 的 `patch_id` 包含当前未提供的相邻 Patch 时，必须保留开放证据边界，不能宣称区域闭合。
- Patch LaneTopo 只在 Patch 内闭合时，不能据此推断跨 Patch movement 不存在。
- `Lane.Width` 为统一默认值、Boundary ID 为空时，不能直接以字段宽度判定伪 Lane。
- 通过 Lane 左右垂线匹配 LaneBoundary 推导宽度时，只有方向/走廊相容且双侧覆盖充分的匹配才能形成有效宽度；单侧缺失不得补造。
- `TrafficLight/TrafficSign` 为三维竖直面时，不能因二维投影退化而直接判为坏几何。
- `DriveZone_fix` 与原始 `DriveZone` 业务语义等价，均表示道路面；`DivStripZone_fix` 与原始 `DivStripZone` 业务语义等价，均表示路面导流带而非 Patch 分区。raw/fix 属于同一证据族，默认消费修正版、保留 raw lineage，禁止重复计权。
- `ReferenceLane` 与 `LaneNextLane` 不一致时，两者都保留为证据并输出冲突/补充原因。

## Requirements

### Functional Requirements

- **FR-001**: P04 MUST 以 `Active POC / 成果模块` 登记，且不得替代现有正式主链。
- **FR-002**: Phase 0 MUST 完整盘点 6 个 Patch 的 29 个非空 Vector 表及价值字段。
- **FR-003**: P04 MUST 将 `SWSD Road.patch_id` 按逗号拆分、去空、去重后解释为 Patch membership 集合。
- **FR-004**: P04 MUST 以 SWSD Road/Node/路口/方向建立目标语义骨架；Vector Road/LaneGroup 不得决定目标道路对象数量和接边关系。SWSD restriction/Laneinfo 与 RoadSplit 在第二里程碑不参与 Road 几何强规则。
- **FR-005**: `Lane`、`LaneNextLane`、`LaneBoundary`、`ReferenceLane`、道路面和硬隔离证据 MUST 保留来源与决策 lineage。
- **FR-006**: 当前 `Road/RoadNextRoad/IntersectionGoInRoad/IntersectionGoOutRoad` MUST 作为派生或比较证据，不得作为 P04 目标拓扑真值。
- **FR-007**: 未经项目/模块契约或用户确认的枚举字段 MUST NOT 进入强规则。
- **FR-008**: 第一里程碑 accepted Lane MUST 保留唯一 primary Road owner 作为整 Lane 诊断；第二里程碑每个 accepted LaneEvidenceSegment MUST 映射到且仅映射到一个目标 RoadSection，原始 Lane 可以跨多个相邻 SWSD Road，但不得覆盖或重写源 Lane 身份。
- **FR-009**: 每条 accepted LaneNextLane MUST 投影为 Road 内连续、Road movement 或显式异常。
- **FR-010**: ReferenceLane MUST 与 LaneNextLane 分层保存；`FlowNum` 只作为轨迹聚合强度弱证据参与候选排序和审计，不代表精确车流量、合法通行规则或单独接受门禁。
- **FR-011**: 第二里程碑 POC RoadGraph MUST 完整保留范围内 SWSD Road；完全高精证据支持为 `hp_supported`，仅部分里程支持为 `partial_hp_supported`，完全没有可用高精证据为 `sd_only`，经过输入质检后仍可信的高精证据与 SWSD 结构冲突时为 `conflict_retained`。只有 `hp_supported` Road 可声明全里程高精支持，`partial_hp_supported` 只能对已发布支持区间声明高精支持。
- **FR-012**: P04 MUST 输出输入、参数、CRS、运行环境、候选、接受、拒绝、冲突和耗时审计。
- **FR-013**: 空间计算 MUST 使用显式米制 CRS；源 WGS84 三维几何和 EPSG:3857 `*_fix` 不得隐式混算。
- **FR-014**: P04 MUST 验证拓扑一致性、几何可解释性、审计可追溯性和可测量性能，不允许 silent fix。
- **FR-015**: 本轮 MUST NOT 新增 repo CLI、root script 或长期执行入口。
- **FR-016**: P04 MUST 使用 Lane 局部垂线到左右最近且方向/走廊相容 LaneBoundary 的距离之和推导 `inferred_lane_width_m`，并记录双侧 Boundary、采样覆盖率和宽度稳定性；当前原始 `Lane.Width` 不得替代该结果。
- **FR-017**: P04 MUST 最大化复用 T00-T12 的正式产物、公开契约和兼容通用能力，但 MUST NOT 修改既有模块的 V1 输入输出、CLI 或业务语义；契约无法无损承载 Road 直出时，MUST 新建显式版本化的 P04 适配层或对应 V2。
- **FR-018**: P04 MUST 将原始 Lane/LaneTopo/LaneBoundary 质量异常发布到独立输入质检层。窄 Lane、宽度/Boundary-gap、宽度不稳定、Boundary 资料不足、方向复核和跨 Road 语义节点异常不得直接映射为 Road `conflict_retained`。
- **FR-019**: 第二里程碑 MUST 为每条 Road 发布归一化支持/缺口区间，满足区间不重叠、全里程覆盖和长度守恒；每个几何片段 MUST 标识 `hp_fitted / swsd_retained / conflict_retained` 来源。
- **FR-020**: 第二里程碑 MUST NOT 消费 SWSD restriction/Laneinfo 或 RoadSplit 形成 Road 几何、四态或 movement 合法性结论；这些能力留待后续里程碑。
- **FR-021**: Directional Road V2 MUST 把有 `usable` 高精证据的 `direction in {0,1}` SWSD 父 Road 发布为 forward/reverse 两个单方向子 Road；完全无 `usable` 证据的父 Road保持纯 `sd_only` SWSD 表达。
- **FR-022**: 每个方向子 Road MUST 只消费与其行驶方向一致的 LaneEvidenceSegment；方向支持状态、支持区间、来源 Lane 和几何审计 MUST 在方向层独立计算。
- **FR-023**: `usable` 证据 MAY 成为硬几何锚点；`review` 仅可用于对照/排序审计，`insufficient/excluded` MUST NOT 拉动 Road 几何。该规则不得把 QA 异常直接提升为 `conflict_retained`。
- **FR-024**: Directional Road V2 MUST 为每个有高精支持的方向 LaneGroup 选择唯一稳定中心锚点。奇数 Lane 优先中间 Lane；偶数 Lane 优先中间两 Lane 的共享 Boundary；Boundary 不可靠时选择覆盖、中心性和曲率稳定性最优的中心 Lane。锚点切换必须显式审计，当前 V2 默认不允许无语义依据切换。
- **FR-025**: Directional Road 几何 MUST 以中心锚点为形态基准并执行平滑/包络约束，不得逐站复制 Lane 中位数；有证据站点必须位于方向 LaneGroup 横向包络内，长度膨胀、相邻横移跳变和高精支持片段横向振荡必须进入机器门禁。包含 SD—高精转换的全 Road 横移总变差只作诊断，不得替代高精片段平滑门禁。
- **FR-026**: Directional Road 首尾 MUST 闭合到自身 DirectionalPortal/Arm；父 SWSD Road/Junction 提供语义 lineage。自身 Portal 闭合只证明单 Road 内部自洽，跨 Road 闭合必须另由 DirectionalMovement 门禁证明。
- **FR-027**: V2 子 Road 几何按行驶方向定向并使用单方向编码；reverse 子 Road必须交换父 Road 的起终点语义并反转几何。输入 RCSD 只作方向/形态对照，不作为目标真值。
- **FR-028**: P04 MUST 保留 M2 callable/产物不变，并以独立 Directional Road V2 callable、输出目录和版本字段承载本轮不兼容语义；不得修改 T00-T12 V1、repo CLI 或 root script。
- **FR-029**: `partial_hp_supported` Directional Road 的高精拟合 MUST 仅作用于证据覆盖站点；所有无证据站点和无证据端点 MUST 精确保留 SWSD 几何，不得使用跨缺口插值或端点外推伪造高精支持。
- **FR-030**: P04 MUST 将可唯一映射到方向 Road 的跨 owner LaneTopo 守恒投影为 confirmed DirectionalMovement；同一物理 Node 的 confirmed movement MUST 协调 Road 端点共点，同一语义路口的不同物理 Node MUST 以显式连接几何表达。
- **FR-031**: 方向复核、语义不连通、方向语义端点冲突或映射不唯一的 LaneTopo MUST 保留为 review evidence，不得参与端点协调或被静默丢弃。当前投影不消费 SWSD restriction/Laneinfo，因而不声明 restriction 意义上的 movement 合法性。
- **FR-032**: 输入 RCSD 精度对照 MUST 允许一个 Directional Road 对应多段同向 RCSD，以走廊采样距离和 2 m/5 m 覆盖率审计；最佳单条 RCSD 匹配只作 lineage，不得作为精度或通过门禁的唯一依据。
- **FR-033**: Directional Road V2 最终终态 MUST 由独立进程只读取已发布 Road/Movement/RoadGraph GPKG 后重新计算；独立 QA 缺失、不可读或 `gate_pass=false` 时，finalizer MUST NOT 发布 `terminal_status=passed`。
- **FR-034**: 独立 QA MUST 覆盖所有发布 Road 共享的多端物理节点，不得只检查 confirmed LaneTopo 子集；1885118 单 Case POC 门禁为节点端点最大间距 `0.05 m`。
- **FR-035**: 支持 Road MUST 使用统一纵向站距，并在独立 QA 中按 5 m 站距与方向对齐后的父 SWSD 比较局部转角增量；当前单 Case POC 上限为 `12°`。端点协调必须沿 Road 平滑传播，不得制造局部硬折返。
- **FR-036**: Movement MUST 按来源终点到目标起点定向，触及两侧 Portal，并在独立 QA 中满足 Portal 偏差 `0.05 m`、两侧接头夹角 `10°`；超限的证据几何必须显式 fallback 并记录来源。
- **FR-037**: Directional Road V2 MUST 在方向实例化前对同一父 Road 的正反向稳定中心锚点执行对称采样距离审计；中位间距低于 `max(0.5 m, 0.5 × 较窄侧 Lane 宽度)` 时，MUST 撤销相关 LaneEvidenceSegment 的硬几何资格并回退为 SWSD 父表达，不得构造横向偏移。原始 `evidence_quality_state` 必须保留，降级原因另写方向几何质量字段。
- **FR-038**: 塌缩降级 Lane MUST 以 `topology_only_review` 关联回退后的 `sd_parent`，确保跨 owner LaneTopo 输入仍可唯一追溯；该关联 MUST NOT 重新启用几何拟合，无法满足方向端点语义的关系继续保留为 review。
- **FR-039**: 每条 Directional Road MUST 发布 `high_precision_claim_scope` 和 `sd_gap_risk_state`。`partial_hp_supported` 只能对支持区间声明高精；最长 SD gap 达到当前 100 m POC 阈值时 MUST 进入 `long_sd_gap_review`，不得删除 Road或伪造高精。
- **FR-040**: 发布后独立 QA MUST 读取 LaneGroup 双向审计和几何来源分段，独立复算正反锚点/高精片段间距；塌缩候选仍存在 forward/reverse 发布对象，或非塌缩方向高精片段低于已发布宽度相对阈值时，终态 MUST 失败。

### Responsibility Views

| 视角 | 当前职责 |
|---|---|
| 产品 | 保证 571 个 SWSD 父 Road 语义完整，并将有证据的双向父 Road展开为两个单方向成果；明确方向级四态、局部高精声明和 POC/生产边界。 |
| 架构 | 定义父语义—方向子 Road、方向 LaneGroup、稳定中心锚点、方向 Portal、DirectionalMovement、四态与输入质检分层。 |
| 研发 | 复用 M1/M2 LaneEvidenceSegment，新增隔离的 Directional Road V2；不修改 M2 与 T00-T12 V1。 |
| 测试 | 覆盖方向拆分、正反证据隔离、稳定锚点、质量证据硬过滤、无证据不外推、平滑/包络、物理共点、复杂路口 movement、CRS 和错误输入。 |
| QA | 使用 1885118 真实数据、输入 RCSD 多段走廊对照、旧 Patch Road/M2 A/B、LaneTopo 守恒、结构化审计、QGIS 工程和自动 overlay 验证，不以目视通过替代机器检查。 |

### Key Entities

- **SWSDRoadSemanticUnit**: 目标有向道路语义单元，拥有 SWSD 身份、端点、方向和 Patch membership。
- **SWSDJunctionUnit**: SWSD 语义路口及其进入/退出 arm 和允许 movement。
- **VectorEvidence**: 带 `patch_id + object_type + source_id` 身份、几何、字段、来源和置信状态的 Patch 证据。
- **LaneHypothesis**: 对 Lane 是否属于机动车道路及目标 RoadSection 的候选判断。
- **RoadCandidate**: 由一个 SWSD 语义单元约束、由多个 Patch/Lane/道路面证据拟合的高精 Road 候选。
- **RoadSupportInterval**: Road 归一化里程上的连续支持或缺口区间，记录证据 Lane、覆盖率、几何来源和合并 lineage。
- **EvidenceQualityFlag**: 与 Road 支持状态分离的输入质量记录，用于承载宽度、Boundary、方向和 LaneTopo 异常。
- **MovementProjection**: Lane movement 到 RoadGraph movement 的可追溯投影结果。
- **DecisionAudit**: 接受、拒绝、资料不足和冲突的证据链。

## Success Criteria

### Measurable Outcomes

- **SC-001**: 1885118 六 Patch 中 29/29 个非空表均有数量、结构含义、价值字段和限制说明；41/41 个空表不进入当前输入契约。
- **SC-002**: 6 个 Patch 中 `RoadNextRoad` 与 `LaneNextLane` 按 `Lane.RoadId` 投影后的外部 Road 对达到 100% 集合一致。
- **SC-003**: 571 条相关 SWSD Road 的 Patch membership 可复现，其中 81 条为双 Patch，24 条连接当前提供的两个 Patch。
- **SC-004**: 所有当前确认的 Vector 外键引用都可审计；跨 Patch 缺失关系被表达为数据边界而不是断路事实。
- **SC-005**: 所有未确认字段在 spec、模块契约和任务中保持 `待确认/观测值`，不存在由样本反推的强枚举规则。
- **SC-006**: P04 模块文档、项目生命周期/盘点和 SpecKit 工件相互一致，且入口登记无新增。
- **SC-007**: 第二里程碑 RoadGraph 满足 `571 = hp_supported + partial_hp_supported + sd_only + conflict_retained`，未发布 Road 数为 0；每条 Road 支持/缺口区间完整覆盖 `[0, 1]` 且无重叠。
- **SC-008**: P04 实现与验证不产生任何既有 T00-T12 V1 行为变化；每项复用均能标明为直接调用、契约消费、只读对照或 V2 隔离。
- **SC-009**: 1885118 中已知输入质量问题全部进入独立 QA 明细；仅凭这些问题产生的 Road `conflict_retained` 数为 0。
- **SC-010**: 571 条 Road 候选均为有效非空 LineString/MultiLineString，几何片段来源可定位；QGIS 工程可同时对比 SWSD、旧 Road、支持区间和本轮 Road 几何。
- **SC-011**: M2 的 571 条 Road首尾点保持 SWSD 门户锚定；每条 Road恰有唯一 `s/e` 两个 Arm，无缺失/重复 Arm 或无效 Junction 引用，Road—Arm 门户最大偏差为 0。V2 另按 SC-015 闭合到自身 DirectionalPortal/Arm。
- **SC-012**: Directional Road V2 中非纯 `sd_only` 的双向 SWSD 父 Road没有 `direction in {0,1}` 的单对象发布；每个父 Road 的方向子对象数量和缺证据侧状态可审计，父语义对象仍为 571 且未发布数为 0。
- **SC-013**: 每个高精方向 Road 的硬锚点来源均为 `usable` Lane 或可追溯共享 LaneBoundary；正反向来源集合互不混用，未解释锚点切换数为 0。
- **SC-014**: V2 有证据站点全部落在对应方向 LaneGroup 横向包络内；相邻站横移跳变、长度膨胀与高精支持片段横向振荡均通过本轮 manifest 中记录的 POC 门禁。包含 SD—高精转换的全 Road 横移总变差只作诊断。
- **SC-015**: 每个 Directional Road 恰有两个自身 DirectionalPortal/Arm，Portal 与 Road 端点最大偏差为 0；reverse 子 Road几何方向、起终点和父语义映射一致。
- **SC-016**: QGIS V2 工程可相对路径回读，包含 M2 Road、V2 Directional Road、中心锚点、方向 LaneGroup、SWSD、旧 Patch Road和输入 RCSD；道路面 overlay、CRS 和图层完整性门禁均输出机器可读 PASS/FAIL。
- **SC-017**: 所有无证据站点和无证据端点相对 SWSD 横移均为 0；站点来源完整落入已登记值域，SD 缺口不再出现高精外推来源。
- **SC-018**: 所有 confirmed 同物理 Node movement 的来源 Road 终点—目标 Road 起点距离为 0；所有发布 movement 几何到两侧 Road Portal 的最大偏差为 0。
- **SC-019**: 跨 owner LaneTopo 输入满足 `confirmed + review = input`，confirmed link 聚合到 Road movement 后数量守恒，所有 review 原因和源 LaneTopo 身份可追溯。
- **SC-020**: QGIS 首组显式显示原始 SWSD、原始 RCSD、新结果三网；另有默认可见的物理节点 movement、复杂语义路口连接及三类 LaneTopo review 图层。
- **SC-021**: 独立 QA 对全部 393 个多端物理节点复核，违规为 0，最大端点间距为 0 m。
- **SC-022**: 独立 QA 对 339 条支持 Road 复核，局部转角增量违规为 0，最大值不超过 12°；对 278 个 Movement 复核，Portal/接头违规为 0，最大接头夹角不超过 10°。
- **SC-023**: 最终权威 run 的 core、独立发布后 QA、QGIS 构建、独立 PyQGIS 回读和道路面 overlay 均通过；任一失败的中间 run 不得提升为权威成果。
- **SC-024**: 1885118 的 50 个双向证据父 Road全部进入独立间距审计；4 个塌缩候选均回退为 SWSD 父表达，错误发布方向子 Road为 0，其余已发布双向高精片段间距违规为 0。
- **SC-025**: 42 条 `long_sd_gap_review` Road 与独立复算集合完全一致；QGIS 显式显示完整 HP/transition/SD 来源分段和长 gap 图层，长 gap 不被误表述为全里程高精或拓扑断裂。
- **SC-024**: QGIS 工程包含独立 Road 平滑、物理 Node 断裂、Movement 接头三个 QA 图层，并可从逐对象明细定位违规或证明违规集合为空。
