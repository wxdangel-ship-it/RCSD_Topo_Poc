# Tasks: T04 Step4 正向 RCSD 选择器重构

## Phase 1

- [ ] 更新 `spec.md`
- [ ] 更新 `plan.md`
- [ ] 更新 `tasks.md`
- [ ] 同步线程 `REQUIREMENT.md`
- [ ] 同步 T04 正式文档

## Phase 2

- [ ] 新增 `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/rcsd_selection.py`
- [ ] 去掉 pair-local RCSD 空时回退到 scoped/case 世界
- [ ] 在 T04 内实现：
  - [ ] pair-local raw observation
  - [ ] candidate scope
  - [ ] node-centric local unit
  - [ ] road-only local unit
  - [ ] SWSD ↔ RCSD role mapping
  - [ ] A/B/C
  - [ ] primary_main_rc_node
  - [ ] required_rcsd_node

## Phase 3

- [ ] 更新 `case_models.py`
- [ ] 更新 `outputs.py`
- [ ] 更新 `review_render.py`
- [ ] 更新 `review_audit.py`（如需要）
- [ ] 更新 `test_step14_pipeline.py`

## Phase 4

- [ ] 跑 `pytest tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py -q -s`
- [ ] 跑 `Anchor_2` 回归
- [ ] 重点检查 `17943587 / 857993 / 30434673 / 785675`
- [ ] 写 `codex_report.md`
- [ ] 写 `codex_oneclick.md`

