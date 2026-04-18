# Tasks: T03 Step45 Degree-2 RCSDRoad Chain Merge

## Phase 0 - Spec Clarification

- [x] T001 新建 `specs/t03-step45-degree2-rcsdroad-chain-merge/spec.md`
- [x] T002 新建 `specs/t03-step45-degree2-rcsdroad-chain-merge/plan.md`
- [x] T003 新建 `specs/t03-step45-degree2-rcsdroad-chain-merge/tasks.md`
- [x] T004 显式记录“degree-2 connector 串接的 RCSDRoad 按 chain 合并，且不考虑角度”的 thread-level clarified requirement

## Phase 1 - Step45 Chain Merge

- [x] T010 在 `step45_rcsd_association.py` 中新增 degree-2 road-chain grouping helper
- [x] T011 让 `required/support` 按 chain 判定后再展开回成员 `road_id`
- [x] T012 确保 `parallel_support_duplicate_dropped_rcsdroad_ids` 与 `excluded_rcsdroad_ids` 不再拆裂 retained chain
- [x] T013 给 blocked Step45 输出补齐 `degree2_merged_rcsdroad_groups: {}`

## Phase 2 - Tests

- [x] T020 扩展 synthetic Step45 case，锁住 degree-2 chain expansion
- [x] T021 新增 synthetic 直角 chain case，锁住“不考虑角度”
- [x] T022 更新 blocked Step45 contract test，锁住空字段 schema
- [x] T023 新增 `test_step67_case_787133_regression.py`，锁住真实 case 恢复路径
- [x] T024 跑 focused pytest，确认 Step45/Step67 回归通过

## Phase 3 - Batch Validation

- [x] T030 重跑正式 58 case 批次
- [x] T031 更新线程级 `SUMMARY / TO_GPT / PROPOSED_UPDATE / RUN_EVIDENCE`
- [x] T032 复盘剩余失败 case，并说明本轮 chain merge 的真实收益与未解决问题
