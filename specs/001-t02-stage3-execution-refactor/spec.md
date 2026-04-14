# Feature Specification: T02 Stage3 Execution-Layer Refactor

**Feature Branch**: `001-t02-stage3-execution-refactor`  
**Created**: 2026-04-13  
**Status**: Draft  
**Input**: User description: "先进入 speckit 的计划模式，先把重构的任务流程明确清楚，再往下继续。先给我计划。"

## User Scenarios & Testing

### User Story 1 - 执行层先完成契约化重构 (Priority: P1)

作为 T02 / Stage3 的维护者，我需要先把 Step3~Step7 从当前单体主流程中拆成独立、单向依赖、可审计的执行层组件，这样后续业务优化不再以 case patch 为主要推进方式。

**Why this priority**: 当前最大问题不是个别 case 没修好，而是执行层仍未完成结构性重构，导致 case 驱动 patch 持续反复。

**Independent Test**: 只检查执行层结构，不跑 `61-case` 全量，也能判断是否已完成核心重构门槛。

**Acceptance Scenarios**:

1. **Given** 当前 Stage3 主流程仍在单个超大函数内串联 Step3~7，**When** 完成本轮重构，**Then** Step3~Step7 必须各自产出显式结果对象，并且主入口只负责 orchestrate，不再直接承载语义裁决与 late cleanup 细节。
2. **Given** Step7 是最终准出裁决层，**When** 结构重构完成，**Then** Step7 之后不得再发生会改写几何、foreign 语义或准出结果的 trim/cleanup。

---

### User Story 2 - 审计链从步骤原生结果生成 (Priority: P1)

作为 QA / 目视审查使用者，我需要 `root_cause_layer / root_cause_type / visual_review_class` 直接来自 Step3~Step7 的原生结果，而不是由 `acceptance_reason/status` 事后反推。

**Why this priority**: 当前包装层虽已部分收口，但执行层与审计层仍未真正契约化，导致系统判定和业务认知不断漂移。

**Independent Test**: 只检查输出的 step result 和 audit assembler，即可验证是否满足契约，不依赖某个具体 case 成败。

**Acceptance Scenarios**:

1. **Given** 某 case 在 Step5 命中 foreign 硬排除，**When** 最终写出 `audit.json`，**Then** `root_cause_layer` 必须直接来自 Step5 结果，而不是通过 `acceptance_reason` 文本映射。
2. **Given** 某 case 在 Step4 存在 `stage3_rc_gap`，**When** 生成审计链，**Then** 该 gap 必须作为原生审计信号输出，而不是混入 Step7 启发式裁决。

---

### User Story 3 - 重构验收通过后再恢复 case 优化 (Priority: P2)

作为主控集成 Agent，我需要先有明确的结构验收门槛，只有当执行层重构完成后，才恢复 `Anchor 61` 的全量回归和目视审查闭环。

**Why this priority**: 如果不先冻结“何时算重构完成”，后续仍会回到一边 patch case、一边声称已重构完成的错误路径。

**Independent Test**: 即便还没恢复全量 `61-case`，只要结构门槛和再入门槛清晰，也能独立验证计划是否成立。

**Acceptance Scenarios**:

1. **Given** 重构尚未满足结构门槛，**When** 进入测试阶段，**Then** 只允许做结构检查、最小焦点回归和保护锚点检查，不恢复 `61-case` 正式全量。
2. **Given** 重构已通过结构验收，**When** 恢复全量回归，**Then** 必须把“正常准出正确性”与“目视分类正确性”拆成两条验证线。

---

## Edge Cases

- 如果某个 late cleanup 逻辑既承担几何优化又承担 foreign 主语义修复，必须先上收到 Step5/6，不能原样保留到优化层。
- 如果某个 selected node 只有依赖 foreign corridor / foreign tail 才能保住，必须在 Step4/5 边界被明确降级，而不是由 Step6 尾部 patch 临时放过。
- 如果 Step7 前没有稳定的 Step result，就不得通过字符串 reason 推断 `visual_review_class`。
- 如果结构重构期间某个保护锚点回退为 `V4/V5`，必须阻断继续迁移，先修复分层回归。

## Requirements

### Functional Requirements

- **FR-001**: System MUST define explicit result objects for `Step3LegalSpace`, `Step4RCSemantics`, `Step5ForeignModel`, `Step6GeometrySolve`, and `Step7Acceptance`.
- **FR-002**: System MUST make `Step3 -> Step4 -> Step5 -> Step6 -> Step7` a one-way dependency chain; later steps MUST NOT rewrite earlier-step contracts.
- **FR-003**: System MUST ensure Step7 is the single final verdict layer for `accepted / review_required / rejected`.
- **FR-004**: System MUST emit `root_cause_layer / root_cause_type / visual_review_class` from structured step results rather than text keyword inference.
- **FR-005**: System MUST downgrade existing `late_*cleanup* / late_*trim*` passes into bounded optimizers, or migrate their semantics into Step4/5/6 owned logic.
- **FR-006**: System MUST reduce `virtual_intersection_poc.py` from a monolithic execution core to an orchestrator that delegates to stage-specific modules.
- **FR-007**: System MUST define a structural acceptance gate that must pass before `Anchor 61` full regression is resumed.
- **FR-008**: System MUST preserve current packaging-layer guarantees for `mainnodeid / kind / EPSG:3857 / review_index / review_summary`.
- **FR-009**: System MUST separate post-refactor validation into two tracks: `正常准出正确性` and `目视分类正确性`.
- **FR-010**: System MUST forbid new case-specific branching or late-pass additions while the execution-layer refactor is in progress.

### Key Entities

- **Stage3Context**: 运行 Step3~Step7 的统一只读上下文，封装语义路口组、道路分支、RCSD 本地上下文、DriveZone、代表节点信息等。
- **Step3LegalSpaceResult**: 合法活动空间及其硬边界，包含允许占用区、must-cover 约束、禁止反向扩写标志。
- **Step4RCSemanticsResult**: `required / support / excluded RC` 语义分类结果，以及 `stage3_rc_gap` 等只读审计信号。
- **Step5ForeignModelResult**: foreign 语义排除模型，按 foreign node / road-arm-corridor / rc context 等子型输出。
- **Step6GeometrySolveResult**: 受约束几何生成结果与有限优化结果，显式区分 primary solve 与 bounded cleanup。
- **Step7AcceptanceResult**: 最终准出裁决，唯一来源于 Step3~6 的冻结结果。
- **Stage3AuditRecord**: 机器审计记录，直接引用各 Step result 的事实。
- **Stage3ReviewIndexEntry**: 正式审查索引条目，连接测试用例、输入路径、输出目录和审计结果。

## Success Criteria

### Measurable Outcomes

- **SC-001**: `virtual_intersection_poc.py` 不再承担 Step3~7 的全部执行细节；Step3~7 至少以独立模块或独立执行单元存在，并被主入口显式调用。
- **SC-002**: Step7 之后不存在会修改最终几何、foreign 语义或 acceptance 的 late trim/cleanup。
- **SC-003**: `root_cause_layer / root_cause_type / visual_review_class` 可以追溯到结构化 Step result，而不是通过 `acceptance_reason/status` 文本推断。
- **SC-004**: QA 能基于结构门槛明确给出“结构性重构完成 / 未完成”的结论，而不依赖 case 通过数。
- **SC-005**: 只有在结构门槛通过后，才恢复 `Anchor 61` 全量；恢复后能把“正常准出正确性”与“目视分类正确性”分别统计和对账。
