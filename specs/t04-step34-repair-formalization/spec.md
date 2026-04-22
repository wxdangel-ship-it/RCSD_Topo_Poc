# Feature Specification: T04 Step3/Step4 Repair Formalization

**Feature Branch**: `codex/t04-step14-speckit-refactor`  
**Created**: 2026-04-21  
**Status**: In Progress  
**Input**: User request to按 SpecKit + 多 Agent 方式，以 `/mnt/e/_chatgpt_sync/RCSD_Topo_Poc/T04_1/REQUIREMENT.md` 为输入，对齐 T04 `Step3/Step4` 需求文档与代码实现，并完成 continuous merge complex 修复。

## Context

- T04 当前正式范围只到 `Step1-4`；`Step3 = topology skeleton`，`Step4 = fact event interpretation + review outputs`。
- 当前真实审计已确认两类问题：
  - Step3 粗骨架在复杂连续分歧 case 上被误读成“Step4 的权威定位结构”。
  - Step4 在 complex / multi 场景下，把 Step3 粗骨架继续当成半个事实定位层，导致 throat、ownership、reverse tip 语义错位。
- 当前多 Agent 审计已确认：输入需求自洽，但 repo 内 T04 source-of-truth 与代码实现都把 `continuous complex/merge` 的 unit-local branch 语义收窄了。
- 本轮目标不是只冻结方案，而是先用 spec 固化变更边界，再回写正式文档、修代码并完成 real-case 回归。
- 本轮同时包含一次内部架构拆分：把 `event_interpretation.py` 从单大文件拆成 facade + 子模块，但不得改变 Step4 对外契约、审计字段与 runner 入口。

## Confirmed Problem Statements

### P1. Step3 输出层与 Step4 输入层错位

- 当前 `step3_status.json` / `step3_audit.json` / case overview 主要表达 case-level skeleton。
- 但 complex 真正进入 Step4 时，代码又对每个 unit 用 `singleton_group=True` 重算单节点 context/topology。
- 结果是：
  - 执行层已经部分是 single-node-level
  - 审计层仍是 case-level
  - source-of-truth 没显式区分这两层 skeleton

### P2. Step4 继续沿用旧单事件粗骨架语义

- `event unit` 已拆出来，但传给 T02 内核时，`population / throat / ownership` 仍沿用旧的粗骨架语义。
- `augmented_member_node_ids` 重新回流到事实解释层。
- `branch-middle / throat gate` 在 complex/multi 场景中，仍可能退回全局 `main pair`。
- complex 子单元局部 scope 稀薄时，会静默回退成整条 complex 走廊。

### P2b. Step4 pair 传播与 sibling arm 选择缺失

- 输入需求已明确：Step4 的第一层单元是有序相邻 branch pair `(L, R)`，不是匿名 branch 集。
- complex / multi 场景里，Step4 传播的不是单条 road，而是 `(L, R, middle-region)`。
- sibling node 上 arm 的正式选择顺序也已明确：
  - `external associated road` 一致
  - `L' / R'` 之间不得夹入其他 road
  - 左右顺序不变
  - 最小转角只作 tie-breaker
- 当前实现仍以单 branch greedy continuation 为主，导致：
  - `607951495` 与 `510969745` 曾被错误并枝
  - `node_55353233` 无法稳定得到 `502953712 + 41727506 + 620950831`
  - Step4 的 `boundary_branch_ids / preferred_axis_branch_id / pair-local region` 仍可能建立在错误 pair 或错误 arm 上

### P3. ownership 与 review materialization 代理错位

- `shared_event_core_segment_with` 目前基于 localized patch。
- `shared_divstrip_component_with` 却又基于 coarse anchor zone。
- `fact point` 与 `review point` 仍混在一起，RCSD recenter 可能污染 Step4 审计语义。

## Non-Goals

- 不进入 `Step5-7`。
- 不新增 repo 官方 CLI / shell 入口。
- 不重写 T02 全量 Step3/Step4 内核。
- 不把 `17943587` 的 road id 现象直接硬编码成通用规则。

