# Feature Specification: T03 Step45 Degree-2 RCSDRoad Chain Merge

**Feature Branch**: `codex/t03-step67-directional-cut`  
**Created**: 2026-04-18  
**Status**: Draft  
**Input**: User clarification: "不要考虑角度，只有是二度关联的RCSDRoad都合并作为一条RCSDRoad进行考虑"

## Context

- 当前 T03 Step45 已经把 `degree = 2` 的 `RCSDNode` 作为 connector node 审计，但此前并未把该 connector 两侧的 `RCSDRoad` 先合并成同一条 road chain，再参与 `required/support/excluded` 分类。
- 真实 case `787133` 证明，若仍按碎段 `road_id` 分别分类，会把同一条 through-road 的后一段打成 `excluded_rcsdroad`，再在 Step6 中错误进入 hard negative mask。
- 用户已明确确认：本轮 chain merge 不考虑角度，只要 candidate `RCSDRoad` 通过 `degree = 2` connector node 串接，就应视为同一条 `RCSDRoad chain` 统一考虑。

## Thread-Level Clarified Requirement

以下条目为本轮线程级 clarified requirement，不假装是旧正式文档已经冻结的事实：

1. `degree = 2` 的 `RCSDNode` 继续只作为 connector，不进入 `required semantic core node`。
2. 任意 candidate `RCSDRoad` 只要经 `degree = 2` connector 串接，就必须先按同一 `RCSDRoad chain` 合并，再参与 Step45 `required / support / excluded` 分类。
3. 本轮 chain merge 不考虑角度，不使用方向连续性作为 merge 前提。
4. chain 一旦被保留为 `required` 或 `support`，其成员 `road_id` 不得再同时出现在 `excluded_rcsdroad_ids`。
5. Step45 审计必须显式输出 `degree2_connector_candidate_rcsdnode_ids` 与 `degree2_merged_rcsdroad_groups`，用于解释分类结果。

## User Scenarios & Testing

### User Story 1 - 合并 degree-2 chain 后再做 required/support 分类 (Priority: P1)

作为 Step45 维护者，我需要在 `required / support / excluded` 分类前，先把经 `degree = 2` connector 串接的 `RCSDRoad` 合并成 road chain，这样不会把同一路链拆成 retained + excluded。

**Why this priority**: 这是 `787133` 类失败的直接根因。

**Independent Test**: synthetic Step45 case 即可独立验证，不依赖 Step67。

**Acceptance Scenarios**:

1. **Given** 两条 candidate `RCSDRoad` 仅通过 `degree = 2` connector node 串接，**When** Step45 分类，**Then** 它们必须先被归并到同一 chain，再统一落入 `required` 或 `support`。
2. **Given** 合并后的 chain 中至少一个成员已被判为 retained，**When** 输出 `excluded_rcsdroad_ids`，**Then** 同链其它成员不得再落入 `excluded_rcsdroad_ids`。

### User Story 2 - 合并规则不考虑角度 (Priority: P1)

作为规则确认者，我需要 degree-2 chain merge 不引入角度过滤，这样业务规则与用户已确认口径一致。

**Why this priority**: 当前口径已经明确“不要考虑角度”。

**Independent Test**: synthetic 直角链 case 即可验证。

**Acceptance Scenarios**:

1. **Given** 两条 candidate `RCSDRoad` 通过 `degree = 2` connector node 串接且互相成直角，**When** Step45 分类，**Then** 它们仍必须被归并到同一 chain。

### User Story 3 - 真实 case 787133 不再拆成 support + excluded (Priority: P1)

作为人工复核者，我需要 `787133` 在 chain merge 落地后，不再把 `5395678910152738` 当作 `excluded_rcsdroad`，从而避免 Step6 hard foreign mask 的误包。

**Why this priority**: 这是本轮最关键的真实锚点。

**Independent Test**: 真实 case `787133` 跑 Step45->Step67 即可确认。

**Acceptance Scenarios**:

1. **Given** `787133`，**When** 运行 Step45，**Then** `support_rcsdroad_ids` 必须同时包含 `5395678910152720` 与 `5395678910152738`，且 `excluded_rcsdroad_ids` 为空。
2. **Given** `787133`，**When** 继续运行 Step67，**Then** 不得再因 `excluded_rcsdroad` 误包而失败，最终结果应为 `accepted`。

## Edge Cases

- 多级传递 chain：`road A -> degree2 -> road B -> degree2 -> road C` 也应作为同一 chain 合并；本轮不因 chain 长度增加而切回角度规则。
- connector node 本身仍不提升为 semantic core node；被合并的是 road chain，不是 node 语义。
- blocked / not_established case 也应保持 schema 稳定，输出空的 `degree2_merged_rcsdroad_groups`。

## Requirements

### Functional Requirements

- **FR-001**: System MUST identify candidate `RCSDRoad` chains connected through `degree = 2` connector nodes before Step45 `required/support/excluded` classification.
- **FR-002**: System MUST merge degree-2-connected road chains without any angle-based gating in this round.
- **FR-003**: System MUST expand retained `required` and `support` road sets from chain identity back to member `road_id` sets.
- **FR-004**: System MUST NOT allow any retained chain member to appear in `excluded_rcsdroad_ids`.
- **FR-005**: System MUST emit `degree2_connector_candidate_rcsdnode_ids` and `degree2_merged_rcsdroad_groups` in Step45 audit/status outputs.
- **FR-006**: System MUST keep blocked Step45 outputs schema-stable by emitting empty `degree2_merged_rcsdroad_groups`.
- **FR-007**: System MUST make `787133` recover from `excluded_rcsdroad` split and pass Step67.

### Key Entities

- **Degree-2 Connector Node**: graph degree 为 `2`、仅用于串接 road chain 的 `RCSDNode`；不进入 semantic core。
- **RCSDRoad Chain**: 经一个或多个 degree-2 connector node 串接形成的 road 成员集合；本轮为 Step45 road 分类的最小工作单元。
- **Expanded Retained Road IDs**: 以 chain 为单位判定后，再展开回成员 `road_id` 的 `required / support` 最终输出集合。

## Success Criteria

### Measurable Outcomes

- **SC-001**: synthetic 直角 chain case 中，degree-2 connector 两侧 road 必须被归并为同一 chain，且不因角度被拆开。
- **SC-002**: `787133` 的 `support_rcsdroad_ids` 同时包含 `5395678910152720` 与 `5395678910152738`，`excluded_rcsdroad_ids` 为空。
- **SC-003**: `787133` 在 real-case Step67 回归中从 `rejected / V4` 恢复为 `accepted / V1`。
