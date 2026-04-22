# T04 - INTERFACE_CONTRACT

## 定位

- 本文件是 `t04_divmerge_virtual_polygon` 的稳定契约面。
- 当前正式范围为：T04 `Step1-4` doc-first formalization 与模块化实现。
- `README.md` 只承担操作者入口职责；长期设计以 `architecture/*` 为准。

## 1. 目标与范围

- 模块 ID：`t04_divmerge_virtual_polygon`
- 目标：
  - 将线程级 T04 Step1-4 需求落入 repo source-of-truth
  - 提供 case-package 输入下可运行的 Step1-4 pipeline
  - 提供 Step4 review PNG / flat mirror / index / summary
- 当前正式范围：
  - case-package loader / preflight
  - Step1 candidate admission
  - Step2 local context
  - Step3 topology skeleton
  - Step4 fact event interpretation
  - case-level / batch-level review outputs
- 明确不在当前正式范围：
  - Step5 geometric support domain
  - Step6 polygon assembly
  - Step7 final acceptance / publishing
  - repo 官方 CLI / shell 入口扩展

## 2. Inputs

### 2.1 必选输入

- case-package 根目录
- 每个 case 当前至少包含：
  - `manifest.json`
  - `size_report.json`
  - `drivezone.gpkg`
  - `divstripzone.gpkg`
  - `nodes.gpkg`
  - `roads.gpkg`
  - `rcsdroad.gpkg`
  - `rcsdnode.gpkg`

### 2.2 输入前提

- 所有空间处理统一到 `EPSG:3857`
- `nodes` 当前至少需具备：
  - `id`
  - `mainnodeid`
  - `has_evd`
  - `is_anchor`
  - `kind` 或 `kind_2`
  - `grade_2`
- `roads / rcsdroad` 当前至少需具备：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
- `rcsdnode` 当前至少需具备：
  - `id`
  - `mainnodeid`

## 3. Stable Business Semantics

### 3.1 Step1 Candidate Admission

- Step1 是准入 gate，不是正确性 gate。
- 当前接受：
  - `kind/kind_2 = 8`
  - `kind/kind_2 = 16`
  - 连续分歧 / 合流聚合语义下的 `kind/kind_2 = 128`
- 准入前提：
  - `has_evd = yes`
  - `is_anchor = no`
- `RCSD` 缺失不影响准入。
- `mainnodeid_out_of_scope` 只表示不属于当前 T04 范围，不得承接后续解释失败。

### 3.2 Step2 Local Context

- seed 只来自当前 case 的 SWSD 语义路口与其关联 road 方向。
- PatchID 用于定位当前 `DriveZone / DivStrip` 局部世界。
- recall window 冻结为：
  - diverge：主干向后 `50m`，分支向前 `200m`
  - merge：主干向前 `50m`，分支向后 `200m`
  - complex：各分支向前/向后 `200m`
- Step2 只定义 SWSD 侧负向上下文；RCSD 负向语义后移。

### 3.3 Step3 Topology Skeleton

- Step3 正式拆成两层：
  - `case coordination skeleton`
  - `unit-level executable skeleton`
- `case coordination skeleton` 必须显式给出：
  - `member_node_ids`
  - `passthrough_node_ids`
  - `branch_ids`
  - `main_branch_ids`
  - `input_branch_ids`
  - `output_branch_ids`
  - `is_in_continuous_chain`
  - `related_mainnodeids`
  - `unstable_reasons`
- `case coordination skeleton` 的职责仅限：
  - 语义 member population
  - continuous chain coordination
  - case overview / case-level audit
  - event-unit population
- `case coordination skeleton` 不得直接作为 complex `Step4` 的 throat / branch-middle / preferred axis 权威输入。
- `unit-level executable skeleton` 是 `Step4` 可执行输入。它至少必须显式给出：
  - `topology_scope`
  - `member_node_ids`
  - `context_augmented_node_ids`
  - `branch_ids`
  - `main_branch_ids`
  - `input_branch_ids`
  - `output_branch_ids`
  - `boundary_branch_ids`
  - `preferred_axis_branch_id`
  - `unstable_reasons`
