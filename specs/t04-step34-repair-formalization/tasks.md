# Tasks: T04 Step3/Step4 Repair Formalization

## Phase 1 - Specify

- [ ] T001 冻结 Step3 `case coordination skeleton` 与 `unit-level executable skeleton` 的边界
- [ ] T001A 冻结 continuous complex/merge 的 `pair propagation context`，明确“unit population 不扩，但 `(L, R, middle-region)` 可跨 sibling internal node 延续”
- [ ] T001B 冻结 `external associated road / closed interval / sibling arm 4 条规则`
- [ ] T002 冻结 Step4 `unit envelope` 字段集合
- [ ] T003 冻结 Step4 geometry/point 语义拆层
- [ ] T004 列出并确认当前 T04 source-of-truth 冲突点

## Phase 2 - Formal Docs

- [ ] T009 同步更新 `/_chatgpt_sync/RCSD_Topo_Poc/T04_1/REQUIREMENT.md`
- [ ] T010 新增 `modules/t04_divmerge_virtual_polygon/architecture/06-step34-repair-design.md`
- [ ] T011 更新 `INTERFACE_CONTRACT.md` 中 Step3/Step4 契约
- [ ] T012 更新 `04-solution-strategy.md`，消除与契约冲突的策略表述
- [ ] T013 更新 `10-quality-requirements.md`，补充 Step3/Step4 回归与图审要求

## Phase 3 - Code Refactor

- [x] T019 用 spec-kit 固化 `event_interpretation.py` 的 facade + 子模块拆分边界
- [x] T019A 新增 `event_interpretation_shared.py`，承接私有 dataclass 与共用 geometry/scope helper
- [x] T019B 新增 `event_interpretation_branch_variants.py`，承接 direct-adjacency / complex continuation / executable branch variants
- [x] T019C 新增 `event_interpretation_selection.py`，承接 candidate merge、priority、case-level reselection、ownership guard
- [x] T019D 更新 `05-building-block-view.md`，把 Step4 编排层拆分写回模块架构视图
- [ ] T020 给 Step3 增加 `topology_scope` 与 unit-level 持久化输出
- [ ] T021 让 Step4 只消费 unit-level executable skeleton
- [ ] T022 从 Step4 可执行输入中区分 `context_augmented_node_ids` 与 same-case sibling `branch continuation`
- [ ] T023 为 complex/multi 引入 `ordered pair (L, R)` 与 `unit-local event branches / boundary branches / preferred axis`
- [ ] T023A 为 continuous merge complex 增加 `(L, R, middle-region)` sibling propagation
- [ ] T023B 在 sibling node 上按 `external associated road -> no inserted roads -> side preservation -> min turn` 选择 arm
- [ ] T024 禁止 complex 局部 scope 静默回退全走廊；改成显式 degraded state
- [ ] T025 拆分 `selected_component_union_geometry / localized_evidence_core_geometry / coarse_anchor_zone_geometry`
- [ ] T026 拆分 `fact_reference_point / review_materialized_point`
- [ ] T027 规范 reverse tip 状态机，只保留受控触发原因

## Phase 4 - Regression

- [ ] T030 跑 `pytest tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py -q -s`
- [ ] T031 用 `/mnt/e/TestData/POC_Data/T02/Anchor_2` 跑全量 batch
- [ ] T032 重点回归 `17943587 / 30434673 / 73462878`
- [ ] T032A 新增 real-case `17943587 -> node_17943587` 回归，锁住 `510969745` 与 `607951495 + 528620938` 的 branch membership
- [ ] T032B 新增 `17943587 -> node_17943587` 几何回归，锁住 `pair_local_middle within structure_face within region`
- [ ] T032C 新增 `17943587 -> node_55353233` 回归，锁住 `502953712 + 41727506 + 620950831`
- [ ] T032D 新增 `17943587 -> node_55353233` 回归，锁住 sibling arm 选择不会退化成 `605949403`
- [x] T032E 新增 `17943587 -> node_55353239` 回归，锁住本地三臂 branch memberships 与当前 off-node Layer 2 candidate 行为
- [ ] T033 新增至少四类 Step4 回归样例：
- [ ] T034 `forward throat-pass`
- [ ] T035 `same-axis conflict -> reverse success`
- [ ] T036 `forward/reverse 都不通过 throat`
- [ ] T037 `shared component but Δs>5m allowed`

## Phase 5 - Handoff

- [ ] T040 输出修复实现报告
- [ ] T041 输出回归结果与风险清单
- [ ] T042 重新请求 Cursor/人工审计
