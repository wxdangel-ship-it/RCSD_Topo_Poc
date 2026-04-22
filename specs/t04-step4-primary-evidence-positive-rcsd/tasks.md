# Tasks: T04 Step4 Primary Evidence + Positive RCSD Iteration

## Phase 1 - Specify

- [ ] T001 冻结本轮 Step4 新口径清单
- [ ] T002 列出当前线程需求 / repo 文档 / 实现之间的偏差

## Phase 2 - Plan

- [ ] T010 明确 Step4 最小代码改动路径
- [ ] T011 明确 review 输出需要新增的字段与图示
- [ ] T012 明确 baseline 保护点与回归样本

## Phase 3 - Tasks

- [ ] T020 更新 `/_chatgpt_sync/RCSD_Topo_Poc/T04_1/REQUIREMENT.md` 的 Step4 章节
- [ ] T021 更新 `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`
- [ ] T022 更新 `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`
- [ ] T023 在 `event_interpretation.py` 中补齐正向 RCSD 输出与 A/B/C 分类
- [ ] T024 在 `case_models.py` / `outputs.py` 中补齐字段落仓
- [ ] T025 在 `review_render.py` / `review_audit.py` 中增强可视化与审计摘要
- [ ] T026 在 `test_step14_pipeline.py` 中补齐最小断言集

## Phase 4 - Implement / Verify

- [ ] T030 跑 `pytest tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py -q -s`
- [ ] T031 跑 `Anchor_2` batch 回归
- [ ] T032 检查 `step4_review_index.csv` / `step4_review_summary.json` / `step4_review_flat`
- [ ] T033 产出 handoff：`codex_report.md` / `codex_oneclick.md`
