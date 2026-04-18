# Tasks: T03 Step67 Foreign Mask Normalization

## Phase 0 - Spec Clarification

- [x] T001 新建 `specs/t03-step67-foreign-mask-normalization/spec.md`
- [x] T002 新建 `specs/t03-step67-foreign-mask-normalization/plan.md`
- [x] T003 新建 `specs/t03-step67-foreign-mask-normalization/tasks.md`
- [x] T004 显式记录“Step5 不再生成 hard foreign polygon context、Step6 只保留 road-like 1m mask”的 thread-level clarified requirement
- [x] T005 在 spec-kit 中补记 Step45 degree-2 road-chain merge 是本轮 foreign normalization 的上游依赖

## Phase 1 - Foreign Mask Normalization

- [x] T010 在 `step45_foreign_filter.py` 中停掉 `foreign_swsd_context_geometry` / `foreign_rcsd_context_geometry` 的 hard polygon context 构造
- [x] T011 保留 Step45 审计字段中的 `excluded_* / true_foreign_* / connector_*`，将 node 类 foreign 降为 audit-only
- [x] T012 在 `step67_geometry.py` 中把 `foreign_mask_geometry` 重组成 normalized `1m` road-like mask
- [x] T013 让 Step6 审计显式写出 `foreign_mask_mode / foreign_mask_sources`

## Phase 2 - Tests

- [x] T020 更新 `test_step45_foreign_filter.py`，锁住 Step5 不再输出 hard foreign SWSD/RCSD polygon context
- [x] T021 更新 `test_step67_case_698330_regression.py`，锁住 selected-road length 不再因 foreign 缩短
- [x] T022 新增 `test_step67_case_706389_707476_regression.py`，锁住 node-based foreign rejection 恢复为 accepted
- [x] T023 保留 `test_step67_case_520394575_regression.py` 作为 negative guard，确认该 case 仍 rejected
- [x] T024 跑 focused pytest，确认 Step45/Step67 单测通过

## Phase 3 - Batch Validation

- [x] T030 重跑正式 58 case 批次
- [x] T031 更新线程级 `SUMMARY / TO_GPT / PROPOSED_UPDATE / RUN_EVIDENCE`
- [x] T032 复盘 foreign failure 统计是否下降，并给出剩余问题清单
