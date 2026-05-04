# Tasks: T04 Step4 Arbiter Rearchitecture

**Branch**: `codex/t04-step4-arbiter-rearchitecture`
**Status**: tasks
**执行守则**：每个 task 完成后 → 跑对应测试子集 → 在本文件状态更新 → commit message 区分"已修改 / 已验证 / 待确认"。

## T-01 文件拆分前置 · P0 · 阻塞所有后续

**目标**：把 T04 模块内 ≥ 50 KB 文件做一轮安全拆分，并同轮更新 `docs/repository-metadata/code-size-audit.md`。

**输入文件清单**（按当前体量降序）：
- `polygon_assembly.py`（~83 KB）→ 拆出 `polygon_assembly_raster.py` + `polygon_assembly_path.py`，每个 < 35 KB。
- `_runtime_types_io.py`（~76 KB）→ 拆出 `_runtime_types.py` + `_runtime_io.py`，每个 < 40 KB。
- `_runtime_step4_kernel_base.py`（~65 KB）→ 拆出 `_runtime_step4_kernel_geometry.py`，主文件 < 40 KB。
- `_runtime_step4_geometry_core.py`（~64 KB）→ 拆出 `_runtime_step4_geometry_constants.py`，主文件 < 40 KB。
- `step4_rcsd_anchored_reverse.py`（~60 KB）→ 拆出 `step4_rcsd_anchored_reverse_policy.py` + `step4_rcsd_anchored_reverse_graph.py`，每个 < 30 KB。

**约束**：
- 不改任何业务语义；只移代码 + 重整 import。
- 每个被拆分文件保留原 public API import surface（旧 import 路径仍可用）。
- 同轮更新 `code-size-audit.md`。
- `tests/` 全部测试不动且通过。

**验证**：
- `pytest tests/modules/t04_divmerge_virtual_polygon/ -x`
- 所有源码文件 < 100 KB
- `code-size-audit.md` 与实际体量一致

**完成后停机汇报**："T-01 完成，拆分边界 / 体量数字 / `code-size-audit.md` diff" → 等用户确认。

**Status**：completed

---

## T-02 契约修订草案 · P0

**目标**：在不改值域的前提下，修订 T04 INTERFACE_CONTRACT 与 architecture，注明"Step4 仲裁层是 surface_scenario_type / rcsd_alignment_type / rcsd_match_type / section_reference_source 的唯一发布层"。

**修订位置**：
- `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`：
  - §3.4 末尾追加 1 段说明。
  - §3.5 末尾追加 1 段说明。
  - §4.4 字段族追加：`step4_candidate_ledger / arbitration_decision_trace / rcsd_decision_history_count / rcsd_replacement_due_to_main_evidence / aggregate_rcsd_consistency_score`。
- `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`：Step4 章节追加 4 层架构图与数据流。
- `modules/t04_divmerge_virtual_polygon/architecture/10-quality-requirements.md`：质量门槛追加 destructive_downgrade_guard、候选生命周期审计、main-evidence re-arbitration。

**约束**：不改 §3.1-3.3 / §3.6-3.8 任何值域；不动 §5；不动 §6 baseline 数字。

**验证**：与 `docs/doc-governance/README.md` 阅读链路自检通过；仅文档变更不跑测试。

**完成后停机汇报**："T-02 草案 diff" → 等用户确认。

**Status**：completed

---

## T-03 ledger / scoring / arbiter 数据结构 · P0

**目标**：新增 `T04Step4Candidate / T04Step4CandidateLedger / T04ArbitrationDecision / T04ArbiterCaseContext`。

**落地位置**（评估体量后选）：优先 `case_models.py` 末尾追加；备选新增 `_step4_arbiter_models.py`（< 25 KB）。

**字段**：见 `spec.md FR-001` 与 `plan.md §2`。
- `T04Step4CandidateLedger`：`unit_id / case_id / candidates: list[T04Step4Candidate]` + `append(...)` 单调追加方法（list 不允许直接 mutate）。
- `T04ArbitrationDecision`：所有最终字段 + `decision_trace / downgrade_from / downgrade_to / downgrade_reason / suppressed_rcsd_snapshot / rcsd_replacement_due_to_main_evidence / aggregate_rcsd_consistency_score`，提供 `as_field_kwargs() -> dict`。
- `T04ArbiterCaseContext`：传给仲裁器的 case 级上下文。

