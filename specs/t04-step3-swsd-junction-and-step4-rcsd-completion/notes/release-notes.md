# T04 Step3 SWSD Junction + Step4 RCSD Completion Release Notes

## 状态

- 本地完成时间：`2026-05-04 15:44 CST`
- 本地 HEAD：`c1ee12b`
- 当前分支：`speckit/t04-step3-swsd-junction-phase2-step5-render-migration`
- GitHub 操作状态：未 push、未新建 PR、未提交；按用户要求等待本地统一提交。
- 正式 39-case run root：`outputs/_work/t04_step14_batch/codex_t04_step3_swsd_junction_20260504_131905`
- 目视 / 渲染审计 root：`outputs/_work/t04_swsd_render_audit/codex_t04_step3_swsd_junction_20260504_131905`

## 已修改

- Step3 实体化 `swsd_semantic_junction`，输出 `member_node_ids / intra_junction_road_ids / semantic_arms / inter_junction_connector_road_ids`，并让 Step5 与 render 直接消费该实体派生的 SWSD 道路集合。
- Step4 补齐 `RCSDSemanticJunction`、`RCSDRoadOnlyChain` 与 `swsd_rcsd_alignment_consistent`，持久化到 `step4_event_interpretation.json / step4_candidates.json / review_index`。
- 修复 785731 类 `rcsdroad_only_alignment` 被冻结为 `no_rcsd_alignment` 的链路，使其按 `no_main_evidence_with_rcsdroad_fallback_and_swsd` 消费并 accepted。
- 新增 `final_review_render_audit.json` 与 39-case `render_audit.csv`，用于比对 Step3 SWSD 实体道路集合与 `final_review.png` 可见道路集合。
- 更新模块契约、质量要求、SpecKit tasks/run-log，记录 D4/D5 冻结决策的实证结果与本地串行执行模式。
- 补充/更新 T04 模块测试，包括 Step3 SWSD semantic junction snapshot、Step4 RCSD semantic/chain/consistency verdict，以及当前正式输出下的真实 Anchor_2 回归预期。

## 已验证

- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py tests/modules/t04_divmerge_virtual_polygon/test_consistency_verdict.py tests/modules/t04_divmerge_virtual_polygon/test_step4_rcsd_alignment_type.py -q` -> `23 passed in 3.48s`
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate -x` -> `1 passed in 102.49s`
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_30case_surface_scenario_baseline_gate -x` -> `1 passed in 136.33s`
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_39case_official_surface_scenario_gate -q` -> `1 passed in 172.34s`
- Anchor_2 39-case 正式 run：`total_case_count=39`，`accepted=35`，`rejected=4`，`failed_case_ids=[]`，`review_png_present_count=39`，`nodes_consistency_passed=true`，`performance.threshold_status=within_threshold`。
- `render_audit.csv` 全 39-case `missing_road_ids = []`；命名 case `724067 / 758784 / 760213` 的 `swsd_entity_road_count == render_visible_road_count`。
- Phase 7 QA：CRS 全部 `EPSG:3857`，geometry invalid count `0`，provenance 可追溯，性能阈值通过。
- `python3 -m py_compile` 覆盖所有修改过的 Python 源码与测试文件，结果通过。
- `pytest -s tests/modules/t04_divmerge_virtual_polygon -q` -> `166 passed in 797.40s`
- `git diff --check` 通过。
- 所有修改过的 `.py` 文件体量均低于 `100 KB`，最大为 `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py = 83315` bytes。

## 待确认

- 本轮未执行 GitHub push / PR / commit；等待用户确认是否统一提交。
- 用户可继续目视确认正式 39-case `final_review.png`：`outputs/_work/t04_step14_batch/codex_t04_step3_swsd_junction_20260504_131905/cases/<case_id>/final_review.png`。
- 暂未进行除本次要求之外的历史 PNG fingerprint 比对；这是用户授权的不比对项。
