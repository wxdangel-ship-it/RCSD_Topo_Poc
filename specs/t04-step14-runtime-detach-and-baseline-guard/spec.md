# Feature Specification: T04 Step1-4 Runtime Detach And Baseline Guard

**Feature Branch**: `codex/t04-step14-runtime-detach-and-baseline-guard`  
**Created**: 2026-04-22  
**Status**: In Progress  
**Input**: 用户要求以 SpecKit + 多 Agent 方式，将 `t04_divmerge_virtual_polygon` 在 `Step1-4` 范围内推进到运行时独立于 `t02_junction_anchor`、冻结当前重要 baseline、降低结构债，并为下一轮 `Step4 final tuning` 准备稳定底座。

## Context

- `T04` 当前正式范围仍只到 `Step1-4`，不进入 `Step5-7`，不新增 repo 官方 CLI。
- 当前人工目视已确认：正向 RCSD 召回结果正确。本轮不是推翻结果，而是在不破坏当前结果的前提下做自主化与稳态优化。
- 当前 repo 文档与实现仍存在“优先复用 T02 Stage4 核心能力 / 直接调用 T02 私有实现”的旧口径和旧依赖。
- 深审已明确点名：
  - `event_interpretation.py` 逼近 `100 KB`
  - `rcsd_selection.py` 与 `test_step14_pipeline.py` 体量偏大
  - T04 当前大量直接 runtime import `t02_junction_anchor`

## Thread-Level Hard Boundaries

1. `T04` 只能在理解 `T02-Stage4` 的基础上研制，但运行时 **不得 import/call `t02_junction_anchor`**。
2. 本轮先做 `baseline freeze`，再做代码改动；不得 silent regression。
3. 本轮只做 `Step1-4` 自主化、基线冻结、架构减债与回归稳态。
4. 本轮不进入 `Step5-7`，不做 `Step4 final closeout`，不新增 repo 官方入口。
5. `17943587` 的跨 unit 相同 RCSD 召回问题不是本轮主修目标；只要求不恶化，不写 case-specific hack。

## User Scenarios And Testing

### User Story 1 - T04 运行时脱离 T02 (Priority: P0)

作为维护者，我需要 `T04` 在 `Step1-4` 范围内运行时完全不再依赖 `t02_junction_anchor`，避免 T02 重构直接打穿 T04。

**Independent Test**: 搜索 `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/**`，运行时代码中不存在 `t02_junction_anchor` import；T04 pytest 与冻结 case 回归仍能跑通。

### User Story 2 - 冻结并守住当前重要 baseline (Priority: P0)

作为 QA，我需要先冻结 `Anchor_2` 重要 case 的关键字段与正向 RCSD 结果，再验证去依赖与拆分没有造成回退。

**Independent Test**: 生成 `baseline_compare.csv`，覆盖重点 case，并明确 `before/after` 的 `primary_candidate_id / layer / selected_evidence_state / review_state / positive_rcsd_present` 是否变化及原因。

### User Story 3 - 无语义拆分降低结构债 (Priority: P1)

作为开发者，我需要把 `event_interpretation.py`、`rcsd_selection.py`、`test_step14_pipeline.py` 按职责拆开，但不顺手改业务口径。

**Independent Test**: 拆分后模块职责更清晰，原有 frozen regression 仍通过，关键输出与 baseline 保持一致。

## Edge Cases

- `complex / continuous 128` 仍需保持 `unit population 不扩、event branch 可 continuation` 的现有语义。
- `pair-local` 为空时，必须直接 `C / no_support`，不得回退到 case/scoped RCSD 世界补对象。
- `positive_rcsd_present = true` 不得自动保底 `B`；归一化后结构性硬冲突仍允许落 `C`。
- `17943587 / node_55353233` 不得回退到 `502953712 + 605949403`。
- `17943587 / node_55353248` 不得回退到 trunk 主导或丢失 `607962170` continuation。

## Requirements

### Functional Requirements

- **FR-001**: System MUST inventory every direct and transitive T04 runtime dependency on `t02_junction_anchor` and record the before/after result.
- **FR-002**: System MUST migrate all T04 runtime-needed logic to T04-local private modules or T04-internal copies; runtime `after` count MUST be `0`.
- **FR-003**: System MUST freeze the current `Anchor_2` baseline before source-code changes and use it as the regression gate for this round.
- **FR-004**: System MUST guard at least `primary_candidate_id`、`primary_candidate_layer`、`selected_evidence_state`、`review_state`、`positive_rcsd_present`.
- **FR-005**: System MUST keep current positive RCSD recall semantics and current accepted results stable for the frozen cases unless an explicitly explained, non-regressive structural normalization occurs.
- **FR-006**: System MUST split `event_interpretation.py`、`rcsd_selection.py` and `tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py` by responsibility without changing business semantics.
- **FR-007**: System MUST minimally sync T04 formal docs so they explicitly state: T04 may reference T02 logic, but runtime must be independent.
- **FR-008**: System MUST produce `spec.md`、`plan.md`、`tasks.md`、`t02_runtime_dependency_inventory.md`、`baseline_compare.csv`、`codex_report.md`、`codex_oneclick.md`.

### Key Entities

- **Runtime Dependency Inventory**: 记录 T04 当前所有 direct/transitive `T02` runtime import、用途、替代方案、迁移去向与 before/after 计数。
- **Frozen Baseline Row**: 以 `case_id + event_unit_id` 为粒度，记录 before/after 核心字段与变化原因。
- **Detached Runtime Module**: 为 T04 提供本地 `types / contracts / io / step2 / step3 / step4 legacy core` 的私有实现，不暴露为 repo 官方入口。

## Success Criteria

### Measurable Outcomes

- **SC-001**: `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/**` 运行时代码对 `t02_junction_anchor` 的 import 数量从 `before > 0` 降到 `after = 0`。
- **SC-002**: 冻结 case 的 `selected_evidence`、`fact_reference_point`、正向 RCSD 结果与 review 输出没有 silent regression。
- **SC-003**: `event_interpretation.py`、`rcsd_selection.py`、`test_step14_pipeline.py` 完成职责拆分，且拆分后无单文件超过 `100 KB`。
- **SC-004**: T04 仍能独立跑完 `Step1-4`，并产出正式 review/index/summary 工件。
- **SC-005**: 本轮交付明确区分 `已修改 / 已验证 / 待确认`，并给出是否建议进入下一轮 `Step4 final tuning` 的裁决。
