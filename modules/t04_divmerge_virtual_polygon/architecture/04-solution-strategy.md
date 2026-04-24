# 04 Solution Strategy

## 总体策略

- 采用 `case_loader -> admission -> local_context -> topology -> event_interpretation -> support_domain -> polygon_assembly -> final_publish -> review_render -> outputs -> batch_runner` 主链。
- Step2/3 参考 T02 Stage4 的既有语义，但正式运行时内核在 T04 私有实现中落地。
- Step4 参考 T02 的单事件解释思路并增加 event-unit 物化与 T03 风格 review 输出，但正式执行不得回调 T02 模块代码。
- Step5/6/7 参考 T03 的产物风格、批量审计与汇总组织方式，但正式执行不得直接 import / 调用 / 硬拷贝 T03 模块代码。

## 关键策略

### 1. 输入组织

- 采用 T03 风格 case-package loader。
- 在 T04 case-package 中把 `divstripzone.gpkg` 提升为正式输入文件。

### 2. Step1-3

- Step1 使用显式 admission contract。
- Step2 保留 patch-scoped recall window 与 SWSD negative context。
- Step3 保留 member/passthrough/branch/main pair/chain augmentation 语义，但正式拆成两层：
  - `case coordination skeleton`
  - `unit-level executable skeleton`
- `case coordination skeleton` 只负责：
  - member population
  - continuous chain coordination
  - event-unit population
  - case overview / case-level audit
- `unit-level executable skeleton` 才是 Step4 的可执行输入；complex `1 node = 1 unit` 时，Step4 仍只消费当前 representative node 为锚点的 unit-local skeleton，但该 skeleton 的 branch 语义必须保持拓扑语义连续，不能因为穿过 same-case sibling internal node 就被机械切断。
- `augmented_member_node_ids` 只保留为 case 外 `chain_context_hint`，不再直接冒充 Step4 的可执行 population；same-case sibling internal node 的 branch continuation 必须通过 unit-local executable branches 显式表达，不能混进 `context_augmented_node_ids`。

### 3. Step4

- 先显式拆分 event unit，再对每个 event unit 做事实解释。
- simple 默认单单元。
- multi-diverge / multi-merge 使用角度相邻的有序 branch pair `(L, R)`。
- complex 使用当前 case 的 member node 粒度；chain augmentation 只补上下文，不直接扩 event-unit population。
- complex 子节点在 Step4 解释阶段继承 complex 128 上下文提示，不因为聚合后 `kind_2=0` 被静默丢弃。
- Step4 先在 T04 层显式构造 `pair-local` 搜索空间，而不是在大走廊里无边界找证据：
  - `unit-local branch pair region`
  - `unit-local structure face`
- 候选空间正式规则以 `INTERFACE_CONTRACT.md §3.4 / §3.5` 为主；本节只解释为什么 T04 仍保留 `branch-first + slice-fill`，而不把完整规则在此平行重写。
- `unit-local branch pair region` 通过当前 unit 的有序边界 pair `(L, R)`、throat / node 起始切片和 pair-middle 纵向扫描切出；当前策略上冻结为：
  - continuation 硬上限 `200m`
  - 先定合法方向，再单向延伸
  - stop reason / separation metrics 必须显式审计
  - `road intrusion between branches` 必须用 geometry gate，而不是只靠角度近似
- complex / multi 下真正传播的不是单条 road，而是 `(L, R, middle-region)`。到每个 sibling node 时，T04 必须尝试找到新的 `(L', R')`，并满足：
  - `L'` 继承 `L` 的排布侧
  - `R'` 继承 `R` 的排布侧
  - `L' / R'` 之间仍构成当前 unit 的 middle-region
  - `L' / R'` 之间不能夹入其他 road
- 若 sibling node 上 pair 无法唯一传播、`pair-middle` 关系失效、或 `L' / R'` 之间夹入其他 road，则当前 unit 就地停止，不得再扩大候选空间。
- sibling node 上 arm 的选择顺序冻结为：
  - 先看 `external associated road` 是否一致
  - 再看 `L' / R'` 之间是否夹入其他 road
  - 再看左右顺序是否保持不变
  - 最后才允许用最小转角做 tie-breaker
