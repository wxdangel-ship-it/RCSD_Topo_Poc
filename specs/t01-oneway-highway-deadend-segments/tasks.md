# Tasks: T01 单向高速与断头 Segment 扩展

**Input**: Design documents from `/specs/t01-oneway-highway-deadend-segments/`  
**Prerequisites**: `plan.md`, `spec.md`  
**Tests**: Required. Add failing focused tests before implementation.

## Current Status

- Phase A single-way highway / `kind_2=128` implementation is complete.
- Dead-end leaf Segment implementation is complete locally and supports both a single bidirectional road and a reciprocal two-road one-way bundle.
- Innernet QA remains pending because latest innernet output was not provided in this implementation round.

## Phase 1: Setup and Governance

**Purpose**: Confirm implementation can start without violating source facts, entrypoint governance, or file-size constraints.

- [x] T001 Read `docs/repository-metadata/code-boundaries-and-entrypoints.md` before source edits.
- [x] T002 Confirm no new entrypoint is needed; keep existing `t01-run-skill-v1` and `t01-continue-oneway-segment`.
- [x] T003 Before editing any `.py` file, record current byte size for each target source/test file.
- [x] T004 Update this task list if target `.py` files are at/above `100 KB`; stop and prepare split plan if required.

---

## Phase 2: Source Facts Update

**Purpose**: Resolve the current conflict between accepted baseline and confirmed new requirements.

- [x] T005 [P] Update `modules/t01_data_preprocess/INTERFACE_CONTRACT.md` to state single-way `road_kind=1` is allowed while dual-way remains excluded.
- [x] T006 [P] Update `modules/t01_data_preprocess/INTERFACE_CONTRACT.md` to include `kind_2=128` in `0-1单 / 0-2单`, not `0-0单`.
- [x] T007 [P] Update `modules/t01_data_preprocess/architecture/02-constraints.md` for scoped `road_kind=1` single-way behavior.
- [x] T008 [P] Update `modules/t01_data_preprocess/architecture/03-context-and-scope.md` for scoped single-way `road_kind=1` and `kind_2=128`.
- [x] T009 [P] Update `modules/t01_data_preprocess/architecture/04-solution-strategy.md` with Phase A single-way strategy.
- [x] T010 [P] Update `modules/t01_data_preprocess/architecture/06-accepted-baseline.md` with confirmed Phase A `road_kind=1` and `kind_2=128` semantics.
- [x] T010A [P] Update source facts for dead-end leaf semantics when Phase B implementation starts.

**Checkpoint**: Source facts describe the intended behavior before code implements it.

---

## Phase 3: User Story 1 - Single-way `road_kind=1` (Priority: P1)

**Goal**: Allow highway/closed-road single-way candidates to build without changing dual-way baseline.

**Independent Test**: A fixture with `road_kind=1`, `direction=2`, legal single-way terminates produces one single-way Segment.

### Tests

- [x] T011 [P] [US1] Add failing test in `tests/modules/t01_data_preprocess/test_step5_oneway_segment_completion.py` for `road_kind=1` single-way chain.
- [x] T012 [P] [US1] Confirm dual-way behavior remains isolated by keeping `road_kind=1` change inside single-way code path.

### Implementation

- [x] T013 [US1] Update `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_oneway_segment_completion.py` so candidate collection does not exclude `road_kind=1`.
- [x] T014 [US1] Add `road_kind_1_candidate_count` and `road_kind_1_built_road_count` to `oneway_segment_summary.json`.
- [x] T015 [US1] Run focused single-way tests.

**Checkpoint**: `road_kind=1` is allowed only in single-way continuation.

---

## Phase 4: User Story 2 - `kind_2=128` Single-way Terminate (Priority: P1)

**Goal**: Treat confirmed complex diverge/merge nodes as single-way terminates.

**Independent Test**: A single-way candidate chain ending at `kind_2=128` builds in `0-1单` or `0-2单`.

### Tests

- [x] T016 [P] [US2] Add failing `kind_2=128` terminate test in `tests/modules/t01_data_preprocess/test_step5_oneway_segment_completion.py`.
- [x] T017 [P] [US2] Add assertion that `0-0单` does not include `kind_2=128`.

### Implementation

- [x] T018 [US2] Update `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_oneway_segment_completion.py` phase specs for `0-1单 / 0-2单`.
- [x] T019 [US2] Add `kind_2_128_terminate_count` summary evidence.
- [x] T020 [US2] Run focused single-way tests.

