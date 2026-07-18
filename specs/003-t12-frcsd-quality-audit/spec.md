# Feature Specification: T12 FRCSD 质量审计

**Feature Branch**: `codex/003-t12-frcsd-quality-audit`
**Created**: 2026-07-18
**Status**: Implemented and locally validated
**Input**: 新增 T12 FRCSD 质检模块，检查原始 1V1 FRCSD 与 SWSD 的通行拓扑等价性，复用 T06 诊断能力并接入 T10，保持当前 T10 兼容实验的业务效果。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 批量发现原始 1V1 FRCSD 的通行质量候选 (Priority: P1)

作为路网质量工程师，我希望把 SWSD Segment、路口锚定证据和原始 1V1 FRCSD Road/Node 交给 T12，批量发现 FRCSD 中可能导致通行能力不等价的局部问题，以便在内网完整数据上获得可复核的质量候选，而不是依赖逐 Segment 人工浏览。

**Why this priority**: 这是 T12 的核心业务价值，也是把本地 T10 兼容实验推广到完整数据的前提。

**Independent Test**: 使用 `1026960` 用例的原始 SWSD、原始 1V1 FRCSD、T01 Segment、T05/T07 路口证据和 T06 兼容诊断证据独立运行候选发现；检查每个候选都包含方向、锚点、局部/全图路径、几何偏离、长度与来源证据，并且输入未被修改。

**Acceptance Scenarios**:

1. **Given** SWSD 要求某方向可通行且两端路口关系可解释，**When** 原始 1V1 FRCSD 在对应局部 corridor 内缺少有向 carrier，**Then** T12 输出可复核候选并记录无向 carrier、全图绕行或完全断连证据。
2. **Given** FRCSD 使用复合路口的另一合法 portal 或路口组成员承载通行，**When** 单主节点搜索会产生假告警，**Then** T12 必须保留全部可解释 portal/组成员并将等价 carrier 证据写入排除依据，不得因单节点模型直接认定 FRCSD 错误。
3. **Given** CRS 缺失、不一致或不能安全转换到米制处理 CRS，**When** T12 启动，**Then** 运行显式失败或阻断并记录原因，不得猜测 CRS。

---

### User Story 2 - 复核闭环只发布已确认质量问题 (Priority: P1)

作为质量复核人员，我希望对 T12 候选作出“问题成立、假阳性排除、仍需人工判断”的明确决定，并让系统只把已确认成立的记录计入最终 FRCSD 质量问题清单。

**Why this priority**: 用户要求最终输出经复核后应当真实存在质量问题，不再以高概率或中概率代替质量结论。

**Independent Test**: 将 `1026960` 已完成的复核决定作为外部审计输入运行发布阶段；最终结果必须是 10 个已确认问题、25 个排除、0 个待定，且确认问题 ID 集合与当前核实结果完全一致。

**Acceptance Scenarios**:

1. **Given** 候选具有合法复核决定和证据说明，**When** 决定为 `confirmed_frcsd_quality_issue`，**Then** 该记录进入最终问题清单和最终计数。
2. **Given** 决定为 `excluded_false_positive`，**When** 发布最终结果，**Then** 该记录只进入排除审计，不进入最终问题清单。
3. **Given** 候选未复核、决定无效或证据不足，**When** 发布最终结果，**Then** 该记录进入 `manual_review_required`，且最终完成态不得把它计作已确认问题。
4. **Given** 最终问题结果已生成，**When** 检查输出字段，**Then** 不存在 `high`、`medium` 或概率等级字段；最终问题以复核状态和可追溯证据表达。

---

### User Story 3 - 在 T10 中标准编排 T12 且不改变既有业务 handoff (Priority: P2)

作为端到端流程维护人员，我希望 T10 能在 T06 兼容诊断完成后编排 audit-only 的 T12，并继续保持 T06、T11、T09 的现有输入输出语义和业务效果。

**Why this priority**: 内网完整数据需要统一编排和可恢复运行，但 T12 不能侵入 T06 替换规则或改变 T09 正式承载输入。

**Independent Test**: 运行包含 T12 的 `1026960` T10 流程，确认 stage manifest、handoff、summary 和输出路径完整；移除或关闭 T12 时，原 T06→T11→T09 handoff 仍保持兼容。

**Acceptance Scenarios**:

