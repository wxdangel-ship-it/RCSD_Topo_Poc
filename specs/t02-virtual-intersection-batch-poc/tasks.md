# Tasks: T02 虚拟路口锚定统一全量入口 POC

**Input**: Design documents from `/specs/t02-virtual-intersection-batch-poc/`
**Prerequisites**: `plan.md`, `spec.md`

**Tests**: 本特性要求最小单测、CLI 测试与 smoke；每个用户故事都应能独立验证。

**Organization**: 任务按用户故事分组，保证“入口统一”“并行与上限控制”“统一输出与审计”可以分阶段落地。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件、无直接依赖）
- **[Story]**: 所属用户故事（`US1` / `US2` / `US3`）
- 所有任务都包含明确文件路径

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 为统一全量入口建立独立 orchestrator，不把逻辑继续塞进超 `100 KB` 的单 case worker

- [ ] T001 Create `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py` skeleton with unified full-input artifact dataclass and run entry
- [ ] T002 Update `src/rcsd_topo_poc/cli.py` so existing `t02-virtual-intersection-poc` becomes the unified full-data entry with mode params
- [ ] T003 [P] Create `tests/modules/t02_junction_anchor/test_virtual_intersection_full_input_poc.py` with fixtures for full-layer inputs and baseline no-regression checks

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 先实现所有用户故事共用的 preflight、模式判定和统一输出骨架

**⚠️ CRITICAL**: 没完成这一阶段前，不进入具体用户故事实现

- [ ] T004 Implement full-layer GeoPackage preflight and deterministic layer resolution in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T005 Implement root output contract writer (`preflight.json`, `summary.json`, `perf_summary.json`, `_rendered_maps/`) in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T005A Implement root unified polygon collection writer (`virtual_intersection_polygons.gpkg`) in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T006 [P] Add unit tests for preflight layer resolution and multi-layer failure in `tests/modules/t02_junction_anchor/test_virtual_intersection_full_input_poc.py`
- [ ] T007 [P] Add CLI parsing coverage for unified mode params (`mainnodeid`, `max_cases`, `workers`) in `tests/test_cli_t02.py`
- [ ] T008 [P] Add baseline regression guard that existing test-case entrance semantics do not change in `tests/modules/t02_junction_anchor/test_virtual_intersection_poc.py`

**Checkpoint**: Foundation ready - user story work can now begin

---

## Phase 3: User Story 1 - 统一全量入口支持“指定路口”和“自动识别”两种模式 (Priority: P1) 🎯 MVP

**Goal**: 用同一个完整数据入口支持指定路口验证和自动识别两种模式

**Independent Test**: 同一命令入口在传/不传 `mainnodeid` 时分别进入指定路口模式和自动识别模式，并都能产出统一根目录结构

### Tests for User Story 1

- [ ] T009 [P] [US1] Add unified mode routing tests for `mainnodeid` present/absent in `tests/modules/t02_junction_anchor/test_virtual_intersection_full_input_poc.py`
- [ ] T010 [P] [US1] Add candidate discovery tests based on representative `has_evd / is_anchor / kind_2` in `tests/modules/t02_junction_anchor/test_virtual_intersection_full_input_poc.py`

### Implementation for User Story 1

- [ ] T011 [US1] Implement unified full-input mode selection in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T012 [US1] Implement candidate discovery from full `nodes` input for auto mode in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T013 [US1] Implement per-selected-case invocation of `run_t02_virtual_intersection_poc(...)` and case directory layout in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T014 [US1] Aggregate per-case status, risk and output path into unified summary in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`

**Checkpoint**: User Story 1 should be independently runnable as an MVP

---

## Phase 4: User Story 2 - 用参数控制最大处理量并支持并行化 (Priority: P2)

**Goal**: 用 `max_cases` 和 `workers` 稳定限制规模并提升自动识别模式性能

**Independent Test**: 同一套输入在 `workers=1` 与 `workers>1` 下得到一致的结果集合，并能记录超过上限未处理的候选

### Tests for User Story 2

- [ ] T015 [P] [US2] Add deterministic ordering and `max_cases` limit tests in `tests/modules/t02_junction_anchor/test_virtual_intersection_full_input_poc.py`
- [ ] T016 [P] [US2] Add `workers` validation and deterministic parallel result tests in `tests/modules/t02_junction_anchor/test_virtual_intersection_full_input_poc.py`
- [ ] T017 [P] [US2] Add invalid `max_cases / workers` CLI validation tests in `tests/test_cli_t02.py`

### Implementation for User Story 2

- [ ] T018 [US2] Add `max_cases` and `workers` parameter parsing and validation in `src/rcsd_topo_poc/cli.py`
- [ ] T019 [US2] Implement stable candidate ordering and top-N selection in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T020 [US2] Implement parallel per-case execution with deterministic merge in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T021 [US2] Record skipped-by-limit candidates and reasons in summary/audit structures in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`

