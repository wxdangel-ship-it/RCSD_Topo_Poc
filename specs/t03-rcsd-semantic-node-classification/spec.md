# Feature Specification: T03 RCSD semantic node classification

**Date**: 2026-04-28
**Module**: T03 virtual junction anchor

## Product View

T03 must not treat `RCSDNode.mainnodeid` as an automatic semantic-junction fact. A non-empty and non-`0` `mainnodeid` only marks a semantic-junction candidate or grouping hint. The final business meaning must use the same standard for nodes with and without `mainnodeid`.

## Requirements

- **FR-001**: A `RCSDNode` with non-empty and non-`0` `mainnodeid` is only a semantic candidate.
- **FR-002**: A candidate whose effective RCSD degree is `2` must be treated as a nonsemantic connector, the same as a single node without `mainnodeid`.
- **FR-003**: A candidate on a final u-turn structure must not become required/support/strong related semantic evidence.
- **FR-004**: `related_outside_scope_rcsdroad_ids` may only use a one-hop effective-degree-2 connector from `required_rcsdroad_ids`; `support_rcsdroad_ids` and `related_group_rcsdroad_ids` must not seed outside-scope expansion.
- **FR-005**: `related_outside_scope_rcsdroad_ids` must stop at effective semantic junctions, remote / unpackaged endpoints, non-active endpoints, and any connector outside the current allowed/candidate scope.
- **FR-006**: Step5 must classify effective-degree-2 connector nodes as `nonsemantic_connector_rcsdnode_ids` regardless of `mainnodeid`.
- **FR-007**: Step6 must consume Step4 terminal-node classification and must not use degree-2 connector nodes as horizontal semantic extent anchors.

## Role Perspectives

- Product: preserve visual/business intent by avoiding false cross-junction expansion while allowing true same-path connector continuation.
- Architecture: Step4 owns RCSD semantic classification; Step5 and Step6 consume Step4 facts rather than redefining `mainnodeid`.
- Development: remove `mainnodeid != 0` as an exclusion predicate for connector classification; replace it with effective-degree and u-turn facts.
- Testing: cover synthetic mainnodeid-degree2 connector behavior and real cases `709632 / 707476 / 706389 / 506658745`.
- QA: verify formal accepted/rejected behavior remains stable and audit fields explain connector vs semantic-junction decisions.

## Out Of Scope

- No new Step3 business rule rewrite.
- No PNG/review path change.
- No formal output filename change.
- No module naming change.
