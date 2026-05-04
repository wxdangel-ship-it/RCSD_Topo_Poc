# T04 Step3 SWSD 语义路口实体化 + Step4 RCSD 完整性与一致性补齐 Spec

## 1. Scope

本 SpecKit 任务覆盖两个层次的对称治理：

- **Step3 中期治理**：把"SWSD 语义路口本体 + 路口内道路 + 到其他 SWSD 语义路口的关联道路"显式实体化为 Step3 的一等输出（`SWSDSemanticJunction` / `SWSDSemanticArm`）；并把当前散落在 Step5 的 `_expanded_related_road_ids` 召回逻辑前移到 Step3 唯一权威实现。
- **Step4 审计缺口补齐**：在 Step3 SWSD 实体化基础上，对 RCSD 语义路口（完整 / partial）实体化 `intra_junction_road_ids` 与 `inter_junction_connector_road_ids`；为 `rcsdroad_only_alignment` 增加"两 RCSD 语义路口间完整道路链"端点对与闭合证明；冻结 `rcsd_consistency_result` 取值域；新增单一 `swsd_rcsd_alignment_consistent` consistency verdict 字段。

本任务**不进入 implement 阶段**，正式编码必须在本 spec、plan、tasks 三件套与 gap audit 经用户确认后再开始。

## 2. Source Requirement Baseline

本任务以模块源事实为准，尤其是：

- `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`（§2.3 SWSD/RCSD 语义路口基础判定、§3.4 RCSD alignment 与负向掩膜口径、§3.5 六场景与生成模式）
- `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`（§4 Step3、§5 Step4、§6 Step5）
- `modules/t04_divmerge_virtual_polygon/architecture/05-building-block-view.md`（topology / event_interpretation / support_domain 分层）
- `modules/t04_divmerge_virtual_polygon/architecture/10-quality-requirements.md`（正确性、可审计性、回归门槛）
- `modules/t04_divmerge_virtual_polygon/architecture/12-glossary.md`

`specs/*` 是变更工件，不替代模块源事实。`RCSD_Topo_Poc_T04_REQUIREMENT.md` 不作为更高优先级输入。Anchor_2 当前正式 case 清单为 `E:\TestData\POC_Data\T02\Anchor_2`（WSL：`/mnt/e/TestData/POC_Data/T02/Anchor_2`）下 39 个 case。

## 3. Problem Statement

来自 2026-05-04 审计（见对话纪要 [Step4 t04 module audit](audit-conversation-2026-05-04)）的事实：

### 3.1 Step3 缺口

`_runtime_step3_topology_skeleton._build_road_branches_for_member_nodes` 当前只产出：

- `internal_road_ids`：两端都落在 `member_node_ids` 上的"路口内道路"。**该集合未被持久化到 `step3_status.json`**，仅作为函数返回值在 Step4 内部消费。
- `road_branches`：incident road 第一段聚类后的 arm 列表。**未沿 degree==2 passthrough chain 延伸到下一个语义路口**，因此不构成"到其他 SWSD 语义路口的关联道路"。

真正的"语义路口相关道路全量召回"在 `support_domain_builder.build_step5_support_domain` 第 813–877 行通过 `support_domain_cuts._expanded_related_road_ids` 完成，**层次倒置**：Step5 在做拓扑事实判定，而 Step3 不输出该事实。

已知漏召 / 过召场景（导致渲染层"少画道路"或"越过其它语义路口多画道路"）：

- 场景 A：continuous complex / merge case 中，`current_semantic_node_ids` 只取代表节点 + group_nodes，未消费 Step3 的 `augmented_member_node_ids`，`_expanded_related_road_ids` 在 sibling internal node 处被 degree>2 截断。
- 场景 B：arm 遇到其它 SWSD 语义路口候选（语义节点组 `degree >= 3`）后仍按角度连续穿透，导致召回越界道路；2026-05-04 用户修订口径冻结为：**只有语义节点组 `degree == 2` passthrough chain 可继续穿透，语义节点组 `degree >= 3` 必须立即作为 semantic boundary 停止**。语义节点组按 `mainnodeid` 聚合；无有效 `mainnodeid` 时按节点自身 `id` 成组。
- 场景 C：admission 阶段 group_nodes 收集不全 → seed 漏匹配 → 召回不全。

### 3.2 Step4 缺口

