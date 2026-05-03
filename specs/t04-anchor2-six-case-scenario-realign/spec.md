# Feature Specification: T04 Anchor_2 六个 Case 场景与构面对齐重做

**Feature Branch**: `codex/t04-anchor2-six-case-scenario-realign`
**Created**: 2026-05-03
**Status**: Implemented (D-2 only) — Phase 2-4 deferred; close-out 2026-05-04 (B-3 path)
**Input**: 用户在 2026-05-03 目视审计后给出 6 个 Anchor_2 case（`706347`、`724081`、`765050`、`768675`、`785731`、`795682`）的最终场景结论；要求按场景结论修正 T04 实现，使 `surface_scenario_type` 与 `final_state` 与目视一致，并交付 `final_review.png` 供最终目视确认。

## 1. Context

### 1.1 与上一轮 SpecKit 的关系

`specs/t04-anchor2-swsd-window-repair/spec.md` 在 2026-05-02 把 `785731 / 795682` 归类为 `no_main_evidence_with_swsd_only`；本轮目视审计把这两个 case 重新归类为 `no_main_evidence_with_rcsdroad_fallback_and_swsd`（子-B：`rcsdroad_only_alignment`）。本 spec 显式 supersede 上一轮关于 `785731 / 795682` 的场景结论；其余 case（`785629 / 785631 / 807908 / 823826` 等）不在本轮范围内。

### 1.2 实现现状（基于 `outputs/_work/t04_negative_mask_hard_barrier_final/negative_mask_hard_barrier_final_20260503/`）

| Case | 用户目视应属场景 | 当前实现判定 | 当前 `final_state` | `final_case_polygon_component_count` |
|---|---|---|---|---|
| 706347 | `no_main_evidence_with_rcsdroad_fallback_and_swsd` 子-B | `no_main_evidence_with_rcsdroad_fallback_and_swsd` 子-B | rejected | 2 |
| 724081 | `no_main_evidence_with_rcsd_junction` | `no_main_evidence_with_rcsdroad_fallback_and_swsd` 子-B | rejected | 4 |
| 765050 | `no_main_evidence_with_rcsdroad_fallback_and_swsd` 子-B（3 unit 共享 `5392491910661086`） | 同左 | rejected | 2（3 unit） |
| 768675 | `no_main_evidence_with_rcsd_junction` | `main_evidence_with_rcsd_junction`（虚构主证据） | accepted（路径错） | 1 |
| 785731 | `no_main_evidence_with_rcsdroad_fallback_and_swsd` 子-B | `no_main_evidence_with_swsd_only` | rejected | 3 |
| 795682 | `no_main_evidence_with_rcsdroad_fallback_and_swsd` 子-B | `no_main_evidence_with_swsd_only` | rejected | 4 |

### 1.3 实现错位形态（按 case 数据反推）

- **F1 — 弱 `road_surface_fork` 升主证据 + `role_mapping_partial_relaxed_aggregated` 升完整 `rcsd_junction`（`768675`）**：Step4 将 `evidence_source = road_surface_fork` 与 `decision_reason = road_surface_fork_relaxed_primary_rcsd_present` 联动促成 `has_main_evidence = true` + `reference_point_present = true`；契约 `architecture/10-quality-requirements.md` 第 35-36、43、53 行已禁止该路径。
- **F2 — case 顶层 RCSD 召回聚合压平（`724081`、`785731`）**：unit 内候选具有 `positive_rcsd_present = true` 或 `rcsd_alignment_type = rcsdroad_only_alignment`，但聚合到 case 顶层时退到 `swsd_junction_window_no_rcsd` / `no_rcsd_alignment`。
- **F3 — RCSD candidate 物化漏召（`795682`）**：unit 级深层从未出现 `rcsdroad_only_alignment` 候选，是 Step4 候选物化阶段就没拿到样本。
- **F4 — Step6 装配阶段可能存在"先生成后切割"反模式（共性假设，需 Phase 0.5 探针验证）**：5 个 rejected case（`706347 / 724081 / 765050 / 785731 / 795682`）的最终 `final_case_polygon` 全部出现 `final_case_polygon_component_count ∈ {2, 3, 4}`，且所有 case 的 `bridge_negative_mask_crossing_detected = false` + 全部 negative mask channel `overlap_area_m2 = 0.0`，**没有任何一个 case 命中 §1.4 中"A 场景两截面对象间真实硬阻断"或"B 复杂多 unit inter-unit bridge 真实硬阻断"的合法多 component 路径**。按 §1.4 架构原则，缺真实硬阻断举证的多 component 都属于实现 bug；初步推断当前 Step6 raster / polygon assembly 不是"barrier-aware grow"，而是"先 grow 出包络 region、后用 negative mask 做几何 difference 切割"，导致包络区域跨越掩膜的多个分支被切成多 polygon。`765050` 的 `unit_surface_merge_performed = false`、未实施 inter-unit section bridge 是同一架构问题在多 unit 形态上的额外表现：连 bridge 都没尝试，自然也谈不上"bridge 真实硬阻断"。该假设须在 Phase 0.5 探针中通过实测 raster cost map / grow 序列与 inter-unit bridge dispatch 路径复核后才能确认或反驳。
- **F5 — `barrier_separated_case_surface_ok` 审计标记滥用（5 个 rejected case 全部命中）**：`bridge_negative_mask_crossing_detected = false` 且所有 channel `overlap_area_m2 = 0.0` 时，该字段不应被设为 `true`。