## User Scenarios & Testing

### User Story 1 - Step3/Step4 continuous merge 需求回写 (Priority: P1)

作为维护者，我需要把输入需求中关于 continuous complex/merge 的 branch 与 pair-local 语义写回 repo 正式文档，避免 source-of-truth 继续把合法连续合流 case 收窄成“只看当前 node 周边”。

**Independent Test**: 对 `17943587` 这类 complex case，能明确区分：
- `case coordination skeleton`
- `representative-node-anchored unit-level executable skeleton`
- `unit population 不扩` 与 `branch continuation 可跨 sibling internal node` 这两件事不会再被混淆

### User Story 2 - Step4 pair-local propagation 修复实现 (Priority: P1)

作为实现者，我需要修正 complex Step4 的 pair / throat / axis / ownership 输入，让 `node_17943587`、`node_55353233` 这类 case 能基于正确的 unit-local pair 语义生成候选空间。

**Independent Test**: 对 `17943587` 的多个 node，方案能解释为什么某些 unit 的合法边界需要跨 sibling node 传播，且不会退回全走廊或与其他 unit 共享同一局部区域。

## Edge Cases

- `continuous complex 128`：
  - case-level chain coordination 需要保留
  - 但不得继续冒充整条 complex corridor 的权威 throat 结构
  - 允许在不扩大 unit population 的前提下，把当前 unit 的 branch 沿 same-case sibling internal node 做语义连续延拓
- `complex / multi sibling propagation`：
  - 当前 unit 必须传播 `(L, R, middle-region)`，而不是单条 road
  - 若某个 sibling node 上 `L' / R'` 之间夹入其他 road、pair 无法唯一传播、或当前 pair-middle 被新 pair 替代，则必须停止
- `external associated road`：
  - 不是任意第一个外部 exit
  - 必须与当前边界 branch 的传播语义一致
- `multi-diverge / multi-merge`：
  - 必须保留相邻 pair 语义
  - 不能被错误重写成 per-node complex
- 同一 physical divstrip component 但 `same axis + |Δs| > 5m`：
  - 属于允许共存的契约例外
- forward 不通过 local throat gate：
  - 可以触发 reverse
  - 但 reverse 仍必须与当前 unit 的 local throat 有实际关系

## Requirements

### Functional Requirements

- **FR-001**: System MUST split Step3 output semantics into `case coordination skeleton` and `unit-level executable skeleton`.
- **FR-002**: System MUST define that complex Step4 consumes only the current unit’s executable skeleton, not the case-level skeleton.
- **FR-003**: System MUST preserve Step3 branch semantics as topology-semantic continuous arms, not mechanically cut them at internal nodes.
- **FR-004**: System MUST define Step4’s first-layer unit as an ordered adjacent branch pair `(L, R)`.
- **FR-005**: For continuous complex/merge, system MUST allow the current unit’s executable pair to continue across same-case sibling internal member nodes when the same `pair-middle` semantic remains continuous, open, and unambiguous.
- **FR-006**: System MUST keep `unit_population_node_ids` anchored to the current representative node even when pair propagation crosses sibling internal nodes.
- **FR-007**: System MUST treat `context_augmented_node_ids` as chain/external context hints only, not event-unit population input or a shortcut for widening executable branch boundaries.
- **FR-008**: System MUST propagate `(L, R, middle-region)` rather than a single road in complex / multi sibling traversal.
- **FR-009**: System MUST select sibling-node arms in this order: external-associated-road consistency, no inserted roads between `L' / R'`, preserved left/right order, and only then minimum turn as tie-breaker.
- **FR-010**: System MUST define unit-local `event_branch_ids / boundary_branch_ids / preferred_axis_branch_id` from the current unit’s merge/diverge pair semantics, not by silently falling back to the case-level `main pair`.
- **FR-011**: System MUST forbid Step4 from silently widening complex sub-unit scope back to the whole corridor without surfacing an explicit degraded state.
- **FR-012**: System MUST split Step4 evidence geometry into at least `selected_component_union_geometry`, `localized_evidence_core_geometry`, and `coarse_anchor_zone_geometry`.
- **FR-013**: System MUST split Step4 point semantics into `fact_reference_point` and `review_materialized_point`.
- **FR-014**: System MUST keep the existing exception that allows shared physical component usage when `same axis` and `|Δs| > 5m`.
- **FR-015**: System MUST modularize `event_interpretation.py` into an unchanged public facade plus internal submodules for shared helpers, branch variants, and case-level selection without changing Step4 behavior.

