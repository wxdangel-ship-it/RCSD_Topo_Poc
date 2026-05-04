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

## 2026-05-04 Degree-2 Boundary 修订

### 已修改

- 用户确认新业务口径：SWSD / RCSD 语义路口 connector 只允许沿 `degree == 2` passthrough chain 穿透；遇 `degree >= 3` 必须立即作为 semantic boundary 停止。
- `spec.md / plan.md / tasks.md / INTERFACE_CONTRACT.md` 已同步删除旧的 degree==3 角度连续穿透口径。
- Step3 `_walk_arm_to_neighbor_semantic_junction` 已改为 degree>=3 立即停止，并修正 seed 处理顺序：只有确认 seed road 直接触达当前 `member_node_ids` 后才可进入 connector。
- SWSD 单测新增/更新 degree>=3 boundary 守门；真实 snapshot 新增 `698380 / 17943587`，分别锁定排除 `109815830 / 29824276`。
- RCSD 单测新增对称守门，确认 `RCSDSemanticJunction` connector 在 degree>=3 节点停止。

### 已验证

- `698380 / 17943587` 双 case run：`outputs/_work/t04_degree2_boundary/cases_17943587_698380_degree2_boundary_v2`，`109815830 / 29824276` 均已进入 `unrelated_swsd_road_ids`。
- 39-case 固定输出：`outputs/_work/t04_degree2_boundary/anchor2_39case_degree2_boundary_v2`。
- 39-case render audit：`outputs/_work/t04_degree2_boundary/anchor2_39case_degree2_boundary_v2_render_audit/render_audit.csv`，`missing_road_ids` 全 0。
- 39-case 汇总：`total_case_count=39`，`accepted=35`，`rejected=4`，`failed_case_ids=[]`，`nodes_consistency_passed=true`。
- 与上一轮输出相比，18 个 case 去除了越过 semantic boundary 的 SWSD roads；无新增 over-recall。
- 全 39-case 拓扑审计：非 direct connector 均至少有一个 `degree==2` endpoint，`violation_count = 0`。
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py tests/modules/t04_divmerge_virtual_polygon/test_step4_rcsd_alignment_type.py -q` -> `22 passed in 9.59s`。
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_39case_official_surface_scenario_gate -q` -> `1 passed in 187.31s`。
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_30case_surface_scenario_baseline_gate -q` -> `2 passed in 215.17s`。
- `pytest -s tests/modules/t04_divmerge_virtual_polygon -q` -> `167 passed in 928.69s`。
- `.venv/bin/python -m py_compile` 覆盖本轮修改 Python 文件，通过。
- `git diff --check` 通过。
- 本轮修改 Python 文件均低于 `100 KB`。

### 待确认

- 需要用户目视确认新的 39-case `final_review.png`，尤其是本次去除 SWSD over-recall 的 17 个 case。
- 本轮尚未 commit / push。

## 2026-05-04 Semantic Group Degree Boundary 补充

### 已修改

- 根因修正：先前 degree-2 规则仍有路径按物理单节点 incident road 数判定；现在统一改为语义节点组进入 / 退出道路 degree。
- SWSD / RCSD 同口径：有效 `mainnodeid` 按 `mainnodeid` 聚合，无有效 `mainnodeid` 按节点自身 `id` 成组；组内道路不计入 degree。
- Step3 SWSD arm walk、Step4 RCSD connector、RCSDRoad-only endpoint 均改为语义组 degree==2 可穿透、degree>=3 停止。
- 新增 `706243 / 724081 / 785731` 真实 snapshot，锁定本轮用户指出的有 `mainnode` 语义路口越界问题。

### 已验证

- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py tests/modules/t04_divmerge_virtual_polygon/test_step4_rcsd_alignment_type.py` -> `25 passed in 16.24s`。
- 目标输出：`outputs/_work/t04_degree2_boundary/anchor2_semantic_group_degree_target_cases`，`785731 / 706243 / 724081 / 698380 / 17943587` 全部 accepted。
- 新 39-case 输出：`outputs/_work/t04_degree2_boundary/anchor2_39case_semantic_group_degree_20260504_001`，`accepted=35`，`rejected=4`，`failed_case_ids=[]`，`nodes_consistency_passed=True`，`review_png_present_count=39`。
- 目标三例越界 road 均不在 related，且进入 unrelated：`785731: 517308491 / 33027389`，`706243: 88046473`，`724081: 516795731`。
- 目标三例 CRS 均为 `EPSG:3857`，输入 / 输出 geometry invalid count 均为 `0`，SWSD road-node endpoint missing count 均为 `0`。
- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_39case_official_surface_scenario_gate` -> `1 passed in 201.41s`。
- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_30case_surface_scenario_baseline_gate` -> `2 passed in 244.05s`。
- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_new_structure_only_road_surface_forks_keep_760598_rejected` -> 更新 724081 新几何预期后，`1 passed in 24.13s`。
- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon` -> `170 passed in 848.56s`。
- `.venv/bin/python -m py_compile` 与 `git diff --check` 均通过；本轮 Python 源码 / 测试文件均低于 `100 KB`，最大 `test_step7_final_publish.py = 83315` bytes。

### 待确认

- 请用户目视确认新 39-case PNG：`outputs/_work/t04_degree2_boundary/anchor2_39case_semantic_group_degree_20260504_001/step4_review_flat`。
- 本轮尚未 commit / push。

## 2026-05-04 Baseline/Test Contract Cleanup

### 已修改

- 将 Anchor_2 baseline 口径统一为 official 39-case：`39 / 35 / 4`，rejected set 为 `607602562 / 760598 / 760936 / 857993`。
- 新增 official manifest：`tests/modules/t04_divmerge_virtual_polygon/data/anchor2_official_39case_baseline_20260504.json`。
- 将 23-case 与 30-case 测试从真实 batch gate 降为 manifest projection gate，保留历史子集覆盖但不再维护独立真相或 PNG raw fingerprint。
- 同步更新模块契约、README、architecture、glossary、SpecKit `spec / plan / tasks` 与 `code-size-audit.md`。

### 已验证

- Manifest JSON 格式校验通过。
- `test_step7_final_publish.py` py_compile 通过。
- legacy projection gates：`2 passed in 3.10s`。
- official 39-case gate：`1 passed in 173.71s`。
- `test_step7_final_publish.py = 56366` bytes，低于 `100 KB` 硬阈值。

### 待确认

- 未执行全模块回归；本轮清理只改测试契约与文档，并已跑 official 39-case gate。
- 未 commit / push。
