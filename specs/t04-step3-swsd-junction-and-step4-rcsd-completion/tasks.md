# T04 Step3 SWSD 语义路口实体化 + Step4 RCSD 完整性补齐 Tasks

> 严格按 Phase 顺序推进。每完成一个 `[ ]` 项，必须回报"已修改 / 已验证 / 待确认"三档。
> 任何源码 / 脚本文件写入前，**必须前置自检字节数**（`AGENTS.md §3`）。
> 触发硬停机条款（`AGENTS.md §1`）时立即停机回报，不得继续推进。

---

## Phase 0 — Requirement & Contract Freeze

- [x] 阅读 `AGENTS.md`、`modules/t04_divmerge_virtual_polygon/AGENTS.md`、`.agents/skills/default-imp/SKILL.md`、本目录 `spec.md` 与 `plan.md`。
- [x] 确认 `spec.md §7` 五条冻结决策（D1–D5）已于 2026-05-04 由用户授权，implement 阶段直接遵守。
- [x] **D2 守门 dry-run**（必须先做，再开始任何代码修改）：
  - [x] 用当前 main 分支跑 `505078921` 与 `17943587` 两个 case 的 Step3，导出 `event_units/<id>/step3_status.json` 中 `unit_envelope.to_status_doc()` 输出，落到 `notes/d2-baseline-505078921.json` 与 `notes/d2-baseline-17943587.json`。
  - [x] Phase 1 完成后再次导出，与 `notes/d2-baseline-*.json` **逐字段比对必须完全相同**；任何差异立即停机回报。
- [x] 修订 `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`：
  - [x] §2 增加 §2.4 *SWSD 语义路口实体* 与 §2.5 *RCSD 语义路口实体 / RCSDRoad-only chain*。
  - [x] §3 增加 §3.x *swsd_rcsd_alignment_consistent 枚举值域* 与 §3.x *rcsd_consistency_result 冻结值域*。
  - [x] §4.4 Step4 review index 字段族增加 `swsd_rcsd_alignment_consistent`。
- [x] 修订 `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`：
  - [x] §4 Step3 段落补充 `SWSDSemanticJunction` 输出职责。
  - [x] §5 Step4 段落补充 `RCSDSemanticJunction / RCSDRoadOnlyChain / swsd_rcsd_alignment_consistent` 输出职责。
  - [x] §6 Step5 段落明确"不再做 SWSD 相关道路召回判定，消费 Step3 实体"。
- [x] 修订 `modules/t04_divmerge_virtual_polygon/architecture/05-building-block-view.md`：`topology` / `support_domain_builder` 描述同步。
- [x] 修订 `modules/t04_divmerge_virtual_polygon/architecture/12-glossary.md`：增补 `intra_junction_road / inter_junction_connector_road / rcsdroad_only_chain / swsd_rcsd_alignment_consistent` 词条。
- [x] 修订 `modules/t04_divmerge_virtual_polygon/architecture/10-quality-requirements.md`：声明本轮不再与 23-case PNG fingerprint 比对（用户授权）；Phase 6 重新跑 39-case 输出的新 `final_review.png` 作为本轮新基线参考。
- [x] 字节数自检：以上每个被改动的 `.md` 文件无体量约束（仅源码 / 脚本受 §3 约束），但仍记录修订摘要到本地完成记录。

完成回报：契约 / 架构 / 词表 / 质量文档四方修订点列表 + 文件路径。

---

## Phase 1 — `SWSDSemanticJunction` Dataclass & Recall

- [x] 字节数前置自检：`_runtime_step23_contracts.py / _runtime_step3_topology_skeleton.py / topology.py`。
- [x] 在 `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step23_contracts.py` 新增：
  - [x] `@dataclass(frozen=True) class SWSDSemanticArm` —— `arm_id / direction / angle_deg / first_branch_id / first_road_ids / inter_junction_connector_road_ids / terminal_node_id / terminal_kind / neighbor_semantic_junction_id / continuation_through_micro_junction`。
  - [x] `@dataclass(frozen=True) class SWSDSemanticJunction` —— `junction_id / member_node_ids / intra_junction_road_ids / semantic_arms / unstable_reasons / source = "step3_topology_skeleton"`。
  - [x] `Stage4TopologySkeleton` 增字段 `swsd_semantic_junction: SWSDSemanticJunction`；`to_audit_summary` 同步输出。
