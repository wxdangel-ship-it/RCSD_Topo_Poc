# Implementation Plan: T03 RCSD u-turn and same-path chain semantics

## Technical Context

- Module: `t03_virtual_junction_anchor`
- Primary contract: `modules/t03_virtual_junction_anchor/INTERFACE_CONTRACT.md`
- Primary implementation:
  - `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association.py`
  - `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry.py`
- Tests:
  - `tests/modules/t03_virtual_junction_anchor/test_association.py`
  - `tests/modules/t03_virtual_junction_anchor/test_step6_step7_case_706389_707476_regression.py`

## Product / Architecture / Development / Testing / QA Views

- Product: Same-path RCSDRoad chain has priority over local u-turn heuristics; T-mouth strong RCSD semantic nodes are capped to two.
- Architecture: Step4 owns same-path protection, narrowed u-turn filtering, and strong semantic node selection. Step6 consumes Step4 facts.
- Development: Keep changes localized to Step4/Step6 helpers and audit fields. Do not alter Step3, Step7, CLI, or output filenames.
- Testing: Add synthetic association tests and update real-case `706389` regression expectations.
- QA: Confirm CRS stability, topology explainability, audit traceability, no silent geometry fix, and regression safety.

## Design Decisions

1. Build pre-u-turn candidate RCSDRoad chains from raw active roads and raw degree-2 connector nodes.
2. Protect chains whose non-connector endpoints include at least two candidate semantic RCSDNodes.
3. Keep `u_turn_rcsdroad_ids` as the compatibility field for final qualified u-turns.
4. Add audit/status fields for candidates, protection, and T-mouth strong nodes without renaming existing outputs.
5. Prefer Step4-provided strong T-mouth RCSD semantic node ids in Step6 single-sided horizontal tracing when the strong set preserves both-side terminal coverage; otherwise keep existing endpoint tracing for compatibility.

## Constraints

- No new official entrypoint.
- No change to Step3 frozen legal-space semantics.
- No change to formal output filenames.
- No source/script file may exceed 100 KB after edits.

## Verification Plan

1. Run focused association tests.
2. Run focused real-case Step6/Step7 tests for `706389` and existing nearby regressions.
3. Run status/audit inspection for `706389` to confirm `5395732498090127` is retained and final state remains accepted.
