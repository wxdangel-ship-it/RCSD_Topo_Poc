# Tasks: T07 Semantic Junction Anchor Step1/Step2/Step3

**Input**: `specs/t07-semantic-junction-anchor-step12/spec.md`, `specs/t07-semantic-junction-anchor-step12/plan.md`
**Prerequisites**: User has confirmed `kind_2`, representative-node gate, and NULL behavior for out-of-scope `kind_2`.

**Tests**: Required. Add focused synthetic tests before implementation.

## Phase 1: Scope Freeze

**Purpose**: Confirm implementation can start without violating source facts, entrypoint governance, or file-size constraints.

- [x] T001 Confirm whether this round is allowed to register `t07_semantic_junction_anchor` in project/module source facts, or must remain implementation-only under `src/` and `tests/`.
- [x] T002 Confirm no repo CLI, `tools/`, module `run.py`, or module `__main__.py` will be added in this implementation round; only the approved innernet wrapper scripts are allowed.
- [x] T003 Before editing any `.py` file, record current file byte size per repository rule.
- [x] T004 Re-read `docs/repository-metadata/code-boundaries-and-entrypoints.md` before any source or entrypoint-adjacent change.

**Checkpoint**: Scope is authorized and no §1 hard-stop condition is active.

## Phase 2: Product And Architecture Contract

**Purpose**: Make the T07 behavior explicit before writing implementation.

- [x] T005 If module registration is authorized, create `modules/t07_semantic_junction_anchor/AGENTS.md`.
- [x] T006 If module registration is authorized, create `modules/t07_semantic_junction_anchor/INTERFACE_CONTRACT.md` with Step1/Step2 input/output/value-domain contract.
- [x] T007 If module registration is authorized, create `modules/t07_semantic_junction_anchor/architecture/01-introduction-and-goals.md`.
- [x] T008 If module registration is authorized, create `modules/t07_semantic_junction_anchor/architecture/02-constraints.md`.
- [x] T009 If module registration is authorized, create `modules/t07_semantic_junction_anchor/architecture/03-context-and-scope.md`.
- [x] T010 If module registration is authorized, create `modules/t07_semantic_junction_anchor/architecture/04-solution-strategy.md`.
- [x] T011 If module registration is authorized, create `modules/t07_semantic_junction_anchor/architecture/10-quality-requirements.md`.

**Checkpoint**: Product and architecture facts match the confirmed requirement.

## Phase 3: User Story 1 - Semantic Junction has_evd (Priority: P1)

**Goal**: Compute representative-node `has_evd` at semantic-junction level with no Segment input.

**Independent Test**: Run Step1 tests using only `nodes` and `DriveZone`.

### Tests

- [x] T012 [P] [US1] Add Step1 allowed `kind_2` tests in `tests/modules/t07_semantic_junction_anchor/test_runner.py`.
- [x] T013 [P] [US1] Add Step1 disallowed `kind_2` NULL test in `tests/modules/t07_semantic_junction_anchor/test_runner.py`.
- [x] T014 [P] [US1] Add representative-only write test for multi-node `mainnodeid` groups.

### Implementation

- [x] T015 [US1] Create `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/__init__.py`.
- [x] T016 [US1] Implement semantic junction grouping in `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/runner.py`.
- [x] T017 [US1] Implement Step1 DriveZone gate in `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/runner.py`.
- [x] T018 [US1] Implement Step1 semantic-junction-level summary/audit fields in `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/runner.py`.

**Checkpoint**: Step1 works without Segment input.

## Phase 4: User Story 2 - Semantic Junction Anchor Recognition (Priority: P1)

**Goal**: Compute representative-node `is_anchor / anchor_reason` for `has_evd = yes` semantic junctions.

**Independent Test**: Run Step2 tests using Step1-style nodes and `RCSDIntersection`.

### Tests

- [x] T019 [P] [US2] Add Step2 yes/no tests in `tests/modules/t07_semantic_junction_anchor/test_runner.py`.
- [x] T020 [P] [US2] Add Step2 `fail1 / fail2` tests.
- [x] T021 [P] [US2] Add `kind_2 = 64 / 128` Step2 `no / NULL` and conflict-exclusion tests.
- [x] T022 [P] [US2] Add `kind_2 = 2048` same-single-`RCSDIntersection` `anchor_reason = t` test and non-matching `no / NULL` fallback test.
- [x] T023 [P] [US2] Add `has_evd != yes` NULL test.

