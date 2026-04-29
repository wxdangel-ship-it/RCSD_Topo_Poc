# Implementation Plan: T03 RCSD u-turn geometry fallback hardening

## Technical Context

- Module: `t03_virtual_junction_anchor`
- Primary contract:
  - `modules/t03_virtual_junction_anchor/INTERFACE_CONTRACT.md`
  - `modules/t03_virtual_junction_anchor/architecture/*.md`
- Primary implementation:
  - `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association.py`
- Tests:
  - `tests/modules/t03_virtual_junction_anchor/test_association.py`
  - `tests/modules/t03_virtual_junction_anchor/test_step6_step7_case_706389_707476_regression.py`

## Product / Architecture / Development / Testing / QA Views

- Product: Missing `formway` must not cause broad geometry deletion. Only direction-proven u-turn structures can be filtered; direction-ambiguous structures remain audit-only.
- Architecture: Step4 keeps `formway_bit` as authoritative mode and narrows `geometry_fallback_no_formway` into semantic topology, trunk geometry, and direction proof stages.
- Development: Keep the change localized to Step4 helpers, audit/status fields, tests, and contracts. Do not alter Step3, Step6 solver rules, Step7, CLI, scripts, or output filenames.
- Testing: Add synthetic tests for confirmed geometry u-turn and suspect audit-only candidate; update real-case regression expectations for `707476`; verify `765003` no longer emits broad geometry fallback u-turns.
- QA: Confirm CRS stability, topology explainability, audit traceability, no silent geometry fix, formal output compatibility, and no unregistered entrypoint changes.

## Design Decisions

1. Keep `formway_bit` mode unchanged and authoritative.
2. Define a compact semantic RCSD junction using existing single-node / compact same-`mainnodeid` grouping.
3. Compute effective degree from external incident roads after grouping.
4. Require each endpoint to have exactly two host roads after removing the candidate road.
5. Require host pairs to be nearly collinear and endpoint trunk axes to be nearly parallel.
6. Derive trunk flow only from trusted one-way direction values `2/3`; bidirectional or missing direction is untrusted.
7. Put direction-untrusted structural candidates into `u_turn_suspect_rcsdroad_ids` instead of filtering.

## Constraints

- No new official entrypoint.
- No change to Step3 frozen legal-space semantics.
- No change to Step6 boundary-first or Step7 final-state contract.
- No formal output filename change.
- No source/script file may exceed 100 KB after edits.

## Verification Plan

1. Run focused association tests.
2. Run real-case tests for `706389`, `707476`, and `765003`.
3. Run Step5 foreign filter tests to confirm mask semantics remain stable.
4. Inspect `765003` and `707476` Step4 audit fields for final vs suspect u-turn behavior.