### 1.4 用户给定架构原则（2026-05-03 lockdown）

T04 Step5 / Step6 的构面装配必须遵循"负向掩膜先行 / 正向生长 barrier-aware"原则：

- **掩膜在生长之前生效**：负向掩膜（unrelated SWSD nodes / roads、unrelated RCSDNode / RCSDRoad、forbidden domain、terminal cut、不可通行区、导流带 void / interior 等）必须在 Step5 即写入 cost map / 生长屏障；Step6 raster / polygon assembly 在 grow 阶段就把这些区域当作不可越过的硬墙，不允许越过后再裁剪。
- **正向生长不得侵入负向掩膜**：正向掩膜（must_cover / allowed_growth / 截面边界内的正向 SWSD roads + RCSDRoad fallback）从合法起点（截面边界、Reference Point、SWSD 语义路口、RCSD 语义路口、`5392491910661086` 类 unique alignment 对象等）开始 BFS-like / level-set 生长；遇到负向掩膜自动停止，不得跨过。
- **禁止"先生成后切割"反模式**：不得先生成不受掩膜约束的初始包络面（如沿 allowed_growth domain 的整体 union），再用负向掩膜做几何 difference；该模式必然导致跨掩膜的不同分支被切成多 polygon，违反"barrier-aware"。
- **multi-component 只允许出现在以下两类真实硬阻断场景**：
  - **A. 场景 `main_evidence_with_rcsd_junction` 的截面对象之间被掩膜阻断**：该场景存在两个分离截面来源（`Reference Point` + `RCSD 语义路口`），如果两截面之间被真实负向掩膜阻断、barrier-aware grow 无法连通，按契约第 49 行 `multi_component_result` 拒绝。
  - **B. 复杂路口多个 unit 之间的 inter-unit section bridge 被掩膜阻断**：复杂 / 多 unit case 各 unit 自身按场景规则 barrier-aware grow 出独立 unit surface 后，相邻 unit 临近截面之间执行 inter-unit section bridge；如果 bridge zone 被真实负向掩膜阻断（即不存在不侵入掩膜的连通路径），按契约 `INTERFACE_CONTRACT.md §3.5` 末段 + 第 336 行 `multi_component_result` 拒绝。
- **A / B 两类场景必须显式举证真实硬阻断**：`bridge_negative_mask_crossing_detected = true` 与某个 channel `overlap_area_m2 > tolerance`，并在 `reject_reason_detail` 中写明阻断范围、负向掩膜来源、bridge 尝试与失败原因；缺举证一律按"普通多组件结果"拒绝。
- **A / B 之外的所有正常场景**（单 unit 的 `_with_swsd_only / _with_rcsdroad_fallback_and_swsd / _with_rcsd_junction / _without_rcsd / _with_rcsdroad_fallback / main_evidence_without_rcsd / main_evidence_with_rcsdroad_fallback`，以及 multi-unit 中各 unit 内部）：在 barrier-aware grow 下应天然单连通；多 unit case 经 inter-unit bridge 后应形成唯一联通面。出现 multi-component 都视为：(i) Step6 不是 barrier-aware grow 而走"先生成后切割"反模式；或 (ii) Step5 allowed_growth 计算把单连通区切成多块；或 (iii) inter-unit bridge 未实施。三者均为实现 bug，须按 root cause 修复。
- **`barrier_separated_case_surface_ok = true` 仅在 A / B 两类场景且具备真实硬阻断举证时才可置 true**：其它情况下置 true 视为审计字段污染。

