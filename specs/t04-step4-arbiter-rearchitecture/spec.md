# Spec: T04 Step4 Arbiter Rearchitecture

**Feature Branch**: `codex/t04-step4-arbiter-rearchitecture`
**Created**: 2026-05-04
**Status**: specify
**Module**: `modules/t04_divmerge_virtual_polygon/`

## 1. Context

T04 Step4 当前架构存在系统性"中间态 = 终态"耦合：

- `T04EventUnitResult` 的 `selected_rcsdroad_ids / selected_rcsdnode_ids / required_rcsd_node / positive_rcsd_present / rcsd_alignment_type / rcsd_selection_mode / selected_evidence_summary / fact_reference_point` 等终态字段由 5 个串行 pipeline 阶段直接 `replace()`：
  1. `event_interpretation.build_case_result(...)`
  2. `step4_final_conflict_resolver.resolve_step4_final_conflicts(...)`
  3. `step4_road_surface_fork_binding.apply_road_surface_fork_binding(...)`（含 6 个绑定函数 + `_restore_divstrip_primary_for_wide_surface_fork` + `align_*_swsd_unit_to_rcsdroad`）
  4. `step4_rcsd_anchored_reverse.apply_rcsd_anchored_reverse_lookup(...)`
  5. `surface_scenario.classify_surface_scenario(...)` 在 `outputs.write_case_outputs` 阶段做派生
- 任何阶段都可以无条件覆盖、清空或继承前面阶段的结果；缺少 best-so-far 守门、destructive downgrade guard、`downgrade_from / downgrade_to / reason` 审计字段（仓库内 0 处匹配）。
- 主证据 replacement（`divstrip_primary_over_wide_road_surface_fork / recovery 翻面 / cleanup 清空`）与 RCSD 对齐**未解耦**：主证据切换后 RCSD 字段由 `replacement` 直接拷贝，不重新仲裁；`required_rcsd_node` 保留但 `required_rcsd_node_geometry` 丢失。
- 同型缺陷不仅作用于 RCSD，也作用于 `main_evidence_type / fact_reference_point / section_reference_source / selected_evidence_summary / evidence_source / SWSD 状态翻面 / 已正向 RCSD 沦为 unrelated mask`。

698389（`accepted` baseline 内）当前发布：

- `surface_scenario_type = main_evidence_with_rcsd_junction`
- `main_evidence_type = divstrip`
- `evidence_source = reverse_tip_retry`
- `rcsd_selection_mode = road_surface_fork_forward_rcsd_binding`
- `required_rcsd_node = 5396318492905216`

但目视审计判定 RCSD 路口结构与 SWSD 路口结构差异明显，附近存在更一致的 RCSDRoad / RCSD 语义结构未被发布。

## 2. Goal

把 Step4 重构为 4 层架构：

1. **候选生成层（Generators）**：所有候选生成函数只向 ledger 追加候选，不写 `T04EventUnitResult.selected_*`。
2. **候选评分层（Scoring）**：基于 SWSD/RCSD 趋势 + 角色完整性 + reference point 距离 + 跨语义对象惩罚 + 更近候选惩罚计算多维一致性分。
3. **唯一仲裁层（Arbiter）**：`arbitrate_step4_unit(unit, ledger, *, case_context) -> T04ArbitrationDecision` 是 Step4 内**唯一**写最终字段的函数，集成 destructive_downgrade_guard、best-so-far、main-evidence re-arbitration、scenario / section_reference 派生。
4. **发布消费层（Publish）**：`surface_scenario.classify_surface_scenario` 与 `outputs.write_case_outputs` 直接消费仲裁结果，不再"派生"。

`T04EventUnitResult` 字段语义保持，写入入口收窄到仲裁层。

## 3. Non-Goal

- 不进入 Step5-7 算法重写；Step5 `support_domain_builder` 仅按仲裁结果消费 `related / unrelated rcsd`。
- 不动 `INTERFACE_CONTRACT.md §3` 状态机值域；只改"由哪一层发布"。
- 不动 `INTERFACE_CONTRACT.md §5` 稳定执行面签名。
- 不新增 repo 官方 CLI；不向 `entrypoint-registry.md` 注册新入口。
- 不修改 T01 / T02 / T03 模块。
- 不重新定义 30-case / 39-case baseline 划分；`857993 / 760598 / 760936 / 607602562` 维持 `rejected`。
- 不扩大 `divstrip_primary_over_wide_road_surface_fork` 的触发条件。

## 4. User Scenarios

