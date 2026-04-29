# Feature Specification: T03 RCSD u-turn and same-path chain semantics

**Feature Branch**: `codex/t03-rcsd-uturn-chain-semantics`
**Created**: 2026-04-28
**Status**: Implemented
**Input**: User confirmed new T03 RCSD semantics for same-path chains, narrowed u-turn filtering, and T-mouth strong semantic RCSD limits.

## Context

T03 already supports `center_junction` and `single_sided_t_mouth` through the formal `Step1~Step7` chain. Existing Step4 semantics filter `u_turn_rcsdroad` before recomputing `degree = 2 connector` and `RCSDRoad chain merge`.

Case `706389` exposed a semantic gap: a short RCSDRoad in a route-to-route same-path chain can satisfy the old local u-turn geometry predicate, causing a legitimate RCSDNode to be downgraded from strong related semantic evidence. The user confirmed that this is not the desired RCSD interpretation.

## User-Confirmed Rules

1. RCSDRoads linked between RCSD junctions through degree-2 connectors are a same-path chain and must be treated as one path-level unit.
2. `u_turn_rcsdroad` must mean a short connector between upstream/downstream or opposite parallel road paths, not a short segment inside the same path chain.
3. Same-path chain protection has higher priority than u-turn filtering.
4. Under `single_sided_t_mouth`, strong related RCSD semantic junctions are limited to at most two. Nodes generated only by u-turn structures do not count as strong related semantic junctions.

## User Scenarios & Testing

### User Story 1 - Same-path chain is protected before u-turn filtering

As a T03 reviewer, I need RCSDRoad chains between semantic RCSD junctions to remain available for Step4 classification, so legitimate path segments are not removed as u-turns.

**Acceptance Scenarios**:

1. Given a short RCSDRoad that belongs to a same-path chain between candidate semantic RCSDNodes, when Step4 evaluates u-turn candidates, then that road must be protected and must not appear in `u_turn_rcsdroad_ids`.
2. Given a same-path chain member is protected, when Step5 builds excluded road masks, then that member must not become hard negative.

### User Story 2 - Real u-turn short connectors are still filtered

As a T03 reviewer, I still need true RCSD u-turn short connectors to be removed from current-case semantic association.

**Acceptance Scenarios**:

1. Given a short RCSDRoad that connects opposite parallel path sides and is not part of a protected same-path chain, when Step4 runs, then it must remain in `u_turn_rcsdroad_ids`.
2. Given a true u-turn road is filtered, when Step6 traces single-sided geometry, then it must not be reinterpreted as local required RC.

### User Story 3 - T-mouth strong semantic RCSD nodes are capped and auditable

As a T03 reviewer, I need `single_sided_t_mouth` to expose at most two strong related RCSD semantic junctions, so extra path/turn artifacts do not inflate the semantic core.

**Acceptance Scenarios**:

1. Given more than two RCSDNode candidates are near a T-mouth, when Step4 chooses strong related RCSD semantic nodes, then no more than two remain in the strong semantic set.
2. Given Case `706389`, when Step4 and Step6 run, then `5395732498090127` is not downgraded by u-turn filtering, the case remains accepted, and the trace remains explainable.

## Requirements

- **FR-001**: Step4 MUST identify protected same-path RCSDRoad chains before final u-turn filtering.
- **FR-002**: Step4 MUST NOT classify protected same-path chain members as `u_turn_rcsdroad`.
- **FR-003**: Step4 MUST keep true u-turn filtering for unprotected short opposite-path connectors.
- **FR-004**: Step4 MUST expose audit fields for protected same-path chains, u-turn candidates, qualified u-turns, and u-turns rejected by same-path protection.
- **FR-005**: Step4 MUST cap `single_sided_t_mouth` strong related RCSD semantic junctions to at most two.
- **FR-006**: Step6 MUST prefer Step4's strong T-mouth semantic RCSD nodes for horizontal tracing when they cover both horizontal sides without shrinking confirmed terminal extent; otherwise it MUST keep the existing reachable endpoint tracing behavior.
- **FR-007**: Existing formal output filenames, Step7 machine states, CRS, and Step3 frozen semantics MUST remain unchanged.

## Success Criteria

- **SC-001**: `706389` keeps `accepted` final state and includes `5395732498090127` in the strong T-mouth semantic RCSD set.
- **SC-002**: A synthetic same-path short chain member does not appear in `u_turn_rcsdroad_ids`.
- **SC-003**: A synthetic true u-turn short connector still appears in `u_turn_rcsdroad_ids`.
- **SC-004**: Regression tests for association and Step6/Step7 continue to pass.

## Key Entities

- **Same-path RCSDRoad Chain**: A path-level group of RCSDRoads connected through degree-2 connector nodes and bounded by candidate semantic RCSDNodes.
- **Protected Same-path Road**: A road member of a same-path chain that cannot be downgraded to `u_turn_rcsdroad`.
- **Qualified u-turn RCSDRoad**: A short unprotected connector that satisfies the narrowed u-turn semantics and is removed from downstream RCSD association.
- **T-mouth Strong RCSD Semantic Node**: A strong related RCSDNode retained by Step4 for `single_sided_t_mouth`; capped to at most two.

## Assumptions

- All geometry remains in `EPSG:3857`.
- Step4 remains the owner of RCSD association semantics; Step6 consumes Step4's facts and does not redefine u-turn business meaning.
- This feature does not add, remove, or rename any repo official CLI or shell wrapper.