- `topology_scope` 当前正式允许：
  - `case_coordination`
  - `single_node_event_input`
  - `multi_divmerge_case_input`
- Step3 branch 的正式语义是“拓扑语义连续单元”，不是按原始内部 node 机械切断的 road 聚合。
- complex `1 node = 1 unit` 场景下，`Step4` 只允许消费当前 representative node 为锚点的 `single_node_event_input` skeleton；这里的“single node”表示 unit population 锚定在当前 node，不表示 executable branches 只能包含与该 node 直接接触的 road。
- 对 `continuous complex/merge`，若当前 unit 的同一 `pair-middle` 语义在 same-case sibling internal node 之后仍连续、开放且未引入新的竞争 pair，则 unit-level executable branches 允许跨该 internal node 做 branch continuation；该 continuation 可以进入 `event_branch_ids / boundary_branch_ids / preferred_axis_branch_id`，但不得反向扩大 `unit_population_node_ids`。
- `context_augmented_node_ids` 只保留为 case 外 continuous chain 的 `chain_context_hint` / audit 辅助；same-case sibling internal node 的 branch continuation 不属于这类 `context_augmented_node_ids`，也不得借此静默回流成整条 complex corridor 的 executable branch 边界。
- chain augmentation 边界：
  - 到下一个关联语义路口前停止
  - 单侧不超过 `200m`

### 3.4 Step4 Fact Event Interpretation

- event unit 规则：
  - simple：`1 case = 1 event unit`
  - multi-diverge / multi-merge：按角度相邻的有序 branch pair `(L, R)` = `1 event unit`
  - complex：`1 node = 1 event unit`
  - complex 的 unit population 来自当前 case 的语义 member nodes；`augmented_member_node_ids` 只用于连续链上下文，不自动扩成 event units。
- Step4 unit 的第一层正式定义是“有序相邻 branch pair `(L, R)`”，而不是匿名 branch 集合；其中 `L / R` 表示当前 unit 候选空间的左右边界，必须来自 Step3 的语义连续 branch，而不是原始单条 road segment。
- Step4 当前第一层候选空间不再是 case 级 corridor；正式切换为：
  - `unit-local branch pair region`
  - `unit-local structure face`
- `unit-local branch pair region` 表示：当前 unit 的相邻 branch pair 在 throat / node 起始切片附近形成的局部中间区域；forward / reverse / structure-mode 都只能在这同一空间内活动。
- `unit-local branch pair region` 的纵向延续仍沿用当前 Step4 的扫描长度要求，但一旦确定当前 `(L, R)` 的合法延续方向，候选空间构造阶段只能沿该方向单向延伸，不得再为补齐候选空间做反向追溯。
- local truncation 只约束扫描方向，不得把当前 boundary branch 已确认的合法 continuation membership 再截回 seed road；若 `(L, R)` 已合法跨 same-case sibling internal node 延续，则候选空间必须沿该 continuation 继续。
- 对 `continuous complex/merge`，`unit-local branch pair region` 以当前 representative node 为锚点起算，但允许沿当前 unit 的同一 `pair-middle` 关系跨 same-case sibling internal node 延伸；停止条件不是“碰到内部 node”，而是 `pair-middle` 被封闭、被切断、被新的 pair 关系替代、碰到语义边界或触及 Step2 硬上限。
- `unit-local branch pair region` 的纵向传播单位不是单条 road，而是 `(L, R, middle-region)`；到每个 sibling node 时，都必须尝试找到新的 `(L', R')`，并同时满足：
  - `L'` 继承 `L` 的排布侧
  - `R'` 继承 `R` 的排布侧
  - `L' / R'` 之间仍构成当前 unit 的 `middle-region`
  - `L' / R'` 之间不能夹入其他 road
