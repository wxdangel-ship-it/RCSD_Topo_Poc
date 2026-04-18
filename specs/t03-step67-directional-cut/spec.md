# Feature Specification: T03 Step67 Directional Cut

**Feature Branch**: `codex/t03-step67-directional-cut`  
**Created**: 2026-04-18  
**Status**: Draft  
**Input**: User clarification: "先解决 20 米规则没有落地的问题，并按 spec-kit + 多 Agent 方式执行。"

## Context

- 当前模块正式文档仍冻结在 `Step4-5`，`Step6/7` 尚未作为模块级长期真相收口。
- 当前代码里的 `20m` 只用于 `selected_road_core_cover_ratio` 校验窗口，没有参与 Step6 polygon 构造。
- 本轮已获得线程级澄清：`20m` 必须进入 Step6 构面主链，按 entering / exiting roads 的方向裁剪候选空间。

## Thread-Level Clarified Requirement

以下条目为本轮线程级 clarified requirement，不假装是旧正式文档已经冻结的事实：

1. Step6 的 `20m` 是几何构造规则，不是仅用于验证的窗口。
2. Step6 应先按道路方向裁剪 Step3 `allowed_space`，再执行 foreign / must-cover / required RC 校验。
3. 当某方向在候选空间内本来就不足 `20m` 时，应保留该方向的现有候选空间边界，不得强行截短。
4. `B / support_only` 与 `C / no_related_rcsd` 在 Step6 合法收敛后允许成功。
5. Step6 发现 foreign 冲突时，应先通过方向裁剪尝试收敛合法解，不能把 overlap 直接当最终结论。
6. Step7 主策略输出维持二态 `accepted / rejected`；`V1-V5` 只属于目视审计层。

## User Scenarios & Testing

### User Story 1 - 20m 进入 Step6 构面主链 (Priority: P1)

作为 T03 Step67 维护者，我需要 `20m` 从校验窗口前移为方向裁剪规则，这样 `584141` 之类 case 的最终面才真正由路向截断生成，而不是由 buffer 收敛碰巧形成。

**Why this priority**: 当前最直接的业务偏差是 `20m` 没有参与构面，导致 Step6 审计和实际业务理解不一致。

**Independent Test**: 在合成 center-junction case 上，仅检查最终 polygon 与 selected roads 的相交长度和 branch-cut audit，就能判断 `20m` 是否已进入构面主链。

**Acceptance Scenarios**:

1. **Given** selected roads 在候选空间内可用长度大于 `20m`，**When** Step6 构面，**Then** 最终面必须由该方向 `20m` 近似垂直裁剪后的候选空间收敛而来。
2. **Given** 某条 selected road 在候选空间内可用长度不足 `20m`，**When** Step6 构面，**Then** 审计必须记录 `preserve_candidate_boundary=true`，且该方向不得被额外截短。

### User Story 2 - support_only / no_related_rcsd 走合法成功路径 (Priority: P1)

作为业务审计者，我需要 `B / support_only` 和 `C / no_related_rcsd` 在 Step6 合法收敛后能进入成功，而不是沿用旧的 review guard。

**Why this priority**: 这是当前线程已确认的新业务口径，直接影响 `584141` 这一类 case 的判断。

**Independent Test**: 在 `support_only` 合成 case 上，只检查 Step6 构面与 Step7 二态结果即可验证，不依赖全量批跑。

**Acceptance Scenarios**:

1. **Given** `association_class = B` 且 Step6 满足 legal / foreign / must-cover / required RC，**When** Step7 发布，**Then** 主状态必须是 `accepted`。
2. **Given** `association_class = C` 且不存在条件性 required RC 缺口，**When** Step6 满足前置硬约束，**Then** 主状态必须是 `accepted`。

### User Story 3 - 审计要直接证明 20m 是否生效 (Priority: P2)

作为人工复核者，我需要 Step6 审计直接告诉我每条 road branch 的 `available_length / cut_length / preserve_candidate_boundary`，这样我能快速确认像 `584141` 这样的 case 是否真的按规则裁剪。

**Why this priority**: 没有 branch 级审计，就无法证明 `20m` 是构造规则而不是文本说明。

**Independent Test**: 只检查 `step6_audit.json` 的 branch-cut 字段即可确认。

**Acceptance Scenarios**:

1. **Given** 任意建立成功或失败的 Step6 case，**When** 写出 `step6_audit.json`，**Then** 必须存在 branch-cut 规则与每条 branch 的审计记录。

## Edge Cases

- 若 selected road 为穿越 target anchor 的整段折线，应按 target anchor 两侧拆成独立 branch，再分别判定 `20m` 裁剪。
- 若 branch 在 candidate 内部很短，不能因为 road centerline 长度不足就误判为“需要额外截短”。
- 若 Step6 方向裁剪后仍无法同时满足 foreign / must-cover / required RC，允许失败，但必须保留明确根因。
- 本轮不宣称已完成 `A` 类趋势匹配和 `single_sided_t_mouth` 横向 `5m` 特化，只要求 `20m` 已进入 Step6 构面主链并可审计。

## Requirements

### Functional Requirements

- **FR-001**: System MUST compute Step6 polygon from `Step3 allowed_space` intersected with selected-road directional cut geometry, rather than from whole-road buffer union.
- **FR-002**: System MUST build directional cut geometry from selected-road branches anchored at the current semantic junction target group.
- **FR-003**: System MUST cap each eligible branch at `20m` when the candidate space can support `20m`, and MUST preserve the candidate-space boundary when it cannot.
- **FR-004**: System MUST continue enforcing Step6 hard priority as `legal space -> foreign exclusion -> Step1 must-cover -> Step4 conditional required RC -> bounded optimization`.
- **FR-005**: System MUST emit branch-level Step6 audit fields including `available_length_m`, `cut_length_m`, and `preserve_candidate_boundary`.
- **FR-006**: System MUST keep `B / support_only` and `C / no_related_rcsd` on the accepted path when Step6 converges under frozen constraints.
- **FR-007**: System MUST NOT introduce any new CLI or execution entrypoint in this round.

### Key Entities

- **Directional Cut Geometry**: 由 selected-road branches 生成的宽窗裁剪几何，用于对 `allowed_space` 做 Step6 主裁剪。
- **Directional Branch Audit Row**: 单条 road branch 的裁剪审计记录，至少包含 branch id、candidate 可用长度、实际 cut 长度与是否保留候选空间边界。
- **Step6 Polygon Seed**: `allowed_space` 与 directional cut geometry 相交后的候选 polygon，作为 foreign subtract 之前的 Step6 主候选面。

## Success Criteria

### Measurable Outcomes

- **SC-001**: `step67_geometry.py` 中的 `20m` 不再只服务 `selected_road_core_cover_ratio` 校验，而是直接进入 polygon 构造。
- **SC-002**: 在合成 long-road case 上，最终 polygon 对 selected roads 的覆盖长度不再无限延伸，而是被 `20m` branch-cut 明显收敛。
- **SC-003**: `step6_audit.json` 可以直接看出每条 branch 是否命中 `20m` 截断或 `preserve_candidate_boundary`。
- **SC-004**: `support_only` 合成 case 在 Step6 合法收敛后维持 `accepted`，不回退到旧的 review guard。
