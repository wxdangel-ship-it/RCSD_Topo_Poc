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

## 可维护性

- 代码按领域能力分层。
- 避免单一超大 orchestrator。
- 与 T02/T03 的复用边界显式写入文档。
- 允许复用 T02 的 topology / event interpretation 内核，但 T04 必须先把 unit-local 结构封装清楚，再传入 T02。

## 可回归性

- 至少保留 synthetic smoke。
- 至少跑 selected real-case batch。
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
- 复杂连续分歧、multi-diverge / multi-merge、simple 二分歧三类场景都必须有可复查样本。