## 2. User Scenarios & Testing

> **本 spec 不再守"23-case PNG fingerprint 不变"或"非本轮 6 case 的所有字段不变"**。用户 2026-05-03 决定：本轮只守 6 个 case 的目视结果与 23-case + 30-case baseline test 的 `accepted / rejected` 列表；其它 case 的 fingerprint / 字段差异留待后续重新审计评估。`857993 / 760598 / 760936 / 607602562 = rejected` 与 `699870 = accepted` 等关键回归项仍守。
>
> **本 spec 实际 user story 划分依赖 Phase 0.5 探针结论**。下面先列出"探针后 Path A：F4 反模式确认"的 user story 集合作为 default；如果探针反驳 F4，按本节末段 "Path B" 重新拆分，并在 `audit.md` 同步更新。

### User Story 0 — 多面切碎根因探针 (Phase 0.5, Priority: P1 前置必做)

依据 §1.4 架构原则，所有 multi-component 必须举证为合法 A / B 类硬阻断；当前 5 个 rejected case 没有一个命中合法路径。本探针在任何 implement 任务之前完成，确认或反驳 §1.3 F4 的"先生成后切割"反模式假设，并锁定 706347 / 765050 等 case 切碎的真实根因。

**Why this priority**: 探针结论决定后续 phase 范围——若反模式确认，706347 / 765050 / 724081 / 785731 / 795682 在 Step6 装配阶段共享一个架构修复；若反模式被反驳，按 case 单独定位。

**Independent Test**: 提交一份"诊断报告"`audit.md` 中的 `phase_0_5_root_cause` 章节，覆盖至少：

- 当前 `polygon_assembly.py / polygon_assembly_*.py / support_domain_builder.py` 是否在 grow 之前把 negative mask 写入 cost map / barrier；
- 706347 / 765050 / 785731 / 795682 / 724081 在当前 run root 中的 step6 中间产物 / raster snapshot 能否复现"先 grow 后裁"的几何特征；
- 765050 inter-unit bridge dispatch 是否被实际调用；如未被调用，是被哪个上游 guard 跳过；
- 反模式确认后的修复方向草稿（共享 Step6 架构修复 vs 各 case 单点）。

**Acceptance Scenarios**:

1. **Given** 当前 run root 与既有代码，**When** 完成探针，**Then** 输出可定位 root cause 的诊断报告；用户审完回 `OK` 或 `不通过 + 原因` 后才进 Phase 1。
2. **Given** 探针确认 §1.3 F4 反模式，**When** 进入 Phase 1，**Then** 706347 / 765050 / 724081 / 785731 / 795682 在 Step6 装配阶段共享 US A1 架构修复（详见下文）。
3. **Given** 探针反驳 §1.3 F4 反模式（即当前确实 barrier-aware grow），**When** 进入 Phase 1，**Then** 切碎根因须按 case 单独定位（更可能源自 Step5 allowed_growth 计算或 inter-unit bridge dispatch 漏调用），按本节末 Path B 重新拆分 user story。

---

### Path A — 探针确认 F4"先生成后切割"反模式（默认假设）

#### User Story A1 — Step6 barrier-aware grow 架构修复 (Priority: P1, MVP)

把 Step6 装配从"先生成后切割"重写为"barrier-aware grow"，并在该子模块内部包含 inter-unit section bridge：

- 负向掩膜（unrelated SWSD nodes/roads、unrelated RCSDNode/RCSDRoad、forbidden domain、terminal cut、不可通行区、导流带 void / interior）在 grow 之前作为硬墙；
- 正向起点为合法的截面边界 / 主证据 Reference Point / 唯一对齐 RCSD 对象 / SWSD 语义路口；
- BFS-like / level-set 生长直至遇墙停止；
- 多 unit 复杂路口在 unit surface 之间执行 inter-unit section bridge，bridge zone 同样 barrier-aware grow。

**覆盖 case**: 706347 单 unit + 765050 inter-unit bridge + 724081 / 785731 / 795682 在 US A2 / A3 / A4 修正 Step4 后的 Step5/6 装配收敛。

**Why this priority**: §1.4 架构原则的工程兑现，决定其它 case 修完 Step4 后能否真正单连通。

**Independent Test**:

