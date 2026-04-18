# Tasks: T03 Step67 Directional Cut

## Phase 0 - Spec Clarification

- [x] T001 新建 `specs/t03-step67-directional-cut/spec.md`
- [x] T002 新建 `specs/t03-step67-directional-cut/plan.md`
- [x] T003 新建 `specs/t03-step67-directional-cut/tasks.md`
- [x] T004 显式记录 thread-level clarified requirement 与旧正式文档的差异

## Phase 1 - Step6 Directional Cut

- [x] T010 在 `step67_geometry.py` 中新增 selected-road branch directional cut helper
- [x] T011 将 `allowed_space` 主裁剪切换为 directional cut geometry
- [x] T012 将 `selected_road_core_cover_ratio` 对齐到 directional-core geometry
- [x] T013 为 Step6 审计补充 branch-level `available_length / cut_length / preserve_candidate_boundary`

## Phase 2 - Tests

- [x] T020 更新 `test_step67_geometry.py`，锁住 center-junction directional cut 生效
- [x] T021 更新 `test_step67_geometry.py`，锁住 `support_only` 仍可 accepted
- [x] T022 新增 single-sided helper 相关 Step67 directional cut 断言
- [x] T023 增强 `test_step67_case_520394575_regression.py`，确认 directional cut 已参与该 case 的 Step6

## Phase 3 - Validation

- [x] T030 跑 Step67 相关 pytest
- [x] T031 定点审计 `584141`，确认 `20m` 已从校验窗口变成构面规则
- [x] T032 定点复查 `520394575`，确认失败锚点未被误洗白
