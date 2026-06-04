# Feature Specification: T07 Semantic Junction Anchor Step1/Step2/Step3

**Feature Branch**: `codex/t07-semantic-junction-anchor-step12`
**Created**: 2026-05-21
**Status**: Active - Step1/Step2 implemented; Step3 relation补锚 implemented
**Input**: User request to refactor T02 Step1/Step2 business requirements into T07, only for semantic-junction-level `has_evd / is_anchor / anchor_reason`, without Segment processing; subsequent request to add independent Step3 using T05 `intersection_match_all.geojson`.

## Context

- 2026-05-23 更新：用户已选择授权路径 `1`，允许登记 `t07_semantic_junction_anchor`、同步项目级 source-of-truth 与入口治理，并新增内网执行脚本。
- 2026-05-29 更新：用户修正 Step2 / Step3 口径：`kind_2 = 64 / 128` 在 Step2 写 `no / NULL`；`kind_2 = 2048` 不满足全组同一 `RCSDIntersection` 时写 `no / NULL`；Step3 只以 `has_evd = yes` 且 `is_anchor = no` 的 SWSD 语义路口为候选。
- 2026-06-04 更新：用户修正 Step2 一面多 SWSD 语义路口口径：若同一个 `RCSDIntersection` 面包含多个 SWSD 语义路口，代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}` 均记录为 `fail2`。
- 2026-06-04 更新：用户修正 Step3 处理范围，Step3 仅处理代表 node `kind_2 in {4, 8, 16}`，不再处理 `kind_2 = 2048`。
- 2026-05-29 更新：用户要求 T07 对齐 T02/T03/T04 handoff 成果，Step2 输出 `t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.csv/json`；Step3 输出复制 Step2 surface 的 `t07_rcsdintersection_anchor_surface.gpkg`，以及合并 `intersection_match_t07.geojson` 成功补锚成果、并记录 Step2 / Step3 锚定数量的 `t07_swsd_rcsd_relation_evidence.csv/json`。
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

**Independent Test**: 构造多组语义路口与 `RCSDIntersection` 面，覆盖单面命中、未命中、多面命中、同一面多组命中、`kind_2 = 64 / 128` 专项基础写 `no`、T 型路口同面命中、T 型路口不满足条件，以及同一面多组命中对 `{4,8,16,64,128,2048}` 的 `fail2` 覆盖。

**Acceptance Scenarios**:

1. **Given** 语义路口 `has_evd = yes` 且命中唯一 `RCSDIntersection`，**When** 执行 T07 Step2，**Then** 代表 node `is_anchor = yes`。
2. **Given** 语义路口 `has_evd = yes` 且未命中任何 `RCSDIntersection`，**When** 执行 T07 Step2，**Then** 代表 node `is_anchor = no`。
3. **Given** 语义路口 `has_evd != yes`，**When** 执行 T07 Step2，**Then** 代表 node `is_anchor = NULL` 且 `anchor_reason = NULL`。
4. **Given** T07 Step2 产生锚定成功与失败语义路口，**When** 检查 Step2 输出，**Then** 存在 `t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.csv/json`，且 surface 只包含 `is_anchor = yes` 且可定位 `RCSDIntersection` 的记录。

### User Story 3 - Segment 剥离与审计可追溯 (Priority: P2)

作为 QA，我需要确认 T07 不读取、不输出、不统计 Segment，并能从 summary/audit 中解释每个语义路口的处理状态。

**Why this priority**: 用户明确要求“不对 Segment 进行处理”，这必须是可验证边界，而不是实现细节。

**Independent Test**: 运行 T07 时不提供 `segment.gpkg`；检查输出中没有 `segment.gpkg`、`segment.has_evd`、`summary_by_s_grade`、`anchor_summary_by_s_grade`。

**Acceptance Scenarios**:

1. **Given** 只提供 `nodes / DriveZone / RCSDIntersection`，**When** 执行 T07 Step1/Step2，**Then** 运行不要求 `segment` 输入。
2. **Given** 输出目录，**When** 检查 T07 产物，**Then** 不存在任何 Segment 输出或 Segment 视角 summary。

### User Story 4 - T05 relation 补锚 Step3 (Priority: P1)

作为数据融合维护者，我需要 T07 独立读取 T05 `intersection_match_all.geojson`，把已经成功关联到仍存在 RCSD 语义路口的候选 SWSD 语义路口补写为锚定。

**Why this priority**: Step3 是用户新增的正式业务口径，且要求不与 Step1/Step2 合并。

**Independent Test**: 构造 Step2 后 `nodes`、T05 relation 主表和输入 `RCSDNode`，覆盖成功 relation、relation 失败、relation 缺失、RCSD `base_id` 不存在、`kind_2 = 64` 不进入 Step3。

**Acceptance Scenarios**:

1. **Given** SWSD 代表 node `kind_2 = 4`、`has_evd = yes`、`is_anchor = no`，且 T05 relation `status = 0 / base_id != 0`，并且输入 `RCSDNode` 存在该 `base_id`，**When** 执行 Step3，**Then** 输出该 relation 到 `intersection_match_t07.geojson`，并把 SWSD 代表 node `is_anchor = yes / anchor_reason = NULL`。
2. **Given** 候选 SWSD 语义路口存在 T05 relation，但输入 `RCSDNode` 不存在 `base_id`，**When** 执行 Step3，**Then** 不写锚定成功，并在 audit / summary 中记录 `rcsd_junction_missing`。
3. **Given** 代表 node `kind_2 = 64 / 128`，**When** 执行 Step3，**Then** 不进入补锚规则。
4. **Given** Step2 evidence 与 Step3 成功 relation 同时存在，**When** 执行 Step3，**Then** 输出合并后的 `t07_swsd_rcsd_relation_evidence.csv/json`，同一 `target_id` 以 Step3 成功 relation 行覆盖 Step2 原失败行，并在顶层记录 Step2 / Step3 锚定数量。
5. **Given** Step2 输出目录存在 `t07_rcsdintersection_anchor_surface.gpkg`，**When** 执行 Step3，**Then** Step3 输出目录也必须存在同名 surface，内容复制 Step2 结果。

## Edge Cases

- `mainnodeid` 有效成组但组内不存在 `id == mainnodeid` 的代表 node：必须显式审计 `representative_node_missing`，不得 silent fallback。
- `mainnodeid` 为空的 node：作为 singleton 语义路口处理。
- 代表 node `kind_2` 为空、`0` 或不在 `{4, 8, 16, 64, 128, 2048}`：`has_evd / is_anchor / anchor_reason` 均为 `NULL`。
- 从属 node 不写业务状态；从属 node 空值不得解释为失败、未处理或候选结果。
- `DriveZone` 或 `RCSDIntersection` CRS 缺失、不可投影、几何为空：执行失败并留审计，不得转成业务 `no`。
- `RCSDIntersection` 边界接触与 T02 一致，视为命中。
- `fail2` 优先级高于 `fail1` 与基础 `yes / no / t` 判定，且覆盖 `anchor_reason`；一面多 SWSD 语义路口场景覆盖代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}`。
- Step3 候选只包括代表 node `kind_2 in {4, 8, 16}`、`has_evd = yes` 且 `is_anchor = no` 的语义路口。
- `intersection_match_all.geojson` 中失败 relation（`status != 0` 或 `base_id = 0`）不得触发锚定成功。
- T05 relation 成功但输入 `RCSDNode.id/mainnodeid` 不存在对应 `base_id` 时不得触发锚定成功。