| 项 | 契约要求 | 当前实现 | 缺口 |
|---|---|---|---|
| RCSD 语义路口实体（完整 / partial）的"路口内道路 vs 跨路口连接道路" | §3.4 暗含（语义路口与语义道路压缩口径与 SWSD 同源） | `selected_rcsdroad_ids` 是混合集合 | 未拆分 |
| RCSDRoad-only "两 RCSD 路口间完整道路" | §3.4 第 218 行明文 | 仅 `fallback_rcsdroad_ids` ID 列表 | 端点对、闭合性、对应 RCSD 路口 id 都未输出 |
| RCSDRoad-only 与 SWSD 进出方向一致性 | §3.4 + 推论 | Step5 `_shared_rcsdroad_aligned_swsd_road_ids` 仅在多 unit + 全场景5 触发 | Step4 无 verdict；单 unit 场景 5 完全不跑 |
| `rcsd_consistency_result` 取值域 | §3 状态机应冻结 | 各 binding 模块自行硬编码字符串 | 取值域未在契约中冻结 |
| 单一 `swsd_rcsd_alignment_consistent` verdict | 客户端期望 | 一致性散落在 alignment_type / consistency_level / axis_polarity_inverted / rcsd_consistency_result 四轴 | 无聚合 verdict 字段 |

## 4. Business Rules

### 4.1 SWSD 语义路口实体（Step3 一等输出）

每个 case 在 Step3 阶段必须输出至少一个 `SWSDSemanticJunction` 对象作为 case coordination skeleton 的一部分。复杂路口由多个 unit 组成时，**case 级唯一一个 SWSD 语义路口**，每个 unit 引用同一 junction id 并标注其在该路口内的 arm 视角。

`SWSDSemanticJunction` 必须满足：

- `junction_id`：取自 representative node 的 `mainnodeid`（与 `T04AdmissionResult.mainnodeid` 对齐）。
- `member_node_ids`：合并 `topology_skeleton.branch_result.member_node_ids` 与 `augmented_member_node_ids`。该集合是判定"路口内"的唯一边界。
- `intra_junction_road_ids`：两端都落在 `member_node_ids` 上的所有 SWSD road id（即原 `internal_road_ids`，但持久化）。
- `semantic_arms`：3 条及以上的 `SWSDSemanticArm`；少于 3 条时该 case 应在 Step3 stability 中标记 `unstable_reasons += "swsd_junction_below_semantic_threshold"` 并允许 case 继续走（不阻断 admission 已通过的候选）。

每个 `SWSDSemanticArm` 必须满足：

- `arm_id`：稳定字符串（建议 `arm_<index>` 与 Step3 现有 `branch_id` 一一映射）。
- `direction`：`in / out / bi`，沿用 `_road_flow_flags_for_group` 已有逻辑。
- `angle_deg`：与 Step3 现有 `BranchEvidence.angle_deg` 对齐。
- `inter_junction_connector_road_ids`：该 arm 沿 *合法 continuation* 从 `member_node_ids` 边界向外延伸到**第一个**满足任一条件的节点为止，全部 SWSD road id 的有序链。这里的 `degree` 必须按语义节点组进出道路数统计，`mainnodeid` 非 `0` / 非空时按 `mainnodeid` 聚合，`mainnodeid = 0` / 空值时按节点自身 `id` 成组，组内道路不计入度数：
  1. 语义节点组为 `degree >= 3` 且不属于 `member_node_ids`（命中下一个语义路口候选）；
  2. 语义节点组 `degree == 1`（道路死端）；
  3. 节点退出 case patch（local context 边界）。
- `terminal_node_id`：该 arm chain 的末端节点 id。
- `terminal_kind`：`semantic_neighbor / dead_end / patch_boundary` 三选一。
- `neighbor_semantic_junction_id`：当 `terminal_kind = semantic_neighbor` 时，若该末端节点的 `mainnodeid` 可解析，记录；否则为 `null`。

延伸规则（"合法 continuation"定义）：

- 默认：沿语义节点组 degree==2 passthrough chain 延伸（与现 `_expanded_related_road_ids` 行为一致）。
- 禁止 degree>=3 穿透：当遇到语义节点组 `degree >= 3` 且不属于当前 `member_node_ids` 的节点时，必须立即停止并写 `terminal_kind = semantic_neighbor`。即使角度连续，也不得把该节点之后的 SWSDRoad 纳入当前 case 的 `inter_junction_connector_road_ids`。
- `continuation_through_micro_junction` 保留为兼容审计字段；在本冻结口径下，Step3 不再把 `degree >= 3` 节点标为可穿透 micro-junction。