1. **Given** T10 获得显式的原始 1V1 FRCSD 输入和 T12 所需上游证据，**When** 执行 T12 stage，**Then** T10 记录输入、参数、输出、状态、耗时和日志。
2. **Given** T12 发现问题或存在待复核候选，**When** T10 继续运行，**Then** T12 作为 audit-only 阶段不修改 T06 输出，也不改变 T11/T09 的既有业务输入。
3. **Given** 未提供原始 1V1 FRCSD 输入，**When** 运行不要求 T12 的既有 T10 场景，**Then** 原有流程保持兼容；当调用方明确要求 T12 时则必须阻断并报告缺失输入。

### Edge Cases

- SWSD Segment 的两个 pair 端点相同，或路口映射后坍缩到同一 FRCSD 语义路口。
- SWSD 单向/双向语义与 FRCSD Road direction 字段组合不同，但几何 carrier 实际存在。
- 复合路口存在多个合法进出 portal，正向到达 portal 与反向出发 portal 不相同。
- FRCSD 节点通过 `id/subnodeid/mainnodeid` 形成别名组，主节点不直接位于 carrier 端点。
- 局部有无向 carrier 但有向 carrier 缺失；全图存在远距离绕行；局部有向和无向均断开。
- SWSD 与 FRCSD 几何长度相近但偏离 corridor，或长度差异较大但仍位于合法道路面内。
- DriveZone/道路面参考存在覆盖缺口；参考面只能作为证据，不能静默否决拓扑事实。
- T06 Step2/Step3 证据缺失、过期或来源 target 不是当前原始 1V1 FRCSD。
- 空数据、无候选、大规模候选、重复 ID、无效几何、GeometryCollection 或多部件几何。
- 复核文件包含未知 Segment、重复决定、缺失理由或与本次运行 manifest 不一致。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须新增正式 `T12 FRCSD 质量审计` 模块，质检对象必须是调用方显式提供的原始 1V1 FRCSD Road/Node，不得把 T06 Step3 修改后的 F-RCSD 当作被检真值。
- **FR-002**: 系统必须消费 SWSD Segment/Road/Node，并按 SWSD 方向语义构造每个 Segment 的必需通行方向。
- **FR-003**: 系统必须消费 T05 统一 relation、T07/RCSDIntersection 标准路口证据及路口组成员，构造可解释的 FRCSD 锚点组和进出 portal；不得只接受单一主节点。
- **FR-004**: 系统必须复用 T06 已有的方向、图构建、buffer corridor、路径和失败诊断能力；如现有能力不能安全复用，可提取不改变 T06 行为的共享纯函数，但不得复制并分叉同一套业务规则。
- **FR-005**: 系统必须能够消费与当前 T05/T06 运行链同批次的 T06 Step2 rejected、buffer-only probe、failure audit、problem registry 和 replacement plan 作为候选/交叉证据；T06 消费的 T05 copy-on-write FRCSD 与原始 1V1 FRCSD 必须显式登记为 `derived_copy_on_write`，不得要求两者文件指纹相同，也不得把 T06 Step3 topology audit 用来覆盖原始 FRCSD 事实。
- **FR-006**: 系统必须分别检查局部有向可达、局部无向 carrier、全图有向绕行、路径长度比和相对 SWSD corridor 的几何偏离，并保存实际路径 Road ID。
- **FR-007**: 系统至少必须区分 `directed_carrier_missing` 与 `required_local_connectivity_missing` 两类问题；新增类型必须保持可审计且不得改变既有类型语义。
- **FR-008**: 自动阶段必须输出候选证据，不得把未经复核的候选直接写入最终已确认问题清单。
- **FR-009**: 复核阶段必须支持 `confirmed_frcsd_quality_issue`、`excluded_false_positive`、`manual_review_required` 三种状态；只有第一种进入最终问题计数。
- **FR-010**: 最终确认问题输出不得包含高概率/中概率分类；候选层也不得用概率等级替代证据和复核状态。
- **FR-011**: 生产实现不得硬编码 `1026960` 的 Segment ID、Road ID、Node ID、复核决定或本机绝对数据路径。
- **FR-012**: 系统必须对复核输入执行完整性校验：候选身份、运行身份、重复决定、未知决定、决定理由和证据引用均需可追溯。
- **FR-013**: 系统不得修改输入 FRCSD/SWSD/T05/T06 数据，不得自动修复几何、方向、节点关系或拓扑；所有异常必须显式输出。
- **FR-014**: 系统必须显式验证 CRS、坐标变换、几何有效性、Road 端点 Node 完整性和图拓扑一致性；任何转换或降级都必须进入审计。
- **FR-015**: 每次运行必须记录输入路径与摘要、文件指纹、参数、输出、运行环境、耗时、候选/复核/确认计数和 silent-fix 状态。
- **FR-016**: 系统必须输出机器可读 summary、候选、最终确认问题、排除项、待复核项和空间证据图层；空间输出必须保留处理 CRS 与原始对象引用。
- **FR-017**: T12 必须作为 T10 的 audit-only stage 可选编排；未启用时保持既有 T10 行为，启用时不得改变 T06→T11→T09 的业务 handoff。
- **FR-018**: T10 必须使用语义明确的原始 1V1 FRCSD 输入 slot，不得继续借用 `RCSD` 输入名称掩盖 target 语义。
- **FR-019**: T12 正式入口、模块契约、项目主链、生命周期登记和入口注册必须在同一变更中保持一致。
- **FR-020**: 系统必须支持内网完整数据的批量运行、稀疏进度、确定性输出、失败后定位和可验证性能统计；不得声称已在内网执行，除非实际获得内网访问能力。
- **FR-021**: `1026960` 回归必须以外部复核 fixture 重现当前已核实结果：35 个候选中 10 个确认、25 个排除、0 个待定，且确认 ID 集合完全一致。
- **FR-022**: `1001716_1010487` 与 `1039488_1039490` 必须通过通用的 portal/路口组逻辑排除，不得通过生产代码中的对象级白名单排除。

