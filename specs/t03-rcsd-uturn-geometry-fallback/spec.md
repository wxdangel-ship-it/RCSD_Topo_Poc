# Feature Specification: T03 RCSD u-turn geometry fallback hardening

**Feature Branch**: `codex/t03-rcsd-uturn-geometry-fallback`  
**Created**: 2026-04-28  
**Status**: Implemented  
**Input**: User confirmed that `RCSDRoad.formway` is authoritative when present, and when absent geometry fallback may only filter a u-turn if semantic topology, trunk geometry, and trusted direction all agree.

## Context

T03 Step4 already prioritizes `RCSDRoad.formway`: when the field exists, `(formway & 1024) != 0` is the only u-turn criterion. Existing case packages can still miss this field, so Step4 needs a safer `geometry_fallback_no_formway` mode.

The old fallback used a broad local heuristic: short road plus opposite incident road evidence at both endpoints. Visual audits on cases such as `765003` showed this can misclassify short connectors or composite-junction fragments as u-turn roads.

## User-Confirmed Rules

1. A geometry-only RCSD u-turn candidate must connect two semantic RCSD junctions.
2. A semantic RCSD junction may be a single `RCSDNode` or a compact multi-node semantic junction.
3. Both endpoint semantic junctions must be effective degree 3: main-road entry, main-road exit, and u-turn entry/exit.
4. After removing the candidate u-turn road, the two main trunk road pairs must be nearly collinear at each endpoint.
5. The two endpoint trunk axes must be approximately parallel.
6. Trusted `direction` evidence must prove the two trunks run in opposite directions before the road is directly filtered.
7. If direction is unavailable or untrusted, the road is only a suspect u-turn and must remain in normal RCSD association while being recorded in audit.

## User Scenarios & Testing

### User Story 1 - Confirmed geometry fallback u-turn is filtered

As a T03 reviewer, I need a formway-missing but geometrically clear u-turn connector to be filtered only when the two semantic endpoints and trunk directions prove the u-turn semantics.

**Acceptance Scenarios**:

1. Given a short RCSDRoad connects two different effective-degree-3 semantic RCSD junctions, and the two main trunks are parallel with trusted opposite flow, when Step4 runs, then the road appears in `u_turn_rcsdroad_ids`.

### User Story 2 - Direction-ambiguous geometry candidate is audit-only

As a T03 reviewer, I need direction-ambiguous candidates to remain available for downstream association, so missing direction metadata does not delete legitimate RCSD evidence.

**Acceptance Scenarios**:

1. Given the same effective-degree-3 and parallel-trunk geometry, but host-road `direction` is unavailable, bidirectional, or otherwise untrusted, when Step4 runs, then the road appears in `u_turn_suspect_rcsdroad_ids` and does not appear in `u_turn_rcsdroad_ids`.

### User Story 3 - Composite and same-path structures are not over-filtered

As a T03 reviewer, I need same-path chains and composite semantic junction fragments to avoid geometry-only deletion.

**Acceptance Scenarios**:

1. Given a short road belongs to a protected same-path chain, when Step4 runs, then it must not appear in final `u_turn_rcsdroad_ids`.
2. Given Case `765003`, when Step4 runs without `formway`, then previously broad geometry candidates no longer become final u-turn roads.

## Requirements

- **FR-001**: Step4 MUST keep `formway_bit` mode authoritative when any active RCSDRoad has parseable `formway`.
- **FR-002**: Step4 MUST only enter `geometry_fallback_no_formway` when active RCSDRoads have no parseable `formway`.
- **FR-003**: Geometry fallback MUST require two different semantic endpoint groups, both effective degree 3.
- **FR-004**: Geometry fallback MUST require two host roads per endpoint after removing the candidate road, and those host roads MUST be nearly collinear.
- **FR-005**: Geometry fallback MUST require the two endpoint trunk axes to be nearly parallel.
- **FR-006**: Geometry fallback MUST directly filter only when trusted `direction` proves the two trunk flows are opposite.
- **FR-007**: Geometry fallback MUST classify direction-unavailable or direction-untrusted structural candidates as suspect audit-only.
- **FR-008**: Step4 MUST expose `u_turn_suspect_rcsdroad_ids` and `u_turn_suspect_rcsdroad_audit`.
- **FR-009**: Formal output filenames, Step3 frozen semantics, Step6 boundary-first semantics, Step7 machine states, CRS, and repo entrypoints MUST remain unchanged.

## Success Criteria

- **SC-001**: A synthetic effective-degree-3, parallel-trunk, trusted-opposite-flow candidate is filtered.
- **SC-002**: A synthetic effective-degree-3, parallel-trunk, untrusted-direction candidate is audit-only and not filtered.
- **SC-003**: Case `765003` has no final geometry-fallback u-turn road under missing `formway`.
- **SC-004**: Real regression cases `706389 / 707476 / 765003` remain accepted.

## Key Entities

- **Semantic RCSD Junction**: A single RCSDNode or compact multi-node same-`mainnodeid` group used as one junction for effective-degree calculations.
- **Effective Degree**: Count of external incident RCSDRoads after compact semantic grouping and excluding intra-group roads.
- **Host Trunk Pair**: The two non-u-turn incident RCSDRoads at one endpoint semantic junction.
- **Confirmed Geometry U-turn**: A candidate satisfying semantic endpoints, trunk geometry, and trusted opposite-flow direction evidence.
- **Suspect Geometry U-turn**: A candidate satisfying semantic endpoints and trunk geometry, but lacking trusted direction proof.

## Assumptions

- All geometry remains in `EPSG:3857`.
- `direction` follows existing T03/T02 semantics: `0/1` are bidirectional or not direction-unique, `2` is `snodeid -> enodeid`, `3` is `enodeid -> snodeid`.
- Step4 owns u-turn semantics; Step6 consumes Step4 facts and does not redefine u-turn business meaning.
