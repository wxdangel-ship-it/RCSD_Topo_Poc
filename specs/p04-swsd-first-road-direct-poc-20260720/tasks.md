# Tasks: P04 SWSD-first Road 直出 POC

**Input**: `spec.md`、`research.md`、`data-model.md`、`plan.md`、`contracts/poc-output-contract.md`

## Phase 1: P04 启动与数据理解（本轮）

- [x] T001 在 `docs/doc-governance/module-lifecycle.md`、`current-module-inventory.md` 和 `module-doc-status.csv` 登记 `p04_road_direct_generation`。
- [x] T002 建立 `modules/p04_road_direct_generation/` 标准模块文档面。
- [x] T003 在 `architecture/1885118-patch-vector-baseline.md` 登记 29 个非空表、价值字段、限制、CRS、引用关系和 SWSD overlap 统计。
- [x] T004 完成项目级 source-of-truth 的 P04 POC 边界同步，不修改正式主链顺序。
- [x] T005 验证文档无模板占位符、模块登记一致、入口 registry 无需变化。

## Phase 2: 可重复数据 Profiler

- [x] T006 [US1] 写入任何 `.py` 前先执行文件体量前置自检，并创建 `src/rcsd_topo_poc/modules/p04_road_direct_generation/` 小文件实现结构。
- [x] T007 [US1] 实现只读 Patch 表/字段/CRS/几何/引用 profiler，输出 input manifest 和 profile。
- [ ] T008 [US1] 为 29/41 表盘点、外键解析、关系空 geometry、三维竖直面和 Length 实测编写测试。
- [x] T009 [US1] 冻结 1885118 Phase 0 结构基线；对输入变化使用 manifest/hash 显式失败或新建基线，不覆盖当前结论。

## Phase 3: SWSD 语义骨架（第一里程碑）

- [x] T010 [US2] 复用共享字段解析，将 SWSD `id/snodeid/enodeid` 安全规范为 canonical ID。
- [x] T011 [US2] 实现 `patch_id` membership 集合解析与单/双 Patch 测试。
- [ ] T012 [US2] 复用 T01 已确认 Segment 语义构建 RoadSection/Junction/Arm/Movement，不复制 T01 私有算法。
- [x] T013 [US2] 对缺失相邻 Patch 发布开放边界审计。

## Phase 4: Vector Evidence Fitting（第一里程碑）

- [x] T014 [US3] 实现 Lane 局部垂线与左右方向/走廊相容 LaneBoundary 的空间关联，输出实测宽度、双侧覆盖率、宽度分位数和波动；枚举未知时不使用线型码做强过滤。
- [x] T015 [US3] 实现 Lane 到 SWSD corridor 的方向、覆盖、连续和 Patch ownership 候选指标。
- [x] T016 [US3] 将 `DriveZone_fix/DivStripZone_fix` 作为对应 raw 图层的同语义修正版消费，保留 raw 属性和修正 lineage，并验证没有 raw/fix 双重计权或把 DivStripZone 误作 Patch 分区。
- [ ] T017 [US3] 在确认 RoadSplit 语义后，将其加入软/硬分割证据层。
- [x] T018 [US3] 保留当前 Road/RoadNextRoad 作为 comparison channel，测试其不能覆盖目标 owner。

## Phase 5: Road 与 Movement 投影

- [x] T019 [US3] 实现 accepted Lane 唯一 Road owner 不变量。
- [ ] T020 [US3] 实现 LaneNextLane 到内部连续/Road movement/冲突的守恒投影。
- [ ] T021 [US3] 将 FlowNum 作为轨迹聚合强度弱证据实现 ReferenceLane 候选排序和审计；不得作为精确流量、合法 movement 或单独接受门禁。
- [ ] T022 [US3] 实现 SWSD restriction/Laneinfo 一致性检查，不在 P04 内重新定义字段语义。
- [ ] T023 [US3] 在后续 movement 里程碑发布完整 RoadGraph movement，将范围内 SWSD movement 分类并验证未发布数为 0。

## Phase 6: 测试、QA 与正式化决策