### Key Entities *(include if feature involves data)*

- **Audit Run**: 一次 T12 运行的身份、输入指纹、参数、环境、状态、耗时和输出索引。
- **Target Manifest**: 当前原始 1V1 FRCSD target 与可选 T06 兼容证据的来源绑定，防止消费错批次证据。
- **Segment Requirement**: 从 SWSD Segment/Road/Node 推导的 pair 端点、必需方向、参考 Road 和 corridor。
- **Anchor Group**: 一个 SWSD 语义路口对应的全部可解释 FRCSD 主/子节点和进出 portal。
- **Carrier Evidence**: 某必需方向下局部/全图、有向/无向路径及 Road ID、长度、比例、偏离和接受状态。
- **Quality Candidate**: 自动发现的潜在 FRCSD 质量问题及完整证据，不等于最终问题。
- **Review Decision**: 人工或外部治理流程对候选作出的状态、理由、复核人/来源和时间记录。
- **Confirmed Quality Issue**: 已复核成立、进入最终计数的 FRCSD 质量问题。

## Assumptions

- SWSD 与原始 1V1 FRCSD 在通行拓扑上应等价是待验证质量假设，只用于定义检查目标，不作为修复规则。
- RCSDIntersection 是 T07 的标准路口输入，可作为人工确定的现实世界路口真值；T05/T07 路口组仍需用于解释合法 portal。
- T06 保持现状；T12 优先复用其稳定能力和结果，但不会把 T06 的替换结论当作原始 FRCSD 质量结论。
- 当前确认问题集合来自 `1026960` 已完成复核，只作为验收 fixture，不固化为生产规则。
- T12 在 T10 中默认 audit-only；发现问题不自动修复 FRCSD，也不自动阻断现有 T09 业务 handoff。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 在 `1026960` 回归中，候选发现覆盖全部 10 个已确认问题，召回率为 100%。
- **SC-002**: 使用登记的 `1026960` 复核 fixture 后，最终问题清单恰好包含 10 个已确认 ID、25 个排除、0 个待定，最终清单相对已核实真值的准确率为 100%。
- **SC-003**: 两个已知复杂 portal 假阳性 `1001716_1010487`、`1039488_1039490` 均由通用证据逻辑排除，生产实现对象级硬编码数量为 0。
- **SC-004**: 100% 的候选和最终问题都能追溯到 Audit Run、输入指纹、SWSD Segment、FRCSD Road/Node、锚点组、方向和路径证据。
- **SC-005**: 100% 的运行显式记录 CRS、拓扑、几何、审计、性能和 `silent_fix=false`；任何必需检查缺失时运行不得标记为通过。
- **SC-006**: 在 `1026960` 上，先在与正式 T12 相同的运行环境中复跑当前兼容实验同等范围并建立单环境基线；正式 T12 候选发现与复核发布总耗时不高于该基线的 150%。来自不同 Python/操作系统的历史耗时不得相加作为通过基线。
- **SC-007**: 启用 T12 后，既有 T06 输出与 T11/T09 业务输入文件指纹保持不变；未启用 T12 的既有 T10 场景全部回归通过。
- **SC-008**: 内网完整数据入口能够在预检阶段发现缺失输入、CRS 冲突、证据批次不一致和输出覆盖风险，并在真正处理前明确阻断。