**验证**：`pytest tests/modules/t04_divmerge_virtual_polygon/ -x` 通过（不应有任何回归）；静态扫描 ledger.append 是唯一写入路径。

**Status**：completed

---

## T-04a 候选生成器 dual-write（ledger 影子捕获）· P0

**目标**：候选生成器在保留现有 `replace(unit, selected_*=...) / replace(unit, positive_rcsd_*=...) / replace(unit, rcsd_alignment_type=...) / replace(unit, selected_evidence_summary=...)` 写回的**同时**，并行追加 `T04Step4CandidateLedger`。ledger 仅写入 audit；不影响 `T04EventUnitResult` 字段发布。

**改造文件**（仅追加 `ledger.append(...)`，不删除任何现有写回）：
- `step4_road_surface_fork_binding_forward.py` `_bind_strong_rcsd_to_surface`
- `step4_road_surface_fork_binding_promotions.py` `_promote_selected_surface_rcsd_junction_window / _promote_selected_surface_partial_rcsd / _downgrade_far_surface_rcsd_to_swsd_window / _promote_relaxed_primary_rcsd_binding`
- `step4_road_surface_fork_binding_recovery.py` `_recover_surface_from_candidate`
- `step4_road_surface_fork_binding_cleanup.py` `_retain_structure_only_surface_candidate / _clear_unbound_surface_candidate`
- `step4_road_surface_fork_binding_divstrip.py` `_restore_divstrip_primary_for_wide_surface_fork`
- `step4_road_surface_fork_binding_swsd_rcsdroad.py` `align_complex_swsd_units_to_shared_rcsdroad / align_single_swsd_unit_to_rcsdroad`
- `step4_rcsd_anchored_reverse.py` `apply_rcsd_anchored_reverse_lookup`
- `step4_final_conflict_resolver.py` `resolve_step4_final_conflicts / _apply_required_node_claim`
- `_event_interpretation_core.py` `_evaluate_unit_candidate` 的 `no_bound_target_rcsd` 分支
- `outputs.py`：把 ledger 写入 `step4_audit.json` 顶层 `step4_candidate_ledger` 键。

**强制产物：dual_write_manifest**
T-04a 必须在 `step4_audit.json` 顶层写出 `dual_write_manifest`，作为 T-04b 的 checklist：

```json
{
  "dual_write_manifest": [
    {
      "file": "step4_road_surface_fork_binding_forward.py",
      "line": 164,
      "function": "_bind_strong_rcsd_to_surface",
      "source_stage": "forward_bind",
      "fields_written": ["selected_rcsdroad_ids", "selected_rcsdnode_ids", "required_rcsd_node", "positive_rcsd_present", "rcsd_alignment_type", "rcsd_selection_mode"]
    },
    ...
  ]
}
```

每条记录对应"新增 ledger.append + 保留旧 replace"的一对位置。

**约束**：
- 不引入 `_step4_arbiter.py / _step4_candidate_scoring.py`。
- 不调用任何仲裁器。
- ledger.append 必须捕获完整 `T04Step4Candidate` 字段（spec FR-001 全集），含 `source_stage / candidate_id / source_audit_blob`。
- 不修改 `T04EventUnitResult.selected_*` 任何写回路径的语义。

**验证**：
- `pytest tests/modules/t04_divmerge_virtual_polygon/ -x` 全量通过。
- 30-case + 39-case 全量回归与 baseline **完全一致**（dual-write 不改业务字段）。
- `step4_audit.json` 100% case 含 `step4_candidate_ledger` 与 `dual_write_manifest` 顶层键。
- 新增轻量测试 `test_ledger_dual_write_parity`：断言每次生成器写 unit 时 ledger 同步追加了对应候选，字段一致性校验。

**完成后停机汇报**："T-04a 完成，dual_write_manifest 含 N 条记录，30-case + 39-case baseline 与 main 一致，等待 T-05 启动确认。"

**Status**：completed

---

## T-05 仲裁器实现 · P0

**目标**：实现 `arbitrate_step4_unit` 与 `_step4_candidate_scoring`。

**落地位置**：
- `_step4_candidate_scoring.py`（≤ 30 KB）
- `_step4_arbiter.py`（≤ 35 KB）

