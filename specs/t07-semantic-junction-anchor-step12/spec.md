# Feature Specification: T07 Semantic Junction Anchor Step1/Step2

**Feature Branch**: `codex/t07-semantic-junction-anchor-step12`
**Created**: 2026-05-21
**Status**: Draft - user-confirmed requirement, implementation not started
**Input**: User request to refactor T02 Step1/Step2 business requirements into T07, only for semantic-junction-level `has_evd / is_anchor / anchor_reason`, without Segment processing.

## Context

- 2026-05-23 更新：用户已选择授权路径 `1`，允许登记 `t07_semantic_junction_anchor`、同步项目级 source-of-truth 与入口治理，并新增内网执行脚本。
- T02 当前 Step1/Step2 同时包含语义路口集合与 Segment 引用路口集合，且会输出 `segment.has_evd` 与 Segment 视角 summary。
- T07 的业务诉求是从 T02 Step1/Step2 中抽取“语义路口级资料 gate + anchor recognition”，并剥离全部 Segment 处理。
- 用户已确认：
  - 字段只使用 `kind_2`，不使用 `Kind_2`。
  - `kind_2` 范围判断以代表 node 为准。
  - `kind_2` 不在 `{4, 8, 16, 64, 128, 2048}` 的语义路口，`has_evd / is_anchor / anchor_reason` 均保持或写为 `NULL`。

## User Scenarios & Testing

### User Story 1 - 语义路口级 has_evd gate (Priority: P1)

作为数据处理维护者，我需要 T07 只按 `nodes` 的语义路口集合计算代表 node 的 `has_evd`，避免 Segment 引用关系改变路口级资料存在性结果。

**Why this priority**: `has_evd` 是 Step2 的前置 gate，且用户明确要求只做语义路口级处理。

**Independent Test**: 构造包含多节点 `mainnodeid` 组、单节点 fallback、合法/非法 `kind_2`、命中/未命中 `DriveZone` 的节点输入；运行 Step1 后只检查代表 node 的 `has_evd`。

**Acceptance Scenarios**:

1. **Given** 代表 node `kind_2 = 4` 且组内任一 node 落入或接触 `DriveZone`，**When** 执行 T07 Step1，**Then** 代表 node `has_evd = yes`。
2. **Given** 代表 node `kind_2 = 8` 且组内所有 node 均未命中 `DriveZone`，**When** 执行 T07 Step1，**Then** 代表 node `has_evd = no`。
3. **Given** 代表 node `kind_2 = 1`，**When** 执行 T07 Step1，**Then** 代表 node `has_evd = NULL`，且该语义路口不进入 Step2。

### User Story 2 - 语义路口级 anchor recognition (Priority: P1)

作为下游融合模块维护者，我需要 T07 只对 `has_evd = yes` 的语义路口执行 `RCSDIntersection` 锚定判定，并输出代表 node 的 `is_anchor / anchor_reason`。

**Why this priority**: `is_anchor / anchor_reason` 是 T02 Step2 要继承的核心业务输出。

**Independent Test**: 构造多组语义路口与 `RCSDIntersection` 面，覆盖单面命中、未命中、多面命中、同一面多组命中、roundabout、T 型路口。

**Acceptance Scenarios**:

1. **Given** 语义路口 `has_evd = yes` 且命中唯一 `RCSDIntersection`，**When** 执行 T07 Step2，**Then** 代表 node `is_anchor = yes`。
2. **Given** 语义路口 `has_evd = yes` 且未命中任何 `RCSDIntersection`，**When** 执行 T07 Step2，**Then** 代表 node `is_anchor = no`。
3. **Given** 语义路口 `has_evd != yes`，**When** 执行 T07 Step2，**Then** 代表 node `is_anchor = NULL` 且 `anchor_reason = NULL`。

### User Story 3 - Segment 剥离与审计可追溯 (Priority: P2)

作为 QA，我需要确认 T07 不读取、不输出、不统计 Segment，并能从 summary/audit 中解释每个语义路口的处理状态。

**Why this priority**: 用户明确要求“不对 Segment 进行处理”，这必须是可验证边界，而不是实现细节。

**Independent Test**: 运行 T07 时不提供 `segment.gpkg`；检查输出中没有 `segment.gpkg`、`segment.has_evd`、`summary_by_s_grade`、`anchor_summary_by_s_grade`。

**Acceptance Scenarios**:

1. **Given** 只提供 `nodes / DriveZone / RCSDIntersection`，**When** 执行 T07 Step1/Step2，**Then** 运行不要求 `segment` 输入。
2. **Given** 输出目录，**When** 检查 T07 产物，**Then** 不存在任何 Segment 输出或 Segment 视角 summary。

## Edge Cases