- 706347 单 unit 在 SWSD section window 内 `final_case_polygon_component_count = 1`；
- 765050 复杂路口 `unit_surface_merge_performed = true` + `final_case_polygon_component_count = 1`；
- 全 6 case 中 `barrier_separated_case_surface_ok = true` 仅在 §1.4 A / B 类真实硬阻断时出现，附 `bridge_negative_mask_crossing_detected = true` + 至少一个 channel `overlap_area_m2 > tolerance`；
- 30-case baseline test 中 706347 / 724081（注意 724081 走 US A2 修复后的 `no_main_evidence_with_rcsd_junction`） / 765050 = accepted。

**Acceptance Scenarios**:

1. **Given** Step5 已经按场景规则给出 `must_cover / allowed_growth / forbidden / terminal_cut / negative masks` 与 section reference，**When** Step6 运行，**Then** 装配在 grow 之前把 negative mask 写入 barrier；正向 grow 自动停在 barrier 边；不出现"包络面再裁剪"的中间产物。
2. **Given** 复杂路口多 unit case，**When** 各 unit 完成自身 barrier-aware grow，**Then** 相邻 unit 临近截面之间执行 inter-unit section bridge，bridge zone 同样 barrier-aware grow；如果 bridge zone 不被掩膜阻断，则 case 级最终面单连通；如果被阻断，按 §1.4 B 路径 reject 并写明真实硬阻断证据。
3. **Given** Phase 0.5 探针得出共享根因，**When** US A1 修复完成，**Then** 706347 / 765050 / Step4 修复后的 724081 / 785731 / 795682 全部得到单连通面（或在 §1.4 A / B 真实硬阻断时合法 reject 并举证）。

---

#### User Story A2 — 724081 / 785731 case 级 RCSD 召回聚合不再压平 (Priority: P1)

unit 内候选已识别到 `positive_rcsd_present = true`（`724081`）或 `rcsd_alignment_type = rcsdroad_only_alignment`（`785731`），case 顶层却退到 `no_rcsd_alignment / swsd_junction_window_no_rcsd`，导致 `724081` 错失 `rcsd_semantic_junction`、`785731` 错失 `rcsdroad_only_alignment`。本 user story 仅修 Step4 case 顶层聚合；Step5/6 装配收敛由 US A1 完成。

**Why this priority**: 30-case gate 的 `724081 = accepted` 锁当前已破，`785731` 是 6-case 修复目标；二者根因在同一聚合层，可一次完成。

**Independent Test**:

- `724081`：`step4_event_interpretation.json` 顶层 `rcsd_alignment_type = rcsd_semantic_junction`、`surface_scenario_type = no_main_evidence_with_rcsd_junction`、`section_reference_source = rcsd_junction`、`required_rcsd_node` 非空。
- `785731`：顶层 `rcsd_alignment_type = rcsdroad_only_alignment`、`surface_scenario_type = no_main_evidence_with_rcsdroad_fallback_and_swsd`、`section_reference_source = swsd_junction`、`fallback_rcsdroad_ids` 非空。
- `final_state = accepted`（在 US A1 完成后达成）。

**Acceptance Scenarios**:

1. **Given** 724081 输入，**When** Step4 case 级聚合 unit candidate 发现至少一个 unit 候选具有 `positive_rcsd_present = true` 且 RCSD 路口语义可识别，**Then** case 顶层 `rcsd_alignment_type = rcsd_semantic_junction`，`reference_point_present = false`，`section_reference_source = rcsd_junction`，并执行 `surface_generation_mode = rcsd_junction_window`。
2. **Given** 785731 输入，**When** Step4 case 级聚合 unit candidate 发现至少一个 unit 候选具有 `rcsd_alignment_type = rcsdroad_only_alignment`，**Then** case 顶层不退到 `no_rcsd_alignment`，应保留为 `rcsdroad_only_alignment`，并执行 `surface_generation_mode = swsd_with_rcsdroad_fallback`。

---

#### User Story A3 — 795682 RCSD candidate 物化漏召修复 (Priority: P2)

unit 级深层都没有 `rcsdroad_only_alignment` 候选，意味着 Step4 候选物化阶段就没拿到样本。需修复 candidate 召回路径，使局部可对齐 RCSDRoad 进入 candidate pool。`final_state = accepted` 仍依赖 US A1。

**Why this priority**: 跟 US A2 是同方向但不同根因（US A2 是聚合层压平，US A3 是物化层漏召），应单独定位修复。该 case 不在 30-case gate 锁里，但属于 Anchor_2 6-case 修复目标。

**Independent Test**: `cases/795682/step4_event_interpretation.json` 顶层 `rcsd_alignment_type = rcsdroad_only_alignment`、`fallback_rcsdroad_ids` 非空；至少一个 unit 级 candidate 出现 `rcsd_alignment_type = rcsdroad_only_alignment`。