- `external associated road` 不是“遇到的任意第一个外部 exit”，而是沿 unit 边界 branch 的合法单向延续外推后、与当前 pair 传播语义一致的首个非 complex 内部 road。它当前只用于 arm 选择一致性和停止条件审计，不再驱动候选空间反向追溯。只有当前 unit 在 complex 内构成 `closed interval` 时，才允许不继续接近外部关联 road。
- `unit-local structure face` 由道路结构面在该 pair-local region 内定义主事实空间；导流带只在这个空间里做分界、镂空和 throat / middle 强化。该结构面只能由当前 `(L, R)` 及其合法 continuation 所围成，不得吸纳非分支道路面。
- Step4 在进入 T04 私有解释内核前，先构造 `unit envelope`：
  - `unit_population_node_ids`
  - `context_augmented_node_ids`
  - `event_branch_ids`
  - `boundary_branch_ids`
  - `preferred_axis_branch_id`
- 在 `pair-local region` 内，T04 先生成 `local candidate unit` 候选池，而不是把整块导流带对象直接拿去优选：
  - `pair_local_divstrip`
  - `pair_local_structure_mode`
- `selected_candidate_region` 只保留为 pair-local 容器输出，不再等同于主证据。
- 正式主输出改为 `selected_evidence`：
  - 只允许来自 `local candidate unit`
  - 当前 unit 若无合法主证据，则输出 `selected_evidence_state = none`
- `structure:middle:01` 不再作为正式主证据候选；若实现内部仍保留类似中间带几何，只能作为容器 / 审计辅助。
- 每个 `local candidate unit` 都显式保留：
  - `upper_evidence_object_id`
  - `local_region_id`
  - `ownership_signature`
  - `point_signature`
- complex `sub-unit` 在 Step4 内必须把 scope 锚定在当前 representative node 的 throat 邻域与当前 unit 的 executable event branches 上；若同一 `pair-middle` 语义在 same-case sibling internal node 之后仍连续、开放且未引入新的竞争 pair，则允许 branch continuation 穿过该 internal node，但不得因此把当前 unit 退回整条 complex 走廊。
- 若当前 unit-local scope 无法形成有效 throat pair 或 branch-middle gate，系统不得静默回退成整条 complex 走廊；必须显式记录 `degraded_scope_reason / degraded_scope_severity / degraded_scope_fallback_used`，其中 severe degraded 允许升 `STEP4_FAIL`。
- 候选先按三层优先级分层，再在层内优选：
  - Layer 1：主体稳定落在 `throat core + pair-middle`
  - Layer 2：主体稳定落在 `pair-middle`
  - Layer 3：仅弱进入当前 unit 候选空间，只作 reverse / mode switch / 审计参考
- T04 当前不把三层混成一个总分；正式策略是“先层级，再层内排序”。
- `axis_position_m = 0` 或 reference 贴 node 的候选，统一记为 `node_fallback_only`；这类候选只能作为审计 / 兜底参考，不得直接成为主排序第一名。无导流带时的道路结构面分叉候选 `candidate_scope = road_surface_fork` 是唯一例外：reference point 应落在分支点上，并允许成为正式主证据。
- forward / reverse / structure-mode 都共享同一个 `pair-local region`：
  - forward：当前 unit 的自然事实形成方向
  - reverse：同一空间内的反向重试，不是独立证据体系
  - structure-mode：同一空间内的道路结构面主导定位，不是跨区兜底
- reverse 只作用于候选空间内的证据查找，不得再作为候选空间边界延伸或反向补全机制。
- 同一 case 的 sub-unit / event-unit 先各自生成候选池和初选，再做单 Case 内重选；若多个 unit 初选撞到一起，优先保留更高层/更稳的候选，其它 unit 在自己的候选池内改选，而不是直接 fail。
- 若当前初选候选被 `branch-middle / throat` gate 或 `node_fallback_only` 拒绝，必须继续在当前候选池内重选；若重选后仍无合法候选，则显式输出 `selected_evidence_state = none`。
- 当前单 Case Step4 输出只视为“初选结果”；跨 Case 共用证据冲突不在单 Case 内硬解，等全量 Step4 结束后再做二次处理。
- Step4 final tuning 正式增加 second-pass resolver：
  - 先做 same-case evidence conflict inventory / gate
  - 再做 same-case RCSD claim reconcile
  - 最后做 cross-case inventory / cleanup
  - 非冲突单元冻结
  - RCSD 冲突默认只能改 claim，不能单独推翻主证据