### Key Entities

- **Case Coordination Skeleton**: Step3 case-level coordination result. It is used for member population, chain relation, overview, and cross-unit orchestration.
- **Executable Unit Skeleton**: Step3 unit-level structure that Step4 is allowed to consume for actual fact interpretation.
- **Branch Continuation Context**: `continuous complex/merge` 下，用于判断当前 unit 的某条 branch 是否可跨 same-case sibling internal node 延续的局部语义约束；它不能扩大 `unit population`，也不能把整条 case corridor 直接开放给当前 unit。
- **Ordered Branch Pair `(L, R)`**: Step4 当前 unit 的左右边界；它们是 Step3 输出的语义连续 branch，不是单条 road。
- **External Associated Road**: 从当前 unit 边界 branch 沿允许方向持续追溯，首次走出当前 complex 后连接到的第一条非 complex 内部 road。
- **Closed Interval**: 当前 unit 的两条边界 branch 在 complex 内重新闭合，形成封闭 middle-region，且不再通向新的 external associated road。
- **Unit Envelope**: Step4 unit input bundle containing `unit_population_node_ids`, `context_augmented_node_ids`, `event_branch_ids`, `boundary_branch_ids`, `preferred_axis_branch_id`.
- **Selected Component Union Geometry**: 当前 unit 选中的物理 DivStrip component 完整并集，用于 component ownership。
- **Localized Evidence Core Geometry**: 当前 unit 的 localized throat/tip 邻域证据，用于 core-segment ownership 与 review。
- **Coarse Anchor Zone Geometry**: 粗参考区，仅用于审计可视化，不得代理 component ownership。
- **Fact Reference Point**: 与 `event_chosen_s_m` 对齐的事实参考点。
- **Review Materialized Point**: 仅用于 PNG 的可视化参考点。

## Known Source-of-Truth Conflicts To Freeze Before Formal Backwrite

1. `REQUIREMENT.md` 已把 Step4 unit 明确为有序相邻 pair `(L, R)`，但当前 source-of-truth 仍以匿名 branch 集为主叙述。
2. `REQUIREMENT.md` 已要求 sibling node 传播 `(L, R, middle-region)` 与四条 arm 选择规则，但当前 `INTERFACE_CONTRACT.md / architecture/*` 仍只有粗粒度 branch continuation 表述。
3. `context_augmented_node_ids` 目前既被放进 `unit envelope`，又被 source-of-truth 限定为 hint-only，缺少“same-case sibling pair propagation 不属于这类 hint”的正式区分。
4. 当前 source-of-truth 仍把 complex `~60m` 邻域收紧写进策略层，与输入需求中“沿 pair-middle 延伸直到语义边界/Step2 上限”的纵向边界定义冲突。

## Success Criteria

### Measurable Outcomes

- **SC-001**: Spec 明确区分 Step3 `case coordination skeleton` 与 `unit-level executable skeleton`。
- **SC-002**: Spec 明确限定 Step4 只能消费 unit-level executable skeleton。
- **SC-003**: Spec 明确 continuous complex/merge 下“unit population 不扩，但 branch continuation 可跨 sibling internal node”的修复边界。
- **SC-004**: Spec 明确列出当前 T04 source-of-truth 冲突点，并把本轮正式文档回写与代码修复范围收口到 Step3/Step4。