- 若某个 sibling node 上 pair 无法唯一传播、当前 `pair-middle` 关系失效、或 `L' / R'` 之间夹入其他 road，则当前 unit 必须停止延伸，不得继续扩大候选空间。
- `external associated road` 定义为：从当前 unit 的边界 branch 沿当前 pair 的合法延续方向持续外推，首次走出当前 complex 后连接到的第一条非 complex 内部 road。
- `external associated road` 方向规则：
  - diverge：沿退出延续方向外推
  - merge：沿进入延续方向外推
- `external associated road` 当前用于 sibling arm 选择一致性与停止条件审计；它不再驱动 Step4 候选空间做反向追溯。
- 分歧 unit 的退出边界、合流 unit 的进入边界，只允许沿当前 unit 的合法单向延续去接近自身的 `external associated road`；只有当前 unit 在 complex 内构成 `closed interval` 时，才允许在内部停止。
- `closed interval` 定义为：当前 unit 的两条边界 branch 在 complex 内重新闭合，形成一个被封闭的中间区域，且不再通向新的 `external associated road`；这是合法停止条件，不是退回大走廊的理由。
- sibling node 上 arm 的正式选择顺序冻结为：
  - 先看 `external associated road` 一致性
  - 再看 `L' / R'` 之间不得夹入其他 road
  - 再看左右顺序是否保持不变
  - 只有仍无法唯一确定时，才允许用最小转角做 tie-breaker
- `unit-local structure face` 表示：当前 pair-local region 内，由道路结构面定义的单连通主事实空间；导流带只负责在该空间内做分界、镂空与 throat / middle 强化，不再承担“主证据 vs fallback”二分。
- `unit-local structure face` 与后续 `local candidate unit` 只能由当前 unit 的两条边界 branch `(L, R)` 及其合法 continuation 共同围成；不属于当前 pair 的非分支道路面，不得被吸纳进候选空间。
- Step4 当前正式候选对象不是“整块导流带对象 / 整个道路面对象”，而是 `local candidate unit`：
  - 上层证据对象 ID
  - 当前 unit 内切出的局部单连通区域
  - 一个代表性参考位置
- `Step4` 当前正式执行输入必须以 `unit envelope` 表达，至少包括：
  - `unit_population_node_ids`
  - `context_augmented_node_ids`
  - `event_branch_ids`
  - `boundary_branch_ids`
  - `preferred_axis_branch_id`
- `local candidate unit` 必须按三层优先级分层，而不是混成总分：
  - Layer 1：主体稳定落在 `throat core + pair-middle`
  - Layer 2：主体稳定落在 `pair-middle`，但不一定命中最强 throat core
  - Layer 3：仅弱进入当前 unit 候选空间，主要靠边缘接触；不能直接当最终主结果，只能作 reverse / mode switch / 审计参考
- 证据共用口径正式冻结为：
  - 对象级共用：允许
  - 区域级共用：原则上不允许
  - 点位级共用：严格不允许
- 因此不同 event unit 之间不得共用同一事实依据核心段、同一参考位置、同一导流带局部区域；若复用同一上层对象，必须落在不同 `local candidate unit` 上。
- 事实位置链路至少表达：
  - `event_anchor_geometry`
  - `selected DivStrip component`
  - `event axis`
  - `scan origin`
  - `crossline scan`
  - `DivStrip ref s / DriveZone split s`
  - `fact_reference_point`
- `Step4` 点位语义正式拆成两层：
  - `fact_reference_point`：与 `event_chosen_s_m` 对齐的事实参考点
  - `review_materialized_point`：仅用于 PNG 的可视化落点
