# Tasks: T03 RCSD u-turn geometry fallback hardening

## Phase 1: Contract

- [x] T001 Update T03 module contract for strict geometry fallback in `modules/t03_virtual_junction_anchor/INTERFACE_CONTRACT.md`
- [x] T002 Update T03 architecture constraints / solution / quality docs
- [x] T003 Update project-level field governance constraint for T03 `RCSDRoad.formway` fallback behavior

## Phase 2: Implementation

- [x] T004 Add effective semantic group / effective-degree helpers in `step4_association.py`
- [x] T005 Replace broad geometry fallback with strict endpoint-trunk-direction evaluation
- [x] T006 Add `u_turn_suspect_rcsdroad_ids` and `u_turn_suspect_rcsdroad_audit`
- [x] T007 Keep `formway_bit` authoritative behavior unchanged

## Phase 3: Tests

- [x] T008 Add synthetic confirmed geometry fallback u-turn test
- [x] T009 Add synthetic direction-untrusted suspect audit-only test
- [x] T010 Update same-path and real-case regression expectations

## Phase 4: QA

- [x] T011 Run focused association tests
- [x] T012 Run real-case regression tests for `706389 / 707476 / 765003`
- [x] T013 Confirm no Step3 / Step6 / Step7 / entrypoint / formal filename changes
