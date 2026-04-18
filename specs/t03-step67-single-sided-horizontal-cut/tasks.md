# Tasks: T03 Step67 Single-Sided Horizontal Cut Fix

## Phase 0 - Audit

- [x] T001 复核 `706389` 的 Step3 / Step6 / Step7 中间产物与当前 cut 规则
- [x] T002 确认修复只针对 `single_sided_t_mouth` 横向 pair roads

## Phase 1 - Implementation

- [x] T010 在 `step67_geometry.py` 中新增 single-sided 横向特化 cut 逻辑
- [x] T011 补充 Step6 审计字段，区分 generic `20m` 与 horizontal `semantic+5m`

## Phase 2 - Verification

- [x] T020 更新 `706389 / 707476` 回归测试
- [x] T021 运行 focused pytest
- [x] T022 运行 formal 58 case batch regression

## Phase 3 - Thread Sync

- [x] T030 更新线程 `SUMMARY.md`
- [x] T031 更新线程 `TO_GPT.md`
- [x] T032 更新线程 `RUN_EVIDENCE.md`