- 过渡期允许保留 `event_reference_point` 作为 review alias，但它不再承担唯一事实点语义。
- `divstrip_ref` 命中时，`fact_reference_point` 与 `review_materialized_point` 都必须落在当前选中的局部 DivStrip 事实上。
- `fact_reference_point` 的正式语义冻结为：当前分歧 / 合流事实开始形成的一侧，即 `formation-side / throat-side reference`；一般情况下应更靠近当前 representative node / throat，而不是落到导流带远离 node 的 distal tip。
- `review_materialized_point` 可以继续保留 legacy 可视化落点，但不得替代 `fact_reference_point` 的 formation-side 语义；`event_chosen_s_m` 继续作为轴向标量审计值保留。
- review 中表达的 `selected DivStrip` 是当前事实依据的 localized evidence patch，不得继续把整块无关导流带面作为单一事实依据涂出。
- Step4 事实依据几何正式拆成三层：
  - `selected_component_union_geometry`
  - `localized_evidence_core_geometry`
  - `coarse_anchor_zone_geometry`
- `coarse_anchor_zone_geometry` 只用于审计与 review，不得代理 component ownership。
- Step4 在最终接受 `fact_reference_point` 前，必须对当前候选做 `branch-middle / throat` 合法性 gate；若候选与当前分歧 / 合流分支中间区域无实际关系，不得直接放行为有效事实位置。
- complex / multi 场景下，`branch-middle / throat` gate 必须使用当前 unit 的 `boundary_branch_ids`；不得静默退回 case-level `main_branch_ids` 充当 unit-local throat pair。
- merge 单元的 `boundary_branch_ids` 必须由当前 unit 的 entering branches 组成；diverge 单元的 `boundary_branch_ids` 必须由当前 unit 的 exiting branches 组成。`preferred_axis_branch_id` 只能来自当前 unit 的唯一 opposite-direction trunk，不得再通过 `kind_2=128 -> 16` 的静默降级去替代真实 unit-local merge/diverge 语义。
- 连续链 case 若原始 anchor 仍停留在 seed 占位区且不命中当前选中的 DivStrip，T04 必须把 review 用 `event_anchor_geometry` materialize 为围绕当前事实证据的 coarse anchor zone，而不是继续输出固定 seed 方框。
- `fact_reference_point` 不得落到 `DriveZone` 外；若轴向候选越界，T04 必须显式记为无效候选，`review_materialized_point` 只允许收敛回当前道路面内的事实证据位置，并留痕。
- Step4 只负责正向 RCSD 选取与一致性校验，不定义 RCSD 最终负向语义。
- 正向 RCSD 候选池冻结为：
  - 先按当前 unit 特征筛
  - 再按当前主证据附近邻域匹配
  - pair-local scope 为空时，不得回退到更大的 case 级 RCSD 世界补主支持对象
- Step4 正向 RCSD 一致性正式冻结为：
  - `A`：强一致
  - `B`：部分一致
  - `C`：缺失
- 正向 RCSD 作用边界冻结为：
  - `A` 可参与主证据支持、主证据修正与后续 polygon 强约束
  - `B` 只做支持 / 提示 / risk 强化，不直接推翻主证据
  - `C` 只输出 `no_support`，不自动否决主证据
- Step4 当前必须显式输出：
  - `selected_rcsdroad_ids`
  - `selected_rcsdnode_ids`
  - `primary_main_rc_node`
  - `positive_rcsd_support_level`
  - `positive_rcsd_consistency_level`
  - `required_rcsd_node`
- 若当前主证据位置存在正向匹配的 RCSD 路口节点，则该节点必须作为 `required_rcsd_node` 输出；本轮只在 Step4 做输出与审计表达，不扩展到 Step5-7。
- reverse 不是独立证据体系，只是同一 `pair-local region` 内的另一种查找方向；reverse 命中的候选也必须进入相同的三层优先级判断。
- reverse 不得反向扩大、补全或重定义当前 `pair-local region`；候选空间边界一旦由 `(L, R)` 确定，reverse 只能在其内部活动。
- fallback 不是“道路面降级兜底”；它表示在同一 `pair-local region` 内，从“导流带强约束定位”切换到“道路结构面主导定位”的模式切换。
- `reverse tip` 只允许在以下场景作为受控重试：
  - `forward missing`
  - `forward rejected by local throat / branch-middle gate`
  - `forward rejected by same-axis prior conflict`
