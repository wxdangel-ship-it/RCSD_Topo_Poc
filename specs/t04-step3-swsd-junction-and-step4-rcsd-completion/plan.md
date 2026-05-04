# T04 Step3 SWSD 语义路口实体化 + Step4 RCSD 完整性补齐 Plan

## 1. Strategy

按 *"模块源事实先行 → Step3 实体化 → Step5 / 渲染层去重 → Step4 RCSD 对称实体化 → 一致性 verdict 聚合 → baseline 守门"* 顺序推进。**强制约束**：

- 任何改动必须先做契约层修订（spec.md 已先行；本轮 implement 第一步即同步 `INTERFACE_CONTRACT.md` 与 `architecture/*`）；契约未冻结前不允许写运行时代码。
- Step5 / 渲染层不允许保留旧 `_expanded_related_road_ids` 副本；本轮要么删除，要么变成 Step3 调用方。
- 文件体量硬约束 100 KB（`AGENTS.md §3`）：每次写入前置自检；新代码若让任一源文件首次跨 100 KB，必须立刻拆分并同步 `docs/repository-metadata/code-size-audit.md`。
- 不允许"先 patch 再回头补契约"的工作方式；契约-代码-测试三方同轮闭合。

## 2. Role Responsibilities（AGENTS.md §6 强制覆盖五视角）

| Role | Responsibility | Required Output |
|---|---|---|
| Product | 守"SWSD 语义路口"的语义定义与渲染口径，给出对照案例 | case-by-case "应被召回道路集合"对照表（用户提供怀疑 case 后填充） |
| Architecture | 定义 `SWSDSemanticJunction / RCSDSemanticJunction / RCSDRoadOnlyChain / ConsistencyVerdict` 边界与持久化协议；控制文件体量 | dataclass schema、模块拆分方案、契约 delta diff |
| Development | 按切片实现 Step3 实体化 / Step4 完整性 / Step5 去重 / 渲染层迁移 | 小步可回滚 PR、audit 字段、向后兼容字段映射 |
| Testing | 补 unit / synthetic / real-case 三层回归；锁 30-case 与 23-case baseline | pytest gates、fixtures、conftest 工具 |
| QA | 守 CRS、几何 valid、性能不退化、视觉 fingerprint 刷新需 diff 报告、契约一致性 | release checklist、视觉 diff 报告、性能审计、契约一致性核查 |

## 3. Implementation Slices

### Slice 0 — Requirement & Contract Freeze

- spec.md §7 五条决策（D1–D5）已由用户于 2026-05-04 冻结；implement 阶段直接遵守，不再返工讨论。
- 修订 `INTERFACE_CONTRACT.md` 增补 §2.4（SWSD 语义路口实体）、§2.5（RCSD 语义路口实体 / RCSDRoad-only chain）与 §3.x（`swsd_rcsd_alignment_consistent` 枚举 / `rcsd_consistency_result` 冻结值域）。
- 修订 `architecture/04-solution-strategy.md` §4/§5/§6 段落职责。
- 修订 `architecture/05-building-block-view.md` `topology / support_domain_builder` 描述。
- 修订 `architecture/12-glossary.md` 增加 4 条词条。
- 不再与 23-case PNG visual fingerprint 做比对（用户授权）；Phase 6 重新跑 39-case 输出新 `final_review.png` 作为本轮新基线。
- D2 dry-run 守门：用 `505078921 / 17943587` 跑改造前后 `unit_envelope.to_status_doc()` 比对，差异为 0 才能进入 Slice 1。

完成判据：契约 / 架构 / 词表三处均已写入新概念；spec.md §7 五条决策均与文档措辞一致；D2 dry-run 比对差异为 0。

### Slice 1 — `SWSDSemanticJunction` Dataclass & Recall

