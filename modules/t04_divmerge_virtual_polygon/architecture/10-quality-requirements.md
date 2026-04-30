# 10 Quality Requirements

## 文件职责

- 本文件维护 T04 的正确性、可审计性、可维护性、可回归性与 frozen baseline gate。
- Step1-7 的业务策略写在 `architecture/04-solution-strategy.md`。
- 稳定输入、输出、状态机、枚举和值域写在 `INTERFACE_CONTRACT.md`。
- 本文件不得把 Step4 的 `STEP4_REVIEW` 解释为 Step7 最终第三态，也不得把 `857993 = rejected` 解释为待修复缺陷。

## 正确性

- CRS 与几何裁剪必须可追溯。
- full-input 与 case-package 两种执行面必须保持相同 Step1-7 业务语义；full-input candidate discovery 不能替代 Step1 admission。
- Step1/2/3/4 的失败原因不得串层滥用。
- Step3 必须显式区分 `case coordination skeleton` 与 `unit-level executable skeleton`。
- complex / multi 场景下，Step4 只允许消费 `unit-level executable skeleton`，不得继续把 case-level 粗骨架当成 throat 几何。
- 对 `continuous complex/merge`，Step3/Step4 必须能证明“unit population 不扩，但 executable branch 可跨 same-case sibling internal node 延续”的语义没有被压扁成二叉 pair。
- Step4 必须把 unit 的第一层边界解释为有序 branch pair `(L, R)`，而不是匿名 branch 集。
- Step4 候选空间必须只由当前 unit 的两条边界 branch `(L, R)` 及其合法 continuation 物化，不得吸纳非分支道路面。
- Step4 候选空间的纵向延续当前冻结为 `200m`，并且只能沿当前 unit 的合法单向延续推进；不得再通过反向追溯补全 `pair-local region`。
- sibling node 上 arm 的选择不得退化成单纯方位角或最小转角贪心；`external associated road`、pair 排布与“中间不得夹入其他 road”必须先于 tie-breaker 生效。
- `tip / throat` 优先于 `body_center`，不得把 `body_center` 重新提升为 Step4 主事实定位策略。
- candidate pruning 必须采用硬排除与显式 degraded state；被排除 component 不得被后续 fallback 静默复用。
- complex unit-local scope、overlap 与 same-axis ownership guard 的冻结阈值必须继续可审计：`~60m` unit-local scope、`8m2 / 0.2` overlap、same-axis `Delta s <= 5m`。
- Step4 pair-local 输出必须能审出：
  - `pair_local_direction`
  - `branch_separation_mean_m`
  - `branch_separation_max_m`
  - `branch_separation_consecutive_exceed_count`
  - `branch_separation_stop_triggered`
  - `stop_reason`
  - `intruding_road_ids`
- Step4 每个 event unit 的事实依据与位置必须可解释。
- `fact_reference_point`、`review_materialized_point`、`selected_component_union_geometry`、`localized_evidence_core_geometry`、`coarse_anchor_zone_geometry` 的语义边界必须可解释。
- 主证据只允许来自导流带或道路面分叉；RCSD 语义路口、RCSDRoad、SWSD 语义路口、SWSD candidate、历史抽象 node、拓扑召回点和抽象路网代理点不得被写成主证据。
- 无主证据时不得构造虚拟 Reference Point；`fact_reference_point` 必须为空，并以 `no_reference_point_reason` 审计原因。
- Reference Point 必须能追溯到导流带真实决定分歧 / 合流的位置，或道路面形态真实切换的位置。
- RCSD/SWSD 作为 `section_reference_source` 时必须显式标记，不得混写到 `reference_point_source`。
- Step5 必须能稳定产出 Unit / Case 两级的 `must_cover_domain / allowed_growth_domain / forbidden_domain / terminal_cut_constraints`，并对 `1m` hard negative mask、`fallback_support_strip`、`bridge zone` 与 `junction_full_road_fill_domain` 给出可追溯解释。
- Step5 默认以前后 `20m` 横向截面确定构面窗口，横向截面垂直于道路面方向或语义主轴。
- 路口面两侧横向扩展不得超过 `20m`，并且不得越过负向掩膜；负向掩膜包括导流带、hard negative mask、forbidden domain、terminal cut 与不可通行区域。
- RCSDRoad fallback 不得导致沿整条 RCSDRoad 远距离扩面，只能覆盖与当前事实分歧 / 合流或当前 section reference 相关的局部段。
- 对同时具备主证据 Reference Point 与 required RCSDNode 的路口面，Step5 必须在 DriveZone 内按语义主轴构造整幅路面填充域：Reference Point 与 RCSDNode 两端各保留 `20m` terminal window，主轴横向单侧不超过 `20m`，并继续受 forbidden masks / terminal cuts 硬裁剪；无主证据时只能使用 section reference，不得把 RCSDNode 推导为 Reference Point。
- Step6 必须能在不突破 Step5 约束的前提下生成单一连通面；只允许业务 hole，不允许算法洞。
- complex / multi 场景下，unit surface 合并后仍须保持 case 级单一连通，除非存在明确业务 hole。
- Step7 必须把最终状态机压缩为 `accepted / rejected` 两态；审计材料可以保留，但不得冒充第三种正式状态。
- Anchor_2 full baseline 的既有 `accepted / rejected` 语义不得静默放宽，不能为了提高 accepted count 弱化 Step7 门禁。