- [x] 在 `_runtime_step3_topology_skeleton.py` 实现：
  - [x] `_collect_intra_junction_road_ids(local_roads, augmented_member_node_ids) -> tuple[str, ...]`：与现 `_build_road_branches_for_member_nodes.internal_road_ids` 行为对齐，但用 *augmented* member 集合。
  - [x] `_walk_arm_to_neighbor_semantic_junction(seed_branch, local_roads, member_node_ids, semantic_mainnodeids) -> tuple[tuple[str,...], str, str, str | None, bool]` —— 返回 `(connector_road_ids, terminal_node_id, terminal_kind, neighbor_junction_id, continuation_through_micro_junction)`。
    - 默认沿 degree==2 passthrough chain；
    - 遇 degree==3 时一次性穿透（角度连续 guard）；
    - 终止条件：`degree>=3 且不属于 member_node_ids` / `degree==1` / 退出 patch。
  - [x] `_build_swsd_semantic_junction(branch_result, local_roads, local_nodes, representative_node) -> SWSDSemanticJunction`。
- [x] `_build_stage4_topology_skeleton` 末段调用 `_build_swsd_semantic_junction`，写入 `Stage4TopologySkeleton.swsd_semantic_junction`。
- [x] 字节数复检：以上 `.py` 文件未首次跨 100 KB；如有，按 §3 拆分并同步 `code-size-audit.md`。
- [x] `topology.build_step3_status_doc` 顶层加 `swsd_semantic_junction` 字段。
- [x] `topology.build_unit_step3_status_doc` 加 `swsd_junction_ref / unit_owned_arm_ids / sibling_unit_arm_ids`（基于 unit 的 `event_branch_ids / boundary_branch_ids` 与 `swsd_semantic_arms[].first_branch_id` 配对）。
- [x] `outputs.write_case_outputs` 中 `step3_status.json` / `step3_audit.json` 写入点同步新字段（通过 Step3 status doc 构造链路持久化，无需改动输出入口）。
- [x] 单元测试 `tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py`：
  - [x] 三 arm + 一条 internal road → `intra/connector` 拆分正确。
  - [x] degree==3 micro-junction 一次性穿透 → `continuation_through_micro_junction = true`。
  - [x] degree==1 dead end → `terminal_kind = dead_end`。
  - [x] 退出 patch → `terminal_kind = patch_boundary` 且 `inter_junction_connector_road_ids` 仅含 patch 内 ID（**D3 决策**）。
  - [x] sibling internal node（continuous complex）合并到 `member_node_ids`（**D2 决策范围**）。
  - [x] **D1 决策守门**：断言 `SWSDSemanticArm.angle_deg == 对应 BranchEvidence.angle_deg`（绝对相等，无浮点容差）。
- [x] **D2 决策守门**：跑完 Phase 1 后立即与 Phase 0 的 `notes/d2-baseline-505078921.json / d2-baseline-17943587.json` 逐字段比对；差异为 0 才能进入 Phase 2。任何差异 → 停机回报。
- [x] dry-run 守门 case：`505078921` / `17943587` / `760213` / `857993`；输出快照对比，确认 unit envelope sibling 切分未漂移。

完成回报：新增 dataclass schema + 测试结果 + 守门 case 快照差异（应为 0）。

---

## Phase 2 — Step5 / Render 去重迁移

- [x] 字节数前置自检：`support_domain_builder.py / support_domain_cuts.py / review_render.py`。
- [x] `support_domain_builder.build_step5_support_domain`：
  - [x] 删除第 787–800 行 `seed_swsd_road_ids` 计算块。
  - [x] 删除第 813–817 行 `_expanded_related_road_ids` 调用。
  - [x] 改为：`related_swsd_road_ids = case_result.base_context.topology_skeleton.swsd_semantic_junction` 派生（intra ∪ Σ connector）。
  - [x] `unrelated_swsd_road_ids` 与 `unrelated_swsd_node_ids` 仍按"补集"派生，但调用 `support_domain_common._derive_unrelated_swsd_ids(...)` 纯函数（如不存在则新建）。