- 正向 RCSD 在 Step4 内改成 T04 自己的正式选择器，而不是继续让旧 T02 bridge 主导正式输出：
  - 先做 `pair-local raw observation`
  - 再构造 `rcsd_candidate_scope`
  - 再构造 `local RCSD unit`
  - 再构造 `aggregated_rcsd_unit`
  - 再做 `polarity normalization`
  - 再做 `SWSD ↔ RCSD role mapping`
  - 先判 `positive_rcsd_present`
  - 最后得出 `A/B/C`、`primary_main_rc_node` 与 `required_rcsd_node`
- `pair-local` 为空时直接 `C / no_support`；不回退到 scoped / case 级 RCSD 世界补主支持对象。
- `local RCSD unit` 正式分为：
  - `node-centric local_rcsd_unit`
  - `road-only local_rcsd_unit`
- `aggregated_rcsd_unit` 是默认正式判级单元；它由共享 road / node / forward 锚点的相邻 matched local units 聚合而成。
- single-unit 只作为 fallback，不再用“单个 local unit 的严格等式”直接替代 aggregated-first 判级。
- `road-only local_rcsd_unit` 最高只能到 `B`
- Step4 正向 RCSD 必须显式分层：
  - 作用域层：`pair-local raw observation / rcsd_candidate_scope / local_rcsd_unit / aggregated_rcsd_unit`
  - 事实层：`positive_rcsd_present`
  - 支持强度层：`A/B/C`
- `axis polarity inverted` 默认在 `aggregated_rcsd_unit` 级别识别；single-unit 仅作 fallback。
- T04 当前显式输出：
  - `selected_rcsdroad_ids`
  - `selected_rcsdnode_ids`
  - `primary_main_rc_node`
  - `positive_rcsd_present`
  - `positive_rcsd_support_level`
  - `positive_rcsd_consistency_level`
  - `required_rcsd_node`
  - `aggregated_rcsd_unit_id`
  - `aggregated_rcsd_unit_ids`
  - `axis_polarity_inverted`
  - `required_rcsd_node_source`
- 一致性在 Step4 内冻结为：
  - `A / primary_support`
  - `B / secondary_support`
  - `C / no_support`
- `A/B/C` 必须由 normalized role mapping 产生，不能再用 `angle_match` 或 nearby fallback 包装。
- `positive_rcsd_present = true` 只表示事实层成立，不等于 `A`，也不自动保底 `B`。
- 事实层成立后，仍必须在 `aggregated_rcsd_unit` 上完成 polarity normalization 与 normalized role mapping；若归一化后仍存在结构性硬冲突，最终允许落到 `C`。
- `C` 同时覆盖：
  - 事实层缺失
  - 事实层虽成立，但归一化后仍存在结构性硬冲突
- side-label mismatch 不得单独把事实存在样本压到 `C`。
- `required_rcsd_node` 必须从已匹配的 local / aggregated RCSD unit 中独立输出，不再依赖 `A`；其 downstream cover / publish 逻辑由 Step5-7 消费，但不在此处重复改写。
- `branch-middle / throat gate` 的 boundary branches 必须来自当前 unit 的 `boundary_branch_ids`；complex / multi 场景下不再允许静默退回 case-level main pair 充当 unit-local throat。
- merge 单元的 `boundary_branch_ids` 必须对应当前 unit 的 entering branches；diverge 单元的 `boundary_branch_ids` 必须对应当前 unit 的 exiting branches；`preferred_axis_branch_id` 只允许来自当前 unit 的唯一 opposite-direction trunk。
- `divstrip_ref` 命中时，Step4 正式拆分：
  - `fact_reference_point`
  - `review_materialized_point`
- `review_materialized_point` 优先物化到当前选中证据的 `tip / throat` 邻域，不再以 `body_center` 作为正式主策略。
- 现有 `split_guided` / `core_mid` / `tip_projection` 候选保留作为后续 fallback，依次尝试；任何一个能通过 `branch-middle / throat` gate 即被采纳。
- review 中表达的 selected divstrip 不直接等于原始 component 全面，而是收敛为围绕当前事实点的 `localized_evidence_core_geometry`。
- Step4 事实依据几何正式拆成三层：
  - `selected_component_union_geometry`
  - `localized_evidence_core_geometry`
  - `coarse_anchor_zone_geometry`
