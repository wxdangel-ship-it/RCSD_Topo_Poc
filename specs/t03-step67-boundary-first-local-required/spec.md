# Feature Specification: T03 Step45/67 Boundary-First And U-Turn Filter Fix

**Feature Branch**: `codex/t03-step67-directional-cut`  
**Created**: 2026-04-18  
**Status**: Draft  
**Input**: User request: “请制定修复计划，对问题进行修复”

## Context

- 当前 Step6 的实现顺序是先按 directional cut 生成 `polygon_seed`，再把 `target / required node / required road` 整体 union 回 `raw_polygon`。
- 这个实现会导致 directional cut 只成为 seed 规则，而不是 final geometry 的硬边界。
- 同时，`single_sided_t_mouth` 的横向保留侧选择会被未过滤的 `RCSD` 局部语义干扰。
- 用户已经正式确认新的业务规则：
  - 若某条 `RCSDRoad` 两端分别关联方向相反的 `RCSDRoad`，则该 road 视为 `调头口 RCSDRoad`
  - `调头口 RCSDRoad` 在当前 case 语义处理中视为不存在
  - 去掉调头口后，再重算 `degree2 connector / chain merge / required-support-excluded`
  - 对 `single_sided_t_mouth + association_class=A`：
    - tracing seed 来自竖方向候选空间内的相关 `RCSDRoad / chain`
    - tracing 过程中的 `RCSDRoad` 不要求整体完全落在候选空间内
    - 只要最终确认的 terminal `RCSDNode` 落在横方向候选空间内，即可作为有效 tracing 结果
    - 若 tracing 无法在横方向两侧都确认 terminal `RCSDNode`，则横方向回到 generic directional boundary
    - 横方向边界以 terminal `RCSDNode` 为主锚点外扩 `5m`
    - 若前方已有其他直接关联语义路口（`RCSD / SWSD`），则必须在该处之前停止
- 真实表现为：
  - `707476` 审计里全部 branch 都是 `cut_at_20m`，但 final geometry 又长回接近 Step3 allowed boundary。
  - `709431` 一侧 branch 被误触发 `single_sided_semantic_plus_5m`，另一侧虽然 seed 已截到 `20m`，final 仍被回补拉长。
  - `706389` 的 `single_sided_t_mouth` 横向 pair road 中，只有包含正确 RCSD 语义外延的一侧应该被保留，另一侧仍应保持 `20m`。
  - `758888 / 851884` 在纯 boundary-first 下出现新的误拒绝，说明边界生成阶段还需要 target-connected regeneration。

## User Scenarios & Testing

### User Story 1 - Directional boundary must be final hard cap (Priority: P1)

作为维护者，我需要 Step6 先确定 directional boundary，再在边界内构面，而不是先裁剪再用 required RC 把面补回来。

**Independent Test**: `707476` 与 `709431` 的 final geometry 在 selected roads 上的覆盖长度必须与 `polygon_seed` 保持一致，不再长回 Step3 allowed full length。

### User Story 2 - Single-sided horizontal T-mouth rule must be trace-based (Priority: P1)

作为维护者，我需要 `single_sided_t_mouth + association_class=A` 的横向口门由 tracing 规则驱动，而不是由单纯的 required-node/road-endpoint 投影启发式驱动。

**Independent Test**: `706389` 的横方向口门由 tracing 可达的 terminal `RCSDNode` 决定，不再退化为纯 required-node/road-endpoint 投影；`709431` 在 tracing 无法形成横向 terminal node pair 时回到 generic `20m`。

### User Story 3 - Required RC validation must become local (Priority: P1)

作为维护者，我需要 `required RC must-cover` 在 directional boundary 内成立，而不是要求 final polygon 覆盖整条 required RCSDRoad。

**Independent Test**: Step6 审计应显式记录 `local_required_rcsdnode_ids`、`local_required_rcsdroad_ids` 与 `required_rc_cover_mode = local_required_rc_within_direction_boundary`。

### User Story 4 - Boundary generation must remain target-connected (Priority: P1)

作为维护者，我需要在 `single_sided_t_mouth` 场景中，如果初始 directional boundary 已经切掉了 target semantic cover，系统应先在边界生成阶段重新放宽相关 branch，而不是直接把 case 判成失败。

**Independent Test**: `758888 / 851884` 在开启 `boundary-first` 后仍保持 `accepted`，不新增伪失败。

## Requirements

### Functional Requirements

- **FR-001**: System MUST treat `polygon_seed` as the directional boundary for Step6 final geometry and MUST NOT let later union/cleanup escape that boundary.
- **FR-002**: System MUST localize required RC coverage to the directional boundary before constructing required cover geometry.
- **FR-003**: System MUST validate `required RC must-cover` against the localized required RC extent inside the directional boundary.
- **FR-004**: System MUST apply `RCSD 调头口过滤` before `degree2 connector / chain merge / required-support-excluded` classification.
- **FR-005**: System MUST implement `single_sided_t_mouth + association_class=A` horizontal mouth solving as a trace-based rule after `RCSD 调头口过滤`.
- **FR-005A**: System MUST start tracing from relevant `RCSDRoad / chain` inside the vertical candidate corridor.
- **FR-005B**: Intermediate traced `RCSDRoad` segments MAY leave the current candidate space, as long as the finally confirmed terminal `RCSDNode` falls inside the horizontal candidate corridor.
- **FR-005C**: System MUST require a confirmed horizontal terminal-node pair before enabling the `single_sided_t_mouth + A` horizontal special rule.
- **FR-005D**: System MUST determine the horizontal cut anchor from the traced terminal `RCSDNode`, then extend outward by `5m`.
- **FR-005E**: System MUST stop before the next directly-associated semantic junction ahead on the same side, whether the stop source is `RCSD` or `SWSD`.
- **FR-006**: System MUST regenerate directional boundary when a single-sided boundary-first cut would otherwise drop the target semantic cover.

## Success Criteria

- **SC-001**: `706389` remains accepted, and only the correct horizontal branch keeps `semantic + 5m`; the opposite horizontal branch returns to `20m`.
- **SC-002**: `707476` final geometry no longer regrows beyond the directional boundary; all selected road coverage lengths match `polygon_seed`.
- **SC-003**: `709431` no longer triggers `single_sided_semantic_plus_5m`; all selected road coverage lengths match `polygon_seed`.
- **SC-004**: `758888 / 851884` remain accepted after the change.
- **SC-005**: Existing focused Step45/Step67 regression tests continue to pass after the change.