**Acceptance Scenarios**:

1. **Given** 795682 输入数据，**When** Step4 RCSD candidate 物化层运行，**Then** 至少召回一个可对齐 RCSDRoad 候选；该候选最终聚合为 case 顶层 `rcsdroad_only_alignment`。
2. **Given** US A3 修复完成 + US A1 装配修复完成，**When** Step5/Step6 消费 case 级 `rcsdroad_only_alignment`，**Then** 生成单连通面且 `final_state = accepted`。

---

#### User Story A4 — 768675 弱 `road_surface_fork` 不得升主证据 (Priority: P3)

`768675` 当前 `final_state = accepted` 但路径错：`evidence_source = road_surface_fork`、`decision_reason = road_surface_fork_relaxed_primary_rcsd_present`、`rcsd_decision_reason = role_mapping_partial_relaxed_aggregated` 全部命中契约红线（`10-quality-requirements.md` 第 43、53 行）。修复后场景应改为 `no_main_evidence_with_rcsd_junction`，`reference_point_present = false`，`section_reference_source = rcsd_junction`。

**Why this priority**: 业务结果不变（`accepted`），但路径与字段全错；优先级最低，但不可遗漏。修复涉及 Step4 `step4_road_surface_fork_binding_promotions.py` 的 promotion guard，其它 23-case 的 fingerprint 改动不再守，按用户决定留待重新审计。但 `505078921 / node_510222629__pair_02 evidence_source = road_surface_fork`（contract 第 267 行硬锁）必须保持原状。

**Independent Test**:

- `cases/768675/step4_event_interpretation.json` 顶层 `has_main_evidence = false`、`main_evidence_type = none`、`reference_point_present = false`、`reference_point_source = none`、`evidence_source ≠ road_surface_fork`、`rcsd_alignment_type = rcsd_semantic_junction`、`section_reference_source = rcsd_junction`、`surface_generation_mode = rcsd_junction_window`。
- `step7_status.json` 的 `final_state = accepted`、`final_case_polygon_component_count = 1`。
- 23-case + 30-case baseline test 中 `accepted / rejected` 列表保持。
- `505078921` 字段未被本 user story 误伤。

**Acceptance Scenarios**:

1. **Given** Step4 在某 unit 上识别到 `road_surface_fork` 形态切换，但该形态仅由 `relaxed_primary_rcsd_binding` 路径支撑，**When** Step4 输出聚合，**Then** 不得把该形态切换提升为 `main_evidence_type = road_surface_fork`，相关字段保持 `has_main_evidence = false`、`reference_point_present = false`。
2. **Given** Step4 聚合 RCSD 候选，**When** RCSD 路口仅由 `role_mapping_partial_relaxed_aggregated` 弱聚合支撑，**Then** 不得直接发布为 `rcsd_semantic_junction`；只允许在 `required RCSD node` 与代表节点 / 当前 SWSD section 局部对齐时升级，否则保留为 `rcsd_junction_partial_alignment` 或 `rcsdroad_only_alignment`，对应场景由聚合后的对齐结果重新判定。

---

#### User Story A5 — `barrier_separated_case_surface_ok` 审计字段语义修正 (Priority: P2)

把 `barrier_separated_case_surface_ok` 设置条件锁定到 §1.4 A / B 类真实硬阻断；当前 5 个 rejected case 全部错置 `true` 必须改回 `false`。该改动可与 US A1 同 phase 完成，但作为独立 user story 可单独验证。

**Independent Test**: 6 个 case 的 step6 / step7 status 中 `barrier_separated_case_surface_ok` 与 §1.4 一致；`bridge_negative_mask_crossing_detected = true` 必须伴随至少一个 channel `overlap_area_m2 > tolerance`。

---

### Path B — 探针反驳 F4 反模式（占位）

若 Phase 0.5 探针证明 Step6 已 barrier-aware grow，则 706347 / 765050 等切碎来自其它根因（Step5 `allowed_growth_domain` 自身被切成多块、unrelated mask 误纳入正向对象、inter-unit bridge dispatch 漏调用）。本 spec §2 在该情况下重新拆分 user story（占位）：

- US B1（P1, MVP）：765050 inter-unit bridge dispatch 修复（如果探针证明 dispatch 漏调用）
- US B2（P1）：706347 / 785731 / 795682 单 unit allowed_growth 计算修复（如果 Step5 allowed_growth 切成多块）
- US B3 / B4 / B5：同 Path A 的 US A2 / A3 / A4
- US B6：同 US A5

