# Feature Specification: T03 Step67 Foreign Mask Normalization

**Feature Branch**: `codex/t03-step67-directional-cut`  
**Created**: 2026-04-18  
**Status**: Draft  
**Input**: User clarification: "Step5 不应生成 4m/5m foreign road context；Step6 对 Roads / RCSDRoad 只保留 1m 级负向掩膜，并采用 spec-kit + 多 Agent 方式整体修复。"

## Context

- 现有 `t03-step67-directional-cut` 已经把 `20m` directional cut 放进 Step6 主构面，但 foreign 仍沿用旧的 Step45 polygon context 链。
- 当前实现里，Step45 会生成 `foreign_swsd_context_geometry` / `foreign_rcsd_context_geometry` 两套 buffer 过的 polygon，再由 Step6 统一 `+1m` 继续扣减。
- 真实结果表明，这条链会把 `698330` 这类本应保留的 selected surface 误缩短，也会把 `706389 / 707476` 这类已经建立语义关联的 case 错杀为 foreign failure。
- 本轮又新增了 Step45 upstream clarified requirement：经 `degree = 2` connector node 串接的 candidate `RCSDRoad` 会先按 road chain 合并，再参与 `required/support/excluded` 分类；Step6 foreign mask 只消费 merge 后的 retained/excluded 结果。

## Thread-Level Clarified Requirement

以下条目为本轮线程级 clarified requirement，不假装是旧正式文档已经冻结的事实：

1. Step5 的职责是 RCSD 分组 / 筛选与审计，不应继续生成 4m/5m 的 hard foreign polygon context。
2. Step6 的 hard foreign subtract 只保留 `1m` 级 road-like negative mask，不再叠加 Step45 polygon context。
3. `node` 类 foreign / excluded 对象继续保留在 Step45 审计里，但本轮不再作为 Step6 hard negative mask。
4. 当前 SWSD foreign 不再通过 Step45 `foreign_swsd_context` 进入 Step6；Step3 legal-space 仍是 SWSD 空间边界的正式前置层。
5. Step7 主状态维持二态 `accepted / rejected`；`V1-V5` 继续只属于视觉审计层。
6. Step6 本轮不再按 merge 前碎段 `RCSDRoad` 单独解释 foreign；所有 road-like foreign carrier 都以上游 Step45 chain merge 后的 retained/excluded 结果为准。

## User Scenarios & Testing

### User Story 1 - Step5 不再输出 hard foreign polygon context (Priority: P1)

作为 Step45/Step67 维护者，我需要 Step5 停掉对 `foreign_swsd_context` / `foreign_rcsd_context` 的 polygon 构造，让 foreign hard constraint 回到更窄、更可解释的边界。

**Why this priority**: 当前的 4m/5m polygon context 是 foreign 误杀的主根因。

**Independent Test**: 在 synthetic overlap case 上，只检查 Step45 输出和审计字段即可验证，不依赖 Step67 批跑。

**Acceptance Scenarios**:

1. **Given** synthetic overlap case 存在当前 selected surface 外侧的 SWSD foreign road，**When** 构建 Step45 结果，**Then** `foreign_swsd_context_geometry` 必须为空，`foreign_swsd_road_ids` 必须为空。
2. **Given** excluded / true foreign RCSD node 存在，**When** 构建 Step45 结果，**Then** node id 仍必须保留在审计中，但 `foreign_rcsd_context_geometry` 不得再以 polygon context 输出。

### User Story 2 - Step6 只消费 road-like 1m mask (Priority: P1)

作为 Step6 几何求解维护者，我需要 Step6 的 foreign subtract 只基于 road-like carrier 的 `1m` negative mask，这样扣减宽度与写出的 foreign mask 图层一致，不再出现多层 buffer 叠加。

**Why this priority**: 当前的 `4m/5m + 1m` 叠加不是业务口径，而是历史实现遗留。

**Independent Test**: 在 focused Step67 unit test 上，只检查 `foreign_mask_mode / foreign_mask_sources` 与最终状态即可确认。

**Acceptance Scenarios**:

