# Plan: T04 Step4 Arbiter Rearchitecture

**Branch**: `codex/t04-step4-arbiter-rearchitecture`
**Status**: plan

## 1. 总体路径

```
T-01 文件拆分前置（守 §3 体量约束）
   ↓
T-02 契约修订草案（INTERFACE_CONTRACT / architecture / code-size-audit）
   ↓
T-03 ledger 数据结构 + 评分层 schema
   ↓
T-04 候选生成器降级为只追加 ledger（不写 selected_*）
   ↓
T-05 仲裁器实现（含 destructive_downgrade_guard + best-so-far + main-evidence re-arbitration）
   ↓
T-06 surface_scenario / outputs 改为消费仲裁结果
   ↓
T-07 audit / review_index / review_summary 字段扩充
   ↓
T-08 测试用例落地（新增 7 个 + 30-case + 39-case 回归）
   ↓
T-09 文档定稿（契约修订正式落地、code-size-audit 同步）
   ↓
T-10 dry-run 与视觉评审，PR 入口
```

## 2. 4 层架构

### 2.1 候选生成层（只追加，不发布）

输入降级（不再写 `T04EventUnitResult.selected_*`）：

- `step4_road_surface_fork_binding_forward.py` `_bind_strong_rcsd_to_surface`
- `step4_road_surface_fork_binding_promotions.py` `_promote_selected_surface_rcsd_junction_window / _promote_selected_surface_partial_rcsd / _downgrade_far_surface_rcsd_to_swsd_window / _promote_relaxed_primary_rcsd_binding`
- `step4_road_surface_fork_binding_recovery.py` `_recover_surface_from_candidate`
- `step4_road_surface_fork_binding_cleanup.py` `_retain_structure_only_surface_candidate / _clear_unbound_surface_candidate`
- `step4_road_surface_fork_binding_divstrip.py` `_restore_divstrip_primary_for_wide_surface_fork`
- `step4_road_surface_fork_binding_swsd_rcsdroad.py` `align_complex_swsd_units_to_shared_rcsdroad / align_single_swsd_unit_to_rcsdroad`
- `step4_rcsd_anchored_reverse.py` `apply_rcsd_anchored_reverse_lookup`
- `step4_final_conflict_resolver.py` `resolve_step4_final_conflicts`
- `_event_interpretation_core.py` `_evaluate_unit_candidate` 的 `no_bound_target_rcsd` 分支

每个生成器返回 `list[T04Step4Candidate]`；`apply_road_surface_fork_binding` facade（保留签名）汇集成 ledger。

### 2.2 候选评分层

新增 `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_step4_candidate_scoring.py`（≤ 30 KB）。

输出（写回 candidate）：

- `swsd_branch_trend_vs_rcsd_road_trend_score`：[-1.0, 1.0]
- `entering_exiting_arms_consistency_score`：[-1.0, 1.0]
- `reference_point_to_rcsd_junction_distance_score`：[0.0, 1.0]
- `cross_semantic_object_penalty`：[0.0, 1.0]
- `closer_alternative_candidate_penalty`：[0.0, 1.0]
- `aggregate_consistency_score`：加权和（默认权重 `0.30 / 0.25 / 0.25 / -0.10 / -0.10`，常量在文件顶部）

### 2.3 唯一仲裁层

新增 `_step4_arbiter.py`（≤ 35 KB）：

```python
def arbitrate_step4_unit(
    unit: T04EventUnitResult,
    ledger: T04Step4CandidateLedger,
    *,
    case_context: T04ArbiterCaseContext,
) -> T04ArbitrationDecision: ...
```

内部步骤：

1. destructive_downgrade_guard 预检（白名单 4 项见 spec FR-004）。
2. best-so-far 排序（FR-005）。
3. main-evidence re-arbitration 钩子。
4. scenario / section_reference 派生（仲裁器内一次性产出，移除 `surface_scenario.classify_surface_scenario` 派生职责）。
5. decision_trace 落档。
6. 返回 `T04ArbitrationDecision`，由 caller 用单次 `replace(unit, **decision.as_field_kwargs())` 写入。

仲裁器**不**调用候选生成器，避免循环依赖。

### 2.4 发布消费层

- `surface_scenario.classify_surface_scenario` 改为 thin reader：直接读 unit 上由仲裁器写入的字段。
- `_main_evidence_type / classify_surface_scenario_from_alignment` 保留为内部 helper，仅被仲裁器调用。
- `outputs.write_case_outputs / final_publish.py` 不变。

## 3. 五视角职责