Path B 的 final user stories 由 Phase 0.5 完成时在 `audit.md` 中给出。

---

### Edge Cases（与 Path 无关，永久成立）

- `barrier_separated_case_surface_ok = true` 必须配 `bridge_negative_mask_crossing_detected = true` + 至少一个 channel `overlap_area_m2 > tolerance`；缺举证按"普通多组件结果"拒绝。
- case 顶层 `rcsd_alignment_type` 跨 unit 不一致（complex / multi）：按 `INTERFACE_CONTRACT.md §3.4` 末段做 case-level 对齐冲突判定，不得静默压平。
- US A4 / US B4（768675）修复让弱 promotion 路径被禁后，原 23-case 中其它 case 可能命中相同 promotion 路径；本轮只观察并记录差异，不为它们额外修；其它 case 留待后续重新审计。`505078921 / node_510222629__pair_02` 必须保持原 `evidence_source = road_surface_fork`。

## 3. Requirements

### Functional Requirements

- **FR-001**：T04 必须把 6 个 case 的 `surface_scenario_type` 与 `final_state` 修正为本 spec §1.2 所列的"用户目视应属场景"与对应的 `accepted`。
- **FR-002**：Step4 case 级 RCSD 召回聚合（F2）必须保留 unit 级候选已识别的 `positive_rcsd_present = true` / `rcsd_alignment_type = rcsdroad_only_alignment` 信号；当至少一个 unit 候选支持完整 `rcsd_semantic_junction` 时，case 顶层不得退到 `no_rcsd_alignment`。
- **FR-003**：Step4 RCSD candidate 物化（F3）必须能在 `795682` 类输入下召回局部可对齐 RCSDRoad；具体召回阈值在 plan 阶段定。
- **FR-004**：Step4 弱 `road_surface_fork` 不得升主证据（F1.a），`role_mapping_partial_relaxed_aggregated` 不得单独升级为 `rcsd_semantic_junction`（F1.b）。两条 guard 必须落入 `step4_road_surface_fork_binding_promotions.py` 与对应 RCSD 聚合层。
- **FR-005**：Step6 装配必须遵循 §1.4 架构原则的"barrier-aware grow"：负向掩膜在 grow 之前作为硬墙；正向生长不得跨越负向掩膜；**禁止"先生成不受掩膜约束的包络面、再用负向掩膜做几何 difference 切割"**。Phase 0.5 探针确认 / 反驳后，Phase 1 按 Path A / Path B 实施。
- **FR-006**：Step6 必须实现 inter-unit section bridge（多 unit 部分）：相邻 unit 的两组临近截面边界之间，按同一正向道路面生长 + 20m 横向控制 + 负向掩膜规则生成 bridge surface，并通过 post-cleanup allowed / forbidden / terminal cut / hole / connectivity 复核。bridge zone 同样遵循 barrier-aware grow。
- **FR-007**：multi-component 仅允许出现在 §1.4 A / B 两类合法路径：(A) 场景 `main_evidence_with_rcsd_junction` 两截面对象间真实硬阻断；(B) 复杂多 unit case inter-unit bridge zone 真实硬阻断。两类路径必须举证 `bridge_negative_mask_crossing_detected = true` + 至少一个 channel `overlap_area_m2 > tolerance`，并写入 `reject_reason_detail`。其它任何场景的 multi-component 一律按"普通多组件结果"或对应约束冲突拒绝并按 root cause 修复，不得 accept。
- **FR-008**：`barrier_separated_case_surface_ok = true` 只允许在 FR-007 (A) / (B) 路径且具备真实硬阻断举证时置 true；本 spec 6 个 case 全部不应命中该路径，因此修复后 6 个 case 的该字段全部应为 `false`。
- **FR-009**：`architecture/10-quality-requirements.md` 中 Anchor_2 audit 区段必须新增 `724081 / 785731 / 795682` 的 `surface_scenario_type` 锁，与现有 `765050 / 768675 / 706347` 同节并列；具体措辞见本 spec §A 附录。
- **FR-010**：30-case baseline gate 测试 `test_anchor2_30case_surface_scenario_baseline_gate` 与 23-case baseline gate 测试 `test_anchor2_full_20260426_baseline_gate` 必须更新断言：30-case 内 `706347 / 724081 / 765050 = accepted`（已锁定但实测 rejected，须修复后通过）；23-case 内 `724081 = accepted` 同步。
- **FR-011**：本轮不再守"23-case PNG fingerprint 整体不变"；23-case `final_review.png` raw hash baseline 在本轮可整体作废，留待后续重新审计评估。**baseline test 的业务断言（accepted/rejected counts、case 列表 final_state、`857993 / 760598 / 760936 / 607602562 = rejected`、`699870 = accepted`）仍守**。
- **FR-012**：6 个 case 的 `final_review.png` 必须按 `INTERFACE_CONTRACT.md §3.5` 末表渲染：标注 `surface_scenario_type`、唯一正向 RCSD 对齐对象的粗红 RCSDRoad（`no_rcsd_alignment` 不绘）、构成截面边界的参考对象。
- **FR-013**：本轮不得新增 repo 官方 CLI、不得改 T04 surface 主产物命名、不得改 `INTERFACE_CONTRACT.md` 现有枚举值；只允许新增审计字段或在 `architecture/10-quality-requirements.md` 中新增 case 锁。
- **FR-014**：`505078921 / node_510222629__pair_02` 的 `evidence_source = road_surface_fork`（contract 第 267 行硬锁）必须保持原状；US A4 / US B4 的 promotion guard 不得误伤该 case。
- **FR-015**：Phase 0.5 探针完成前，禁止任何代码改动；Phase 0.5 完成且用户回 `OK` 后，方可进 Phase 1。