## Requirements

### Functional Requirements

- **FR-001**: T07 Step1 MUST only read `nodes` and `DriveZone`; it MUST NOT require or read `segment`.
- **FR-002**: T07 Step1 MUST build semantic junction groups from `nodes.mainnodeid`; non-empty `mainnodeid` groups nodes together, and missing/empty `mainnodeid` falls back to singleton node groups.
- **FR-003**: T07 Step1 MUST use the representative node's `kind_2` as the only kind filter.
- **FR-004**: T07 Step1 MUST only process representative `kind_2 in {4, 8, 16, 64, 128, 2048}`.
- **FR-005**: T07 Step1 MUST set representative `has_evd = yes` when any group node intersects or touches `DriveZone`, and `has_evd = no` when all group nodes miss `DriveZone`.
- **FR-006**: T07 Step1 MUST set or keep representative `has_evd = NULL` for all representative `kind_2` outside `{4, 8, 16, 64, 128, 2048}`.
- **FR-007**: T07 Step2 MUST only process semantic junctions with representative `has_evd = yes`.
- **FR-008**: T07 Step2 MUST set representative `is_anchor = yes / no / fail1 / fail2 / NULL` and `anchor_reason = t / NULL`.
- **FR-009**: T07 Step2 MUST preserve T02 conflict semantics for handled kinds: multi-intersection group conflict is `fail1` where applicable, shared intersection across multiple semantic groups is `fail2`, and `fail2 > fail1`.
- **FR-010**: T07 Step2 MUST set representative `kind_2 = 64 / 128` to base `is_anchor = no` and `anchor_reason = NULL`; if the same `RCSDIntersection` also corresponds to other SWSD semantic junctions, it MUST override these groups to `fail2`.
- **FR-011**: T07 Step2 MUST set `anchor_reason = t` only for representative `kind_2 = 2048` when every node in the semantic junction group hits the same single `RCSDIntersection`; otherwise it MUST set base `is_anchor = no` and `anchor_reason = NULL`. If the same `RCSDIntersection` also corresponds to other SWSD semantic junctions, it MUST override `kind_2 = 2048` to `fail2`.
- **FR-012**: T07 MUST NOT implement T02 Stage3/Stage4 virtual polygon logic in this scope.
- **FR-013**: T07 MUST NOT add a repo-level CLI, `tools/`, module `run.py`, or module `__main__.py` entrypoint. The approved repo-level scripts are `scripts/t07_run_semantic_junction_anchor_innernet.sh` and `scripts/t07_run_step3_intersection_match_innernet.sh`.
- **FR-014**: T07 outputs MUST be auditable at semantic-junction level and MUST distinguish business `no` from execution failures.
- **FR-015**: T07 implementation MUST cover CRS correctness, topology consistency, geometry semantic explainability, audit traceability, and performance verifiability before closeout.
- **FR-016**: T07 Step3 MUST run as an independent callable/script and MUST NOT be merged into Step1/Step2 execution.
- **FR-017**: T07 Step3 MUST only process representative `kind_2 in {4, 8, 16}` where `has_evd = yes` and `is_anchor = no`.
- **FR-018**: T07 Step3 MUST only accept T05 relation rows with `target_id = SWSD semantic junction id`, `status = 0`, and non-zero `base_id`.
- **FR-019**: T07 Step3 MUST verify accepted relation `base_id` exists in input `RCSDNode.id/mainnodeid` before writing `is_anchor = yes`.
- **FR-020**: T07 Step3 MUST run T05-style relation cardinality QC for candidate successful relations and output `relation_cardinality_errors.csv/json` for one target to many base ids, many targets to one base id, and duplicate success targets.
- **FR-020**: T07 Step3 MUST output accepted relation rows to `intersection_match_t07.geojson` and keep that output aligned with the T05 relation CRS `CRS84`.
- **FR-021**: T07 Step2 MUST output `t07_rcsdintersection_anchor_surface.gpkg` using Step2 accepted `RCSDIntersection` surface candidates.
- **FR-022**: T07 Step2 MUST output `t07_swsd_rcsd_relation_evidence.csv/json` using the T02 relation evidence field family.
- **FR-023**: T07 Step3 MUST output `t07_rcsdintersection_anchor_surface.gpkg` by copying Step2 surface results.
- **FR-024**: T07 Step3 MUST output `t07_swsd_rcsd_relation_evidence.csv/json` by merging Step2 evidence with successful `intersection_match_t07.geojson` backfill rows, and MUST expose Step2 / Step3 anchor counts.

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
- **T05 Relation Evidence**: `intersection_match_all.geojson` rows with `target_id / base_id / status / level / is_highway`, used by Step3 for relation补锚 only.
- **intersection_match_t07**: Step3 accepted relation subset for candidates whose T05 relation succeeds and whose RCSD `base_id` exists in input `RCSDNode`.
- **T07 Audit Row**: Machine-readable row explaining scope, representative node, `kind_2`, decision state, reason, and geometry/CRS validation status.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A synthetic Step1 test suite covers all allowed `kind_2` values `{4, 8, 16, 64, 128, 2048}` and at least one disallowed value.
- **SC-002**: A synthetic Step2 test suite covers `yes / no / fail1 / fail2 / NULL`, including `kind_2 = 64 / 128` base `no / NULL`, `kind_2 = 2048` `t` success, `kind_2 = 2048` `no / NULL` fallback, and one shared `RCSDIntersection` overriding `kind_2 in {4, 8, 16, 64, 128, 2048}` to `fail2`.
- **SC-003**: T07 can run without any `segment` input and produces no Segment artifact.
- **SC-004**: Output `nodes.gpkg` writes business fields only on representative nodes.
- **SC-005**: Audit/summary can count processed, skipped-by-kind, has_evd yes/no/null, anchor yes/no/fail/null, and execution-error groups.
- **SC-006**: Step3 tests cover successful T05 relation, missing relation, failed relation, RCSD `base_id` missing, and `kind_2 = 64 / 128` exclusion.
- **SC-007**: Step2 tests assert `t07_rcsdintersection_anchor_surface.gpkg` and `t07_swsd_rcsd_relation_evidence.csv/json`; Step3 tests assert copied `t07_rcsdintersection_anchor_surface.gpkg`, merged `t07_swsd_rcsd_relation_evidence.csv/json`, and Step2 / Step3 anchor counts.
- **SC-007**: No new official CLI entrypoint is introduced in this round.