### 3.1 产品视角
- 业务问题：698389 类 case 不一致；候选生命周期不可观测；主证据 replacement 与 RCSD 脱钩。
- 业务边界：30-case + 39-case baseline 划分不变；rejected case 维持 rejected。
- 业务交付：`step4_audit.json` 新增 ledger / decision trace；目视审计 PNG 不变。

### 3.2 架构视角
- 4 层架构落地；`T04EventUnitResult` 字段语义保持，写入入口收窄到仲裁层。
- 数据流：候选生成器 → ledger → 评分层 → 仲裁器 → unit。
- 修订 `INTERFACE_CONTRACT §3.4 / §3.5 / §4.4` + `architecture/04 / 10`，不改值域、不改入口、不改 baseline。

### 3.3 研发视角
- T-01 拆分前置先行；候选生成器降级；仲裁器单一写入入口（评估后建议合为 `build_case_result` 末尾单次调用）。
- 兼容层：`STEP4_ARBITER_SHADOW_MODE` 开关，shadow 时仲裁器只写 audit、不覆盖 unit 字段。

### 3.4 测试视角

新增 `tests/modules/t04_divmerge_virtual_polygon/test_step4_arbiter_rearchitecture.py`（≤ 80 KB），至少 7 个 case：

1. `test_ledger_append_only_no_writeback`
2. `test_arbiter_writes_final_fields_once`（静态扫描）
3. `test_destructive_downgrade_guard_whitelist`
4. `test_best_so_far_score_tiebreak`
5. `test_main_evidence_replacement_triggers_rearbitration_698389`
6. `test_scenario_reads_from_arbiter_not_derives`
7. `test_30_case_baseline_unchanged_states`

并扩展 `test_step7_final_publish.py / test_internal_full_input_smoke.py` 的 baseline 期望（仅当 698389 类 case 出现 `selected_rcsdroad_ids` 变化时更新对应 case 期望，rejected baseline 期望不动）。

测试运行：`pytest tests/modules/t04_divmerge_virtual_polygon/ -x`

### 3.5 QA 视角

- **30-case visual gate**：所有 case `final_review.png` 逐图比对；rejected 4 case 维持 rejected 视觉。
- **39-case business gate**：所有 case `final_state` 与 `nodes_anchor_update_audit.json` 与 dry-run 一致（除 698389 类预期变化）。
- **Audit schema gate**：新增字段 100% 填充；旧字段语义不变。
- **Code-size gate**：所有源码 / 测试文件 < 100 KB；`code-size-audit.md` 与现状一致。
- **Contract diff gate**：`INTERFACE_CONTRACT / architecture/04 / 10` diff 由 architecture 视角负责人签字；任何值域扩展分离为治理任务。
- **回滚预案**：仲裁器 shadow mode → 灰度 → 全量；任一阶段视觉差异未通过则停下评审。

## 4. 风险与缓释

| 风险 | 缓释 |
|---|---|
| 文件体量逼近 100 KB | T-01 拆分前置 + `code-size-audit.md` 同轮更新 |
| `surface_scenario.classify_surface_scenario` 派生口径改变导致 30-case scenario 翻面 | shadow mode + 全量 dry-run + 视觉评审 |
| 仲裁器选 candidate 与现行 ranking 微差导致 final_state 翻面 | best-so-far 决胜规则锁定 + shadow mode 捕获差异 + rejected baseline 守白名单 |
| 候选生成器降级漏写 audit blob | 静态扫描断言 + review_audit 字段族测试 |
| `INTERFACE_CONTRACT §3` 值域偷改 | T-02 仅动 §3.4 / §3.5 / §4.4 文字，§3.1-3.3 / §3.6-3.8 锁定 |
| 模块内执行入口签名漂移 | facade 函数签名锁定 |
| Step5 `support_domain_builder` 几何翻面 | shadow mode 阶段只输出 audit；视觉评审通过后再开启写入 |

## 5. 不在本计划内
- 不重写 prepared variant 算法（`_build_candidate_pool` / `variant_ranking.py`）。
- 不改 Step5/6/7 几何算法。
- 不改 T01/T02/T03。
- 不增加新值域。
- 不动 `entrypoint-registry.md`。
- 不修订 23-case frozen baseline。

## 6. baseline 保护

- 23-case：`accepted=20 / rejected=3` 不动。
- 30-case：`accepted=26 / rejected=4` 不动。
- 39-case：与现状一致。
- `857993 / 760598 / 760936 / 607602562` 维持 `rejected` 与 `is_anchor=fail4`。
- `699870` 维持 `accepted` 与 `is_anchor=yes`。
- 698389 维持 `accepted`；只允许 `selected_rcsdroad_ids / required_rcsd_node / aggregate_consistency_score` 变动。