- [x] `support_domain_cuts._expanded_related_road_ids`：
  - [x] 标记 `# DEPRECATED: moved to _runtime_step3_topology_skeleton._walk_arm_to_neighbor_semantic_junction` 并在文件头加 `__all__` 排除。
  - [x] 主代码路径不再调用；仅保留为兼容残留（下一轮 SpecKit 删除）。
- [x] `review_render._related_swsd_road_ids(step5_result)`：
  - [x] 改签名为 `_related_swsd_road_ids(case_result)`，从 Step3 实体取道路集合。
  - [x] 所有调用点同步更新。
- [x] 验证全仓 `rg "_expanded_related_road_ids" --type py` 仅命中 deprecated 阴影点；Step5 / render / outputs 不再直接调用。
- [x] 单元测试 `tests/modules/t04_divmerge_virtual_polygon/test_step5_consumes_step3_swsd_junction.py`：
  - [x] 给定 fixture Step3 输出 → Step5 `related_swsd_road_ids` = Step3 派生集合。
  - [x] 修改 Step3 fixture 的 connector → Step5 输出对应变化。

完成回报：Step5 / render 改造点清单 + `rg` 检索证据 + 测试结果。

---

## Phase 3 — `RCSDSemanticJunction` Dataclass & Mapping

- [x] 字节数前置自检：`rcsd_alignment.py / _event_interpretation_core.py / step4_road_surface_fork_rcsd.py / case_models.py`。
- [x] 在 `rcsd_alignment.py` 增加：
  - [x] `@dataclass(frozen=True) class RCSDSemanticArm` —— 与 SWSDSemanticArm 对称结构（`inter_junction_connector_rcsdroad_ids / neighbor_rcsd_junction_id` 等）。
  - [x] `@dataclass(frozen=True) class RCSDSemanticJunction` —— `junction_id / member_rcsdnode_ids / intra_junction_rcsdroad_ids / semantic_arms / paired_swsd_arm_mapping / alignment_partial_missing_swsd_arm_ids`。
- [x] 在 `step4_road_surface_fork_rcsd.py` 或 `_event_interpretation_core.py`（按文件体量决定）实现：
  - [x] `_build_rcsd_semantic_junction(unit, swsd_semantic_junction, rcsd_alignment_decision) -> RCSDSemanticJunction | None`。
  - [x] 复用 `aggregated_rcsd_units / local_rcsd_units / required_rcsd_node` 已有信号；intra/connector 切分逻辑与 SWSD 完全对称（走 RCSDRoad / RCSDNode 图）。
  - [x] `paired_swsd_arm_mapping`：基于 angle（30° 容差）+ direction role 与 SWSD `semantic_arms` 比对；多解落 `null` 并写 `audit.pairing_ambiguous_arm_ids`。
- [x] `case_models.T04EventUnitResult` / `case_models.T04CandidateAuditEntry` 增加 `rcsd_semantic_junction: RCSDSemanticJunction | None`。
- [x] `case_models.T04EventUnitResult.to_summary_doc` 与 `outputs.write_case_outputs / step4_event_interpretation.json / step4_candidates.json` 持久化新字段。
- [x] 字节数复检；如 `case_models.py` 接近 100 KB 则按 §3 拆分。
- [x] 单元测试扩展 `tests/modules/t04_divmerge_virtual_polygon/test_step4_rcsd_alignment_type.py`：
  - [x] `rcsd_semantic_junction` → `paired_swsd_arm_mapping` 全配对。
  - [x] `rcsd_junction_partial_alignment` → `alignment_partial_missing_swsd_arm_ids` 非空。
  - [x] 多解 → 对应 arm 配对为 `null` 且 audit 记录歧义原因。

完成回报：新增字段持久化点清单 + 测试结果。

---

## Phase 4 — `RCSDRoadOnlyChain` Dataclass & Closure Proof

- [x] 字节数前置自检：相同范围 `.py`。
- [x] 在 `rcsd_alignment.py` 增加 `@dataclass(frozen=True) class RCSDRoadOnlyChain`：
  - [x] `chain_road_ids / chain_endpoint_node_ids / chain_endpoint_kinds / closure_status / swsd_direction_consistent / swsd_direction_evidence / selection_uniqueness_proof`。