- `drivezone_split_window_after_reverse_probe` 只属于 conservative fallback 语义，不得单独算作 reverse-tip 成功证据。
- `structure:middle:01` 不再是 Step4 正式主证据候选；若实现内部仍保留类似中间带几何，只能作为 `selected_candidate_region` 的容器 / 辅助语义，不得直接作为 `selected_evidence`。
- `axis_position_m = 0` 或 reference 贴 node 的候选，正式记为 `node_fallback_only`；它只能作为审计 / 兜底候选，不得直接成为主排序第一名。
- 若候选触发 `event_reference_outside_branch_middle`、`event_reference_axis_conflict_with_prior_unit` 或等价主证据 gate 拒绝，系统必须先在当前 unit 候选池内重选；若无合法候选，必须输出 `selected_evidence_state = none`，不得保留假的主证据占位。
- 对 complex `1 node = 1 event unit` 子单元，Step4 解释阶段必须把 evidence search scope 锚定在当前 representative node 的局部 throat 与当前 unit 的 executable event branches 上；它可以沿同一 `pair-middle` 语义跨 same-case sibling internal node 延续，但不得继续共享整条 complex 走廊。
- 若当前 unit-local scope 无法构成有效 throat pair 或有效 branch-middle gate，系统不得静默回退成整条 complex 走廊；必须显式记录 `degraded_scope_reason`，并至少上浮为 `STEP4_REVIEW`。
- ownership guard 的主判断必须以语义冲突为先：
  - 共用同一物理 DivStrip component（`selected_component_ids` 是局部索引，跨 sub-unit 不稳定，只允许作为 debug label；component ownership 须以 `selected_component_union_geometry` 的物理重叠等价判定）
  - 同一 `event_axis_branch_id` 且 `|Δevent_chosen_s_m| <= 5m`
  - 共用同一 `localized_evidence_core_geometry`
- 上述任一冲突命中时，T04 必须上浮为 `STEP4_FAIL`，不得仅以 `REVIEW` 吞掉。
- 例外（与 REQUIREMENT §9.5 一致）：当两个 unit 共用同一物理 DivStrip component，但同时满足同一 `event_axis_branch_id` 且 `|Δevent_chosen_s_m| > 5m` 时，视为「同一导流带不同位置」的允许场景，不再仅凭 localized core segment 几何重叠触发 fail。
- 单 Case 内必须先完成候选池生成、初选和重选；若多个 unit 初选撞到一起，不得直接“一过一 fail”，必须先在各自候选池内重选。
- 当前 Step4 单 Case 输出是“初选结果”，不是全量最终裁决；跨 Case 的对象级 / 区域级共用冲突不在单 Case 内强行解完，而是在全量 Step4 结束后做二次处理。
- 因此 Step4 单 Case 输出必须保留后续二次处理所需字段：
  - `selected_candidate_region`
  - `selected_evidence_state`
  - `selected_evidence`
  - `alternative_candidates`
  - `ownership_signature`
  - `upper_evidence_object_id`
  - `local_region_id`
  - `point_signature`

### 3.5 当前冻结候选空间基线（2026-04-22）

