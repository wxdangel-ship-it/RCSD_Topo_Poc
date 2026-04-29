# Tasks: T03 RCSD u-turn and same-path chain semantics

## Phase 1: Contract

- [x] T001 Update RCSD stable semantics in `modules/t03_virtual_junction_anchor/INTERFACE_CONTRACT.md`
- [x] T002 Update T03 solution strategy / quality notes if needed in `modules/t03_virtual_junction_anchor/architecture/*.md`

## Phase 2: Implementation

- [x] T003 Add same-path chain protection helpers in `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association.py`
- [x] T004 Narrow final u-turn filtering in `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association.py`
- [x] T005 Add T-mouth strong related RCSDNode cap and audit fields in `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association.py`
- [x] T006 Prefer Step4 strong T-mouth nodes in Step6 single-sided trace when they preserve both-side terminal coverage in `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry.py`

## Phase 3: Tests

- [x] T007 Add synthetic same-path-chain and true-u-turn tests in `tests/modules/t03_virtual_junction_anchor/test_association.py`
- [x] T008 Update `706389` real-case regression in `tests/modules/t03_virtual_junction_anchor/test_step6_step7_case_706389_707476_regression.py`
- [x] T009 Run focused pytest commands and inspect `706389` audit output

## Phase 4: QA

- [x] T010 Confirm no formal output filename, CLI, Step3, or Step7 state contract changed
- [x] T011 Confirm GIS checks: CRS, topology explainability, audit traceability, and no silent fix