- [x] 实现 `_build_rcsdroad_only_chain(unit, swsd_semantic_junction, candidate_rcsdroad_ids, rcsd_road_graph) -> RCSDRoadOnlyChain | None`：
  - [x] 输入：`fallback_rcsdroad_ids ∪ first_hit_rcsdroad_ids` 候选集合；当前 SWSD `semantic_arms` 角度信号。
  - [x] 拓扑序排序：从一端 RCSDNode 出发，沿 RCSDRoad 序列首尾相接构造 chain。
  - [x] `closure_status` 取值：`closed_between_two_rcsd_junctions / open_dead_end / open_patch_boundary / unresolved`。
  - [x] `swsd_direction_consistent`：chain head/tail tangent 与最近 SWSD arm `angle_deg` 比对（容差 30°）；记录 evidence。
  - [x] 多候选 chain 时复用 `ambiguous_rcsd_alignment` 阻断逻辑；唯一选中需有 `selection_uniqueness_proof`。
- [x] `T04EventUnitResult.rcsdroad_only_chain: RCSDRoadOnlyChain | None`。
- [x] 持久化到 `step4_candidates.json / step4_event_interpretation.json`。
- [x] 单元测试新增：
  - [x] `closure_status = closed_between_two_rcsd_junctions` 用 synthetic 构造（**D4 决策**：39-case 实证可能为 0，但 synthetic 单测必须覆盖该状态分支）。
  - [x] 单端 dead end → `open_dead_end`。
  - [x] patch 边界 → `open_patch_boundary`。
  - [x] `swsd_direction_consistent = true / false` 各一例（**D5 决策**：固定 30° 容差）。
  - [x] 多候选 chain → 阻断或唯一选中带 proof。
- [x] **D5 决策守门**：`_build_rcsdroad_only_chain` 内角度容差常量必须直接复用现有 `BRANCH_MATCH_TOLERANCE_DEG = 30.0`，不得新建独立常量；单元测试断言该来源。
- [x] **D5 审计输出**：每个 RCSDRoad-only chain 的 `swsd_direction_evidence` 字典必须包含 `chain_head_angle_deg / chain_tail_angle_deg / matched_swsd_arm_id / angle_gap_deg / consistency_decision_reason` 五个字段，供 Phase 6 跑完 39-case 后审计角度差分布。

完成回报：新增 dataclass + 测试结果。注意：39-case 内 `closure_status` 分布统计在 Phase 6 跑完后才能给出（**D4 决策**允许 0 命中）。

---

## Phase 5 — Consistency Verdict 聚合 + 取值域冻结

- [x] 字节数前置自检：`rcsd_alignment.py / case_models.py / outputs.py / 各 binding 模块`。
- [x] 在 `rcsd_alignment.py` 新增：
  - [x] `class ConsistencyVerdict(StrEnum)` —— 取值 `strong_consistent / partial_consistent / direction_only_consistent / not_applicable / inconsistent / blocked`。
  - [x] `RCSD_CONSISTENCY_RESULT_VALUES: tuple[str, ...]` —— §4.6 冻结值域。
  - [x] `compute_consistency_verdict(rcsd_alignment_type, positive_rcsd_consistency_level, axis_polarity_inverted, rcsdroad_only_chain) -> ConsistencyVerdict` 纯函数。
- [x] `T04EventUnitResult.swsd_rcsd_alignment_consistent: ConsistencyVerdict`；`to_summary_doc / to_csv_row` 同步。
- [x] `outputs.REVIEW_INDEX_FIELDNAMES` 增加 `swsd_rcsd_alignment_consistent` 列；`T04ReviewIndexRow` 同步增字段。
- [x] `outputs.write_review_summary` 增加 `swsd_rcsd_alignment_consistent_counts` 分布统计。
- [x] 收口 `rcsd_consistency_result`：
  - [x] 全仓 `rg "rcsd_consistency_result\s*=" --type py` 列出所有写入点（已知 ≥ 8 处）。
  - [x] 每处写入前 `assert value in RCSD_CONSISTENCY_RESULT_VALUES`，越界字符串触发 `ValueError`（不静默写入）。
  - [x] 现存字符串如 `"positive_rcsd_strong_consistent" / "positive_rcsd_partial_consistent" / "road_surface_fork_without_bound_target_rcsd" / "missing_positive_rcsd"` 全部纳入值域。
  - [x] 新增 `"positive_rcsd_direction_only_consistent" / "positive_rcsd_inconsistent" / "none"` 显式补齐。