## 可审计性

- Step4 review 图必须能直接表达当前事件单元的主证据、主轴、Reference Point、section reference 与正向 RCSD/SWSD 支持状态。
- Step4 review 图必须能一眼区分：
  - `pair_local_rcsd_scope`
  - `selected_candidate_region` 这个空间容器
  - `selected_evidence`
  - `fact_reference_point / review_materialized_point`
  - `section_reference_source / section_reference_geometry`
  - `first_hit RCSDRoad`
  - `local RCSD unit`
  - `positive RCSD road / node`
  - `required_rcsd_node`
  - `positive_rcsd_support_level / positive_rcsd_consistency_level`
  - `rcsd_decision_reason`
- complex / multi 场景下，必须能从持久化输出中直接区分：
  - 顶层 case coordination skeleton
  - 当前 event unit 的 executable skeleton
- 对 `continuous complex/merge`，持久化输出必须能审出当前 unit 的 branch membership、bridge/sibling internal node、`event_branch_ids / boundary_branch_ids / preferred_axis_branch_id` 与 `degraded_scope_reason`。
- 对 `continuous complex/merge`，持久化输出还必须能举证：
  - 当前 unit 的 `(L, R)` 是哪一对有序边界
  - `external associated road` 如何确定
  - propagation 在哪个 sibling node 停止，以及停止原因
  - 当前候选空间是否只沿单向延续展开、是否排除了非分支道路
- `degraded_scope_reason` 必须同时带出 `degraded_scope_severity` 与 `degraded_scope_fallback_used`，否则 QA 无法区分 soft degraded 与 hard degraded。
- 当候选空间语义已经实质丢失时，允许升为 `STEP4_FAIL`；不得永远用 `STEP4_REVIEW` 掩盖 hard degraded。
- reverse tip 审计必须能区分 `forward missing`、`forward rejected by local throat`、`forward rejected by same-axis prior conflict`；`drivezone_split_window_after_reverse_probe` 只能作为 conservative fallback，不得作为独立 reverse-tip 成功语义。
- ownership 冲突必须能举证到：
  - component union
  - localized evidence core
  - same-axis `Δs`
- CSV/JSON summary 必须能让人工快速定位复核对象。
- 正向 RCSD 审计输出必须能明确举证：
  - pair-local raw RCSD 是否为空
  - first-hit RCSDRoad 是哪些
  - 选中的 local RCSD unit 是 node-centric 还是 road-only
  - 是否构成 `aggregated_rcsd_unit`
  - 是否触发 `axis_polarity_inverted`
  - `positive_rcsd_present` 为什么成立或为什么不成立
  - normalized role mapping 为什么得到 `A/B/C`；该 `A/B/C` 只能作为 RCSD 支持强度、一致性、审计质量等级或人工复核优先级，不再作为 T04 主业务场景分类
  - `required_rcsd_node` 为什么输出或为什么为空
