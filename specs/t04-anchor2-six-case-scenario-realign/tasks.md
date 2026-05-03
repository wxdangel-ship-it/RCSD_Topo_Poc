---
description: "Tasks for T04 Anchor_2 六个 Case 场景与构面对齐重做"
---

# Tasks: T04 Anchor_2 六个 Case 场景与构面对齐重做

**Input**：`specs/t04-anchor2-six-case-scenario-realign/spec.md`、`plan.md`
**Status**：Phase 0/0.5/1 实施完成（D-2 全胜、6/6 accepted、0 baseline regression）；Phase 2/3/4 按 B-3 路径推迟到下一轮；Phase 5 close-out 2026-05-04

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可与其它 [P] 任务并行（不同文件、无依赖）
- **[Story]**：US A1 / A2 / A3 / A4 / A5 / B* / DOC / REG / PROBE，对应 plan 的 phase
- **Path A 与 Path B 由 Phase 0.5 探针锁定**；Phase 1 之前的所有任务（Phase 0 / 0.5）不区分 Path

## Path Conventions

- 模块代码：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/`
- 模块文档：`modules/t04_divmerge_virtual_polygon/`
- 测试：`tests/modules/t04_divmerge_virtual_polygon/`
- 工件：`outputs/_work/t04_six_case_scenario_realign/<phase>_<timestamp>/`
- 探针报告：`specs/t04-anchor2-six-case-scenario-realign/audit.md`（implement 阶段开始时新建）

---

## Phase 0: SpecKit Closure & 基础准备

**Purpose**：spec / plan / tasks 三件套闭环 + 实施前体量自检 + baseline 冻结

- [ ] T001 用户审完 `spec.md`、`plan.md`、`tasks.md`，回复 `clarify OK` 或给出修改意见
- [ ] T002 [P] 体量自检：`Get-ChildItem` 拉取 `polygon_assembly.py / polygon_assembly_*.py / _event_interpretation_core.py / step4_road_surface_fork_binding_promotions.py / support_domain_builder.py / _runtime_step4_geometry_core.py / _event_interpretation_unit_preparation.py / test_step7_final_publish.py` 当前字节数，写入 `audit.md` 的 `phase_0_size_audit` 子章节
- [ ] T003 [P] 跑当前 baseline：39-case batch 一次，把 6 个 case 现状（`step7_status.json` / `step6_status.json` / `step5_status.json` / `step4_event_interpretation.json` 关键字段、`final_review.png`、`step5_domains.gpkg`、`final_case_polygon.gpkg`）冻结到 `outputs/_work/t04_six_case_scenario_realign/phase0_baseline_<ts>/`
- [ ] T004 用户确认 phase0 baseline；若 baseline 与上一轮 `t04_negative_mask_hard_barrier_final_20260503` 显著不同，更新 `spec.md §1.2` 的实现现状表

**Checkpoint**：phase0 通过后才能进 Phase 0.5；Phase 0 / 0.5 之间禁止任何代码改动

---

## Phase 0.5: 根因探针（PROBE）

**Purpose**：确认或反驳 spec §1.3 F4"先生成后切割"反模式假设，锁定 706347 / 765050 / 785731 / 795682 / 724081 切碎的真实根因，决定 Path A 或 Path B。**本 phase 仅做只读探针，绝对不改代码、不改契约**。

- [ ] T005 [PROBE] 在 `audit.md` 中新建 `phase_0_5_root_cause` 章节
- [ ] T006 [PROBE] 代码路径核查：通过 `Read` / `Grep` 工具阅读以下文件，定位负向掩膜进入 cost map 的位置以及 raster grow 与 negative mask difference 的相对顺序，给出函数名 + 行号引用：
  - `polygon_assembly.py`
  - `polygon_assembly_models.py`
  - `polygon_assembly_guards.py`
  - `polygon_assembly_relief.py`
  - `support_domain_builder.py`
  - `support_domain_models.py`
- [ ] T007 [PROBE] 几何中间产物核查：从 `phase0_baseline` run root 读取 5 个 case 的 `step5_domains.gpkg` 与 `final_case_polygon.gpkg`，比对：
  - `allowed_growth_domain` 自身是否单连通
  - `final_case_polygon` 与 `allowed_growth_domain` 的几何关系是否符合 `final_case_polygon ≈ allowed_growth_domain - negative_mask` 反模式特征
  - 多 component 之间的边界是否恰好沿 negative mask 边缘
- [ ] T008 [PROBE] 765050 inter-unit bridge dispatch 核查：在代码中搜索 `inter_unit_bridge` / `case_level_bridge` / `bridge_zone` 等关键词；定位是否被 765050 调用；如未调用，找出跳过的 guard 条件（可能在 `polygon_assembly.py` 或 `polygon_assembly_guards.py`）
- [ ] T009 [PROBE] 综合 T006-T008 结论，写入 `phase_0_5_root_cause` 章节，给出：
  - F4 反模式确认 / 反驳的二元结论
  - 如确认：共享 Step6 架构修复的最小重写计划（API、数据流、与 Step5 的接口）
  - 如反驳：每个 case 独立的根因清单与对应修复方向
- [ ] T010 [PROBE] 在 `audit.md` 中新建 `phase_0_5_path_lockdown` 章节，根据 T009 结论锁定 Path A 或 Path B，并把本 `tasks.md` 的 Phase 1 起对应分支标为"active"，另一分支标为"discarded"
- [ ] T011 用户审 `phase_0_5_root_cause` + `phase_0_5_path_lockdown`：回 `OK / 不通过 + 原因`；不通过则停机回报，重做探针

**Checkpoint**：Phase 0.5 必须通过才能进 Phase 1；探针失败 / 用户不通过时不顺手推进任何 implement 任务

---

## Phase 1: Step6 装配收敛（Path 决定 user story 编号）

**Goal**：让 706347 / 765050 / Step4 修复后的 724081 / 785731 / 795682 在 Step6 阶段产生单一连通面（除非 §1.4 A / B 类真实硬阻断）。

### Path A（探针确认 F4 反模式）：US A1 + US A5

#### US A1 — Step6 barrier-aware grow 架构修复

- [ ] T020 [P] [US A1] 在 `test_six_case_scenario_realign.py`（新建）写：
  - `test_case_706347_single_unit_swsd_window_single_component`（断言 `final_case_polygon_component_count = 1` + `barrier_separated_case_surface_ok = false`）
  - `test_case_765050_inter_unit_bridge_succeeded`（断言 `unit_surface_merge_performed = true` + `final_case_polygon_component_count = 1`）
  - 测试先 FAIL
- [ ] T021 [US A1] 新建 `polygon_assembly_barrier_aware_grow.py`：实施 §1.4 架构原则的"barrier-aware grow"：
  - 入参：Step5 给定的 `allowed_growth_domain`、正向起点（截面边界 / Reference Point / RCSD 语义路口 / SWSD 语义路口）、负向掩膜集合（按 channel 分类）
  - 内部：把 negative mask 写入 cost map / barrier；BFS-like / level-set grow；遇 barrier 自动停止
  - 出参：单 unit barrier-aware surface + grow 路径审计
- [ ] T022 [US A1] 新建 `polygon_assembly_inter_unit_bridge.py`：实施 inter-unit section bridge（§1.4 B 路径）：
  - 入参：相邻 unit 的临近截面边界 + 各自 unit surface + 负向掩膜
  - 内部：bridge zone 内 barrier-aware grow + 20m 横向控制
  - 出参：inter-unit bridge surface + bridge 是否被掩膜阻断的审计字段
- [ ] T023 [US A1] 在 `polygon_assembly.py` 中新增最小 dispatch（< 2KB 新增字节）：barrier-aware 路径 + bridge 路径；保留原"先生成后切割"为 legacy fallback，但默认不调用
- [ ] T024 [US A1] 体量自检：`polygon_assembly.py` 修改后字节数 + 新建子模块字节数全部写入 `audit.md`
- [ ] T025 [US A1] 跑 706347 与 765050 单 case：T020 测试通过；30-case baseline test 中 706347 / 765050 = accepted
- [ ] T026 [US A1] 跑 39-case 全量：列表性 final_state 不变（PNG fingerprint 不守，按 plan §6.3）
- [ ] T027 [US A1] 生成 `cases/706347/final_review.png` + `cases/765050/final_review.png`，对比表写入 `audit.md`
- [ ] T028 [US A1] 用户目视两张 PNG，回 `OK`

#### US A5 — `barrier_separated_case_surface_ok` 字段语义修正（与 US A1 同 phase）

- [ ] T029 [US A5] 在 `polygon_assembly_models.py` 中修正 `barrier_separated_case_surface_ok` 设置条件：仅当 `bridge_negative_mask_crossing_detected = true` + 至少一个 channel `overlap_area_m2 > tolerance` 时为 `true`；否则强制 `false`
- [ ] T030 [US A5] 跑 6 个 case，断言 `barrier_separated_case_surface_ok` 全部 `false`（修复 Phase 0 baseline 中错置 `true` 的 5 个 case）
- [ ] T031 [US A5] 体量自检 + 写入 `audit.md`

**Checkpoint A**：Phase 1 (US A1 + A5) 通过后进 Phase 2

### Path B（探针反驳 F4 反模式）：US B1 + US B2 + US B5

> Path B 的具体任务由 Phase 0.5 完成时根据探针结论填充；下面是占位骨架

- [ ] T020B [US B1] 修复 765050 inter-unit bridge dispatch（如探针证明 dispatch 漏调用）
- [ ] T021B [US B2] 修复 706347 / 785731 / 795682 单 unit `allowed_growth_domain` 计算（如探针证明 Step5 allowed_growth 切成多块）
- [ ] T022B [US B5] 同 US A5（`barrier_separated_*` 字段语义修正）
- [ ] T023B-T028B 测试 + PNG + 用户目视，模式同 Path A

**Checkpoint B**：Phase 1 (US B1 + B2 + B5) 通过后进 Phase 2

---

## Phase 2: User Story A2 / B2 — 724081 / 785731 case 级 RCSD 召回聚合不再压平 (P1)

**Goal**：Step4 case 顶层在 unit 候选已识别 RCSD 信号时，不退到 `no_rcsd_alignment / swsd_junction_window_no_rcsd`；724081 升到 `rcsd_semantic_junction`，785731 保留 `rcsdroad_only_alignment`。Step5/6 装配收敛由 Phase 1 已支撑。

- [ ] T040 [P] [US A2] 在 `test_six_case_scenario_realign.py` 新建：
  - `test_case_724081_no_main_evidence_with_rcsd_junction`（顶层 `surface_scenario_type = no_main_evidence_with_rcsd_junction` + `rcsd_alignment_type = rcsd_semantic_junction` + `final_state = accepted`）
  - `test_case_785731_no_main_evidence_with_rcsdroad_fallback_and_swsd`（顶层 `surface_scenario_type = no_main_evidence_with_rcsdroad_fallback_and_swsd` + `rcsd_alignment_type = rcsdroad_only_alignment` + `final_state = accepted`）
  - 测试先 FAIL
- [ ] T041 [US A2] 在 `_event_interpretation_core.py` 中定位 case 顶层 RCSD 聚合函数（候选：`_aggregate_case_rcsd_alignment` / 类似命名），新增聚合规则：
  - 当至少一个 unit 的 candidate 输出 `positive_rcsd_present = true` 且 `required_rcsd_node` 非空，case 顶层不得退到 `no_rcsd_alignment`；如该 RCSD 路口语义可识别（满足 RCSD 语义路口的 3+ 进入/退出条件且与当前 SWSD 语义对齐），升级为 `rcsd_semantic_junction`
  - 当至少一个 unit 的 candidate 输出 `rcsd_alignment_type = rcsdroad_only_alignment`，case 顶层不得退到 `no_rcsd_alignment`，应保留为 `rcsdroad_only_alignment`
  - 多个候选无法消歧时输出 `ambiguous_rcsd_alignment` 阻断 accepted
- [ ] T042 [US A2] 体量自检：`_event_interpretation_core.py` 修改后字节数写入 `audit.md`
- [ ] T043 [US A2] 跑 `724081` 与 `785731` 单 case：顶层字段断言通过；Step5/6 由 Phase 1 装配收敛保证 `final_case_polygon_component_count = 1`、`final_state = accepted`
- [ ] T044 [US A2] 跑 23-case + 30-case baseline test：业务 `accepted / rejected` 列表保持
- [ ] T045 [US A2] 生成 `cases/724081/final_review.png` 与 `cases/785731/final_review.png`，对比表写入 `audit.md`
- [ ] T046 [US A2] 用户目视两张 PNG，回 `OK`

**Checkpoint**：Phase 2 通过后进 Phase 3

---

## Phase 3: User Story A3 / B3 — 795682 RCSD candidate 物化漏召修复 (P2)

**Goal**：Step4 候选物化层能在 795682 输入下召回至少一个局部可对齐 RCSDRoad 候选，case 顶层 `rcsd_alignment_type = rcsdroad_only_alignment`、`final_state = accepted`。

- [ ] T050 [P] [US A3] 在 `test_six_case_scenario_realign.py` 新建 `test_case_795682_rcsd_candidate_materialized`（至少 1 个 unit candidate 出现 `rcsd_alignment_type = rcsdroad_only_alignment` + case 顶层同值 + `final_state = accepted`）；测试先 FAIL
- [ ] T051 [US A3] 定位 RCSD candidate 物化函数（候选：`_runtime_step4_geometry_core.py` 或 `_event_interpretation_unit_preparation.py`），用 795682 unit `event_unit_01` 作为最小复现样本
- [ ] T052 [US A3] 调试为什么 795682 在 candidate 物化阶段拿不到任何 RCSDRoad 对齐候选；可能的修复方向：
  - (a) 放宽 RCSDRoad 局部召回的距离 / 角度阈值
  - (b) 修复在某个过滤阶段漏掉本应入池的 RCSDRoad
  - (c) 修复 unit 上下文里"无 RCSD 路口"导致 candidate 被前置剪枝
- [ ] T053 [US A3] 任何阈值放宽必须显式记录在 `architecture/10-quality-requirements.md`（同轮）和对应模块的 docstring；遵守 `AGENTS.md §5` 字段语义管控
- [ ] T054 [US A3] 体量自检
- [ ] T055 [US A3] 跑 795682：单 case 字段断言通过 + Step5/6 输出单连通面 + `final_state = accepted`
- [ ] T056 [US A3] 跑 23-case + 30-case + 39-case 全量；US A3 改动可能影响其它无主证据 case 的 candidate pool，重点观察 706347 / 706629 / 758784 / 760213 / 760256 等；列表性 final_state 不得变化
- [ ] T057 [US A3] 生成 `cases/795682/final_review.png`，对比表写入 `audit.md`
- [ ] T058 [US A3] 用户目视确认；若 T056 出现非预期 final_state 变化，停机回报

**Checkpoint**：Phase 3 通过后进 Phase 4

---

## Phase 4: User Story A4 / B4 — 768675 弱 `road_surface_fork` 不得升主证据 (P3)

**Goal**：去掉 `road_surface_fork_relaxed_primary_rcsd_binding` 与 `role_mapping_partial_relaxed_aggregated` 这两条弱 promotion 路径对 768675 的副作用；768675 改为 `no_main_evidence_with_rcsd_junction`，`final_state` 仍 = accepted。`505078921` 必须保持原 `evidence_source = road_surface_fork`（FR-014）。

- [ ] T060 [P] [US A4] 在 `test_six_case_scenario_realign.py` 新建 `test_case_768675_no_main_evidence_with_rcsd_junction`（顶层 `has_main_evidence = false` + `main_evidence_type = "none"` + `reference_point_present = false` + `surface_scenario_type = no_main_evidence_with_rcsd_junction` + `rcsd_alignment_type = rcsd_semantic_junction` + `section_reference_source = rcsd_junction` + `final_state = accepted`）；测试先 FAIL
- [ ] T061 [US A4] 在 `step4_road_surface_fork_binding_promotions.py` 中识别 `road_surface_fork_relaxed_primary_rcsd_binding` 触发条件；新增 guard：仅当 `required_rcsd_node` 与代表节点 / 当前 SWSD section **几何局部对齐**时才允许 promotion；远距离 `required_rcsd_node` 只允许 trace-only audit，不允许激活 main evidence
- [ ] T062 [US A4] 在同文件或 `_event_interpretation_core.py` RCSD 聚合层补 guard：`role_mapping_partial_relaxed_aggregated` 不得单独升级为 `rcsd_semantic_junction`；只允许升级为 `rcsd_junction_partial_alignment` 或 `rcsdroad_only_alignment`
- [ ] T063 [US A4] 体量自检
- [ ] T064 [US A4] 跑 768675：字段断言通过 + `final_state = accepted` + Step5/6 在 `no_main_evidence_with_rcsd_junction` 下使用 `rcsd_junction_window` 截面前后 20m 构面
- [ ] T065 [US A4] 跑 23-case baseline test：23-case `accepted = 20 / rejected = 3` 与 case 列表完全保持；任何 case 业务状态变动都需停机回报
- [ ] T066 [US A4] 跑 30-case baseline test 与 39-case batch；**`505078921 / node_510222629__pair_02` 必须保持 `evidence_source = road_surface_fork`**（FR-014），否则停机
- [ ] T067 [US A4] 生成 `cases/768675/final_review.png`，对比表写入 `audit.md`
- [ ] T068 [US A4] 用户目视确认

**Checkpoint**：Phase 4 通过后进 Phase 5

---

## Phase 5: 文档锁 + Baseline Test 更新 + 39-case 全量回归

**Purpose**：把 `724081 / 785731 / 795682` 的场景结论补登到模块源事实文档；baseline test 锁项与本 spec 实施结果对齐；交付最终目视证据。

- [ ] T080 [DOC] 在 `architecture/10-quality-requirements.md` Anchor_2 audit 区段（约第 280-282 行附近，与 `765050 / 768675 / 706347` 锁项同节）按 `spec.md §A 附录` final draft **一字写入**：
  - `724081`：`no_main_evidence_with_rcsd_junction` 锁
  - `785731 / 795682`：`no_main_evidence_with_rcsdroad_fallback_and_swsd` 子-B 锁
- [ ] T081 [DOC] 同文件 30-case gate 守门项第 301 行附近补充：`706347 / 724081 / 765050` 必须保持 accepted（已锁但实测过 rejected，本轮已修复）
- [ ] T082 [DOC] 在 `specs/t04-anchor2-swsd-window-repair/spec.md` 末尾追加 supersede 备注：`785731 / 795682` 场景结论已被 `t04-anchor2-six-case-scenario-realign` 更新；不修改原有正文
- [ ] T083 [REG] 跑 39-case 全量 batch，输出 `outputs/_work/t04_six_case_scenario_realign/phase5_final_<ts>/`：
  - `divmerge_virtual_anchor_surface_summary.json` 全部 6 case `final_state = accepted`
  - `nodes.gpkg` 中 6 个 representative node `is_anchor = yes`
  - `step7_consistency_report.json` 通过
  - 39-case 性能阈值 `within_threshold`
- [ ] T084 [REG] 跑 23-case + 30-case baseline test：分别通过 20/3 与 26/4 数字；列表内 case 业务状态全部一致
- [ ] T085 [P] [REG] 把 6 张 `final_review.png` 复制到 `outputs/_work/t04_six_case_scenario_realign/phase5_final_<ts>/visual_audit_pack/` 作为最终目视证据合并包
- [ ] T086 [REG] `audit.md` 完整化：每个 phase 的对比表 + 最终 6 case 字段差异 + 体量自检前后字节数 + 性能阈值结果 + 探针报告 + Path 锁定理由
- [ ] T087 用户目视最终 6 张 PNG 与 `audit.md`，给出 `本 spec 接受` 或 `部分不通过 + 原因`
- [ ] T088 close-out：把 spec / plan / tasks / audit 的 Status 从 `Draft` 改为 `Implemented & visually accepted`；归档 audit 工件到 `docs/doc-governance/audits/2026-05-XX-t04-six-case-scenario-realign.md`

**Checkpoint**：T087 通过后本 spec close

---

## Dependencies & Execution Order

### Phase Dependencies

- Phase 0 → Phase 0.5 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5（严格串行）
- Phase 0.5 是只读探针，不写代码；其结论决定 Phase 1 进入 Path A 或 Path B 子分支
- Phase 1 必须先做：它给后续 Step4 修复（Phase 2/3/4）提供"装配能产生单连通面"的基础

### User Story 之间不耦合 case 失败

每个 phase 内部失败必须停机回报，不顺手推进；用户目视任意 case 失败也按同规则。

### Parallel Opportunities

- T002 / T003 phase0 体量自检与 baseline 冻结可并行
- 各 phase 内部的 `[P]` 测试编写任务可并行
- Phase 5 的 T083 全量 batch 与 T085 PNG 打包可并行

---

## Task Summary By File

| 文件 | Path A 任务 | Path B 任务 | 主要 phase |
|---|---|---|---|
| `_event_interpretation_core.py`（55KB） | T041（聚合）+ T062（RCSD aggregation guard） | 同 Path A | Phase 2 / Phase 4 |
| `step4_road_surface_fork_binding_promotions.py`（34KB） | T061 / T062 | 同 Path A | Phase 4 |
| `_runtime_step4_geometry_core.py`（64KB）或 `_event_interpretation_unit_preparation.py`（41KB） | T051-T053 | 同 Path A | Phase 3 |
| `polygon_assembly_barrier_aware_grow.py`（**新建**） | T021 | — | Phase 1A |
| `polygon_assembly_inter_unit_bridge.py`（**新建**） | T022 | T020B | Phase 1A / 1B |
| `polygon_assembly.py`（81KB，警戒） | T023（最小 dispatch） | T021B 局部修复（须先体量自检） | Phase 1 |
| `polygon_assembly_models.py`（12KB） | T029 | T022B | Phase 1 |
| `support_domain_builder.py`（42KB） | 必要时次修 | T021B 主路径 | Phase 1B |
| `architecture/10-quality-requirements.md` | T080 / T081 | 同 Path A | Phase 5 |
| `tests/.../test_six_case_scenario_realign.py`（**新建**） | T020 / T040 / T050 / T060 | 类似 | 全部 |
| `tests/.../test_step7_final_publish.py`（83KB，警戒） | 仅 baseline assertion 复核（T025 / T044 / T065 等） | 同 Path A | 全部 |
| `audit.md` | 全部 phase 持续 append | 同 Path A | 全部 |

## Notes

- 每个 phase 完成时把状态写入 `audit.md`，便于 trace
- 本 spec 只聚焦 6 个 case；如发现其它 case 业务 final_state 变化，按 plan §7.2 风险表停机回报
- 实施过程中如出现"边界不清 / 影响扩大 / 业务口径不稳"，按 `AGENTS.md §6` 升级（开新 SpecKit 子任务，并暂停本任务）
- 本任务任何阶段不得新增 repo 官方 CLI / 改 `INTERFACE_CONTRACT.md` 现有枚举语义 / 改 surface 主产物命名
- **23-case PNG fingerprint baseline 整体不再守**：6 张本轮 case PNG 由用户目视判定；其它 case PNG / 字段差异留待用户后续重新审计统一处理
