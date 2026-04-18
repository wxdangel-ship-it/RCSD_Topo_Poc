# Tasks: T03 Step45/67 Boundary-First And U-Turn Filter Fix

## Phase 0 - Audit

- [x] T001 复核 `706389 / 707476 / 709431` 当前 Step6 regrow 根因
- [x] T002 复核 `706389 / 707476` 与 `RCSD 调头口过滤` 缺失的关联性

## Phase 1 - Implementation

- [x] T010 在 `step45_rcsd_association.py` 中引入 `RCSD 调头口过滤`
- [x] T011 在调头口过滤后重算 `degree2 connector / chain merge / required-support-excluded`
- [x] T012 在 `step67_geometry.py` 中把 directional boundary 提升为 final hard cap
- [x] T013 将 `required RC` 几何与校验改为 directional boundary 内局部覆盖
- [x] T014 收紧 `single_sided_t_mouth` 横向 `semantic + 5m` 触发条件
- [x] T015 增加 target-connected boundary regeneration，避免 `758888 / 851884` 误拒绝

## Phase 2 - Verification

- [x] T020 更新 `test_step45_association.py`
- [x] T021 更新 `test_step67_geometry.py`
- [x] T022 更新 `test_step67_case_706389_707476_regression.py`
- [x] T023 运行 focused pytest
- [x] T024 运行 formal 58 case batch regression

## Phase 3 - Thread Sync

- [x] T030 更新模块长期契约文档
- [ ] T031 更新线程 `SUMMARY.md`
- [ ] T032 更新线程 `TO_GPT.md`
- [ ] T033 更新线程 `RUN_EVIDENCE.md`
