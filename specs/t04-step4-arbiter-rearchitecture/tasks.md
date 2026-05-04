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

**Status**：pending

---

## T-04 候选生成器降级 · P0

**目标**：所有候选生成器函数只产出 `list[T04Step4Candidate]`，不再写 `T04EventUnitResult.selected_*` 与 `positive_rcsd_*`。

**改造文件清单**：见 `plan.md §2.1`。
- 所有 `_bind_strong_rcsd_to_surface / _promote_* / _downgrade_* / _recover_* / _retain_* / _clear_* / _restore_divstrip_primary_for_wide_surface_fork / align_*_swsd_unit_to_rcsdroad / apply_rcsd_anchored_reverse_lookup / resolve_step4_final_conflicts / _apply_required_node_claim` 改造为追加 ledger 候选 + 保留 audit blob。
- `apply_road_surface_fork_binding` facade、`apply_rcsd_anchored_reverse_lookup`、`resolve_step4_final_conflicts` 签名锁定不变。
- `_event_interpretation_core._evaluate_unit_candidate` 的 `no_bound_target_rcsd` 分支：改为追加候选 + 由仲裁器决定。
- `event_interpretation.build_case_result`：构造 ledger + 调仲裁器（T-05 提供）。

**静态扫描断言**：仓库内 `replace(.*selected_rcsdroad_ids|selected_rcsdnode_ids|required_rcsd_node|positive_rcsd_present|rcsd_alignment_type|rcsd_selection_mode|selected_evidence_summary)` 写入点降到只剩仲裁器一处（旧 `_replace_unit` 工具函数保留，调用路径仅来自仲裁器）。

**验证**：
- `test_ledger_append_only_no_writeback` 通过。
- `test_arbiter_writes_final_fields_once` 通过（静态扫描）。
- 30-case + 39-case shadow mode dry-run 与 baseline 一致。

**Status**：pending

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
| T-03 ledger / scoring / arbiter 数据结构 | P0 | pending |
| T-04 候选生成器降级 | P0 | pending |
| T-05 仲裁器实现 | P0 | pending |
| T-06 surface_scenario / outputs 改造 | P1 | pending |
| T-07 audit / review_index 字段扩充 | P1 | pending |
| T-08 测试落地 | P0 | pending |
| T-09 文档定稿 | P0 | pending |
| T-10 dry-run 与视觉评审 | P0 | pending |