- `mainnodeid` 有效成组但组内不存在 `id == mainnodeid` 的代表 node：必须显式审计 `representative_node_missing`，不得 silent fallback。
- `mainnodeid` 为空的 node：作为 singleton 语义路口处理。
- 代表 node `kind_2` 为空、`0` 或不在 `{4, 8, 16, 64, 128, 2048}`：`has_evd / is_anchor / anchor_reason` 均为 `NULL`。
- 从属 node 不写业务状态；从属 node 空值不得解释为失败、未处理或候选结果。
- `DriveZone` 或 `RCSDIntersection` CRS 缺失、不可投影、几何为空：执行失败并留审计，不得转成业务 `no`。
- `RCSDIntersection` 边界接触与 T02 一致，视为命中。
- `fail2` 优先级高于 `fail1`，且覆盖 `anchor_reason`。

## Requirements

### Functional Requirements

- **FR-001**: T07 Step1 MUST only read `nodes` and `DriveZone`; it MUST NOT require or read `segment`.
- **FR-002**: T07 Step1 MUST build semantic junction groups from `nodes.mainnodeid`; non-empty `mainnodeid` groups nodes together, and missing/empty `mainnodeid` falls back to singleton node groups.
- **FR-003**: T07 Step1 MUST use the representative node's `kind_2` as the only kind filter.
- **FR-004**: T07 Step1 MUST only process representative `kind_2 in {4, 8, 16, 64, 128, 2048}`.
- **FR-005**: T07 Step1 MUST set representative `has_evd = yes` when any group node intersects or touches `DriveZone`, and `has_evd = no` when all group nodes miss `DriveZone`.
- **FR-006**: T07 Step1 MUST set or keep representative `has_evd = NULL` for all representative `kind_2` outside `{4, 8, 16, 64, 128, 2048}`.
- **FR-007**: T07 Step2 MUST only process semantic junctions with representative `has_evd = yes`.
- **FR-008**: T07 Step2 MUST set representative `is_anchor = yes / no / fail1 / fail2 / NULL` and `anchor_reason = roundabout / t / NULL`.
- **FR-009**: T07 Step2 MUST preserve T02 conflict semantics: multi-intersection group conflict is `fail1`, shared intersection across multiple semantic groups is `fail2`, and `fail2 > fail1`.
- **FR-010**: T07 Step2 MUST set `anchor_reason = roundabout` only for representative `kind_2 = 64` when all group nodes hit any `RCSDIntersection`.
- **FR-011**: T07 Step2 MUST set `anchor_reason = t` only for representative `kind_2 = 2048` when all group nodes hit any `RCSDIntersection`.
- **FR-012**: T07 MUST NOT implement T02 Stage3/Stage4 virtual polygon logic in this scope.
- **FR-013**: T07 MUST NOT add a repo-level CLI, `tools/`, module `run.py`, or module `__main__.py` entrypoint. The only approved repo-level script for this round is `scripts/t07_run_semantic_junction_anchor_innernet.sh`.
- **FR-014**: T07 outputs MUST be auditable at semantic-junction level and MUST distinguish business `no` from execution failures.
- **FR-015**: T07 implementation MUST cover CRS correctness, topology consistency, geometry semantic explainability, audit traceability, and performance verifiability before closeout.

### Non-Goals

- No Segment input, Segment output, Segment summary, or Segment replacement.
- No T02 Stage3 virtual intersection anchoring.
- No T02 Stage4 div/merge polygon processing.
- No final unique anchor decision, probability, confidence, candidate scoring, or recall rescue.
- No project-level module registration until the user explicitly authorizes source-of-truth updates.

### Key Entities

- **Semantic Junction Group**: A node group formed by valid `mainnodeid`, or a singleton node when `mainnodeid` is empty.
- **Representative Node**: The only node in a semantic junction group that receives `has_evd / is_anchor / anchor_reason`.
- **DriveZone Evidence**: Polygon evidence used by Step1 to decide semantic-junction-level `has_evd`.
- **RCSDIntersection Evidence**: Polygon evidence used by Step2 to decide semantic-junction-level anchor state.
- **T07 Audit Row**: Machine-readable row explaining scope, representative node, `kind_2`, decision state, reason, and geometry/CRS validation status.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A synthetic Step1 test suite covers all allowed `kind_2` values `{4, 8, 16, 64, 128, 2048}` and at least one disallowed value.
- **SC-002**: A synthetic Step2 test suite covers `yes / no / fail1 / fail2 / NULL`, including `roundabout` and `t` `anchor_reason`.
- **SC-003**: T07 can run without any `segment` input and produces no Segment artifact.
- **SC-004**: Output `nodes.gpkg` writes business fields only on representative nodes.
- **SC-005**: Audit/summary can count processed, skipped-by-kind, has_evd yes/no/null, anchor yes/no/fail/null, and execution-error groups.
- **SC-006**: No new official entrypoint is introduced in this round.