### 4.2 SWSD 语义路口在 unit 级 skeleton 中的视角

`event_units/<id>/step3_status.json` 增加：

- `swsd_junction_ref`：本 unit 引用的 case-level junction id。
- `unit_owned_arm_ids`：本 unit 视角下从该 SWSD 语义路口"占有"的 arm（=当前 unit 的 `event_branch_ids` 与 `boundary_branch_ids` 对应到 `swsd_semantic_arms` 的 id 集合）。
- `sibling_unit_arm_ids`：本 unit 不占有但属于 sibling unit 的 arm。

### 4.3 RCSD 语义路口实体（Step4 一等输出）

当 `rcsd_alignment_type ∈ {rcsd_semantic_junction, rcsd_junction_partial_alignment}` 时，Step4 必须输出 `RCSDSemanticJunction` 对象，结构与 SWSD 对称：

- `junction_id`：取自 `aggregated_rcsd_unit_id` 或 `required_rcsd_node` 派生的稳定 id。
- `member_rcsdnode_ids`：当前 RCSD 语义路口候选组节点（基于 RCSDNode.mainnodeid 分组）。
- `intra_junction_rcsdroad_ids`：两端都落在 `member_rcsdnode_ids` 上的 RCSDRoad id。
- `semantic_arms`：每个 RCSDSemanticArm 含 `arm_id / direction / angle_deg / inter_junction_connector_rcsdroad_ids / terminal_rcsdnode_id / terminal_kind / neighbor_rcsd_junction_id`。
- `paired_swsd_arm_mapping`：与当前 SWSD 语义路口 arm 的对位映射 `{rcsd_arm_id: swsd_arm_id | null}`；partial alignment 时部分位为 `null`。
- `alignment_partial_missing_swsd_arm_ids`：partial alignment 下相对 SWSD 缺失的 arm id 集合（partial 的核心证据）。

### 4.4 RCSDRoad-only 完整道路链实体（Step4 一等输出）

当 `rcsd_alignment_type = rcsdroad_only_alignment` 时，Step4 必须输出 `RCSDRoadOnlyChain` 对象：

- `chain_road_ids`：按拓扑序排列的 RCSDRoad id 序列；序列中每相邻两条 road 在 RCSDNode 上首尾相接。
- `chain_endpoint_node_ids`：`(start_rcsdnode_id, end_rcsdnode_id)`，序列两端 RCSDNode。
- `chain_endpoint_kinds`：`(start_kind, end_kind)`，每端取值：`rcsd_semantic_junction_member / rcsd_dead_end / rcsd_patch_boundary`。
- `closure_status`：`closed_between_two_rcsd_junctions / open_dead_end / open_patch_boundary / unresolved`。仅当**两端均为** `rcsd_semantic_junction_member` 时取 `closed_between_two_rcsd_junctions`；该状态是契约 §3.4 第 218 行所述"RCSD 语义路口间道路"的代码侧明确化。
- `swsd_direction_consistent`：`bool`，对该 chain 的整体走向与当前 SWSD 语义路口"进入 arm 方向"或"退出 arm 方向"做一致性比对（基于 4.1 的 SWSD `semantic_arms[].angle_deg` 与 chain 起末两段 tangent 角度）。一致性容差沿用 `BRANCH_MATCH_TOLERANCE_DEG = 30°`。
- `swsd_direction_evidence`：审计字典，至少给出 `chain_head_angle_deg / chain_tail_angle_deg / matched_swsd_arm_id / angle_gap_deg / consistency_decision_reason`。
- `selection_uniqueness_proof`：当存在多个候选 chain 时，唯一选中证据（与 `rcsd_alignment_type = ambiguous_rcsd_alignment` 阻断逻辑共用）。

### 4.5 单一 SWSD/RCSD 一致性 verdict

新增 `T04EventUnitResult.swsd_rcsd_alignment_consistent: ConsistencyVerdict`，类型为枚举：