- 在 `_runtime_step23_contracts.py` 新增 `SWSDSemanticJunction / SWSDSemanticArm` frozen dataclass。
- 在 `_runtime_step3_topology_skeleton.py` 实现 `_build_swsd_semantic_junction(...)`：
  - 内部道路：复用 `_build_road_branches_for_member_nodes` 已识别的 `internal_road_ids`，并把 `member_node_ids` 替换为 `branch_result.member_node_ids ∪ augmented_member_node_ids`。
  - arm 延伸：复用 `_chain_candidates_from_topology / _pick_chain_continuation_candidate` 既有原语；新增 `_walk_arm_to_neighbor_semantic_junction(...)`，按 §4.1 "合法 continuation"规则走 chain，记录 `inter_junction_connector_road_ids` 与 `terminal_kind`。
- `Stage4TopologySkeleton` 增加 `swsd_semantic_junction: SWSDSemanticJunction` 字段；`to_audit_summary` 输出对应 audit 子树。
- 在 `topology.build_step3_status_doc` 补输出 `swsd_semantic_junction`；`build_unit_step3_status_doc` 补 `swsd_junction_ref / unit_owned_arm_ids / sibling_unit_arm_ids`。

完成判据：`step3_status.json` 顶层与 unit 级新字段全部出现；老字段（`branch_ids / branch_road_memberships / event_branch_ids / boundary_branch_ids`）保持不变。

### Slice 2 — Step5 / Render 去重迁移

- `support_domain_builder.build_step5_support_domain` 改为消费 Step3 `swsd_semantic_junction`；删除 `seed_swsd_road_ids` 计算块（约第 787–817 行）；`related_swsd_road_ids` 从 Step3 计算结果直接派生。
- `support_domain_cuts._expanded_related_road_ids` 标记 deprecated 并移到 `_runtime_step3_topology_skeleton.py` 作为内部辅助；外层全部不再调用。
- `review_render._related_swsd_road_ids` 改为读 Step3 输出。
- Step5 audit JSON 仍保留 `related_swsd_road_ids / unrelated_swsd_road_ids` 字段（向后兼容），值由 Step3 输出派生而来。

完成判据：`rg "_expanded_related_road_ids" --type py` 仅在 `_runtime_step3_topology_skeleton.py` 与 deprecated 阴影点出现；Step5 / render 不再直接调用。

### Slice 3 — `RCSDSemanticJunction` Dataclass & Mapping

- 在 `rcsd_alignment.py` 增加 `RCSDSemanticJunction / RCSDSemanticArm` frozen dataclass，结构与 SWSD 对称。
- 在 `_event_interpretation_core.py` 或 `step4_road_surface_fork_rcsd.py`（看体量决定落点）实现 `_build_rcsd_semantic_junction(...)`：
  - 复用 `aggregated_rcsd_units / local_rcsd_units / required_rcsd_node` 已有信号；
  - intra/connector 切分逻辑与 SWSD 完全对称，但走 RCSDRoad/RCSDNode 图。
- 在 `_build_rcsd_semantic_junction` 末段产出 `paired_swsd_arm_mapping`（基于 angle 与方向角色与 SWSD `semantic_arms` 比对）。
- `T04EventUnitResult` / `T04CandidateAuditEntry` 新增 `rcsd_semantic_junction: RCSDSemanticJunction | None` 字段。

完成判据：`rcsd_alignment_type ∈ {rcsd_semantic_junction, rcsd_junction_partial_alignment}` 时 `rcsd_semantic_junction` 非空；`partial_alignment` 时 `paired_swsd_arm_mapping` 至少有一个值为 `null`，并通过 `alignment_partial_missing_swsd_arm_ids` 暴露差。

### Slice 4 — `RCSDRoadOnlyChain` Dataclass & Closure Proof

- 在 `rcsd_alignment.py` 增加 `RCSDRoadOnlyChain` frozen dataclass。
- 实现 `_build_rcsdroad_only_chain(...)`：
  - 输入：`fallback_rcsdroad_ids / first_hit_rcsdroad_ids` 候选；当前 SWSD `semantic_arms` 角度信号；RCSD 路网拓扑。
  - 输出：拓扑序排列的 chain、端点 RCSDNode、端点 kind、`closure_status`、`swsd_direction_consistent` 与 evidence。
- 候选 chain 唯一消歧：复用 `selection_uniqueness_proof` 模式；多候选时按 §3.4 规则进入 `ambiguous_rcsd_alignment` 阻断。
- `T04EventUnitResult` 新增 `rcsdroad_only_chain: RCSDRoadOnlyChain | None` 字段。