- Step5 审计输出必须能明确举证：
  - 哪些区域进入 `must_cover_domain`
  - 哪些对象触发 `1m` hard negative mask
  - `fallback_support_strip` 与 `bridge zone` 如何物化
  - `terminal_cut_constraints` 如何从局部道路方向确定
  - `junction_full_road_fill_domain` 是否启用，以及其 `surface_fill_axis_half_width_m`、语义主轴横向带和面积
  - `surface_section_forward_m / surface_section_backward_m / surface_lateral_limit_m` 是否保持默认 `20m` 或显式说明偏离原因
  - RCSDRoad fallback 是否只覆盖相关局部段，且未造成远距离扩面
- Step6 审计输出必须能明确举证：
  - `assembly_canvas` 如何构造
  - 哪些硬种子被写入
  - 最终是否单一连通
  - 是否存在 forbidden overlap / cut violation / 非业务 hole
  - cleanup 后是否重新检查 allowed / forbidden / cut / 横向范围
- Step7 审计输出必须能明确举证：
  - `accepted / rejected` 的最终判定依据
  - 发布层去向
  - `divmerge_virtual_anchor_surface*` 成果与审计材料之间的映射关系
- T04 full baseline 不只校验 `divmerge_virtual_anchor_surface*` surface 发布层，也必须校验 downstream `nodes.gpkg` 的 representative node `is_anchor` 写回结果与 Step7 `final_state` 一致：`accepted -> yes`，`rejected / runtime_failed / formal result missing -> fail4`。
- `nodes_anchor_update_audit.csv/json` 必须与 `nodes.gpkg` 实际写回、`divmerge_virtual_anchor_surface_summary.*` 和 `step7_consistency_report.json` 保持一致；`857993` 必须保持 `fail4`，`699870` 必须保持 `yes`。

## 可维护性

- 代码按领域能力分层。
- 避免单一超大 orchestrator。
- 与 T02/T03 的复用边界显式写入文档。
- 可以参考 T02 的 topology / event interpretation 经验，但正式运行时语义必须在 T04 私有层内封装清楚，不把 T02 runtime 依赖作为质量前提。
- 可以参考 T03 的实现逻辑与产物风格，但 T04 的 `Step5-7` 正式执行逻辑必须保留在模块私有实现内，不得直接 import / 调用 / 硬拷贝 T03 模块代码。
- `nodes_publish.py` 是 T04 私有 downstream 写回层；`fail4` 不得上溢到 T03 语义。

## 可回归性

- 至少保留 synthetic smoke。
- 至少跑 selected real-case batch。
- 正式治理与影响 Step1-7 语义的变更默认按 SpecKit 串行推进，并在每轮显式覆盖：
  - `Product`
  - `Architecture`
  - `Development`
  - `Testing`
  - `QA`
- Step1-7 回归顺序固定为：
  - 先单 case
  - 再 batch
  - 最后做发布层与汇总层核对
- `Step4 候选空间` 当前 accepted baseline 已冻结在 `Anchor_2` real-case 集；后续任何新线程只要触碰 Step4 candidate space / branch propagation / pair-space identity，都必须默认把这组 real-case 当作回归闸门，而不是可选附加验证。
- Step3/Step4 修复后，至少覆盖以下回归样类：
  - `forward throat-pass`
  - `same-axis conflict -> reverse success`
  - `forward/reverse 都不通过 throat`
  - `shared component but Δs>5m allowed`
- Step3/Step4 回归必须覆盖三类真实业务场景：continuous complex、multi-diverge / multi-merge、simple 二分歧 / 二合流。
- 必须至少有一个 real-case continuous merge complex 回归，锁住：
  - `unit population` 不扩
  - branch continuation 经过 same-case sibling internal node
  - `pair_local_middle within pair_local_structure_face within pair_local_region`
- 必须至少有一个 real-case sibling arm selection 回归，锁住：
  - `external associated road` 一致性
  - sibling node 上 `L' / R'` 之间无夹层 road
  - pair propagation 失败时显式停止，而不是静默退回大走廊
- 必须至少有一个 real-case pair-space 回归，锁住：
  - `boundary_branch_ids == event_branch_ids`
  - `valid_scan_offsets_m` 只沿单一合法方向延续
  - 候选空间不覆盖当前 unit 之外的非分支道路