- `strong_consistent`：`rcsd_alignment_type = rcsd_semantic_junction` 且 `positive_rcsd_consistency_level = A` 且 `axis_polarity_inverted = false`。
- `partial_consistent`：`rcsd_alignment_type = rcsd_junction_partial_alignment` 或 (`rcsd_semantic_junction` 且 `consistency_level = B`)，且 `axis_polarity_inverted = false`。
- `direction_only_consistent`：`rcsd_alignment_type = rcsdroad_only_alignment` 且 `swsd_direction_consistent = true`。
- `not_applicable`：`rcsd_alignment_type = no_rcsd_alignment`。
- `inconsistent`：所有不属于以上的情况，包括 `axis_polarity_inverted = true` 单独成立时。
- `blocked`：`rcsd_alignment_type = ambiguous_rcsd_alignment`。

该 verdict 是从既有字段聚合的派生字段，**不替代** `rcsd_alignment_type / consistency_level / axis_polarity_inverted / rcsd_consistency_result`，仅作为客户端唯一查询入口。

### 4.6 `rcsd_consistency_result` 取值域冻结

将代码侧已有的字符串收口到 `INTERFACE_CONTRACT.md §3.x` 状态机，初始值域至少包含：

- `positive_rcsd_strong_consistent`
- `positive_rcsd_partial_consistent`
- `positive_rcsd_direction_only_consistent`
- `positive_rcsd_inconsistent`
- `road_surface_fork_without_bound_target_rcsd`
- `missing_positive_rcsd`
- `none`

任何代码端写入不在该值域内的字符串视为治理违规。

### 4.7 Step5 / 渲染层职责回归

- `support_domain_builder.build_step5_support_domain` 删除 `seed_swsd_road_ids` / `_expanded_related_road_ids` 调用与 `related_swsd_road_ids / unrelated_swsd_road_ids` 的本地计算；改为消费 Step3 输出的 `SWSDSemanticJunction.intra_junction_road_ids ∪ Σ semantic_arms[].inter_junction_connector_road_ids` 作为权威 `related_swsd_road_ids`。
- `unrelated_swsd_road_ids = case_bundle.roads.id 集合 − related_swsd_road_ids`，逻辑保留但移到 `support_domain_common` 下的纯函数。
- `review_render._related_swsd_road_ids` 改为读 `case_result.base_context.topology_skeleton.swsd_semantic_junction`。
- 渲染层不得再依赖 `step5_result` 取 SWSD 路口道路集合。

## 5. Acceptance Criteria

### 5.1 Step3 实体化

- `step3_status.json` 顶层包含 `swsd_semantic_junction` 字段，结构符合 §4.1。
- `event_units/<id>/step3_status.json` 包含 §4.2 的三个新字段。
- `step3_audit.json` 给出 `swsd_semantic_junction.audit`：每条 arm 的 `inter_junction_connector_road_ids` 来源必须可追溯到当前路口 direct road 或语义节点组 degree==2 passthrough chain；不得包含越过语义节点组 degree>=3 semantic boundary 后的 road。
- 对 Anchor_2 39-case 整套，每个 case 必有 `swsd_semantic_junction.junction_id != ""`；arm 数 < 3 的 case 必有 `unstable_reasons` 显式说明。
- 验证：`intra_junction_road_ids ∩ Σ inter_junction_connector_road_ids = ∅`。
- 验证：`Σ inter_junction_connector_road_ids` 在每条 arm 内顺序连贯（首尾节点配对）。

### 5.2 Step4 RCSD 实体化

- `step4_candidates.json` / `step4_event_interpretation.json` 包含 `rcsd_semantic_junction` 实体（当 alignment_type ∈ junction-level 时）。
- 包含 `rcsdroad_only_chain` 实体（当 alignment_type = `rcsdroad_only_alignment` 时）。
- 每个 unit 输出 `swsd_rcsd_alignment_consistent` 枚举值，与 alignment_type / consistency_level / axis_polarity_inverted 推导一致。
- `rcsd_consistency_result` 全量取自冻结值域；任何越界字符串触发测试失败。

### 5.3 一致性与回归