- [x] 单元测试 `tests/modules/t04_divmerge_virtual_polygon/test_consistency_verdict.py`：
  - [x] `compute_consistency_verdict` 真值表全覆盖。
  - [x] 越界 `rcsd_consistency_result` 写入 → `ValueError`。
  - [x] CSV 列序与 INTERFACE_CONTRACT 文档一致。

完成回报：值域冻结清单 + 写入点验证 + 测试结果。

---

## Phase 6 — Real Case Regression

### 6.1 既有 baseline gate（必须通过）

- [x] 跑 30-case baseline gate：`pytest tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate -x`。
  - [x] `accepted = 20 / rejected = 3` 不漂移；`857993 = fail4 / 699870 = yes`。
- [x] 跑 30-case surface scenario gate：`...::test_anchor2_30case_surface_scenario_baseline_gate -x`。
  - [x] `accepted = 26 / rejected = 4` 不漂移。

### 6.2 39-case 重新跑 + 新基线生成

- [x] 跑 Anchor_2 39-case full baseline（手工命令或 `t04_run_internal_full_input_8workers.sh`）：
  - 输入集：`E:\TestData\POC_Data\T02\Anchor_2`（WSL：`/mnt/e/TestData/POC_Data/T02/Anchor_2`）。
  - run_root：`outputs/_work/t04_step14_batch/codex_t04_step3_swsd_junction_<timestamp>`。
- [x] 全 39-case 自动核查（必须全绿）：
  - [x] 每 case `step3_status.json.swsd_semantic_junction.junction_id != ""`。
  - [x] 每 case `step3_status.json.swsd_semantic_junction.intra_junction_road_ids ∩ Σ inter_junction_connector_road_ids = ∅`。
  - [x] 每 case Step5 `related_swsd_road_ids` 与 Step3 派生集合（`intra ∪ Σ connector`）逐项相等。
  - [x] 每 case `summary.json.performance.threshold_status = within_threshold`。
  - [x] 全 39-case 总耗时较 30-case baseline `~180–184s` 上涨 ≤ 5%。
  - [x] 每 case `swsd_rcsd_alignment_consistent` 字段非空且与 alignment_type / consistency_level / axis_polarity_inverted 推导一致。

### 6.3 命名回归 case（用户人工核对发现渲染缺失）

- [x] `724067`：
  - [x] `swsd_semantic_junction` 输出非空。
  - [x] 派生道路集合（`intra ∪ Σ connector`）与 `final_review.png` 上 SWSD 路网图层逐条目视核对，**全部可见**。
  - [x] 任何缺失道路：定位是 Step3 实体未召回还是渲染层未绘制；前者修 `_walk_arm_to_neighbor_semantic_junction`，后者修 `review_render`。
- [x] `758784`：同上 3 项核查。
- [x] `760213`：同上 3 项核查。
- [x] 命名 case 全部通过后，把这三个 case 写入 `tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py` 作为 fixture 锁定（snapshot 比对：`junction_id / intra_junction_road_ids / Σ semantic_arms[].inter_junction_connector_road_ids` 全集）。

### 6.4 全 39-case 渲染缺失抽查（不限于命名 case）

- [x] 对全 39-case 自动生成对照清单：每 case 输出 `(case_id, swsd_entity_road_count, render_visible_road_count, missing_road_ids)` 到 `outputs/_work/t04_swsd_render_audit/<run_root>/render_audit.csv`。
  - 实现策略：在 `review_render` 输出 PNG 同时，dump 一份"图层实际渲染的 SWSD road id 集合"到 audit JSON；与 Step3 实体派生集合做 set-difference。
- [x] 任意 case 出现 `missing_road_ids != []` → 视为 Phase 6 失败项，回退到 Phase 1–2 修 `_walk_arm_to_neighbor_semantic_junction` 或 `review_render`，再跑 6.2 / 6.3 / 6.4。
- [x] 渲染缺失修复后，把所有"Phase 6.4 阶段抽查发现遗漏的 case"也加入 6.3 的 fixture snapshot（命名 case + 抽查发现 case 共同构成 SWSD 实体回归 fixture 集）。

### 6.5 最终目视审计图

