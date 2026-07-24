# Feature Specification: P04 高精骨架优先 Road Direct V3

**Feature Branch**: `codex/p04-road-direct-poc-20260720`
**Created**: 2026-07-21
**Status**: Ready for Implementation
**Input**: 用户确认 Directional Road V2 的自动 `forward/reverse` 实例化不是主要价值，要求以 SWSD 保持语义完整、以 Lane/LaneBoundary/DriveZone 提升高精 Road 骨架，并授权以 `p04_directional_v2_1885118_20260721T154712`（638 条 Road）作为唯一 V2 冻结基线。

## 1. 目标修订

V3 将 SWSD 的职责限制为 Road/Junction 身份、方向、ownership、完整性和缺资料兜底，不再把 SWSD 几何作为有证据 Road 的默认形态。Lane、LaneBoundary、DriveZone 和前后高精锚点共同决定 Road 几何骨架。

V3 不再因 SWSD 双向属性自动生成两条单方向 Road。只有存在两条空间可区分、方向一致、纵向可持续且通过间距门禁的物理方向走廊时才拆分；否则发布一个共享物理 Road，并通过方向字段和 LaneTopo 表达通行关系。

## User Scenarios & Testing

### User Story 1 - 高精证据主导 Road 骨架 (Priority: P1)

作为 Road 直出成果使用者，我需要有可用 Vector 证据的 Road 几何主要由 Lane、LaneBoundary、DriveZone 和高精锚点决定，而不是在局部缺资料时立即回到 SWSD 中心线。

**Why this priority**: V2 全网只有 32.553% 长度为直接高精中心线，55.515% 为 SWSD gap；高精证据只是局部修饰，未形成高精骨架。

**Independent Test**: 对 1885118 六 Patch 运行 V3，逐 Road 复算 `hp_observed / hp_constrained_interpolation / swsd_fallback` 长度，证明有证据 Road 的高精控制覆盖率达到门禁，且直接观测范围没有被插值冒充。

**Acceptance Scenarios**:

1. **Given** Road 某站点存在可信 Lane/共享 Boundary 中心观测，**When** 生成几何，**Then** 该站点使用高精观测并标记为 `hp_observed`。
2. **Given** 两个高精观测之间存在局部资料缺口，**When** 插值满足 LaneGroup/DriveZone 包络、横向斜率和平滑门禁，**Then** 使用高精约束补间并标记为 `hp_constrained_interpolation`。
3. **Given** Road 端部只有单侧高精锚点，**When** 锚点趋势、DriveZone 包络和端点拓扑共同支持延伸，**Then** 可形成可审计的高精约束延伸；不满足时显式回退 `swsd_fallback`。
4. **Given** Road 完全没有可用高精证据，**When** 发布完整 RoadGraph，**Then** 保留 SWSD 几何和语义，状态为 `sd_only`。
5. **Given** 补间或延伸超出道路面、产生过大横移/振荡或无法闭合拓扑，**When** 执行门禁，**Then** 只回退受影响区间并记录原因，不 silent fix、不扩大高精声明。

---

### User Story 2 - 仅按物理走廊条件拆分方向 Road (Priority: P1)

作为 RoadGraph 设计者，我需要 Road 对象表达真实物理走廊，而不是把一条 SWSD 双向 Road机械复制为正反两个方向对象。

**Why this priority**: 方向复制本身不提升几何精度；缺证据区间还会使两个方向对象重新汇入同一 SWSD 线，形成重复对象和低价值拓扑。

**Independent Test**: 对每个 SWSD 父 Road 输出 `shared_physical / directional_carriageway / sd_fallback` 实例化决策。所有方向拆分均有双侧独立高精证据、物理间距和纵向持续性证明；不存在仅反转坐标的重复 Road。

**Acceptance Scenarios**:

1. **Given** 双向父 Road 两侧均存在可用且空间可区分的方向走廊，**When** 通过物理走廊门禁，**Then** 发布两个单方向 `directional_carriageway` Road。
2. **Given** 只有一侧证据、双侧锚点塌缩、纵向重叠不足或无法证明物理分隔，**When** 实例化，**Then** 发布一个 `shared_physical` Road，不补造第二条线。
3. **Given** 原 SWSD 为单方向，**When** 存在可用高精证据，**Then** 发布一个方向保持一致的高精 Road。
4. **Given** 任意两个发布方向对象，**When** 独立 QA 比较高精片段和整线，**Then** 不存在仅方向相反且空间重合的重复对象。

---

### User Story 3 - 保持完整语义和 LaneTopo 自洽 (Priority: P2)

作为拓扑质量负责人，我需要 V3 保留 571 个 SWSD 父 Road语义，Road 端点、Portal/Arm 和 Movement 与 LaneTopo 相互解释，并在资料不足时仍发布完整结果。

**Independent Test**: 验证父语义守恒、每条发布 Road恰有两个 Portal/Arm、共享物理节点闭合、confirmed/review LaneTopo 守恒和 Movement 接头门禁。

**Acceptance Scenarios**:

