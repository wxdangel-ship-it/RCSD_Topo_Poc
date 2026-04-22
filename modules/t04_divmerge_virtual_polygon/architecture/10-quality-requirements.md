# 10 Quality Requirements

## 正确性

- CRS 与几何裁剪必须可追溯。
- Step1/2/3/4 的失败原因不得串层滥用。
- Step3 必须显式区分 `case coordination skeleton` 与 `unit-level executable skeleton`。
- complex / multi 场景下，Step4 只允许消费 `unit-level executable skeleton`，不得继续把 case-level 粗骨架当成 throat 几何。
- 对 `continuous complex/merge`，Step3/Step4 必须能证明“unit population 不扩，但 executable branch 可跨 same-case sibling internal node 延续”的语义没有被压扁成二叉 pair。
- Step4 必须把 unit 的第一层边界解释为有序 branch pair `(L, R)`，而不是匿名 branch 集。
- Step4 候选空间必须只由当前 unit 的两条边界 branch `(L, R)` 及其合法 continuation 物化，不得吸纳非分支道路面。
- Step4 候选空间的纵向延续仍可沿原扫描长度要求执行，但只能沿当前 unit 的合法单向延续推进；不得再通过反向追溯补全 `pair-local region`。
- sibling node 上 arm 的选择不得退化成单纯方位角或最小转角贪心；`external associated road`、pair 排布与“中间不得夹入其他 road”必须先于 tie-breaker 生效。
- Step4 每个 event unit 的事实依据与位置必须可解释。
- `fact_reference_point`、`review_materialized_point`、`selected_component_union_geometry`、`localized_evidence_core_geometry`、`coarse_anchor_zone_geometry` 的语义边界必须可解释。

## 可审计性

- Step4 review 图必须能直接表达当前事件单元的主证据、主轴、参考点与正向 RCSD。
- Step4 review 图必须能一眼区分：
  - `pair_local_rcsd_scope`
  - `selected_candidate_region` 这个空间容器
  - `selected_evidence`
  - `fact_reference_point / review_materialized_point`
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
  - normalized role mapping 为什么得到 `A/B/C`
  - `required_rcsd_node` 为什么输出或为什么为空

## 可维护性

- 代码按领域能力分层。
- 避免单一超大 orchestrator。
- 与 T02/T03 的复用边界显式写入文档。
- 允许复用 T02 的 topology / event interpretation 内核，但 T04 必须先把 unit-local 结构封装清楚，再传入 T02。

## 可回归性

- 至少保留 synthetic smoke。
- 至少跑 selected real-case batch。
- `Step4 候选空间` 当前 accepted baseline 已冻结在 `Anchor_2` real-case 集；后续任何新线程只要触碰 Step4 candidate space / branch propagation / pair-space identity，都必须默认把这组 real-case 当作回归闸门，而不是可选附加验证。
- Step3/Step4 修复后，至少覆盖以下回归样类：
  - `forward throat-pass`
  - `same-axis conflict -> reverse success`
  - `forward/reverse 都不通过 throat`
  - `shared component but Δs>5m allowed`
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
- `17943587 / node_55353248` 不得回退到 trunk 主导或缺失 `607962170` continuation。
- `857993 / node_870089` 不得回退到只剩 node 邻域小块或重新吸入非 pair 道路。
