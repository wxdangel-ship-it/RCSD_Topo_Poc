# Tasks: T07 Semantic Junction Anchor Step1/Step2

**Input**: `specs/t07-semantic-junction-anchor-step12/spec.md`, `specs/t07-semantic-junction-anchor-step12/plan.md`
**Prerequisites**: User has confirmed `kind_2`, representative-node gate, and NULL behavior for out-of-scope `kind_2`.

**Tests**: Required. Add focused synthetic tests before implementation.

## Phase 1: Scope Freeze

**Purpose**: Confirm implementation can start without violating source facts, entrypoint governance, or file-size constraints.

- [ ] T001 Confirm whether this round is allowed to register `t07_semantic_junction_anchor` in project/module source facts, or must remain implementation-only under `src/` and `tests/`.
- [ ] T002 Confirm no repo CLI, `scripts/`, `tools/`, module `run.py`, or module `__main__.py` will be added in this implementation round.
- [ ] T003 Before editing any `.py` file, record current file byte size per repository rule.
- [ ] T004 Re-read `docs/repository-metadata/code-boundaries-and-entrypoints.md` before any source or entrypoint-adjacent change.

**Checkpoint**: Scope is authorized and no §1 hard-stop condition is active.

## Phase 2: Product And Architecture Contract

**Purpose**: Make the T07 behavior explicit before writing implementation.

- [ ] T005 If module registration is authorized, create `modules/t07_semantic_junction_anchor/AGENTS.md`.
- [ ] T006 If module registration is authorized, create `modules/t07_semantic_junction_anchor/INTERFACE_CONTRACT.md` with Step1/Step2 input/output/value-domain contract.
- [ ] T007 If module registration is authorized, create `modules/t07_semantic_junction_anchor/architecture/01-introduction-and-goals.md`.
- [ ] T008 If module registration is authorized, create `modules/t07_semantic_junction_anchor/architecture/02-constraints.md`.
- [ ] T009 If module registration is authorized, create `modules/t07_semantic_junction_anchor/architecture/03-context-and-scope.md`.
- [ ] T010 If module registration is authorized, create `modules/t07_semantic_junction_anchor/architecture/04-solution-strategy.md`.
- [ ] T011 If module registration is authorized, create `modules/t07_semantic_junction_anchor/architecture/10-quality-requirements.md`.

**Checkpoint**: Product and architecture facts match the confirmed requirement.

## Phase 3: User Story 1 - Semantic Junction has_evd (Priority: P1)

**Goal**: Compute representative-node `has_evd` at semantic-junction level with no Segment input.

**Independent Test**: Run Step1 tests using only `nodes` and `DriveZone`.

### Tests

- [ ] T012 [P] [US1] Add Step1 allowed `kind_2` tests in `tests/modules/t07_semantic_junction_anchor/test_step1_has_evd.py`.
- [ ] T013 [P] [US1] Add Step1 disallowed `kind_2` NULL test in `tests/modules/t07_semantic_junction_anchor/test_step1_has_evd.py`.
- [ ] T014 [P] [US1] Add representative-only write test for multi-node `mainnodeid` groups.

### Implementation

- [ ] T015 [US1] Create `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/__init__.py`.
- [ ] T016 [US1] Implement semantic junction grouping in `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/semantic_junctions.py`.
- [ ] T017 [US1] Implement Step1 DriveZone gate in `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/step1_has_evd.py`.
- [ ] T018 [US1] Implement Step1 semantic-junction-level summary/audit fields in `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/outputs.py`.

**Checkpoint**: Step1 works without Segment input.

## Phase 4: User Story 2 - Semantic Junction Anchor Recognition (Priority: P1)

**Goal**: Compute representative-node `is_anchor / anchor_reason` for `has_evd = yes` semantic junctions.

**Independent Test**: Run Step2 tests using Step1-style nodes and `RCSDIntersection`.

### Tests

- [ ] T019 [P] [US2] Add Step2 yes/no tests in `tests/modules/t07_semantic_junction_anchor/test_step2_anchor_recognition.py`.
- [ ] T020 [P] [US2] Add Step2 `fail1 / fail2` tests.
- [ ] T021 [P] [US2] Add `kind_2 = 64` `anchor_reason = roundabout` test.
- [ ] T022 [P] [US2] Add `kind_2 = 2048` `anchor_reason = t` test.
- [ ] T023 [P] [US2] Add `has_evd != yes` NULL test.

### Implementation

- [ ] T024 [US2] Implement Step2 RCSDIntersection hit detection in `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/step2_anchor_recognition.py`.
- [ ] T025 [US2] Implement `fail1 / fail2` conflict resolution with `fail2 > fail1`.
- [ ] T026 [US2] Implement Step2 accepted surface/relation evidence only if this round's contract explicitly asks for those handoff outputs; otherwise keep output to nodes + audit + summary.

**Checkpoint**: Step2 value domain and `anchor_reason` behavior match confirmed requirement.

## Phase 5: User Story 3 - No Segment Dependency And QA Traceability (Priority: P2)

**Goal**: Prove T07 does not process Segment and remains auditable.

**Independent Test**: Run T07 tests without any `segment` fixture or path.

### Tests

- [ ] T027 [P] [US3] Add no-Segment dependency test in `tests/modules/t07_semantic_junction_anchor/test_no_segment_dependency.py`.
- [ ] T028 [P] [US3] Add summary schema test proving there is no `summary_by_s_grade` or `anchor_summary_by_s_grade`.
- [ ] T029 [P] [US3] Add audit reason tests for skipped `kind_2`, representative missing, CRS failure, and geometry missing.

### Implementation

- [ ] T030 [US3] Finalize semantic-junction-level summary schema.
- [ ] T031 [US3] Finalize audit rows with input, parameters, output path, and run environment traceability.
- [ ] T032 [US3] Add perf summary fields for node count, semantic junction count, processed count, skipped count, and elapsed time.

**Checkpoint**: T07 is Segment-free and QA-readable.

## Phase 6: Validation And Closeout

**Purpose**: Verify behavior and document remaining risk.

- [ ] T033 Run focused tests: `.venv/bin/python -m pytest tests/modules/t07_semantic_junction_anchor`.
- [ ] T034 Run `git diff --check`.
- [ ] T035 Report GIS checks: CRS correctness, topology consistency, geometry semantic explainability, audit traceability, and performance verifiability.
- [ ] T036 If module registration was authorized, update project/module inventory and source facts in the same round; otherwise explicitly report T07 remains unregistered draft implementation.

## Coverage Checklist

- [x] Product: confirmed semantic-junction-level Step1/Step2 scope and no Segment processing.
- [x] Architecture: separated T07 from T02 Segment-bound Step1/Step2 behavior.
- [ ] Development: pending implementation.
- [ ] Testing: pending focused tests.
- [ ] QA: pending GIS/topology/audit/performance verification.