1. **Given** 任意 SWSD 父 Road，**When** 发布 V3，**Then** 至少有一个 V3 Road承载该父语义，不因资料不足删除。
2. **Given** confirmed LaneTopo 跨 Road 连接同一物理 Node，**When** 协调端点，**Then** 两侧 Road共点且无 silent snap。
3. **Given** confirmed LaneTopo 连接同一语义路口的不同物理 Portal，**When** 发布 RoadGraph，**Then** 输出显式 Movement 并保持两侧切向连续。
4. **Given** LaneTopo 方向、语义或端点无法唯一解释，**When** 发布，**Then** 保留 review 及源关系，不参与自动协调。

---

### User Story 4 - 可解释比较和人工检查 (Priority: P2)

作为 QGIS 审计人员，我需要同时查看原始 SWSD、原始 RCSD、冻结 V2 和新 V3，并按高精来源而不是 `forward/reverse` 颜色理解结果。

**Independent Test**: QGIS 工程相对路径回读成功，首组包含四套完整 Road 对照，V3 主样式按四态支持状态展示，来源分段按三类几何来源展示。

---

### User Story 5 - 隔离实施并冻结 V2 (Priority: P3)

作为仓库维护者，我需要 V3 复用 P04 M1/M2 正式 POC 产物，但不改变 V2、T00-T12 V1、repo CLI 和 root scripts。

**Independent Test**: V3 使用独立 callable、版本、输出目录和测试；冻结 V2 成果 hash 不变，入口 registry 无新增。

## Edge Cases

- 相邻 Patch 未提供时，端部延伸不得越过开放证据边界冒充高精闭合。
- 单条 Lane 被误识别为道路边缘、非机动车道或宽度异常时，只降低证据资格，不直接产生 Road conflict。
- 两个方向 Lane 在局部可分、全局重合时，不得仅凭局部分隔拆分整条 Road。
- DriveZone 为 Patch 级 dissolve MultiPolygon 时，只作为道路面包络约束，不作为单条 Road owner 或中心线真值。
- 导流带、临时拓宽/变窄、鱼骨线不得单独制造物理 Road 拆分。
- 共享物理 Road含双向 Lane 时，中心骨架必须来自完整横向证据的稳健中心，不得偏向某一侧最左 Lane。
- `conflict_retained` 必须来自通过输入质量门禁后仍可信的结构冲突；输入缺失、窄 Lane 和 Boundary 不足仍属于 QA。

## Requirements

### Functional Requirements

- **FR-001**: V3 MUST 保持 P04 为 `Active POC / 成果模块`，不接入正式 relation-first 主链。
- **FR-002**: V3 MUST 以 `p04_directional_v2_1885118_20260721T154712` 作为唯一冻结 V2 对照；不得覆盖或修改该 run。
- **FR-003**: V3 MUST 完整保留 571 个 SWSD 父 Road语义，每个父 Road至少映射到一个发布对象。
- **FR-004**: SWSD MUST 决定 Road/Junction 身份、方向、Patch membership、ownership 和语义完整性；SWSD 几何只可作为 corridor reference、拓扑参考和显式 fallback。
- **FR-005**: V3 MUST 输出条件式物理走廊决策。双向父 Road只有在正反两侧均有 `usable` 证据、稳定中心可分、纵向持续性充分且宽度相对间距门禁通过时才可拆分。
- **FR-006**: 不满足 FR-005 时 MUST 发布单个 `shared_physical` Road；不得通过复制、反转或人工平移制造第二条 Road。
- **FR-007**: 单方向 SWSD Road MUST 保持单对象和原行驶方向语义。
- **FR-008**: 每个发布 Road MUST 具有唯一稳定中心策略，来源可为稳定中心 Lane、共享 Boundary 或稳健横向中心走廊；不得沿里程无审计切换互不相关锚点。
- **FR-009**: V3 MUST 在统一纵向站距上构建直接中心观测，并保留来源 Lane/Boundary、Patch、质量状态、横向位置和观测覆盖。
- **FR-010**: 几何来源 MUST 严格分为 `hp_observed / hp_constrained_interpolation / swsd_fallback`；插值、延伸或拓扑协调不得记为直接观测。
- **FR-011**: 高精约束补间 MUST 由两端或单端高精锚点、LaneGroup/DriveZone 包络、横向斜率、振荡、长度膨胀和开放边界共同门禁；失败时只回退受影响区间。
- **FR-012**: `hp_supported / partial_hp_supported / sd_only / conflict_retained` 四态 MUST 继续作为 Road 发布支持状态，并与输入质量状态分离。
- **FR-013**: `partial_hp_supported` MUST 发布直接观测、约束补间和 fallback 分段；高精声明范围不得超过直接观测与通过门禁的约束范围。
- **FR-014**: Road 几何 MUST 位于可用 LaneGroup/DriveZone 约束内；LaneGroup 包络违规、valid/simple 失败、不可解释长度膨胀或振荡 MUST 阻止通过。
- **FR-015**: V3 MUST 保持 LaneTopo confirmed/review 守恒，并发布物理节点共点或显式 Movement；review 不参与自动端点协调。
- **FR-016**: 每条 Road MUST 恰有两个 `s/e` Portal/Arm，所有发布 Road共享的多端物理 Node 必须进入独立闭合审计。
- **FR-017**: V3 MUST 使用显式米制 CRS并保留所有源 CRS、转换、输入 hash、参数、代码版本、运行环境和逐阶段耗时。
- **FR-018**: V3 MUST 生成独立发布后 QA；finalizer 只有在 core、QGIS、独立回读、道路面 overlay 和独立质量门禁均通过时才可发布 `terminal_status=passed`。
- **FR-019**: QGIS 工程 MUST 显式对比原始 SWSD、原始 RCSD、冻结 V2 和 V3；V3 主样式按四态支持状态，来源分段按三类几何来源。
- **FR-020**: V3 MUST 使用独立模块内研究 callable 和输出契约；不得新增 repo CLI、root script、正式入口或修改 T00-T12 V1。
- **FR-021**: restriction/Laneinfo、ReferenceLane 补充、RoadSplit 正式语义和未知枚举强规则 MUST NOT 进入本轮几何或通行合法性结论。
- **FR-022**: 当前 RCSD MUST 仅作为位置/形态对照，不能决定目标 Road身份、拓扑或通过结论。
- **FR-023**: V3 MUST 报告高精控制覆盖率、直接观测覆盖率、SWSD fallback 比例、条件拆分数量、回退原因和相对 V2 的逐 Road差异。
- **FR-024**: V3 MUST NOT 通过扩大 `hp_observed` 定义满足覆盖指标；直接观测集合必须可由源 Lane/Boundary 独立复算。