### Story 1 - 698389 类回归不再发生（P1）
主证据从 `road_surface_fork` 切到 `divstrip` 时，RCSD 对齐对象基于新 `fact_reference_point` 重新仲裁，不直接继承被 suppressed 的 fork 绑定。
**Independent Test**：`tests/modules/t04_divmerge_virtual_polygon/test_step4_arbiter_rearchitecture.py` 中 `test_main_evidence_replacement_triggers_rearbitration_698389`。

### Story 2 - 候选生命周期可追溯（P1）
`step4_audit.json` 包含 `step4_candidate_ledger`（list[T04Step4Candidate]）与 `arbitration_decision_trace`。
**Independent Test**：30-case dry-run 全部 case 含上述顶层键。

### Story 3 - destructive downgrade guard 拦截非冲突降级（P1）
后期阶段试图把已正向 RCSD（`positive_rcsd_present=True ∧ required_rcsd_node!=None ∧ rcsd_alignment_type∈{semantic_junction, junction_partial}`）降级时，guard 仅在白名单理由下放行（白名单：`explicit_role_conflict / explicit_trend_conflict / explicit_reference_geometry_conflict / case_level_arbitrated_replacement`）。
**Independent Test**：`test_destructive_downgrade_guard_whitelist`。

### Story 4 - baseline 守门（P0）
30-case `accepted=26 / rejected=4` 与 39-case 业务 gate 全量回归通过；任何 final_state 翻面 PR 内逐一评审。
**Independent Test**：`test_step7_final_publish.py` 全套通过；30-case + 39-case dry-run 与现状一致（除 698389 类预期变化）。

## 5. Functional Requirements

- **FR-001**：新增 `T04Step4Candidate / T04Step4CandidateLedger / T04ArbitrationDecision / T04ArbiterCaseContext` 数据结构；`T04Step4Candidate` 至少含字段 `candidate_id / source_stage / evidence_type / main_evidence_type / reference_point / rcsd_alignment_type / rcsdroad_ids / rcsdnode_ids / required_rcsd_node / support_level / consistency_level / swsd_trend_score / rcsd_role_score / reference_distance_score / cross_semantic_object_penalty / closer_alternative_candidate_penalty / aggregate_consistency_score / conflict_flags / reject_reason / replacement_reason / source_audit_blob`。
- **FR-002**：所有候选生成器（`forward / promotions_* / recovery / cleanup / divstrip / swsd_rcsdroad / anchored_reverse / final_conflict_resolver` 与 `_event_interpretation_core` 的 `no_bound_target_rcsd` 分支）只向 ledger 追加候选，不写 `T04EventUnitResult.selected_*` 与 `positive_rcsd_*` 字段族（仅允许写候选自身的 audit blob）。
- **FR-003**：仲裁器 `arbitrate_step4_unit` 是 Step4 内**唯一**写以下字段的函数：`selected_rcsdroad_ids / selected_rcsdnode_ids / required_rcsd_node / required_rcsd_node_source / positive_rcsd_present / positive_rcsd_present_reason / positive_rcsd_support_level / positive_rcsd_consistency_level / rcsd_alignment_type / rcsd_match_type / rcsd_selection_mode / selected_evidence_summary / selected_candidate_summary / fact_reference_point / review_materialized_point / surface_scenario_type / section_reference_source`。
- **FR-004**：仲裁器集成 destructive_downgrade_guard：pre 状态 `positive_rcsd_present=True ∧ required_rcsd_node!=None ∧ rcsd_alignment_type∈{semantic_junction, junction_partial}`，post 状态降级时仅在白名单理由放行；非白名单降级保留 pre 状态并打 `STEP4_REVIEW: rcsd_destructive_downgrade_blocked`。
- **FR-005**：仲裁器集成 best-so-far 守门：多个 positive 候选时按 `aggregate_consistency_score` 选 top-1；同分按 `support_level (A>B) > consistency_level (A>B>C) > source_stage 优先级 (forward bind > promotion > recovery > divstrip > swsd_rcsdroad > anchored_reverse)` 决胜。
- **FR-006**：候选评分层实现并持久化：`swsd_branch_trend_vs_rcsd_road_trend_score / entering_exiting_arms_consistency_score / reference_point_to_rcsd_junction_distance_score / cross_semantic_object_penalty / closer_alternative_candidate_penalty`。
- **FR-007**：主证据 replacement（`divstrip_primary_over_wide_road_surface_fork / recovery 翻面 / cleanup 清空主证据`）后必须触发 RCSD re-arbitration（仲裁器在新 `fact_reference_point` 与 `selected_evidence_region_geometry` 上重跑评分），不继承 `replacement` 的 RCSD 字段。
- **FR-008**：仲裁结果输出完整 `decision_trace`：每个 ledger 候选的得分、reject_reason、replacement_reason、conflict_evidence；最终 winner 的 selection 路径与 downgrade audit。
- **FR-009**：`surface_scenario.classify_surface_scenario` 与 `outputs.write_case_outputs` 直接消费仲裁结果中的 `surface_scenario_type / section_reference_source / rcsd_match_type / reference_point_source / main_evidence_type / has_main_evidence`，不再独立派生。
- **FR-010**：`step4_audit.json` 新增 `step4_candidate_ledger` 与 `arbitration_decision_trace` 顶层键；`step4_review_index.csv` 字段族追加 `rcsd_decision_history_count / rcsd_replacement_due_to_main_evidence / aggregate_rcsd_consistency_score`。
- **FR-011**：`INTERFACE_CONTRACT.md §3.4 / §3.5 / §4.4` 修订：在不改值域的前提下，注明"`surface_scenario_type / rcsd_alignment_type / rcsd_match_type / section_reference_source` 由 Step4 仲裁层发布，Step5/6/7 只消费"，并登记新增审计字段。
- **FR-012**：`architecture/04-solution-strategy.md` 更新 Step4 内部 4 层架构图与候选 ledger 数据流；`architecture/10-quality-requirements.md` 登记 destructive_downgrade_guard 与候选生命周期审计为质量门槛。
- **FR-013**：`docs/repository-metadata/code-size-audit.md` 在拆分前置任务（T-01）同轮更新；任何文件超 100 KB 必须先拆分。
- **FR-014**：模块内 Python 稳定执行面 `run_t04_step14_batch / run_t04_step14_case / run_t04_internal_full_input` 签名保持不变。

