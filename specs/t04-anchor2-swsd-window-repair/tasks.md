# Tasks: T04 Anchor_2 SWSD Window Repair

## Phase 1 - Specify

- [x] T001 Confirm user visual-audit semantics for six new cases.
- [x] T002 Identify source-fact conflict around `no_surface_reference`.
- [x] T003 Create `spec.md`, `plan.md`, and `tasks.md`.

## Phase 2 - Formal Docs

- [x] T010 Update `INTERFACE_CONTRACT.md` to define valid T04 inputs as SWSD-context-bearing.
- [x] T011 Update `architecture/04-solution-strategy.md` scenario strategy.
- [x] T012 Update `architecture/10-quality-requirements.md` with six-case expectations and no-regression gates.
- [x] T013 Revise source facts for the 2026-05-02 eleven-case visual audit: RCSD current rendering, Reference Point + RCSD full-fill, SWSD-only windows, and slit-relief guard rules.

## Phase 3 - Implementation

- [x] T020 Update scenario classification so valid no-main/no-RCSD cases default to SWSD section reference.
- [x] T021 Update road-surface fork binding cleanup so valid SWSD-window cases are not cleared to normal `no_surface_reference`.
- [x] T022 Update RCSD-anchored reverse classification to avoid false main evidence / virtual Reference Point.
- [x] T023 Repair Step6 component/hole artifacts without weakening post-cleanup guards. No-main SWSD / RCSDRoad fallback windows, dominant-component relief, and cut-sliver relief now assemble the six user-audited cases without disabling post-cleanup guards.
- [x] T024 Repair eleven-case visual-audit issues: active RCSD/SWSD rendering, RCSD over-recall suppression, continuous-chain full-fill guard, weak RCSD local binding, and guarded full-fill slit relief.

## Phase 4 - Tests

- [x] T030 Update surface scenario unit tests.
- [x] T031 Add six-case real Anchor_2 regression.
- [x] T032 Strengthen 30-case semantic no-regression assertions. Existing 30-case gate already asserts scenario / RCSD / main-evidence key fields and was rerun after implementation.

## Phase 5 - Verification

- [x] T040 Run py_compile.
- [x] T041 Run targeted T04 pytest.
- [x] T042 Run six-case batch and inspect Step4/5/6/7 outputs. Outcome: `785629 / 785631 / 785731 / 795682 / 807908 / 823826` accepted with expected user-audit scenarios.
- [x] T043 Run eleven-case batch and inspect Step4/5/6/7 outputs. Outcome: `698380 / 698389 / 760277 / 765050 / 765170 / 768675 / 768680 / 785629 / 785731 / 807908 / 823826` accepted with expected scenario / RCSD / SWSD audit states.
- [x] T044 Run Anchor_2 30-case baseline gate.
- [x] T045 Record CRS/topology/geometry/audit/performance checks in the handoff summary.

## Phase 6 - Handoff

- [ ] T050 Summarize modified files and purpose.
- [ ] T051 Summarize verification outputs.
- [ ] T052 List residual visual-audit items for user confirmation.