- 必须至少有一个 Step4 正向 RCSD 回归，锁住：
  - pair-local RCSD 为空时直接 `C / no_support`
  - 正式结果不回退到 scoped / case 级 RCSD 世界
  - `required_rcsd_node` 可在 `B` 下独立输出
  - `positive_rcsd_present = true` 不再自动保底 `B`
  - 事实层成立但经 aggregated polarity normalization 后仍存在结构性硬冲突时，允许最终落 `C`
  - side-label mismatch 不再单独把事实存在样本压到 `C`
  - `axis_polarity_inverted` 默认在 aggregated 级别识别
- 复杂连续分歧、multi-diverge / multi-merge、simple 二分歧三类场景都必须有可复查样本。
- 六类路口面业务场景和兜底场景必须逐步补齐回归样类：
  - 主证据 + RCSD 语义路口：待补充，不强行给未知 case 归类。
  - 主证据 + RCSDRoad fallback：待补充，不强行给未知 case 归类。
  - 主证据 + 无 RCSD：待补充，不强行给未知 case 归类。
  - 无主证据 + RCSD junction window：已知线索 `760984 / 788824`。
  - 无主证据 + SWSD junction window：已知线索 `706629`。
  - 无主证据 + SWSD junction window + RCSDRoad fallback：待补充，不强行给未知 case 归类。
  - complex / multi unit surface 合并：待补充，不强行给未知 case 归类。
  - 导流带作为负向掩膜：待补充，不强行给未知 case 归类。
  - 横向超过 `20m` 的裁剪或拒绝样例：待补充，不强行给未知 case 归类。

### 当前 accepted baseline gate（2026-04-22）

- 基线输入集冻结为：`/mnt/e/TestData/POC_Data/T02/Anchor_2`
- 当前人工审计参考 run root：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t04_step14_batch/codex_t04_pair_variant_fix_20260422`
- 参考 run root 只承担 audit evidence 角色；默认回归闸门以模块契约和冻结测试为准。

后续只要改动以下任一链路，就必须至少核对这组 case：

- Step3 complex branch variant generation / selection
- Step4 pair-local scope
- sibling propagation / continuation stop gate
- pair-local middle / structure-face candidate materialization
- ownership / reselection 导致的 selected candidate 变化

冻结守门 case：

- `760213`：`node_760213`、`node_760218`
- `785671`：`event_unit_01`
- `857993`：`node_857993`、`node_870089`
- `987998`：`event_unit_01`
- `17943587`：`node_17943587`、`node_55353233`、`node_55353239`、`node_55353248`
- `30434673`：`event_unit_01`
- `73462878`：`event_unit_01`

冻结判据：

- 候选空间只能由当前 unit 的边界 pair `(L, R)` 及其合法 continuation 构成。
- 候选空间不得做反向追溯补全。
- `L / R` 之间不得夹入其他 road。
- `selected_candidate_region` 只校验容器语义：
  - 表示当前 unit 的合法候选空间
  - 覆盖 representative node
  - 不再等同主证据
- accepted baseline unit 的正确性判据应围绕：
  - `selected_evidence`
  - `fact_reference_point`
  - `positive RCSD support / consistency`
  - 不再使用 `selected_candidate = structure:middle:01` 作为正式守门条件
- `17943587 / node_55353233` 不得回退到 `502953712 + 605949403`。
- `17943587 / node_55353248` 当前 full baseline 锁定为 `605949403 / (41727506 + 620950831)` pair，不得回退到 trunk `502953712` 主导；旧 `607962170` continuation 口径仅作为 legacy selected-case 审计线索保留。
- `857993 / node_870089` 不得回退到只剩 node 邻域小块或重新吸入非 pair 道路。

Step4 final tuning 额外质量门槛：

- accepted `8 case / 13 unit` 在 second-pass 后仍必须保持：
  - `selected_evidence_state = found`
  - 主候选不回退
  - `positive_rcsd_present = true`
  - `positive_rcsd_support_level / positive_rcsd_consistency_level` 以当前 full baseline 测试断言为准；`785671 / event_unit_01` 当前冻结为 `secondary_support / B`，不得再用 legacy 全量 `primary_support / A` 口径否决当前 `23 / 20 / 3` baseline。

Step7 legacy selected-case 发布冻结门槛：

- Anchor_2 legacy selected-case 业务基线为 `accepted = 7 / rejected = 1`。
- `857993` 的最终 `rejected` 是人工目视审计确认后的正确结论，不得在治理回归中改成追求 `accepted` 的目标。
- `760598` 在当前数据输入条件下无法正确找到对应数据；该 case 当前接受 `rejected`，并归类为数据输入限制样本，不作为本轮算法继续追修对象。
- 最终发布状态只允许 `accepted / rejected`；Step4 的 `STEP4_REVIEW` 仅保留为内部审计提示，不得作为最终第三态。
- `17943587` 允许在不改主证据、不断 support 的前提下，通过 second-pass claim reconcile 改写 `required_rcsd_node`；若发生该类变化，必须显式产出 pre/post compare，不允许 silent drift。
- same-case non-conflict unit 进入 second-pass 后只能 `kept`，不得被误判成 hard conflict 或 baseline guard 降级。

### Anchor_2 full baseline gate（2026-04-26）

- 基线输入集：`/mnt/e/TestData/POC_Data/T02/Anchor_2`
- 当前人工审计参考 run root：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t04_anchor2_full_requested/anchor2_full_all_20260426_junction_window_guard`
- 当前全量冻结结果：`row_count = 23`，`accepted = 20`，`rejected = 3`。
- 冻结测试入口：`tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate`
- 冻结测试还必须守住 T04 downstream `nodes.gpkg` 写回：20 个 accepted representative node 为 `yes`，3 个 rejected representative node 为 `fail4`，其中 `857993 = fail4`、`699870 = yes`。
- 当前全量 final_state：
  - accepted：`17943587`、`30434673`、`505078921`、`698380`、`698389`、`699870`、`706629`、`723276`、`724067`、`724081`、`73462878`、`758784`、`760213`、`760256`、`760984`、`785671`、`785675`、`788824`、`824002`、`987998`
  - rejected：`760598`、`760936`、`857993`