- [x] 39-case 全部通过 6.2/6.3/6.4 后，`run_root/cases/<case_id>/final_review.png` 即作为**本轮新目视审计基线**；不与 2026-05-01 的 23-case PNG fingerprint 做对比。
- [x] 把 run_root 路径登记到 `architecture/10-quality-requirements.md` 的 *Anchor_2 full baseline gate* 段落作为新参考。
- [x] **不**新增 PNG fingerprint hash 断言（保持当前 23-case fingerprint gate 不动；本轮新基线作为人工审计参考存在，不进 pytest）。

### 6.6 D4 / D5 数字落地

- [x] **D4 实证统计**：39-case 跑完后，把 `closure_status` 在 39-case 上的实际分布数字写入 `notes/run-log.md`（例如 `closed_between_two_rcsd_junctions: 0 / open_dead_end: 4 / open_patch_boundary: 7 / unresolved: 0`）。若 `closed_between_two_rcsd_junctions = 0`，同步在 `INTERFACE_CONTRACT.md §2.5` 末尾追加一句"当前 Anchor_2 39-case 数据集无该状态实证 case，作为契约预留状态保留"。
- [x] **D5 角度差分布**：把所有 RCSDRoad-only case 的 `angle_gap_deg` 数字汇总到 `notes/run-log.md` 表格（case_id / chain_head / chain_tail / matched_swsd_arm / angle_gap_deg / consistent）；若发现密集落在 25–35° 边界区间，在 `notes/run-log.md` 末尾标注"建议下一轮 SpecKit 评估容差调整"，但**本轮不调整**。

### 6.7 完成回报

- 30-case / 30-case scenario / 39-case 三轮 gate 的 pass/fail。
- 39-case 总耗时与 30-case 基线对比（绝对值 + 涨幅百分比）。
- `724067 / 758784 / 760213` 三个命名 case 的核查证据（缺失道路修复前后对比）。
- `render_audit.csv` 的全 39-case 缺失统计（应为全 0）。
- D4 `closure_status` 实证分布数字。
- D5 `angle_gap_deg` 分布表格。
- 新 run_root 路径与登记到 `10-quality-requirements.md` 的本地 HEAD / 最终统一提交后 commit hash。

---

## Phase 7 — QA / Documentation Closeout

- [x] 验证 CRS：所有新增 `step3_status / step4_event_interpretation / step5_status` 写出未改 CRS。
- [x] 验证 geometry valid：新增字段不引入 geometry；纯 ID + 元数据，无 valid 风险。
- [x] 验证文件体量：再次运行 `Get-ChildItem`（PowerShell）或 `stat -c%s`（POSIX）自检，所有源码 `.py` 不跨 100 KB；如发生拆分，确认 `docs/repository-metadata/code-size-audit.md` 已同步。
- [x] 验证契约一致性：`step4_review_index.csv` 列序与 `INTERFACE_CONTRACT.md §4.4` 一致；`step3_status.json` schema 与 §2.4 一致；`step4_event_interpretation.json` schema 与 §2.5 一致。
- [x] 性能审计：`summary.json.performance` 字段齐全；`threshold_source = module_quality_requirement_default_or_env_override`；`threshold_status = within_threshold`。
- [x] 视觉审计采样：从 39-case 中随机抽 5 个 case，人工核对 `final_review.png` 上 SWSD 路口道路集合 = `swsd_semantic_junction` 派生集合（采样核对作为 6.4 全量自动核查之上的人工抽样保险）。
- [x] 生成 Release Notes 草稿：`已修改 / 已验证 / 待确认` 三档分明，置于 `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/notes/release-notes.md`。
- [x] 治理工件登记：在 `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/notes/run-log.md` 写执行轨迹（每 Phase 起止时间 + 本地 HEAD / commit 状态 + GitHub 操作状态 + run_root）。

完成回报：QA checklist 全部勾选 + Release Notes 草稿路径 + run log 路径。

---

## Phase 8 — Codex 完整执行协议（必读，强制遵守）

> 本节是 Codex 在本 SpecKit 任务下的**完整工作协议**。任何与本节冲突的临时做法都视为治理违规。

### 8.1 阅读链路（启动前必须按顺序读完）

