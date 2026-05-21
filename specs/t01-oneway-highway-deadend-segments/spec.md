# Feature Specification: T01 单向高速与断头 Segment 扩展

**Feature Branch**: `codex/t01-oneway-highway-deadend-speckit`  
**Created**: 2026-05-21  
**Status**: Draft - requirements confirmed by user  
**Input**: 用户确认 T01 需要在单向 Segment 中放开 `road_kind=1`，将 `kind_2=128` 作为复杂分歧合流路口纳入单向 terminate，并允许断头路以 leaf node 形式构成 Segment。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 单向高速 Segment 构建 (Priority: P1)

内网操作者在最新 T01 Step5 refreshed 结果上运行 `t01-run-skill-v1` 或 `t01-continue-oneway-segment` 时，`road_kind=1` 的封闭式道路不再被单向补段阶段排除，使高速/高速相关单向 road 可以进入候选、trace 与 Step6 发布。

**Why this priority**: 当前大量高速单向 road 因 `road_kind != 1` 过滤无法构段，是内网结果中最直接的召回缺口。

**Independent Test**: 构造只含 `road_kind=1`、`direction in {2,3}`、非 `formway=128` 的单向链路，运行 Step5 后单向补段，应输出 `0-1单` 或 `0-2单` Segment，并进入最终 `segment.gpkg`。

**Acceptance Scenarios**:

1. **Given** Step5 refreshed roads 中存在未构段的 `road_kind=1` 单向高速链路，且两端满足当前单向 terminate 规则，**When** 执行单向补段，**Then** 该链路应获得 `segmentid` 与单向 `sgrade`。
2. **Given** 双向 Step2/Step4/Step5C 输入仍包含 `road_kind=1` road，**When** 执行双向阶段，**Then** 双向阶段仍保持当前 accepted baseline，不把 `road_kind=1` 纳入双向构段。

---

### User Story 2 - 复杂分歧合流路口作为单向 terminate (Priority: P1)

内网操作者在单向补段中希望 `kind_2=128` 的复杂分歧合流路口参与 terminate 判断，避免高速/匝道链路因端点语义不被识别而留在 `unsegmented_roads`。

**Why this priority**: 用户确认 `kind_2=128` 正式代表复杂分歧合流路口，属于当前内网单向高速缺段的关键端点语义。

**Independent Test**: 构造端点 `kind_2=128`、`closed_con in {2,3}` 的单向链路，运行 Step5 后单向补段，应在 `0-1单 / 0-2单` 阶段成功截停并构段。

**Acceptance Scenarios**:

1. **Given** 单向候选 road 从 `kind_2=4` 端点通向 `kind_2=128` 端点，**When** 执行 `0-1单` 或 `0-2单` 阶段，**Then** `kind_2=128` 端点应作为 terminate 截停。
2. **Given** `kind_2=128` 节点存在但 `closed_con` 不在当前阶段允许集合，**When** 执行单向补段，**Then** 不应因 `kind_2=128` 单独强行构段。

---

### User Story 3 - 断头 road bundle 以 leaf node 构成 Segment (Priority: P2)

内网操作者希望断头路不再全部遗留为未构段 road。断头路可由一条双向 road 表达，也可由两个物理 Node 构成的语义路口与两条方向互补的单向 road 表达；当一端是合法语义端点、另一端是 leaf node，且 leaf 端没有其他有效延展时，应形成可发布 Segment。

**Why this priority**: 该能力会改变双向构段语义、`pair_nodes / junc_nodes` 与 Step6 聚合规则，风险高于单向补段修正，应独立实现与验收。

**Independent Test**: 分别构造合法语义端点连接到单条双向 road 的断头样例，以及两个物理 Node 组成同一语义路口、两条方向互补单向 road 连接 leaf node 的断头样例。运行 T01 后应生成 Segment，`pair_nodes` 可表达语义端点与 leaf node，`junc_nodes` 不误报 leaf node。

**Acceptance Scenarios**:

1. **Given** 单条双向可通行 road 一端连接合法语义端点、另一端为 leaf node，**When** 执行 T01，**Then** 该 road 应构成 dead-end Segment。
2. **Given** 两条方向互补的单向 road 在同一合法语义端点与同一 leaf node 之间形成 dead-end bundle，且合法语义端点可由两个物理 Node 通过 `mainnodeid / working_mainnodeid` 表达，**When** 执行 T01，**Then** 两条 road 应构成同一个 dead-end Segment。
3. **Given** leaf 端 road 为 `formway=128` 或 right-turn-only，**When** 执行 T01，**Then** 仍应按排除规则不构成 Segment。

---

### User Story 4 - 可追溯审计 (Priority: P2)