### Key Entities

- **`surface_scenario_type`**：T04 case 顶层 7 类场景枚举；本轮关注 `no_main_evidence_with_rcsd_junction / no_main_evidence_with_rcsdroad_fallback_and_swsd / main_evidence_with_rcsd_junction` 三个值。
- **`rcsd_alignment_type`**：Step4 输出唯一对齐结果；本轮关注 `rcsd_semantic_junction / rcsd_junction_partial_alignment / rcsdroad_only_alignment / no_rcsd_alignment` 四个值。
- **`final_state`**：Step7 二值最终态；本轮要求把 5 个 case 从 rejected 改为 accepted，1 个 case (`768675`) 保持 accepted 但路径修正。
- **`unit_surface_merge_performed` / `barrier_separated_case_surface_ok`**：Step6 装配审计字段；前者复杂路口必须置 `true`，后者只允许真实硬阻断时置 `true`。
- **`final_review.png`**：每个 case 的目视证据，最终目视确认依赖该工件。

## 4. Success Criteria

### Measurable Outcomes

- **SC-001**：6 个 case 的 `final_state` 与 `surface_scenario_type` 全部与本 spec §1.2 用户目视一致；可由 `cases/<case>/step7_status.json` 与 `divmerge_virtual_anchor_surface_summary.json` 自动断言。
- **SC-002**：30-case baseline test 全部 26 accepted / 4 rejected 通过；23-case baseline test 全部 20 accepted / 3 rejected 通过。
- **SC-003**：每个 case 的 `final_review.png` 已提供给用户目视确认；6 张 PNG 全部通过用户视觉审计。
- **SC-004**：39-case batch 性能阈值（`threshold_seconds_total = 240.0`、`threshold_avg_completed_case_seconds = 6.5`）保持 `within_threshold`。
- **SC-005**：所有发布 GPKG/GeoJSON 在测试中断言 CRS = `EPSG:3857`、geometry valid、非空、summary/audit/feature count 一致。
- **SC-006**：23-case PNG fingerprint baseline 在本轮被整体放弃，不再作为本 spec 的硬 gate；6 个 case 的 `final_review.png` 由用户目视判定 `OK / 不通过`。
- **SC-007**：本轮所有改动文件在写入前完成 §3 体量自检；任何文件不得首次跨过 100KB 阈值，已超阈值文件不追加。
- **SC-008**：Phase 0.5 探针完成时交付的诊断报告通过用户审阅 (`OK`)；后续 phase 严格按探针结论选择 Path A 或 Path B 实施。

## 5. Non-Goals

- 不新增 repo 官方 CLI 或入口脚本签名变更。
- 不改 `INTERFACE_CONTRACT.md` 中 `surface_scenario_type / rcsd_alignment_type / final_state / reject_reason` 等现有枚举值；只允许在 `architecture/10-quality-requirements.md` 中新增 case 锁。
- 不处理 `785629 / 785631 / 807908 / 823826` 等其它 6-case 修复目标——它们由 `t04-anchor2-swsd-window-repair` 或后续 spec 维护。
- 不改 T04 surface 主产物命名 (`divmerge_virtual_anchor_surface*`)。
- 不为提高 accepted count 静默放宽 Step7 门禁；`760598 / 760936 / 857993 / 607602562 = rejected` 不变。
- 不将本轮发现的 case 数据现象反推固化为新的强规则；任何新规则需在同轮把字段语义写入项目级 / 模块级源事实文档（`AGENTS.md §5`）。