- `505078921` 当前作为 complex multi-unit 防回退重点样本：
  - `node_505078921` 必须保持 `required_rcsd_node = 5385438602535104`
  - `node_510222629` 必须保持 `required_rcsd_node = 5385438602535122`
  - `node_510222629__pair_02` 必须保持 `evidence_source = road_surface_fork`，不得被 `rcsd_junction_window` 抢占为独立 RCSD window。
- `706629` 当前锁定为 `swsd_junction_window`：无主证据、无正向 RCSD 时，以 SWSD 路口作为 section reference，前后 `20m` 构面；不得构造 Reference Point。
- `760984 / 788824` 当前锁定为 `rcsd_junction_window`：无主证据、但可召回正向 RCSD 时，以 RCSDNode 作为 section reference，前后 `20m` 构面；不得构造 Reference Point。
- `760598 / 760936 / 857993` 当前保持 `rejected`；后续不得为了提高 accepted count 静默放宽 Step7 门禁。

### RCSD-anchored reverse 定向回归（2026-04-24）

- `699870` 当前属于 Anchor_2 full baseline 的 accepted case，同时也是 Step4 末段 `rcsd_anchored_reverse` 的定向真实回归样本。
- `699870` 用于验证“前向主证据缺位，但 RCSD 端可稳定成团”的旁路能力；该旁路能力已经进入当前 `23 / 20 / 3` baseline 守门。
- `699870` 的 RCSD 端能力不得被解释为 RCSD 推导 Reference Point；如无主证据，只能以 section reference、支撑域来源与审计字段表达。
- 单 case 回归中，`699870` 必须触发 reverse，且 Step4 不得再以 `selected_evidence_state = none` 结束。
- `699870` 的 Step5-7 必须能继续消费 Step4 写回的 `event_chosen_s_m / axis_position_m / selected_evidence_state` 与 legacy Step5 bridge 字段。
- `699870` 的 Step5 必须启用 `junction_full_road_fill`，并以 `surface_fill_axis_half_width_m = 20.0` 约束整幅路面填充；最终 polygon 不得退化为仅覆盖 `terminal_support_corridor_geometry` 的窄带结果。
- 当前 full baseline 中 `699870` 必须保持 `accepted`，且 downstream `nodes.gpkg` 必须写为 `yes`。
- batch / full-input 混跑中，若 `699870` 的 reverse 结果命中 cross-case 已占用 RCSD claim 或 evidence ownership，必须通过 `post_reverse_conflict_recheck` 放弃本次 reverse；该 guard 不能被用于静默破坏当前 full baseline。