1. `AGENTS.md`（仓库级硬约束）
2. `modules/t04_divmerge_virtual_polygon/AGENTS.md`（模块级硬约束）
3. `.agents/skills/default-imp/SKILL.md`（默认编程流程）
4. `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`（重点读 §2.3 / §3.4 / §3.5 / §4.4）
5. `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`（§4 / §5 / §6）
6. `modules/t04_divmerge_virtual_polygon/architecture/10-quality-requirements.md`（baseline gate 段落）
7. 本目录 `spec.md` → `plan.md` → `tasks.md`（按此顺序）
8. 用户对 `spec.md §7` 5 个 Open Questions 的最终回复（已合并到 spec.md 后）

读完每份文档后，在 `notes/run-log.md` 与最终回报中**显式声明**"已阅读 ✅"。读不完就启动编码视为治理违规。

### 8.2 本地串行执行模式（2026-05-04 用户修订）

> 用户于 2026-05-04 明确要求：后续任务不再提交 GitHub，均在本地进行；本次完成后统一提交。自本条修订后，§8.2–§8.3 的 GitHub PR 流程停止适用。

- 不再创建 GitHub PR、不再 push、不再要求用户手动 merge。
- 从当前本地工作区继续串行推进 Phase 3–7；不得多 Phase 并行。
- 每个 Phase 仍必须独立完成对应 `tasks.md` 勾选项、测试纪律、字节体量自检、硬停机检查与 run-log 记录。
- Phase 完成后不提交 GitHub；除非用户另行授权，也不再创建本地阶段性 commit。
- 本轮所有后续修改在本地累积，待 Phase 7 / QA 完成后统一提交。
- 已经创建的 Phase 2 PR 仅作为历史痕迹记录，不再更新、不再依赖其合并状态推进后续 Phase。

### 8.3 本地完成回报模板

每个 Phase 完成本地检查时，必须在 `notes/run-log.md` 与最终回报中覆盖以下内容：

```markdown
## SpecKit Reference
specs/t04-step3-swsd-junction-and-step4-rcsd-completion/{spec.md, plan.md, tasks.md}

## Phase
Phase <N> — <name>

## 阅读链路确认
- [x] AGENTS.md
- [x] modules/t04_divmerge_virtual_polygon/AGENTS.md
- [x] .agents/skills/default-imp/SKILL.md
- [x] INTERFACE_CONTRACT.md §2.3 / §3.4 / §3.5 / §4.4
- [x] architecture/04-solution-strategy.md §4 / §5 / §6
- [x] architecture/10-quality-requirements.md
- [x] specs/t04-step3-swsd-junction-and-step4-rcsd-completion/{spec.md, plan.md, tasks.md}

## 已修改
- 文件路径 1：本 Phase 的修改目的（一句话）
- 文件路径 2：本 Phase 的修改目的（一句话）
...

## 已验证
- 命令 / 测试 / 输出（粘贴关键证据，不要只写"测试通过"）
- 例：`pytest tests/.../test_step3_swsd_semantic_junction.py -x` → `12 passed in 8.34s`
- 例：`Get-ChildItem src/.../topology.py | Select-Object Length` → `46128`（未跨 100 KB）

## 待确认
- 本 Phase 仍需用户决策的开放点（如无，写"无"）

## 硬停机检查
- [ ] 未触发 AGENTS.md §1.1（源事实冲突）
- [ ] 未触发 §1.2（未授权改动模块官方对外接口）
- [ ] 未触发 §1.3（新增长期保留正式执行入口）
- [ ] 未触发 §1.4（文件体量跨 100 KB）
- [ ] 未触发 §1.5（数据现象反推上游字段语义）
- [ ] 未触发 §1.6（路径语义不一致）
- [ ] 未触发 §1.7（入口变更 registry 不一致）

## Tasks Checklist
本 Phase 完成的 tasks.md 项（粘贴勾选行）：
- [x] Phase <N> 项 1
- [x] Phase <N> 项 2
- [ ] Phase <N> 项 3（后续本地 Phase）
```

### 8.4 字节体量自检（每次源码 / 脚本写入前）

**前置自检命令模板**：

PowerShell：
```powershell
Get-ChildItem -Path src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/<file>.py | Select-Object Name, Length
```

POSIX：
```bash
stat -c%s src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/<file>.py
```

