# Feature Specification: T03 Step67 Single-Sided Horizontal Cut Fix

**Feature Branch**: `codex/t03-step67-directional-cut`  
**Created**: 2026-04-18  
**Status**: Draft  
**Input**: User request: “706389，请评估在T型路口横方向的道路面截断是否符合业务需求规则……好的，请正式修复该问题”

## Context

- 当前 `single_sided_t_mouth` 在 Step6 中仍复用 generic `directional_selected_road_cut`，横向 pair roads 直接按 `20m` 处理。
- `706389` 已通过机器判定，但人工目视认为横方向道路面截断不符合业务规则。
- 已确认的 thread-level clarified requirement 是：
  - `single_sided_t_mouth` 竖方向仍按 `20m`
  - 横方向不应直接套 generic `20m`
  - 横方向应按“当前可确认的最外侧相关语义路口，再向外扩 `5m`，若候选空间不足则保留候选空间边界”

## User Scenarios & Testing

### User Story 1 - 修复 706389 横向截断 (Priority: P1)

作为维护者，我需要 `706389` 这类 `single_sided_t_mouth` case 的横方向主路面不再被 generic 20m 过度削窄。

**Independent Test**: `706389` 的横向 pair roads 在 Step6 审计中不再显示为 generic `cut_at_20m`，而应体现 single-sided 横向特化规则。

### User Story 2 - 不影响 generic case 与 remaining rejected anchor (Priority: P1)

作为维护者，我需要本次修复不要把 center case 或 `520394575` 之类 remaining anchor case 洗白。

**Independent Test**: 现有 Step67 focused pytest 继续通过，`520394575` 仍保持 rejected。

## Requirements

### Functional Requirements

- **FR-001**: System MUST add a `single_sided_t_mouth` horizontal-pair override on top of current Step6 directional cut.
- **FR-002**: System MUST keep vertical selected-road branches on `single_sided_t_mouth` under the current `20m` directional cut rule.
- **FR-003**: System MUST compute horizontal branch cut length from the farthest confirmed semantic extent on that branch plus `5m`, capped by available allowed-space length.
- **FR-004**: System MUST preserve candidate boundary when available allowed-space length is shorter than the requested horizontal extent.
- **FR-005**: System MUST keep solver details in implementation/audit only; no new repo official CLI or long-term contract freeze is introduced in this fix.

## Success Criteria

- **SC-001**: `706389` horizontal branches no longer use generic `cut_at_20m` in Step6 audit.
- **SC-002**: `706389` remains `accepted`, but the final polygon visually preserves more of the horizontal road surface consistent with the business rule.
- **SC-003**: `520394575` remains rejected.