1. **Given** Step45 输出包含 `excluded_rcsdroad_geometry`，**When** Step6 构建 foreign mask，**Then** 必须只对该 road-like carrier 做 `1m` buffer 后参与 subtract。
2. **Given** Step45 输出包含 `excluded_rcsdnode_geometry`，**When** Step6 构建 foreign mask，**Then** 该 node 几何不得进入 hard subtract mask。

### User Story 3 - 真实 case 恢复正确路径 (Priority: P1)

作为人工复核者，我需要 `698330 / 706389 / 707476 / 520394575` 这四类代表性 case 在新口径下给出稳定、可解释的结果。

**Why this priority**: 它们分别覆盖了 selected-surface 误伤、node-based foreign 误杀与 negative guard 三类核心风险。

**Independent Test**: 逐个 real case 跑 Step45->Step67，即可确认本轮 foreign normalization 是否成立。

**Acceptance Scenarios**:

1. **Given** `698330`，**When** 运行 Step67，**Then** selected roads 的纵向长度不得再因 foreign mask 缩短，且最终结果为 `accepted`。
2. **Given** `706389` 与 `707476`，**When** 运行 Step67，**Then** 不得再因 excluded node / foreign node 被判 `foreign_intrusion`，且最终结果为 `accepted`。
3. **Given** `520394575`，**When** 运行 Step67，**Then** 该 case 仍必须保持 `rejected`，不得被 foreign normalization 洗白。

## Edge Cases

- 某些 case 可能同时存在 `excluded_rcsdroad` 与 `excluded_rcsdnode`；本轮只把 road-like geometry 作为 hard mask，node 只保留审计，不在本轮宣称已解决所有 node 语义边界。
- `single_sided_t_mouth` 的横向 `5m` 特化仍未在本轮收口；本轮只保证 foreign normalization 不把该专项失败误洗白。
- `Step45` 的 `foreign_*_context.gpkg` 输出文件暂时保留为接口占位，避免 run-root 结构震荡；本轮允许其内容为空。

## Requirements

### Functional Requirements

- **FR-001**: System MUST stop generating Step45 hard foreign polygon context for `foreign_swsd_context_geometry` and `foreign_rcsd_context_geometry`.
- **FR-002**: System MUST keep `excluded_rcsdnode_ids`, `true_foreign_rcsdnode_ids`, and connector-node audit fields in Step45 audit output.
- **FR-003**: System MUST build Step6 `foreign_mask_geometry` from road-like carrier only, with a unified `1m` negative mask.
- **FR-004**: System MUST NOT include Step45 node geometries in the Step6 hard foreign subtract path in this round.
- **FR-005**: System MUST emit Step6 audit fields that make the new mask source explicit, including `foreign_mask_mode` and `foreign_mask_sources`.
- **FR-006**: System MUST keep `698330` accepted and preserve selected-road length after the mask normalization.
- **FR-007**: System MUST recover `706389` and `707476` from node-based foreign rejection to accepted.
- **FR-008**: System MUST keep `520394575` rejected after the foreign mask normalization.
- **FR-009**: System MUST NOT introduce any new CLI or execution entrypoint in this round.

### Key Entities

- **Road-Like Foreign Carrier**: 本轮允许进入 Step6 hard subtract 的线性几何载体；当前实现只包括 `excluded_rcsdroad_geometry`。
- **Audit-Only Node Foreign**: 保留在 Step45 审计中的 node 类 foreign/excluded 对象，本轮不进入 Step6 hard subtract。
- **Normalized Foreign Mask Geometry**: Step6 实际参与 subtract 的 `1m` negative mask polygon，同时也是落盘与渲染的约束图层。

## Success Criteria

### Measurable Outcomes

- **SC-001**: Step45 输出中的 `foreign_swsd_context_geometry` / `foreign_rcsd_context_geometry` 默认为空，不再承载 hard foreign polygon context。
- **SC-002**: Step6 不再对 Step45 polygon context 再做额外 `+1m` buffer，`step6_constraint_foreign_mask.gpkg` 与实际 subtract mask 保持一致。
- **SC-003**: `698330` 在 real-case 回归中保持 `accepted` 且 selected-road longitudinal length 不再缩短。
- **SC-004**: `706389` 与 `707476` 在 real-case 回归中从 foreign failure 恢复为 `accepted`。
- **SC-005**: `520394575` 在 real-case 回归中仍保持 `rejected`。