### Responsibility Views

| 视角 | 本轮职责 |
|---|---|
| 产品 | 把主要价值从方向对象复制调整为高精几何骨架；保证完整 RoadGraph 和四态解释。 |
| 架构 | 定义 SWSD 语义骨架、物理走廊条件拆分、三类几何来源、Portal/Movement 和独立 QA 边界。 |
| 研发 | 新增隔离 V3 callable 与小文件实现，复用 M1/M2 输入，不修改冻结 V2 和既有模块。 |
| 测试 | 先覆盖条件拆分、共享中心、三类来源、补间回退、拓扑守恒、CRS 和错误输入，再实现。 |
| QA | 使用 1885118 真实数据、V2量化基线、QGIS四网对照、自动overlay和发布后独立复算，不以目视替代机器门禁。 |

### Key Entities

- **HighPrecisionRoadUnit**: 一个 SWSD 父语义下的共享物理 Road或独立方向走廊发布单元。
- **PhysicalCorridorDecision**: 是否拆分及其双侧证据、纵向持续性、间距和回退原因。
- **CenterEvidenceObservation**: 固定站点上的 Lane/Boundary 高精中心观测。
- **HighPrecisionControlSpan**: 由直接观测和约束条件共同控制的连续里程范围。
- **GeometrySourceSegment**: `hp_observed / hp_constrained_interpolation / swsd_fallback` 之一的连续几何片段。
- **HighPrecisionRoadCandidate**: 携带四态、几何来源、父语义、方向/共享表达和质量审计的最终 Road。
- **HighPrecisionRoadGraph**: Road、Portal、Arm、Movement 和 LaneTopo lineage 的完整 POC 图。

## Success Criteria

### Measurable Outcomes

- **SC-001**: `571 = distinct(parent_swsd_unit_id)`，每个父 Road至少映射一个 V3 Road，未发布父 Road为 0。
- **SC-002**: V3 Road总量等于 `571 + 通过物理走廊拆分的父 Road数量`，不存在自动按双向字段增加对象。
- **SC-003**: 所有拆分父 Road均有双侧独立 `usable` 观测、纵向持续性和宽度相对间距通过记录；空间重合的纯反向重复 Road数量为 0。
- **SC-004**: 有可用高精证据的 Road中，`hp_observed + hp_constrained_interpolation` 长度占比不低于 80%。
- **SC-005**: 全网 `swsd_fallback` 长度占比低于 40%；若真实数据无法达到，终态必须失败并报告不可达原因，不得修改指标定义。
- **SC-006**: `hp_observed` 集合与源 Lane/Boundary 独立复算一致，声明扩大数量为 0。
- **SC-007**: V3 几何非空、valid、simple 均为 100%，LaneGroup/DriveZone 硬包络违规为 0。
- **SC-008**: 所有发布 Road恰有两个 `s/e` Portal/Arm；多端物理节点间距、Movement—Portal 偏差和 Movement 接头均通过独立门禁。
- **SC-009**: LaneTopo 满足 `confirmed + review = input`，所有 review 原因和源关系可追溯。
- **SC-010**: 冻结 V2 四个核心成果文件 hash 与授权基线一致；V3 输出位于独立 run root。
- **SC-011**: QGIS 工程包含四网对照、四态 V3、三类几何来源、Lane/Boundary/DriveZone、LaneTopo及违规图层，并通过独立回读。
- **SC-012**: 最终权威 run 的 core、独立质量、QGIS、独立回读、overlay、性能和人工分层审计全部有可定位证据，任一缺失不得标记 `passed`。