**Checkpoint**: `kind_2=128` works as scoped single-way terminate.

---

## Phase 5: User Story 3 - Dead-End Leaf Segment (Priority: P2)

**Goal**: Build controlled Segment for dead-end road bundles with one valid semantic endpoint and one leaf endpoint.

**Independent Test**: A single dual-way road from semantic endpoint to leaf node produces a Segment and Step6 fields are correct. A reciprocal two-road one-way bundle from a two-node semantic junction endpoint to a leaf node produces one Segment with both roads.

### Tests

- [x] T021 [P] [US3] Add failing single-road bidirectional dead-end build test in `tests/modules/t01_data_preprocess/test_step5_oneway_segment_completion.py`.
- [x] T022 [P] [US3] Add failing reciprocal one-way two-node-junction dead-end build test in `tests/modules/t01_data_preprocess/test_step5_oneway_segment_completion.py`.
- [x] T023 [P] [US3] Add failing Step6 publication test in `tests/modules/t01_data_preprocess/test_step6_segment_aggregation.py`.
- [x] T023A [P] [US3] Add negative tests for `formway=128`, right-turn-only, and unpaired one-way dead-end roads.

### Implementation

- [x] T024 [US3] Add dead-end leaf detection in the narrowest existing T01 stage that can consume Step5 refreshed residual roads.
- [x] T025 [US3] Write deterministic `segmentid`, `sgrade`, and leaf metadata on built dead-end roads.
- [x] T026 [US3] Update `src/rcsd_topo_poc/modules/t01_data_preprocess/step6_segment_aggregation.py` so leaf endpoints are represented without becoming normal `junc_nodes` or being promoted by normal dual-way grade adjustment.
- [x] T027 [US3] Add dead-end counts to summary output.

**Checkpoint**: Dead-end Segment builds without broadening ordinary pair validation.

---

## Phase 6: User Story 4 - Audit and Innernet QA (Priority: P2)

**Goal**: Make every remaining unsegmented road explainable.

**Independent Test**: Mixed fixture produces distinct audit categories for built, excluded, candidate failed, and publish mismatch roads.

### Tests

- [ ] T028 [P] [US4] Add test coverage for one-way summary counters and unsegmented reasons.
- [ ] T029 [P] [US4] Add test coverage for dead-end summary counters.

### Implementation

- [ ] T030 [US4] Extend existing summary/audit outputs without adding a new CLI entrypoint.
- [x] T031 [US4] Ensure `unsegmented_roads.csv` or companion summary distinguishes filter and trace failure classes.
- [ ] T032 [US4] Run innernet latest T01 output and compare original SWSD vs T01 outputs for CRS/topology/geometry/audit/performance checks.

**Checkpoint**: QA can explain remaining gaps with road-level evidence.

---

## Phase 7: Regression and Closeout

- [x] T033 Run `.venv/bin/python -m pytest tests/modules/t01_data_preprocess/test_step5_oneway_segment_completion.py`.
- [x] T034 Run `.venv/bin/python -m pytest tests/modules/t01_data_preprocess/test_step6_segment_aggregation.py`.
- [x] T035 Run `.venv/bin/python -m pytest tests/modules/t01_data_preprocess/test_skill_v1.py tests/test_cli_t01.py`.
- [x] T036 Run broader T01 test subset if changed helpers are shared with dual-way stages.
- [x] T037 Record verification result with **已修改 / 已验证 / 待确认** split.
- [ ] T038 Do not update active freeze baseline unless separately authorized.

## Dependencies & Execution Order

- Phase 1 blocks all source edits.
- Phase 2 blocks code implementation because source facts currently conflict with requested behavior.
- Phase 3 and Phase 4 can be implemented together after Phase 2, but tests remain independently verifiable.
- Phase 5 depends on Phase 2 and should be kept separate from Phase 3/4 commits if possible.
- Phase 6 depends on implemented behavior from Phase 3/4/5.
- Phase 7 closes the implementation round.

## Role Checklist

- [x] Product: confirmed recall goals and scoped non-goals.
- [x] Architecture: updated source facts and separated single-way/dead-end semantics.
- [x] Development: implemented without new entrypoints and without oversized file writes.
- [x] Testing: added failing-first unit tests and regression tests.
- [ ] QA: completed CRS, topology, geometry semantics, audit traceability, and performance checks.