阈值规则（`AGENTS.md §3`）：
- 当前 < 100 KB → 可写入；写入后再次自检确认未跨阈值。
- 当前 ≥ 100 KB → **禁止写入**；先按 §3 提交"拆分计划"或"豁免说明"，并同轮更新 `docs/repository-metadata/code-size-audit.md`。
- 本 SpecKit 已知接近阈值的高风险文件（必须在本地 Phase 记录中自检）：
  - `_runtime_step4_kernel.py`
  - `_event_interpretation_core.py`
  - `case_models.py`
  - `support_domain_builder.py`
  - `polygon_assembly.py`（已在历史轮次拆分）

### 8.5 测试纪律（每 Phase 必跑）

- Phase 1：跑 `test_step3_swsd_semantic_junction.py`（新建）+ `test_step3_topology_skeleton.py`（既有，不应回归）。
- Phase 2：跑 `test_step5_consumes_step3_swsd_junction.py`（新建）+ Step5 既有 unit / synthetic 测试。
- Phase 3：跑 `test_step4_rcsd_alignment_type.py`（扩展）+ Step4 既有测试。
- Phase 4：跑 `test_step4_rcsdroad_only_chain.py`（新建）。
- Phase 5：跑 `test_consistency_verdict.py`（新建）+ `test_step4_surface_scenario_classification.py`（既有，不应回归）。
- Phase 6：跑 `test_anchor2_full_20260426_baseline_gate` + `test_anchor2_30case_surface_scenario_baseline_gate` + 39-case 完整 batch 跑通。
- Phase 7：跑 `pytest tests/modules/t04_divmerge_virtual_polygon/ -x`（全模块测试无回归）。

每 Phase 本地完成前测试不绿不允许进入下一 Phase。**不允许 `--ignore` / `xfail` 静默跳过任何测试**（如确需跳过，spec.md 同轮显式说明并经用户授权）。

### 8.6 硬停机回报（`AGENTS.md §1` 末段强制）

任何时刻命中 §1.1–§1.7 → 立即停机并在当前线程回报，内容必须包含：

1. **触发条款编号**（精确到 §1.X）。
2. **当前事实**（命中条款的具体证据，含文件路径、行号、关键字段值）。
3. **缺失 / 冲突点**（与契约或 spec 的对比）。
4. **建议的下一步选项**（≥ 2 个，按"安全 → 风险递增"排序）。

不允许"边跑边问"——必须先停机，等用户决策再继续。

### 8.7 完成回报最小集（`AGENTS.md §6` 末段强制）

每个 Phase 的 run-log 条目与最终回复必须区分**已修改 / 已验证 / 待确认**三档。"看起来应该可以"不得表述为"已经修复"。

### 8.8 治理工件维护

Phase 0 起在本 SpecKit 目录维护：

- `notes/run-log.md`：每 Phase 的 起止时间 / 本地 commit hash（若有）/ GitHub 操作状态 / run_root 路径 / 关键决策点。
- `notes/release-notes.md`：Phase 7 写就绪后的 Release Notes 草稿（已修改 / 已验证 / 待确认 三档）。
- 每个 Phase 本地完成后立即更新 run-log.md；后续统一提交。

### 8.9 Phase 完成判据（用户验收）

每个 Phase 本地完成并进入下一 Phase 前，必须满足：

- 该 Phase 在 `tasks.md` 中所有 `[ ]` 任务都已勾选 `[x]`；
- 该 Phase 测试纪律全绿；
- run-log 条目符合 §8.3 模板；
- 字节体量自检通过；
- 硬停机检查 7 条全部 ✅；
- run-log.md 已同步。

不满足任一条 → 用户有权 reject 本地 Phase 交付；Codex 重做后重新回报。

### 8.10 全任务结束

Phase 7 本地 QA 完成后，Codex 必须发**最终汇总回报**，并等待用户确认是否执行统一提交：

- Phase 0–2 历史 PR link 列表（仅作为历史痕迹）+ Phase 3–7 本地完成记录。
- 39-case 跑通的 run_root 路径。
- 30-case / 30-case scenario / 39-case 三轮 gate 的最终 pass 证据。
- `724067 / 758784 / 760213` 三个命名 case 的修复前后对比（`render_audit.csv` 行）。
- 全 39-case `render_audit.csv` 的最终 missing_road_ids 全 0 证据。
- `notes/release-notes.md` 的最终内容。
- 本 SpecKit 任务的"已修改 / 已验证 / 待确认"全集。

完成回报：以上 7 项全集 + 用户最终验收签字。
