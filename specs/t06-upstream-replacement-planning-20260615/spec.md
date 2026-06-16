# Feature Specification: T06 上游化替换计划与问题回流

**Feature Branch**: `codex/t10-rcsd-replacement-quality-20260614`  
**Created**: 2026-06-15  
**Status**: Draft  
**Input**: 用户授权全模块架构改造，要求把本轮发现的 Segment 替换修复前置到应有模块，并保证当前已成功替换 Segment 不业务回退。

## User Scenarios & Testing

### User Story 1 - 统一替换计划 (Priority: P1)

作为端到端质量审计者，我需要 T06 Step2 明确发布最终替换执行计划，使 Step3 只执行 Step2 已发布的计划，不再额外承担替换可行性判断。

**Why this priority**: 当前 `Step2 replaceable` 与 `Step3 replaced` 不一致，根因是 Step3 直接消费额外审计产物，导致漏斗口径失真。

**Independent Test**: 跑 T06 单元测试，确认 Step2 输出 `t06_segment_replacement_plan.*`，Step3 在存在该计划时优先按计划消费 path-corridor group 与特殊路口组。

**Acceptance Scenarios**:

1. **Given** Step2 已生成标准 replaceable、特殊路口组审计和 path-corridor group 审计，**When** Step2 closeout，**Then** 生成统一 replacement plan 并在 summary 中记录计划数量。
2. **Given** Step3 输入目录存在 replacement plan，**When** 执行 Step3，**Then** Step3 优先消费 replacement plan 中的扩展替换范围，而不是直接重新解释 group audit。

### User Story 2 - 失败问题回流注册 (Priority: P1)

作为业务迭代负责人，我需要 T06 对失败 Segment 输出可审计的问题注册表，明确建议归属 T01/T03/T04/T05/T08/T06 或数据裁剪/原始数据问题，以驱动后续上游模块迭代。

**Why this priority**: 用户要求不是 case 级补丁，而是根因追溯到应修模块。

**Independent Test**: 构造 rejected 与已被当前计划覆盖的 Segment，确认 problem registry 能区分 `requires_upstream_iteration`、`covered_by_replacement_plan` 与 `resolved_in_step2_plan`。

### User Story 3 - 既有成功不回退 (Priority: P1)

作为回归验证者，我需要当前已经成功替换的 Segment 在架构收敛后保持成功，尤其是本轮已提升的 group/path-corridor 与特殊路口组场景。

**Why this priority**: 用户明确要求当前成功 Segment 不业务回退。

**Independent Test**: 执行 T06 单元测试与 4 个 T10 Case 端到端复跑，对比 Step3 replaced count 与关键 Segment 状态不下降。

## Requirements

### Functional Requirements

- **FR-001**: T06 Step2 MUST 输出 `t06_segment_replacement_plan.gpkg/csv/json`，作为 Step3 的统一执行计划。
- **FR-002**: replacement plan MUST 至少覆盖标准 Step2 replaceable、passed 特殊路口组内部 RCSD 对象、passed path-corridor group replacement。
- **FR-003**: T06 Step3 MUST 在存在 replacement plan 时优先消费 replacement plan；仅在旧产物无 plan 时回退 legacy audit 兼容路径。
- **FR-004**: T06 Step2 MUST 输出 `t06_segment_replacement_problem_registry.csv/json/gpkg`，记录失败或当前 T06 自动覆盖的问题、根因分类、建议归属模块和证据来源。
- **FR-005**: T06 Step3 MUST 保留现有 copy-on-write 语义，不修改 T01/T05/Step2 输入成果。
- **FR-006**: T10 funnel MUST 能继续读取现有 Step2/Step3 summary，并可逐步扩展 replacement plan 指标。

### Key Entities

- **Replacement Plan Row**: 一个 Step3 可执行或上下文可消费的计划单元，包含 `replacement_plan_id / execution_scope / plan_status / rcsd_road_ids / retained_node_ids / group_segment_ids / source_artifact`。
- **Problem Registry Row**: 一个 Segment 替换问题或已覆盖问题的审计记录，包含 `problem_status / root_cause_category / upstream_issue_owner / recommended_module / feedback_action / evidence_artifacts`。

## Success Criteria

### Measurable Outcomes

- **SC-001**: T06 单元测试通过，且 Step2 summary 包含 replacement plan 与 problem registry 输出路径和计数。
- **SC-002**: 现有 path-corridor group replacement 单元测试在不依赖 group audit 直接输入的情况下仍能通过。
- **SC-003**: 4 个 T10 Case 端到端结果不出现本轮已成功 replaced Segment 回退。
- **SC-004**: GIS / 拓扑质量说明覆盖 CRS、拓扑一致性、几何语义、审计可追溯性、性能可验证性。