完成判据：`rcsd_alignment_type = rcsdroad_only_alignment` 时 `rcsdroad_only_chain.chain_road_ids` 非空且首尾 RCSDNode 配对；`swsd_direction_consistent` 取值与 evidence 一致。

### Slice 5 — Consistency Verdict 聚合 + 取值域冻结

- 在 `rcsd_alignment.py` 新增 `ConsistencyVerdict` 枚举与 `compute_consistency_verdict(...)` 纯函数。
- `T04EventUnitResult.swsd_rcsd_alignment_consistent` 字段；`to_summary_doc / to_csv_row` 同步输出。
- `step4_review_index.csv` REVIEW_INDEX_FIELDNAMES 增加 `swsd_rcsd_alignment_consistent` 列；`step4_review_summary.json` 增加分布计数。
- 把 `rcsd_consistency_result` 取值收口到 §4.6 冻结值域；新增 `rcsd_alignment.RCSD_CONSISTENCY_RESULT_VALUES` 常量；所有写入点改为引用该常量。
- 若违规字符串被发现，编码处直接 `raise` 而非静默写入。

完成判据：所有 binding 模块的 `rcsd_consistency_result=` 字符串均通过 `RCSD_CONSISTENCY_RESULT_VALUES` 校验；`swsd_rcsd_alignment_consistent` 在 39-case 上取值分布合理。

### Slice 6 — Tests（synthetic / unit / real-case）

- 新增 `tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py`：
  - 单 case 三 arm 路口 → `intra/connector` 拆分正确；
  - degree==3 micro-junction 一次性穿透；
  - patch 边界终止；
  - sibling internal node（continuous complex / merge）合并到 `member_node_ids`；
  - `505078921 / 17943587 / 760213 / 857993` 冻结守门 case 的 SWSD 实体快照。
- 扩展 `test_step4_rcsd_alignment_type.py`：
  - `rcsd_semantic_junction` 输出实体且 arm 配对完整；
  - `rcsd_junction_partial_alignment` 给出 `alignment_partial_missing_swsd_arm_ids`；
  - `rcsdroad_only_alignment` 输出 chain 且 `closure_status` 取值符合期望；
  - `swsd_rcsd_alignment_consistent` 五种取值至少各一例。
- 新增 `test_step5_consumes_step3_swsd_junction.py`：Step5 不再调用 `_expanded_related_road_ids`；`related_swsd_road_ids` 与 Step3 实体派生一致。
- Anchor_2 39-case baseline gate 增补：
  - 39 case 全部 `swsd_semantic_junction.junction_id != ""`；
  - 30-case `accepted = 26 / rejected = 4` 不漂移；
  - 23-case PNG fingerprint 若刷新，附 diff 报告（非测试断言，QA 阶段处理）。

完成判据：新增测试全绿；30-case / 23-case 既有 gate 不动。

### Slice 7 — QA Gates

- CRS / valid geometry / feature count / summary-audit 一致性断言扩展到新 `swsd_semantic_junction` 输出。
- 23-case PNG fingerprint 刷新决议（`architecture/10-quality-requirements.md` 内的 visual baseline 段落）。
- 性能：39-case `summary.json.performance.threshold_status` 必须 `within_threshold`；新增字段不得让总耗时上涨超过 5%。
- 视觉审计：`final_review.png` 中 `swsd_semantic_junction.intra_junction_road_ids` 与 `Σ inter_junction_connector_road_ids` 全部可见（采样 5 个 case 人工核对）。
- `docs/repository-metadata/code-size-audit.md` 同轮更新（如发生拆分）。
- `docs/doc-governance/module-lifecycle.md` 不需修订；本轮仍处于 Step1-7 正式范围内。

完成判据：QA checklist 全部勾选；Release Note 草稿可生成。

## 4. Verification Matrix