## 6. Source-of-Truth References

- `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md` §2、§3.4、§3.5、§3.7、§4、§6
- `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`
- `modules/t04_divmerge_virtual_polygon/architecture/10-quality-requirements.md` 第 35-36、43、47-49、53、269、274、280-281、298-307 行
- `specs/t04-rcsd-alignment-surface-rules/spec.md`（业务规则上位）
- `specs/t04-anchor2-swsd-window-repair/spec.md`（关于 `785731 / 795682` 的旧场景结论被本 spec supersede）
- `outputs/_work/t04_negative_mask_hard_barrier_final/negative_mask_hard_barrier_final_20260503/`（实现现状证据）

## Appendix A — `architecture/10-quality-requirements.md` 锁项措辞 final draft

下列三段语句作为 FR-009 的 final 措辞，由 implement 阶段一字写入 `architecture/10-quality-requirements.md` 当前已有 `765050 / 768675 / 706347` 锁项的同节（约第 280-282 行附近）。措辞与既有锁项风格一致；行首使用相同的 `- <case_id>：` 前缀。

```markdown
  - `724081`：按人工目视审计归类为"无主证据 + 有 RCSD 语义路口"；进入 `no_main_evidence_with_rcsd_junction` 场景，以 RCSD 语义路口自身前后 `20m` 为终止截面，不得构造 Reference Point；该 case 在 23-case 与 30-case baseline 中均锁为 accepted。唯一正向 RCSD 语义路口对应的 RCSDRoad 必须用粗红色线型表达。
  - `785731 / 795682`：按人工目视审计归类为"无主证据 + 无 RCSD 语义路口、但存在可对齐 RCSDRoad"；进入 `no_main_evidence_with_rcsdroad_fallback_and_swsd` 场景下的 `rcsdroad_only_alignment` 子状态，以 SWSD 自身前后 `20m` 为终止截面；RCSDRoad 仅作局部正向生长 / fallback 支撑，不参与截面边界构建。不得伪造 RCSD 语义路口，不得构造虚拟 Reference Point。
```

如果 Phase 0.5 / Phase 1 的运行结果暴露上述 case 的几何或 RCSD 召回与目视审计不再一致，必须在同一轮先把目视结论与本附录的措辞一并修订，再启动 implement，不得边写代码边漂移文档。

## Appendix B — Phase 0.5 探针报告交付清单

`audit.md` 中 `phase_0_5_root_cause` 章节最低限度必须覆盖：

1. **代码路径核查**：列出 `polygon_assembly.py / polygon_assembly_*.py / support_domain_builder.py` 中 negative mask 进入 cost map 的位置，以及 raster grow 与 negative mask difference 的相对顺序。给出函数名 + 行号引用（不修改代码）。
2. **几何中间产物核查**：从当前 run root `outputs/_work/t04_negative_mask_hard_barrier_final/negative_mask_hard_barrier_final_20260503/` 抽取 706347 / 765050 / 785731 / 795682 / 724081 的 `step5_domains.gpkg` 与 `step6` 中间几何，复核：
   - `allowed_growth_domain` 自身是否单连通；
   - `final_case_polygon` 与 `allowed_growth_domain` 的几何关系是否符合"先 grow 整个 domain 后扣 negative mask"的特征（即 `final_case_polygon ≈ allowed_growth_domain - negative_mask`）；
   - 两组 component 之间的边界是否恰好沿 negative mask 边缘，反推 grow 序列。
3. **inter-unit bridge dispatch 核查**：765050 在当前实现中是否调用了任何 `inter_unit_bridge` / `case_level_bridge` 类函数；如未调用，列出导致跳过的 guard 条件。
4. **结论**：F4 反模式确认 / 反驳；如确认则给出共享 Step6 架构修复的最小重写计划；如反驳则给出每个 case 独立的根因清单。
5. **修订 Path 选择**：在结论基础上把本 spec §2 锁定为 Path A 或 Path B；同时把对应的 plan / tasks 章节更新到 `audit.md` 的 `phase_0_5_path_lockdown` 子章节。