- 本节冻结的是 `Step4 候选空间 / selected_candidate_region` 的当前 accepted baseline，不扩展到 `Step5-7`。
- 当前 accepted baseline 输入集冻结为：`E:\TestData\POC_Data\T02\Anchor_2`（WSL：`/mnt/e/TestData/POC_Data/T02/Anchor_2`）。
- 当前人工目视审计参考工件为：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t04_step14_batch/codex_t04_pair_variant_fix_20260422`。
- 上述输出目录只是审计证据，不是 source-of-truth；若审计工件缺失，以本契约与 `tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py` 的冻结断言为准。
- 若后续实现与本节冻结基线冲突，默认先视为实现回退；未经用户明确确认，不得自行重设 baseline 或修改本节。

当前冻结的共同要求：

- 候选空间必须由当前 unit 的两条边界 branch `(L, R)` 及其合法 continuation 物化。
- 候选空间纵向延续仍可沿当前扫描长度要求执行，但不得做反向追溯。
- local truncation 只能限制扫描方向，不能切断已确认的 boundary-branch continuation。
- propagation 到 sibling node 时，`L / R` 之间不得夹入其他 road；若无法满足，必须停止延续，而不是换成错误 pair。
- 当前冻结基线只约束 `selected_candidate_region` 的容器语义：
  - 它必须表示当前 unit 的 pair-local 候选空间容器，而不是主证据本身
  - 它必须覆盖当前 representative node
  - 不再冻结 `selected_evidence` 必须等于 `structure:middle:01`

当前冻结的 real-case 基线：

- `760213`
  - `node_760213`、`node_760218` 的候选空间目视正确，作为 simple / local pair 正常样本冻结。
- `785671`
  - `event_unit_01` 的候选空间必须由 `980348` 与 `527854843` 这对边界分支定义。
- `857993`
  - `node_857993` 的边界 pair 冻结为 `12557730 / 1112045`，不得把 trunk `619715536` 误吸入候选空间。
  - `node_870089` 的边界 pair 冻结为 `509954401 / 617462076`，不得把其他非 pair 道路吸入其候选空间。
- `987998`
  - `event_unit_01` 的候选空间必须由 `1026704` 与 `1078428` 这对边界分支定义。
- `17943587`
  - `node_17943587` 的边界 pair 冻结为 `510969745 / (607951495 + 528620938)`。
  - `node_55353233` 的边界 pair 冻结为 `528620938 / (502953712 + 41727506 + 620950831)`；`605949403` 不得重新进入该 unit 的 event pair。
  - `node_55353239` 的 local three-arm 拓扑冻结为 `607962170 / 620950831 / 41727506`，且候选空间必须回到 node / throat / middle 合法位置。
  - `node_55353248` 的边界 pair 冻结为 `605949403 / (41727506 + 607962170)`，trunk `502953712` 不得主导候选空间。
- `30434673`
  - `event_unit_01` 的候选空间必须由 `530277767` 与 `76761971` 这对边界分支定义。
- `73462878`
  - `event_unit_01` 保持当前 pair-space 行为不回退，作为 full-input / degraded-scope 守门样本冻结。

### 3.6 当前冻结主证据 / Reference 基线（2026-04-22）

- 本节冻结的是 `Step4 主证据 / fact_reference_point` 的当前 accepted baseline，不扩展到 `Step5-7`。
- 当前人工目视通过的审计 run 冻结为：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t04_step14_batch/codex_t04_step4_primary_evidence_iteration_20260422_fix3`。
- 上述 run 只是 audit evidence；正式冻结口径仍以本契约和 `tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py` 为准。
- 若后续实现使本节冻结样本重新出现以下任一现象，默认视为 Step4 回退：
  - `selected_evidence_state` 重新退回 `none`
  - 主证据不再是当前已人工确认通过的 local divstrip evidence
  - `fact_reference_point` 重新跑到导流带 distal tip，而不再表示 formation-side / throat-side reference

当前冻结的共同要求：

- `selected_evidence` 必须是当前 unit 内切出的合法 `local candidate unit`，不得重新退回容器语义或假的 `structure:middle` 主证据。
- `fact_reference_point` 必须落在当前 `selected_evidence_region_geometry` 上，并表达当前分歧 / 合流过程的 formation-side / throat-side reference。
- 对当前已接受样本，`fact_reference_point` 应比候选摘要中的远端参考距离更靠近当前 representative node；它不是导流带远端 tip 的展示点。

当前冻结的 Anchor_2 accepted baseline：

- `760213`
  - `node_760213 -> node_760213:divstrip:3:01`
  - `node_760218 -> node_760218:divstrip:3:01`