- Step4 在接受 forward / reverse 候选前，先做 `branch-middle / throat` gate；不与分支中间区域相关的候选直接判无效，再决定是否进入 reverse tip。
- 连续链 case 若原始 anchor 退化为 seed 占位方框，review 输出把 coarse anchor 重新 materialize 到当前事实证据附近，避免可视审计继续被 seed 占位图误导。
- `fact_reference_point` 不得落到 `DriveZone` 外；越界候选只允许作为中间诊断。`review_materialized_point` 只允许在当前道路面内表达最终结果。
- `reverse tip` 只保留两类正式触发：
  - `forward missing`
  - `forward rejected by local throat / same-axis prior conflict`
- `drivezone_split_window_after_reverse_probe` 只保留为 conservative fallback，不再算作独立 reverse-tip 成功语义。
- ownership guard 主判断以语义冲突为先：
  - `selected_component_ids` 仅保留为 debug label，不再承担跨 unit 稳定身份。
  - `selected_component_union_geometry` 负责物理 component ownership。
  - 同一 `event_axis_branch_id` 且 `|Δevent_chosen_s_m| <= 5m`：记 `shared_event_reference_with` 并升 `STEP4_FAIL`。
  - `localized_evidence_core_geometry` 负责 core-segment ownership；`coarse_anchor_zone_geometry` 只用于审计，不再代理 component ownership。
- localized core segment 显著重叠（面积阈值 + 比例阈值）：记 `shared_event_core_segment_with` 并升 `STEP4_FAIL`；但当两 unit 处于同一轴且 `|Δs| > 5m` 时，认定为 REQUIREMENT §9.5 允许的「同一导流带不同位置」，不再触发 segment 重叠 fail。
- Step4 输出除主结果外，还要显式保留备选候选和 pair-local 调试信息，供后续全量二次处理与 case-by-case 审计使用。
- second-pass 结束后，输出层必须把 pre/post candidate / claim 和 conflict component 审计同步到：
  - `step4_event_interpretation.json`
  - `step4_candidates.json`
  - `step4_evidence_audit.json`
  - `step4_review_index.csv`
  - `second_pass_conflict_resolution.json`

### 4. Review 输出

- case overview 表达全局语境。
- event-unit PNG 表达当前事件单元的局部解释。
- 顶层 `step3_status.json` 只表达 `case coordination skeleton`。
- `event_units/<event_unit_id>/step3_status.json` 表达当前 unit 的 `unit-level executable skeleton`。
- `event_units/<event_unit_id>/step4_candidates.json` 表达 pair-local region、selected candidate 与 alternative candidates。
- flat mirror 用于人工平铺质检。

### 5. Step5-7

- `support_domain`
  - 以 Step4 主证据、`fact_reference_point`、正向 RCSD 结果与局部道路面构建 Unit / Case 两级约束层
  - 只定义 `must_cover / allowed_growth / forbidden / terminal_cut`，不生成最终 polygon
  - 对 `rcsd_anchored_reverse` 且同时具备 `Reference Point + required_rcsd_node` 的路口面，必须额外构建 `junction_full_road_fill_domain`：以 Reference Point 与 RCSDNode 定义的语义主轴为中心，纵向只保留两端各 `20m` terminal window，横向单侧不超过 `20m`，再与 DriveZone 道路面和 forbidden masks 共同约束；`terminal_support_corridor_geometry` 在此场景只作为支撑与审计对象，不应成为最终铺面的主范围。
- `polygon_assembly`
  - 在 Step5 约束内以 `raster-first` 方式组装单一连通面
  - 不得突破 `allowed / forbidden / terminal_cut`
- `final_publish`
  - 基于 Step6 结果做最终验收、二态裁决与发布
  - 输出 `divmerge_virtual_anchor_surface` 主层、rejected 层、summary 层与 audit 层

## 当前入口策略

- 不新增 repo 官方 CLI。
- `Step1-4` 继续通过程序内 batch runner 与 pytest/smoke 交付既有能力。
- `Step5-7` 后续实现仍维持模块私有 runner / batch orchestration，不提升为 repo 官方 CLI。