| Level | Required Verification |
|---|---|
| Syntax | 修改的 `.py` `python -m py_compile`；MD 用 `markdownlint`（可选） |
| Unit | `_build_swsd_semantic_junction / _walk_arm_to_neighbor_semantic_junction / _build_rcsd_semantic_junction / _build_rcsdroad_only_chain / compute_consistency_verdict` 的纯函数测试 |
| Synthetic | 三 arm SWSD / 四 arm SWSD / partial RCSD / road-only chain / ambiguous block 各至少 1 例 |
| Real case | 30-case baseline / 23-case baseline / 用户怀疑 case（待提供）/ 769184 等 multi-unit / 760984+788824 等 RCSD junction window |
| QA | CRS、几何 valid、性能阈值、视觉刷新 diff、契约一致性、文件体量 |

## 5. Risks and Controls

| Risk | Control |
|---|---|
| Step3 实体化破坏 unit envelope sibling 切分 | Slice 0 dry-run（`505078921 / 17943587`）；Slice 1 单测覆盖 sibling 合并 |
| `inter_junction_connector_road_ids` 在 patch 边界外漏召 | `terminal_kind = patch_boundary` 显式标注；不在 patch 内的不强求闭合 |
| `_expanded_related_road_ids` 残留调用导致重复召回 | `rg` 全仓搜索 + 测试断言 Step5 输出 = Step3 派生 |
| `RCSDRoadOnlyChain.closure_status` 全 39 case 都不命中 `closed_between_two_rcsd_junctions` | 接受作为契约预留状态；spec §7 Open Question 4 已预报 |
| `swsd_rcsd_alignment_consistent` 与现有 4 个字段产生冲突理解 | 文档明确"派生字段，不替代源字段"；测试覆盖与 alignment_type / consistency_level 的推导一致性 |
| 39-case 中存在未被 `724067 / 758784 / 760213` 覆盖的渲染缺失 case | Phase 6 对全 39-case 做"Step3 实体派生道路集合 vs `final_review.png`"对照核查，发现即补漏 |
| 文件体量首次跨 100 KB | 前置自检 + 拆分模板复用 `polygon_assembly` 历史经验 |
| 性能退化 > 5% | 39-case `threshold_seconds_total = 240.0`；超阈直接回滚或重新评估 |
| 38 个 binding 模块未全部收口 `rcsd_consistency_result` | 引入 `RCSD_CONSISTENCY_RESULT_VALUES` 常量 + `assert` 写入点 |
| `paired_swsd_arm_mapping` 在角度多解时给错配对 | 容差 30°，多解时落 `null` 并记录到 audit；不允许默认贪心 |

## 6. Out-of-Scope（本轮明确不做）

- 不改 `accepted / rejected` 二态最终结果机；不引入第三状态。
- 不改 `kind / kind_2 / mainnodeid` 字段语义；只读消费。
- 不引入 case-level SWSD 候选消歧（admission 决定唯一 mainnodeid 即唯一 SWSD 路口）。
- 不修复 `_pick_chain_continuation_candidate` 的阈值；如需调整另起 SpecKit。
- 不动 Step6 `polygon_assembly` 主链；只在 Step5 输入侧消费 Step3 新实体。
- 不动 Step7 `final_publish` / nodes_publish；下游字段保持兼容。

## 7. Codex Handoff Notes

本 plan 与 spec / tasks 一并交给 Codex 实现时，必须按下列固定顺序：

1. 阅读 `AGENTS.md`、`modules/t04_divmerge_virtual_polygon/AGENTS.md`、`.agents/skills/default-imp/SKILL.md`。
2. 阅读 `INTERFACE_CONTRACT.md` §2.3 / §3.4 / §3.5 / §4.4，再阅读本 spec / plan / tasks。
3. 严格按 `tasks.md` 顺序逐 Phase 推进；每个 `[ ]` 项完成后回报"已修改 / 已验证 / 待确认"。
4. 任何 Phase 中出现源事实冲突 → 立刻按 `AGENTS.md §1.1` 停机回报。
5. 任何源码 / 脚本写入前 → 字节数自检（PowerShell `Get-ChildItem` 或 POSIX `stat -c%s`）；接近 100 KB 立刻按 §3 拆分流程。
6. 每个 Phase 完成后跑该 Phase 对应的 pytest 子集；不得一次性等到最后才跑测试。
7. 30-case / 23-case baseline gate 必须在 Phase 7 前完整跑过；超阈值或失败立刻停机。