- [ ] T024 [US4] 建立 1885118 的拓扑守恒、几何覆盖、来源 lineage、CRS 和性能回归。
- [x] T025 [US4] 生成 QGIS 叠加材料，分开显示 SWSD 骨架、证据、candidate、accepted、conflict、LaneTopo 准备度和旧 Road 对照。
- [ ] T026 [US4] 与当前 T06/T12 结果只读比较，不把 POC 输出写入正式主链。
- [ ] T027 [US4] 基于多 Case 结果决定是否进入正式模块/主链设计，单 Case 不得直接升格。
- [ ] T028 [US4] 建立复用矩阵，逐项记录 T00-T12 能力属于直接调用、契约消费、只读对照或需 V2；任何不兼容能力只设计 P04 专用 V2/适配层，不修改 V1。

## Phase 7: 第二里程碑 Road 四态与几何实例化

- [x] T029 [US3] 将 `support_state` 冻结为 Road 发布层四态 `hp_supported / partial_hp_supported / sd_only / conflict_retained`，并在项目/模块源事实、SpecKit 和输出契约中同步。
- [x] T030 [US3] 将 Lane/LaneTopo/LaneBoundary 质量问题冻结为独立 `evidence_quality_state`，明确不得直接制造 Road `conflict_retained`。
- [x] T031 [US3] 基于 1885118 第一里程碑真实逐 Lane 结果分析 owner 可用证据、Lane 局部分段、Road 归一化里程覆盖、间隙、端部缺口和可解释结构冲突，形成候选参数与敏感性结果。
- [x] T032 [US3] 实现 RoadSupportInterval：可信 Lane 投影、区间合并、支持/缺口互补、来源 lineage 和长度守恒。
- [x] T033 [US3] 实现 Road 四态状态机；QA-only 异常不得触发 conflict，可信结构冲突必须显式保留且不可 silent fix。
- [x] T034 [US3] 实现 Road 混合几何实例化：支持区间采用高精 Lane 拟合，缺口/冲突区间保留 SWSD 参考几何，过渡与片段来源可审计。
- [x] T035 [US3] 发布完整 571 Road 候选与 RoadGraph；Road 数量、唯一 ID、有效几何、四态、区间守恒和 Road—Arm 门户闭合全部通过。
- [x] T036 [US4] 建立输入质量明细输出，复核 5/29/8/131/133 和 Patch `5417631180197930` 的 67 条 Boundary 资料不足样本均未直接转化为 Road conflict。
- [x] T037 [US4] 增加四态、区间、几何、QA 解耦、端点/Arm 拓扑和失败输入的自动化测试，并保证第一里程碑测试无回退。
- [x] T038 [US4] 对六 Patch 执行端到端运行，记录输入 hash、参数、环境、CRS、拓扑、几何、耗时和峰值内存。
- [x] T039 [US4] 生成相对路径 QGIS 工程，对比 SWSD、旧 Road/现有 RCSD、支持/缺口区间、本轮四态 Road 和独立 QA；执行 PyQGIS 回读和自动 overlay 门禁。
- [x] T040 [US4] 第二里程碑结果文档化，区分已证实的单 Case 事实、候选阈值和仍需多 Case/人工真值确认的生产口径。

## Dependencies & Gates

## Phase 8: Directional Road Geometry V2（本轮）

- [x] T041 [US5] 审计 M2 真实几何，冻结方向混合、低质量证据拉动、逐站候选切换和 SWSD 中心门户回拉四类根因及基线指标。
- [x] T042 [US5] 建立父 SWSD Road—DirectionalRoad 子对象模型；仅对存在 `usable` 证据的双向父 Road拆分 forward/reverse，纯 `sd_only` 保留父 SWSD 表达。
- [x] T043 [US5] 按 Lane 几何相对父 SWSD 的方向将 LaneEvidenceSegment 分入方向 LaneGroup，并在方向层重算支持区间与四态；`review/insufficient/excluded` 不得成为硬几何锚点。
- [x] T044 [US5] 实现稳定中心锚点选择：奇数 Lane 优先中心 Lane，偶数 Lane 优先中间共享 Boundary；结合覆盖、中心性和曲率稳定性选择唯一锚点并审计来源。
- [x] T045 [US5] 实现中心走廊拟合、平滑、最大横移步长、LaneGroup 包络和长度膨胀约束；不得强制回拉父 SWSD 中心门户，任何 fallback 必须显式记录。
- [x] T046 [US5] 构建 DirectionalPortal/DirectionalArm；reverse 子 Road反转几何并交换父起终点语义，方向 Road闭合到自身 Portal/Arm。
- [x] T047 [US5] 新增 Directional Road V2 研究 callable、独立输出契约和 M2 只读 lineage；不新增 repo CLI/root script，不改变 M2 或 T00-T12 V1。
- [x] T048 [US5] 增加方向拆分、证据隔离、稳定锚点、质量过滤、平滑/包络、长度膨胀、方向 Portal 和失败输入自动化测试。
- [x] T049 [US5] 对 1885118 六 Patch 执行端到端 V2，记录输入 hash、参数、CRS、拓扑、几何、M2 A/B、输入 RCSD 对照、耗时和峰值内存。
- [x] T050 [US5] 生成相对路径 QGIS V2 工程并执行 PyQGIS 回读和道路面 overlay；文档化已验证结果、POC 参数和待多 Case/人工真值确认项。