内网操作者需要解释每条原始 SWSD road 为什么被构成双向、构成单向、被排除或仍未构段。

**Why this priority**: 没有 road-level 审计，无法区分输入数据问题、业务过滤、trace 失败与 Step6 发布问题。

**Independent Test**: 使用小型混合样例运行后，审计输出中每条未构段 road 都有明确 `audit_reason`。

**Acceptance Scenarios**:

1. **Given** 单向候选 road 因无下游 terminate 失败，**When** 检查审计输出，**Then** 应标记为 trace 类失败，而不是笼统 `unsegmented`。
2. **Given** `road_kind=1` 单向 road 成功构段，**When** 检查审计摘要，**Then** 应统计 `road_kind_1_oneway_built_count`。

### Edge Cases

- `road_kind=1` 只在单向补段阶段放开，双向阶段继续保持 `road_kind != 1`。
- `kind_2=128` 只加入 `0-1单 / 0-2单`，不加入 `0-0单`，除非后续另行确认一级封闭连通口径。
- `formway=128` 与 right-turn-only road 仍不得参与 T01 Segment 构建。
- leaf node 只能表达断头端，不得被误当作普通语义路口 through。
- dead-end leaf Segment 仅允许单条双向 road 或两条方向互补的单向 road bundle；单条未成对单向 road 暂不作为 dead-end Segment 构建。
- geometry 坐标方向与 `snodeid -> enodeid` 不一致时，审计必须标记风险，不得 silent fix。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: T01 单向补段阶段 MUST allow `road_kind=1` road to enter candidate collection when all other single-way filters pass.
- **FR-002**: T01双向 Step2/Step4/Step5A/Step5B/Step5C MUST keep the existing `road_kind != 1` accepted baseline unless a separate explicit requirement changes it.
- **FR-003**: T01 单向 `0-1单` and `0-2单` terminate node sets MUST include `kind_2=128` with existing `closed_con` and `grade_2` stage constraints.
- **FR-004**: T01 单向 `0-0单` terminate node set MUST remain unchanged for this feature.
- **FR-005**: T01 MUST support a dead-end Segment mode where one endpoint is a valid semantic endpoint and the other endpoint is a leaf node, subject to road exclusion rules; supported road bundle forms are one bidirectional road or two reciprocal one-way roads.
- **FR-006**: Step6 MUST preserve single-way grades and correctly publish dead-end Segment fields without misclassifying leaf nodes as normal inner junction nodes.
- **FR-007**: The implementation MUST emit road-level audit data sufficient to distinguish candidate filtering, terminate absence, trace failure, dead-end construction, and Step6 publish mismatch.
- **FR-008**: The module source-of-truth documents MUST be updated in the same implementation round as code changes.
- **FR-009**: The implementation MUST not add a new repo-level CLI or script entrypoint.
- **FR-010**: Existing active freeze baseline MUST NOT be refreshed automatically.

### Key Entities

- **Oneway Candidate Road**: Unsegmented Step5-refreshed road eligible for single-way trace, now including `road_kind=1` while still excluding `formway=128` and right-turn-only.
- **Complex Diverge/Merge Terminate**: Semantic node represented by `kind_2=128`, eligible as `0-1单 / 0-2单` terminate when `closed_con / grade_2` also match.
- **Dead-End Segment**: Segment with one valid semantic endpoint and one leaf node endpoint, built from either a single bidirectional road or a reciprocal two-road one-way bundle.
- **Road Audit Record**: Per-road explanation record linking original SWSD/T01 road id to filter, trace, construction, and publish status.

## Role Coverage *(mandatory for this repository)*

- **Product**: Prioritize recall for highway/complex diverge-merge single-way Segment gaps while preserving accepted dual-way baseline.
- **Architecture**: Keep dual-way and single-way semantics separated; introduce dead-end Segment as explicit sub-mode, not implicit fallback.
- **Development**: Implement in existing T01 modules without new entrypoints; prefer small helper functions and tests.
- **Testing**: Add focused unit tests for `road_kind=1`, `kind_2=128`, dead-end leaf, and Step6 publication.
- **QA**: Require GIS/topology audit checks and innernet full-input comparison before declaring accepted.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A local fixture with `road_kind=1` single-way candidate roads produces at least one `0-1单` or `0-2单` Segment.
- **SC-002**: A local fixture with `kind_2=128` endpoint produces a single-way Segment terminating at that endpoint.
- **SC-003**: A local dead-end fixture produces one Segment with no leaf-node misclassification in `junc_nodes`.
- **SC-004**: Existing T01 single-way and Step6 local tests continue to pass.
- **SC-005**: Innernet audit can report counts for `road_kind=1` candidates, `kind_2=128` terminates, dead-end built roads, and remaining unsegmented reasons.