**函数签名**：见 `plan.md §2.3`。

**内部步骤**：destructive_downgrade_guard → best-so-far 排序 → main-evidence re-arbitration 钩子 → scenario / section_reference 派生 → decision_trace 落档 → 返回 `T04ArbitrationDecision`。

**约束**：
- 仲裁器不调用候选生成器（避免循环依赖）。
- 默认开启 `STEP4_ARBITER_SHADOW_MODE`（环境变量或 `T04ArbiterCaseContext` 字段，二选一，T-05 实现时定）：true 时只写 audit、不覆盖 unit 字段。

**验证**：
- 测试 #3 / #4 / #5 / #6 通过。
- shadow mode 下 30-case + 39-case dry-run 与 baseline 一致。
- 关闭 shadow mode 后 30-case + 39-case 全量回归通过。

**完成后停机汇报**：shadow mode dry-run 报告 + 决策差异列表 → 等用户确认后再切 normal mode。

**与 T-04a / T-04b 的关系**：
- T-05 进入时，T-04a 的 dual-write 已就位：每个生成器同时写 unit 字段（旧路径）与 ledger（新路径）。
- T-05 默认开启 shadow mode：仲裁器读 ledger → 计算决策 → 仅写 `step4_audit.json` 的 `arbitration_decision_trace` 与 `arbitration_decision_shadow`。**不写** `T04EventUnitResult`，**不删除** T-04a 保留的旧写回。
- shadow 期间 30-case + 39-case 全量回归仍与 baseline 完全一致。
- T-05 stop 点的 dry-run 报告必须列出每个 case 的 `arbitration_decision_shadow` 与 unit 实际字段差异，按"预期变化（698389 类）/ rejected baseline 不变 / 其他差异"分类，等用户逐项确认。

**Status**：pending

---

## T-04b 切换 normal mode + 移除旧写回 · P0

**前置**：T-05 stop 点用户已确认 shadow diff 符合预期。

**目标**：把仲裁器从 shadow mode 切到 normal mode，移除候选生成器内的旧 `replace(unit, ...)` 写回路径，使仲裁器成为 Step4 唯一写最终字段的位置。

**改造**：
- `event_interpretation.build_case_result` 末尾：仲裁器决策从"仅写 audit"改为 `replace(unit, **decision.as_field_kwargs())` 写入 unit。
- 候选生成器（T-04a 改过的同一组文件）：按 T-04a 产出的 `dual_write_manifest` 逐项删除旧 `replace(unit, selected_*=...) / replace(unit, positive_rcsd_*=...) / replace(unit, rcsd_alignment_type=...) / replace(unit, selected_evidence_summary=...)` 等写回；**保留** ledger.append。
- `_replace_unit` 工具函数保留，但调用方仅来自仲裁器。
- shadow mode 开关默认值切换为 false（仅保留环境变量逃生口）。

**双向静态扫描断言**（必须通过才算完成）：
- 反向断言（旧路径已死）：仓库内对 `selected_rcsdroad_ids / selected_rcsdnode_ids / required_rcsd_node / required_rcsd_node_source / positive_rcsd_present / positive_rcsd_present_reason / positive_rcsd_support_level / positive_rcsd_consistency_level / rcsd_alignment_type / rcsd_match_type / rcsd_selection_mode / selected_evidence_summary / selected_candidate_summary / fact_reference_point / review_materialized_point / surface_scenario_type / section_reference_source` 字段族的 `replace(...)` 写入位置只剩仲裁器一处。
- 正向断言（新路径完整）：T-04a `dual_write_manifest` 中每条记录对应的 `ledger.append(...)` 必须仍然存在；任意一条丢失即视为 T-04b 未完成。

**验证**：
- 双向静态扫描断言全部通过。
- 新增测试 `test_ledger_append_only_no_writeback`、`test_arbiter_writes_final_fields_once` 通过。
- 30-case + 39-case 全量回归通过；rejected baseline (`857993 / 760598 / 760936 / 607602562`) 维持 `rejected` 与 `is_anchor=fail4`。
- 698389 的 `selected_rcsdroad_ids / required_rcsd_node` 变化在视觉评审通过；`final_state` 仍为 `accepted`。

**完成后停机汇报**："T-04b 完成，双向静态扫描通过，30-case + 39-case 视觉差异已生成，等待用户视觉评审后进入 T-06。"