## Phase 9: Directional Road 连续性与 LaneTopo movement 修订

- [x] T051 [US5] 审计 V2 无证据站点/端点外推和跨 Road 物理断裂，保留旧权威 run 为只读基线。
- [x] T052 [US5] 将高精拟合限制在证据覆盖范围；无证据 gap/端点精确保留 SWSD，SD—高精转换来源显式审计。
- [x] T053 [US5] 将可唯一映射的跨 owner LaneTopo 投影到 Directional Road；同物理 Node movement 协调 Road 端点共点，复杂语义路口发布显式连接。
- [x] T054 [US5] 保留方向复核、语义不连通和方向 Road 端点冲突为 review evidence；restriction/Laneinfo movement 合法性仍不在本轮范围。
- [x] T055 [US4] 将输入 RCSD 对照升级为同向多段走廊采样审计，并在 QGIS 中显式加入 movement、端点协调和三类 review 图层。
- [x] T056 [US4] 对 1885118 新建 run 完整重跑，执行核心、PyQGIS 回读、道路面 overlay、人工路口检查、性能和文档终验。

## Phase 10: 独立几何/拓扑验收与迭代修复

- [x] T057 [US4] 对旧权威结果建立独立发布后审计，覆盖全部物理节点、支持 Road 对齐局部转角和 Movement 两侧接头，不复用生产器内存结论。
- [x] T058 [US5] 将 Directional Road 拟合改为统一纵向站距，并以纵向距离约束横向斜率，消除密集父顶点导致的局部 V/S 折线。
- [x] T059 [US5] 将端点协调扩展至全部发布 Road 的共享物理 Node，并以全 Road/自适应过渡平滑传播端点修正。
- [x] T060 [US5] 修正 Movement 证据几何方向与裁剪，增加接头夹角门禁和可审计切向 fallback。
- [x] T061 [US4] 新增只读取发布 GPKG 的独立 QA JSON/GPKG；finalizer 将其设为 `passed` 硬门禁，QGIS 增加三类违规图层。
- [x] T062 [US5] 新增双向 provisional 中心锚点宽度相对间距审计；4 个塌缩父 Road回退为 SWSD 父表达，8 个 LaneEvidenceSegment 仅保留 LaneTopo lineage，禁止人工横移。
- [x] T063 [US5] 新增 `high_precision_claim_scope / sd_gap_risk_state`、100 m 长 SD gap 复核、完整 HP/transition/SD QGIS 分段和发布后独立 direction-pair QA；完成 1885118 第三轮分层人工审计。
- [x] T064 [US4] 每轮修复后重新运行 1885118 六 Patch 与独立验收；保留 `T144926/T145354/T153934/T154309` 失败或口径不一致证据，确认 `T154712` 的物理节点、Road 平滑、Movement 接头、双向间距和长 gap 声明均通过并同步文档。

- T001-T005 是本轮完成门槛。
- T006-T009 可在枚举未确认时执行，因为只做结构 profiler。
- T017、T022 和 restriction 意义上的 movement 合法性不属于第二里程碑或本轮修订；RoadSplit、restriction/Laneinfo 不阻断 T031-T064。
- T014 不依赖 Boundary 枚举即可使用纯几何宽度；宽度、Boundary-gap 和方向异常进入独立 QA，不等同于 Road 冲突。
- Phase 5 依赖 Phase 3 骨架和 Phase 4 evidence assignment。
- T032-T035 依赖 T031 的真实数据分析，但候选参数仍是 POC 配置，不升级为正式字段语义。
- 任何正式入口任务都不在本 task list 授权范围内，需要单独入口治理任务。
- T042-T050 只授权 P04 内部 Directional Road V2 callable；repo CLI、root script 和 T00-T12 入口仍不在范围内。