- Anchor_2 official 39-case baseline：`accepted = 35 / rejected = 4` 不变；`857993 / 607602562 / 760598 / 760936 = fail4`，`699870 = yes` 不变。
- Anchor_2 23-case / 30-case baseline 只作为 official 39-case manifest 的历史子集投影：23-case 投影 `accepted = 20 / rejected = 3`，30-case 投影 `accepted = 26 / rejected = 4`。**本轮不再与历史 PNG visual fingerprint 比对**，也不再把 23/30 子集作为独立 batch gate。Phase 6 重新跑 Anchor_2 39-case 后，新生成的 `final_review.png` 直接作为本轮目视审计图基线，由人工抽样确认；不强求与 2026-05-01 的 23-case fingerprint 一致。
- **命名回归 case**（用户人工核对发现 SWSD 路口某些道路在 `final_review.png` 中渲染缺失）：
  - `724067`
  - `758784`
  - `760213`
  - **不限于以上三个 case**：Codex 在 Phase 6 必须对全部 39-case 做"`swsd_semantic_junction` 派生道路集合 vs `final_review.png` 实际可见 SWSD 路网图层"对照核查；任何 case 上发现遗漏，都视为本轮回归任务的失败项，需要补漏后才能进入 Phase 7。
- 对每个命名回归 case 与抽查发现的额外 case，新实现下 `swsd_semantic_junction.intra_junction_road_ids ∪ Σ inter_junction_connector_road_ids` 必须**全部**出现在 `final_review.png` 的 SWSD 路网图层中；视觉缺失的道路必须在 Step3 输出实体中也存在（即 Phase 6 的核查范围是 Step3 实体集合本身的全量召回，不是渲染层 cosmetics）。
- `support_domain_builder` 不再保留 `_expanded_related_road_ids` 调用（迁移到 `topology` 层）。
- 39-case full baseline 下 Step3 输出 `swsd_semantic_junction` 的 case 数 = 39。

### 5.4 文档与契约

- `INTERFACE_CONTRACT.md` 新增 §2.4 *SWSD 语义路口实体*、§2.5 *RCSD 语义路口实体 / RCSDRoad-only chain* 与 §3.x *swsd_rcsd_alignment_consistent / rcsd_consistency_result 取值域* 两节。
- `architecture/04-solution-strategy.md` §4 Step3 段落补充 `SWSDSemanticJunction` 的输出职责；§5 Step4 段落补充 `RCSDSemanticJunction / RCSDRoadOnlyChain / swsd_rcsd_alignment_consistent` 的输出职责；§6 Step5 段落明确"不再做 SWSD 相关道路召回判定"。
- `architecture/05-building-block-view.md` `topology` 与 `support_domain_builder` 的职责描述同步更新。
- `architecture/12-glossary.md` 增补 `intra_junction_road / inter_junction_connector_road / rcsdroad_only_chain / swsd_rcsd_alignment_consistent` 词条。
- `INTERFACE_CONTRACT.md §4.4` Step4 review index 字段族增加 `swsd_rcsd_alignment_consistent`。

### 5.5 性能与文件体量

- 新增字段不得让 `step4_review_index.csv` 列数超过 100；如超则同轮新增 `step4_alignment_index.csv` 二级索引并登记到契约 §4.1。
- 任何被改动的 `.py` 文件必须前置自检字节数；接近 100 KB 时执行拆分（参考 `polygon_assembly` 历史拆分模板）。
- 39-case `summary.json.performance.threshold_seconds_total = 240.0` 不放宽；本轮改造允许的瞬时增长 ≤ 5%。

## 6. Non-Goals

- 不新增 repo 官方 CLI 或改变 `entrypoint-registry.md`。
- 不改变 `divmerge_virtual_anchor_surface*` 主产物命名。
- 不引入"SWSD 语义路口候选消歧"逻辑（admission/group 已确定的 mainnodeid 即为唯一 case-level 路口；本轮只做实体化）。
- 不改 RCSD 语义路口的判定标准（沿用 `rcsd_alignment_type` 已冻结的五值域）。
- 不把 `_pick_chain_continuation_candidate` 用作 SWSD/RCSD 语义路口 road 召回的 degree>=3 穿透依据；该函数若被其它已授权场景使用，保持其既有阈值，不在本轮调整。
- 不把 `857993 = rejected` 改成 accepted；不为提高 accepted count 弱化 Step7 门禁。
- 不引入新的 review state；保持 `STEP4_OK / STEP4_REVIEW / STEP4_FAIL` 三态。
- 不改 `accepted / rejected` 二态最终结果机。

## 7. Frozen Decisions（已冻结，2026-05-04 用户授权）