## 6. Success Criteria

- **SC-001**：30-case full baseline `accepted=26 / rejected=4` 守住；`857993 / 760598 / 760936 / 607602562` 维持 `rejected`，`is_anchor=fail4`。
- **SC-002**：39-case baseline 全量回归通过；任何 final_state 翻面在 PR 内逐一评审并视觉确认。
- **SC-003**：698389 的 `selected_rcsdroad_ids / required_rcsd_node` 在仲裁器主证据 replacement re-arbitration 落地后变化（具体值在 dry-run 后确认）；最终 `final_state` 仍为 `accepted`。
- **SC-004**：`step4_audit.json` 100% case 含 `step4_candidate_ledger` 与 `arbitration_decision_trace`；`step4_review_index.csv` 新字段族 100% 填充。
- **SC-005**：仓库内全文检索 `T04EventUnitResult.selected_rcsdroad_ids / selected_rcsdnode_ids / required_rcsd_node / positive_rcsd_present / rcsd_alignment_type` 的写入位置只剩仲裁器一处，其余位置全部为读。
- **SC-006**：`tests/modules/t04_divmerge_virtual_polygon/` 新增至少 7 个测试用例（见 `plan.md §3.4`），全部通过。
- **SC-007**：所有源码 / 脚本文件 < 100 KB；`code-size-audit.md` 与现状一致。
- **SC-008**：`INTERFACE_CONTRACT.md` 与 `architecture/04 / 10` 修订后通过 `docs/doc-governance/README.md` 阅读链路自检。

## 7. Edge Cases

- ledger 内**没有**任何 positive 候选：仲裁器输出 `rcsd_alignment_type=no_rcsd_alignment`，但 `decision_trace` 保留所有被检查过的候选与 reject_reason。
- ledger 内**多个 top-1 同分**：按 source_stage 优先级决胜（FR-005），同时打 `STEP4_REVIEW: arbiter_tied_top_candidates`。
- 主证据 replacement re-arbitration 与 forward bind 选择**完全一致**：不打 STEP4_REVIEW，但 `decision_trace` 仍记录 re-arbitration 发生过。
- forward bind 命中 `_strong_aggregated_unit / role_mapping_exact_aggregated` 但 `aggregate_consistency_score < 0`（趋势冲突）：仲裁器选另一候选；不允许把 698389 现状翻成 `rejected`，只允许改 `selected_rcsdroad_ids / required_rcsd_node`。
- `step4_final_conflict_resolver` 跨 unit `_apply_required_node_claim` 同 case 抢 required_node：在仲裁器内统一处理，pre/post 节点均进 `decision_trace`。
- ambiguous_rcsd_alignment 保留原阻断语义（不静默降级为 `no_rcsd_alignment`），与 `INTERFACE_CONTRACT.md §3.4` 一致。

## 8. Out-of-Scope

- 不重写 `_event_interpretation_core._build_candidate_pool` 与 `variant_ranking.py`。
- 不改 Step5/6/7 几何算法。
- 不改 T01/T02/T03 模块。
- 不修复 23-case 历史 frozen baseline。
- 不增加新 evidence_source / rcsd_alignment_type / surface_scenario_type 值。