**Status**：pending

---

## T-06 surface_scenario / outputs 改造 · P1

**目标**：移除 `surface_scenario.classify_surface_scenario` 派生职责，改为读 unit 上由仲裁器写入的字段。

**改造**：
- `surface_scenario.classify_surface_scenario` → thin reader。
- `_main_evidence_type / classify_surface_scenario_from_alignment` 保留为内部 helper，仅被仲裁器调用。
- `outputs.write_case_outputs / final_publish.py` 不变。

**验证**：
- `test_scenario_reads_from_arbiter_not_derives` 通过。
- 30-case + 39-case scenario 与 baseline 一致。

**Status**：pending

---

## T-07 audit / review_index / review_summary 字段扩充 · P1

**目标**：在 `step4_audit.json / step4_review_index.csv / step4_review_summary.json` 落地新字段。

**改造文件**：
- `outputs.py`：写 `step4_candidate_ledger / arbitration_decision_trace`；扩展 csv 字段族。
- `review_audit.py`：扩展 review row schema。
- `review_render.py`：可选——在 final_review PNG 标注 `aggregate_rcsd_consistency_score`（评估后定）。

**验证**：30-case dry-run 全部 case 含新顶层键 + csv 新字段 100% 填充。

**Status**：pending

---

## T-08 测试落地 · P0

**目标**：实现 `spec.md §4` 列出的 7 个测试 + 扩展现有 baseline 测试。

**新增**：`tests/modules/t04_divmerge_virtual_polygon/test_step4_arbiter_rearchitecture.py`（≤ 80 KB）。

**扩展**：`test_step7_final_publish.py`、`test_internal_full_input_smoke.py` 的 baseline 期望（仅 698389 类 case 更新；rejected baseline 不动）。

**验证**：`pytest tests/modules/t04_divmerge_virtual_polygon/ -x` 全量通过。

**Status**：pending

---

## T-09 文档定稿 · P0

**目标**：T-02 草案最终落地 + 同步 `code-size-audit.md`。

**改造**：
- `INTERFACE_CONTRACT.md / architecture/04 / 10`：草案 → 正式。
- `code-size-audit.md`：与 T-08 后实际体量同步。
- `docs/doc-governance/current-doc-inventory.md`（如适用）：登记新增 architecture 章节。

**验证**：阅读链路自检通过；`code-size-audit.md` 与实际一致。

**Status**：pending

---

## T-10 dry-run 与视觉评审 · P0

**目标**：30-case + 39-case full baseline dry-run + 逐 case 视觉评审 + PR 入口。

**步骤**：
1. shadow mode dry-run：跑 30-case + 39-case，比对 `arbitration_decision_trace` 与 unit 实际字段，差异点记录。
2. 关闭 shadow mode：跑 30-case + 39-case，比对 `final_state / nodes_anchor_update_audit.json / final_review.png`。
3. 任何 final_state 翻面 PR 内人工评审；rejected baseline 不允许翻 accepted。
4. 698389 类 case 的 `selected_rcsdroad_ids / required_rcsd_node` 变化在 PR 内逐图视觉确认。
5. 提交 PR：标题 `T04 Step4 Arbiter Rearchitecture`，body 含 spec / plan / tasks 链接 + dry-run 报告 + visual diff 截图。

**验证**：SC-001 ~ SC-008 全部满足。

**完成后停机汇报**：PR URL + 视觉差异截图汇总 → 等用户最终确认后 merge。

**Status**：pending

---

## 状态汇总

| Task | 优先级 | 状态 |
|---|---|---|
| T-01 文件拆分前置 | P0 | completed |
| T-02 契约修订草案 | P0 | completed |
| T-03 ledger / scoring / arbiter 数据结构 | P0 | completed |
| T-04a 候选生成器 dual-write | P0 | completed |
| T-05 仲裁器实现（shadow mode） | P0 | pending |
| T-04b 切换 normal mode + 移除旧写回 | P0 | pending |
| T-06 surface_scenario / outputs 改造 | P1 | pending |
| T-07 audit / review_index 字段扩充 | P1 | pending |
| T-08 测试整合 + baseline 期望表更新 | P0 | pending |
| T-09 文档定稿 | P0 | pending |
| T-10 dry-run 与视觉评审 + PR | P0 | pending |