**Checkpoint**: User Stories 1 and 2 should both work independently

---

## Phase 5: User Story 3 - 统一输出一个路口面图层和一个 Render 目录 (Priority: P3)

**Goal**: 两种完整数据模式都统一落成一个虚拟路口面图层、一个 Render 目录和一份可审计 summary

**Independent Test**: 指定路口模式和自动识别模式运行结束后，都能在批次根目录读到 `virtual_intersection_polygons.gpkg` 与 `_rendered_maps/`

### Tests for User Story 3

- [ ] T022 [P] [US3] Add unified polygon collection output tests in `tests/modules/t02_junction_anchor/test_virtual_intersection_full_input_poc.py`
- [ ] T023 [P] [US3] Add unified render directory output tests in `tests/modules/t02_junction_anchor/test_virtual_intersection_full_input_poc.py`
- [ ] T024 [P] [US3] Add smoke test for the unified full-input flow in `tests/test_smoke_t02_virtual_intersection_full_input_poc.py`

### Implementation for User Story 3

- [ ] T025 [US3] Write `preflight.json` with resolved layers, feature counts, CRS and bounds in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T026 [US3] Write unified candidate inventory fields for eligible / excluded / skipped-by-limit states in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T027 [US3] Collect successful per-case `virtual_intersection_polygon.gpkg` outputs into root-level `virtual_intersection_polygons.gpkg` with `mainnodeid / status / source_case_dir` fields in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T028 [US3] Ensure all render outputs are indexed and written under one root `_rendered_maps/` directory in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T029 [US3] Write unified perf summary and progress/log integration in `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py`
- [ ] T030 [US3] Update `modules/t02_junction_anchor/README.md` and `modules/t02_junction_anchor/INTERFACE_CONTRACT.md` after implementation to register the unified full-input entry and output contract

**Checkpoint**: All user stories should now be independently functional and auditable

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 收口批量 POC 的文档、回归验证和结构债控制

- [ ] T031 [P] Run targeted pytest for `tests/modules/t02_junction_anchor/test_virtual_intersection_full_input_poc.py`
- [ ] T032 [P] Run baseline regression for existing test-case entrance and `tests/modules/t02_junction_anchor/test_virtual_intersection_poc.py`
- [ ] T033 [P] Run CLI regression in `tests/test_cli_t02.py`
- [ ] T034 [P] Run smoke for `tests/test_smoke_t02_virtual_intersection_full_input_poc.py`
- [ ] T035 Confirm `virtual_intersection_poc.py` only receives thin reuse edits and does not continue carrying unified full-input orchestration

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成；阻塞所有用户故事
- **User Stories (Phase 3+)**: 依赖 Foundational 完成
- **Polish (Phase 6)**: 依赖目标用户故事完成

### User Story Dependencies

- **US1 (P1)**: Foundational 完成后即可开始；这是 MVP
- **US2 (P2)**: 依赖 US1 的统一模式路由与候选发现骨架
- **US3 (P3)**: 依赖 US1 / US2 的运行结果与统一根目录结构

### Parallel Opportunities

- `T003`、`T006`、`T007`、`T008` 可并行
- `T009` 和 `T010` 可并行
- `T015`、`T016`、`T017` 可并行
- `T022`、`T023`、`T024` 可并行
- `T031`、`T032`、`T033`、`T034` 可并行

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational
3. 完成 Phase 3: User Story 1
4. 停下来验证：同一入口可切换指定路口模式和自动识别模式

### Incremental Delivery

1. 先做 US1，获得“一个完整数据入口 + 两种模式”的最小闭环
2. 再做 US2，把 `max_cases / workers` 和并行调度冻结
3. 最后做 US3，补齐统一图层、统一 render 目录和审计可解释性

### Notes

- 本变更只规划“受控实验统一全量入口 POC”，不把其提升为正式产线方案
- `max_cases` 是当前唯一冻结的“最大处理量”语义
- `workers` 是当前唯一冻结的“并行度”语义
- 若后续需要批量文本证据包、字节级处理量上限或全量产线调度，应另起变更，不在本轮混入