以下 5 条决策已经过用户最终确认，**implement 阶段必须严格遵守**。任何偏离都视为治理违规，触发硬停机回报。

### D1 — arm 角度直接复用 Step3 现有值

`SWSDSemanticArm.angle_deg` **直接复用** `BranchEvidence.angle_deg`，不重算、不微调。

- 业务理由：与 Step3 现行 branch clustering（`_cluster_branch_candidates`，30° 容差）保持同一份方向真相，避免下游出现"老视图与新视图角度不一致"的双口径风险。
- 实现：`_build_swsd_semantic_junction` 直接读取 `BranchEvidence.angle_deg` 写入 `SWSDSemanticArm.angle_deg`，禁止加任何二次计算。
- 守门：单元测试断言两值绝对相等。

### D2 — 合并节点集合仅作用于 case-level 路口本体

`member_node_ids = branch_result.member_node_ids ∪ augmented_member_node_ids` 这一并集**仅用于** `SWSDSemanticJunction.member_node_ids` 与 `SWSDSemanticJunction.intra_junction_road_ids` 的判定。

- **不回写**到 `T04UnitEnvelope.unit_population_node_ids / event_branch_ids / boundary_branch_ids / preferred_axis_branch_id` 等 unit-level 边界字段。
- Slice 0 强制 dry-run 守门：用 `505078921` 与 `17943587` 两个冻结 case 在改造前后比对 `unit_envelope.to_status_doc()` 的输出，必须**逐字段完全相同**；若有任何差异立即停机回报，不得带病进入 Slice 1。
- 业务理由：复杂路口的 unit 切分逻辑已在 official 39-case baseline 中冻结；本轮治理只新增 case-level 实体，不动 unit 切分。

### D3 — arm 链走出 patch 边界时不外推

`inter_junction_connector_road_ids` 沿 chain 延伸到 patch 边界时，**只持久化 patch 内已识别的道路 ID**；超出 patch 的部分一律不估、不外推、不补全。

- 终止标识：`SWSDSemanticArm.terminal_kind = patch_boundary`、`SWSDSemanticArm.terminal_node_id = chain 在 patch 内的最末端节点 id`、`SWSDSemanticArm.neighbor_semantic_junction_id = null`。
- 业务理由：扩 patch 属于 Step2 数据加载层职责，不在本轮 SpecKit 范围；据局部样本反推 patch 外结构会触发 `AGENTS.md §1.5` 硬停机。
- 下游消费者契约：看到 `patch_boundary` 即理解为"该 arm 在当前数据条件下的不完整链"，不得当作"真实死端"。

### D4 — `closed_between_two_rcsd_junctions` 接受 0 样本

`RCSDRoadOnlyChain.closure_status = closed_between_two_rcsd_junctions` 在 Anchor_2 39-case 上**允许 0 命中**。

- Phase 6 跑完后，必须把每种 `closure_status` 的实际分布数字落到 `notes/run-log.md`；具体数字（包括"0 命中"）作为审计事实记录。
- 若 39-case 真出现 0 命中，spec.md §7 与 `INTERFACE_CONTRACT.md §2.5` 显式声明"当前 Anchor_2 数据集无该状态实证 case，作为契约预留状态保留"。
- 不强行扩数据集、不人工构造样本以凑命中。
- 业务理由：闭合状态是契约语义保留位；常态命中分布由真实业务数据决定，不应由实现端造数据反推。

### D5 — 方向一致性 30° 容差固定，不做敏感性分析

`swsd_rcsd_alignment_consistent = direction_only_consistent` 的判定容差**本轮固定为 30°**，与仓库现有 `BRANCH_MATCH_TOLERANCE_DEG / RCSD 对齐 30°` 保持同源。

- 不在本轮做 25° / 35° 敏感性扫描。
- Phase 6 必须把每个 RCSDRoad-only case 的实际 `angle_gap_deg` 数字（chain head/tail tangent 与最近 SWSD arm `angle_deg` 的差）写入 `step4_event_interpretation.json` 的 `rcsdroad_only_chain.swsd_direction_evidence`。
- 若后续审计发现 case 密集落在 25–35° 边界区间，由独立 SpecKit 任务调整阈值；本轮不做。
- 业务理由：保持容差与仓库其他角度判定同步；调整阈值需要在更大样本范围（≥ 39-case 之外）做评估。