### Implementation

- [x] T024 [US2] Implement Step2 RCSDIntersection hit detection in `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/runner.py`.
- [x] T025 [US2] Implement `fail1 / fail2` conflict resolution with `fail2 > fail1`.
- [x] T026 [US2] Output Step2 nodes + audit + summary plus `t07_rcsdintersection_anchor_surface.gpkg` and `t07_swsd_rcsd_relation_evidence.json`.

**Checkpoint**: Step2 value domain and `anchor_reason` behavior match confirmed requirement.

## Phase 5: User Story 3 - No Segment Dependency And QA Traceability (Priority: P2)

**Goal**: Prove T07 does not process Segment and remains auditable.

**Independent Test**: Run T07 tests without any `segment` fixture or path.

### Tests

- [x] T027 [P] [US3] Add no-Segment dependency test in `tests/modules/t07_semantic_junction_anchor/test_runner.py`.
- [x] T028 [P] [US3] Add summary schema test proving there is no `summary_by_s_grade` or `anchor_summary_by_s_grade`.
- [x] T029 [P] [US3] Add audit/error reason tests for skipped `kind_2`, CRS failure, and missing required fields.

### Implementation

- [x] T030 [US3] Finalize semantic-junction-level summary schema.
- [x] T031 [US3] Finalize audit rows with input, parameters, output path, and run environment traceability.
- [x] T032 [US3] Add perf summary fields for semantic junction count, processed count, skipped count, candidate/conflict counts, and elapsed time.

**Checkpoint**: T07 is Segment-free and QA-readable.

## Phase 6: User Story 4 - T05 Relation 补锚 Step3 (Priority: P1)

**Goal**: 独立消费 Step2 后 `nodes`、T05 `intersection_match_all.geojson` 与输入 `RCSDNode`，对符合条件的 SWSD 语义路口补写 `is_anchor = yes`。

**Independent Test**: Run Step3 tests using synthetic nodes, T05 relation rows, and RCSDNode fixtures.

### Tests

- [x] T033 [P] [US4] Add Step3 candidate识别、成功 relation 与 RCSD `base_id` 存在性测试 in `tests/modules/t07_semantic_junction_anchor/test_step3_intersection_match.py`.
- [x] T034 [P] [US4] Add Step3 relation missing / failed relation / missing RCSD / `kind_2 = 64` exclusion assertions.
- [x] T034a [P] [US4] Add Step3 merged `t07_swsd_rcsd_relation_evidence.json` assertions.

### Implementation

- [x] T035 [US4] Implement independent Step3 callable in `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/step3_intersection_match.py`.
- [x] T036 [US4] Export Step3 callable from `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/__init__.py`.
- [x] T037 [US4] Add independent innernet wrapper `scripts/t07_run_step3_intersection_match_innernet.sh`.
- [x] T038 [US4] Update T07 source facts, module docs, and entrypoint registry for Step3.

**Checkpoint**: Step3 is independent from Step1/Step2 and produces `intersection_match_tool7.geojson` plus merged `t07_swsd_rcsd_relation_evidence.json`.

## Phase 7: Validation And Closeout

**Purpose**: Verify behavior and document remaining risk.

- [x] T039 Run focused tests: `.venv/bin/python -m pytest tests/modules/t07_semantic_junction_anchor`.
- [x] T040 Run `bash -n` for T07 innernet shell wrappers.
- [x] T041 Run `git diff --check`.
- [x] T042 Report GIS checks: CRS correctness, topology consistency, geometry semantic explainability, audit traceability, and performance verifiability.
- [x] T043 If module registration was authorized, update project/module inventory and source facts in the same round; otherwise explicitly report T07 remains unregistered draft implementation.

## Coverage Checklist

- [x] Product: confirmed semantic-junction-level Step1/Step2/Step3 scope and no Segment processing.
- [x] Architecture: separated T07 from T02 Segment-bound Step1/Step2 behavior and kept Step3 independent.
- [x] Development: implementation completed in module-local runner plus approved innernet wrapper.
- [x] Testing: focused tests passed.
- [x] QA: CRS/topology/audit/performance checks are represented in runner behavior, tests, summary/audit/perf outputs, and closeout report.