- `785671`
  - `event_unit_01 -> event_unit_01:divstrip:3:01`
- `785675`
  - `event_unit_01 -> event_unit_01:divstrip:5:01`
- `857993`
  - `node_857993 -> node_857993:divstrip:4:01`
  - `node_870089 -> node_870089:divstrip:4:01`
- `987998`
  - `event_unit_01 -> event_unit_01:divstrip:4:01`
- `17943587`
  - `node_17943587 -> node_17943587:divstrip:2:01`
  - `node_55353233 -> node_55353233:divstrip:2:01`
  - `node_55353239 -> node_55353239:divstrip:2:01`
  - `node_55353248 -> node_55353248:divstrip:2:01`
- `30434673`
  - `event_unit_01 -> event_unit_01:divstrip:4:01`
- `73462878`
  - `event_unit_01 -> event_unit_01:divstrip:1:01`

## 4. Outputs

### 4.1 Run Root 固定输出

- `preflight.json`
- `summary.json`
- `step4_review_index.csv`
- `step4_review_summary.json`
- `step4_review_flat/`
- `cases/`

### 4.2 单 case 固定输出

- `step1_status.json`
- `case_meta.json`
- `step3_status.json`
- `step3_audit.json`
- `step4_event_interpretation.json`
- `step4_event_evidence.gpkg`
- `step4_audit.json`
- `step4_review_overview.png`
- `event_units/<event_unit_id>/step4_review.png`
- `event_units/<event_unit_id>/step3_status.json`
- `event_units/<event_unit_id>/step4_candidates.json`

### 4.3 Step3 输出分层

- case 根目录下的 `step3_status.json / step3_audit.json` 当前固定表达 `case coordination skeleton`。
- `event_units/<event_unit_id>/step3_status.json` 当前固定表达当前 unit 的 `unit-level executable skeleton`。
- complex / multi 场景下，`Step4` 的可执行输入审计必须以 `event_units/<event_unit_id>/step3_status.json` 为准；顶层 `step3_status.json` 不再暗示自己就是 Step4 的唯一输入。

### 4.4 review index / summary

- `step4_review_index.csv` 至少包含：
  - `sequence_no`
  - `case_id`
  - `event_unit_id`
  - `event_type`
  - `review_state`
  - `evidence_source`
  - `position_source`
  - `reverse_tip_used`
  - `positive_rcsd_support_level`
  - `positive_rcsd_consistency_level`
  - `selected_rcsdroad_ids`
  - `selected_rcsdnode_ids`
  - `primary_main_rc_node`
  - `required_rcsd_node`
  - `selected_candidate_region`
  - `primary_candidate_id`
  - `primary_candidate_layer`
  - `axis_position_m`
  - `reference_distance_to_origin_m`
  - `ownership_signature`
  - `upper_evidence_object_id`
  - `local_region_id`
  - `point_signature`
  - `image_name`
  - `image_path`
- `step4_review_summary.json` 至少包含：
  - `total_case_count`
  - `total_event_unit_count`
  - `STEP4_OK`
  - `STEP4_REVIEW`
  - `STEP4_FAIL`
  - `selected_layer_1_count`
  - `selected_layer_2_count`
  - `selected_layer_3_count`
  - `cases_with_multiple_event_units`

## 5. EntryPoints

### 5.1 当前正式入口状态

- 当前 **无 repo 官方 CLI**。
- 当前模块正式执行面为程序内 runner：
  - `run_t04_step14_batch(...)`
  - `run_t04_step14_case(...)`
- 本轮不更新 `entrypoint-registry.md`。

## 6. Acceptance

1. repo 已存在 T04 正式模块文档面。
2. Step1-4 可对 case-package 运行并产出稳定文件集。
3. Step4 review overview / event-unit png / flat mirror / index / summary 可直接人工检查。
4. 本轮未进入 Step5-7，也未新增 repo 官方入口。
