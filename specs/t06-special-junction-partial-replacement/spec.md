# Feature Specification: T06 特殊路口局部替换策略

**Feature Branch**: `codex/t06-special-junction-partial-replacement`
**Created**: 2026-07-01
**Status**: Draft
**Input**: 用户确认 T06 环岛和复杂路口不再采用全组可替换才统一替换的策略，允许部分 Segment 在特殊路口边界处替换。

## User Scenarios & Testing

### User Story 1 - 环岛局部替换 (Priority: P1)

作为 T06 替换结果审核者，我需要当环岛无法被 RCSD 全部替换时，保留 SWSD 的环岛内部 road 与全部 nodes，同时允许已经可替换的 RCSD Segment 接到环岛端点。

**Why this priority**: 旧策略会因为一个环岛成员不可替换而移除同组已可替换 Segment，导致可安全替换的外接路段被误杀。

**Independent Test**: 构造部分可替换环岛，确认 `gate_status=partial`，已可替换 Segment 仍进入 `replaceable`，replacement plan 不发布环岛内部端点间的 RCSD Road。

### User Story 2 - 复杂路口局部替换 (Priority: P1)

作为复杂路口替换审核者，我需要复杂路口内 RCSD 可替换的联通 Road 整体替换，SWSD 不能替换的保留 road 继续保留，并由所有端点共同构成语义路口。

**Why this priority**: 复杂路口常见部分关系缺失，旧全组门控会阻断已经满足替换条件的联通 Road。

**Independent Test**: 复用已有 T06 特殊组 fixture，确认部分特殊组不会新增 `special_junction_group_not_fully_replaceable` 拒绝原因，也不会移除已硬审计通过的 `replaceable` Segment。

### User Story 3 - 全量可替换保持原策略 (Priority: P1)

作为回归验证者，我需要当环岛或复杂路口所有关联 Segment 都可替换时，仍按 RCSD 完整替换特殊组，不回退既有成功场景。

**Independent Test**: 对既有特殊组全通过用例做回归，确认 `gate_status=passed` 与 `special_junction_group_internal` 计划语义保持。

## Requirements

### Functional Requirements

- **FR-001**: T06 Step2 special junction gate MUST 输出 `passed / partial / blocked` 三态。
- **FR-002**: `partial` 组 MUST 只阻断缺失或不可替换的 Segment，不得移除已经硬审计为 `replaceable` 的 Segment。
- **FR-003**: 环岛 `partial` 组 MUST 保留 SWSD 环岛内部 road 与全部 nodes，不得在 replacement plan 中发布 RCSD 内部端点间 road。
- **FR-004**: 复杂路口 `partial` 组 MUST 保留不可替换 SWSD road；可替换的联通 RCSD Road 仍按标准/path-corridor 计划执行。
- **FR-005**: 只有 `passed` 特殊组 MAY 发布 `special_junction_group_internal` replacement plan。
- **FR-006**: Step3 语义路口输出 MUST 能承载 partial 特殊组端点集合，使替换后的 RCSD 端点和保留 SWSD 端点共同成组。
- **FR-007**: Step2 summary MUST 暴露 `special_junction_group_partial_count`，并保留旧字段兼容读取。

### Key Entities

- **Special Junction Gate Row**: 特殊路口组审计行，包含 `gate_status / associated_segment_ids / replaceable_segment_ids / missing_replaceable_segment_ids / rcsd_junction_road_ids`。
- **Partial Special Junction**: 至少一个关联 Segment 可替换、至少一个关联 Segment 不可替换的特殊路口组。
- **Semantic Junction Group**: Step3 输出的语义路口端点集合，用于表达 partial 特殊组中 RCSD 新端点与保留 SWSD 端点的共同路口语义。

## Success Criteria

- **SC-001**: 单元测试覆盖 partial 环岛不发布内部 RCSD Road、partial 复杂组不移除 replaceable Segment、全 blocked 组仍 blocked。
- **SC-002**: 至少一个既有复杂路口基准 Case 显示 partial 策略提升可替换数量，且不增加拓扑失败。
- **SC-003**: 至少一个既有全通过特殊组 Case 显示 replaced 结果不下降。
- **SC-004**: QA 回报覆盖 CRS、拓扑一致性、几何语义、审计可追溯性、性能可验证性。
