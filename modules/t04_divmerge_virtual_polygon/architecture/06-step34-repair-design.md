# 06 Step3/Step4 Repair Design

## 1. 文档目的

本文档用于冻结 T04 在 `Step3` 与 `Step4` 上的修复设计边界，重点解决两类问题：

- Step3 粗骨架的输出层级不清，导致 case-level 与 unit-level 语义混用。
- Step4 在 complex / multi 场景下，把粗骨架继续当成半个事实定位层，进而污染 throat、ownership、reverse tip 与审计输出。

本文档是 `INTERFACE_CONTRACT.md` 的设计展开面，不替代稳定契约本身。

## 2. 问题归因

### 2.1 Step3 当前问题

- T04 实际执行时，complex unit 已经在 `singleton_group=True` 下重建单节点 topology。
- 但 T04 对外落盘的 `step3_status.json`、`step3_audit.json`、case overview 仍主要表达 case-level skeleton。
- 结果是：
  - 执行层已经部分切到 single-node 语义
  - 审计层仍停在 case-level 粗骨架
  - 维护者无法分辨 Step4 到底消费了哪一层 Step3

### 2.2 Step4 当前问题

- `event unit` 虽然已拆分，但传给 T02 内核时，`population / throat / ownership` 仍沿用旧的单事件粗骨架语义。
- `augmented_member_node_ids` 回流到事实解释层。
- complex 子单元局部 scope 稀薄时，会静默退回全走廊。
- `branch-middle / throat gate` 在 complex/multi 场景中，仍可能退回全局 `main pair`。
- ownership 与 review materialization 混用了错误几何代理。

## 3. Step3 修复设计

### 3.1 两层 skeleton

Step3 正式拆成两层：

1. `case coordination skeleton`
2. `unit-level executable skeleton`

### 3.2 case coordination skeleton

职责：

- 维护 `member nodes`
- 维护 `related_mainnodeids`
- 维护 continuous chain coordination
- 决定 event-unit population
- 提供 case overview / case-level audit

不承担：

- unit-local throat 几何
- unit-local preferred axis
- unit-local branch-middle 边界

### 3.3 unit-level executable skeleton

职责：

- 为当前 event unit 提供可执行的 topology 输入
- 明确 unit-local 的 branch / main / input / output / boundary / preferred axis
- 为 Step4 throat gate 提供结构边界

### 3.4 三类场景下的规则

#### A. 连续分歧 / 连续合流 complex

- case-level skeleton 负责表达“这是连续链上的一组语义 member nodes”。
- representative-node-anchored skeleton 负责表达“当前 node 的 unit-local in/out branches、boundary branches 与 preferred axis”。
- Step4 只允许把后者当作可执行输入。
- `unit population` 仍然只属于当前 representative node。
- 但对 `continuous complex/merge`，当前 unit 的 executable branches 允许在 same-case sibling internal node 上做 branch continuation；前提是 continuation 后仍属于当前 unit 的同一 merge/diverge 臂，且 `pair-middle` 语义连续、开放、未被新的竞争 pair 替代。
- `continuous chain` 只允许作为 case 外 `chain_context_hint`，不得把整条 complex corridor 直接回流成 unit-local throat 几何或 event-unit population。
- 这里的 continuation 目标不再是“给单条 road 找下一跳”，而是给当前 unit 的有序 pair `(L, R)` 找到新的 `(L', R')`。当前轮次候选空间一旦确定当前 pair 的合法延续方向，就只允许沿该方向单向推进，不再为了补全候选空间做反向追溯；continuation 的正式硬上限冻结为 `200m`。只要 sibling node 上无法唯一传播 pair、`L' / R'` 之间夹入其他 road、当前 pair-middle 被新 pair 关系替代、或显式 separation stop 命中，就必须立即停止。
- local truncation 只限制扫描方向，不得把 boundary branch 的合法 continuation membership 再裁回 seed road；只要 `(L, R)` 已合法跨 same-case sibling node 延续，pair-middle 就必须沿该 continuation 继续物化。
- sibling node 上 arm 的选择顺序冻结为：
  1. `external associated road` 一致
  2. `L' / R'` 中间不得夹入其他 road
  3. 左右顺序不变
  4. 最小转角只作为 tie-breaker

#### B. 多分歧 / 多合流

- Step3 必须保留多个方向，不得过度压塌。
- Step3 需要稳定保留：
  - `ordered_side_branch_ids`
  - `adjacent_side_pairs`
  - `unit_boundary_branch_ids`
  - `preferred_axis_branch_id`
- Step4 以后只在 pair-local 结构上做 throat gate。

#### C. simple 二分歧 / 二合流

- Step3 允许维持 trunk / event-side 的粗框架。
- 但 Step4 仍必须自行完成：
  - DivStrip 事实依据
  - throat / tip
  - final reference
- Step3 不得越界承担事实定位。

## 4. Step4 修复设计

### 4.1 unit envelope

每个 unit 在进入 T02 解释内核前，必须先形成 `unit envelope`：

- `unit_population_node_ids`
- `context_augmented_node_ids`
- `event_branch_ids`
- `boundary_branch_ids`
- `preferred_axis_branch_id`

### 4.2 local throat gate

- complex / multi 的 `branch-middle / throat gate` 必须使用当前 unit 的 `boundary_branch_ids`。
- 不再允许静默退回 case-level `main pair` 充当 unit-local throat。
- 若当前 unit 无法形成有效 throat pair，必须显式记录 `degraded_scope_reason`。
- `degraded_scope_reason` 当前必须补 `degraded_scope_severity` 与 `degraded_scope_fallback_used`；当候选空间语义已实质丢失时，允许升到 `STEP4_FAIL`，不能永远只留在 `STEP4_REVIEW`。
- merge 单元的 `boundary_branch_ids` 来自当前 unit 的 entering branches；diverge 单元来自当前 unit 的 exiting branches；`preferred_axis_branch_id` 来自唯一 opposite-direction trunk。
- `boundary_branch_ids` 的求解必须遵循当前 unit 的有序 pair `(L, R)`；对 complex / multi，不能再靠匿名 branch 集或单路 greedy continuation 近似替代。
- `external associated road` 是 boundary branch 的正式外部归宿审计点，不是任意碰到的第一个外部 exit；当前轮次它只用于 arm 选择一致性与停止条件判断，不再作为候选空间反向延伸的硬终点。若当前 unit 在 complex 内形成 `closed interval`，才允许在内部停止。
- pair-local 候选空间还必须显式输出 `branch_separation_*` 与 `stop_reason`，并把“中间夹其他 road”的判断落到 geometry-level intrusion gate，而不是继续只靠角度近似。

### 4.3 reverse tip 状态机

正式允许的 reverse tip 触发只有：

- `forward missing`
- `forward rejected by local throat`
- `forward rejected by same-axis prior conflict`

`drivezone_split_window_after_reverse_probe` 保留为 conservative fallback，但不再算作独立 reverse-tip 成功语义。

补充边界：

- reverse tip 只属于候选空间确定后的证据查找重试，不得用于扩大、补全或反向追溯当前 `pair-local region`。

### 4.4 ownership 几何拆层

Step4 正式拆成三层几何：

1. `selected_component_union_geometry`
2. `localized_evidence_core_geometry`
3. `coarse_anchor_zone_geometry`

其中：

- `selected_component_union_geometry` 用于 component ownership
- `localized_evidence_core_geometry` 用于 core-segment ownership
- `coarse_anchor_zone_geometry` 只用于审计 / review

### 4.5 point 语义拆层

Step4 正式拆成两层点位：

1. `fact_reference_point`
2. `review_materialized_point`

规则：

- `fact_reference_point` 与 `event_chosen_s_m` 对齐
- `review_materialized_point` 只服务 PNG
- 过渡期可保留 `event_reference_point` 作为 review alias

## 5. 与当前正式契约的收口决定

### 5.1 已冻结决定

- `tip / throat` 优先，否决 `body_center` 作为正式主策略
- candidate pruning 采用硬排除 + 显式 degraded state，不再保留静默复用被排除 component
- `~60m` complex unit-local scope、`8m² / 0.2` overlap、`same-axis Δs <= 5m` 冻结为正式阈值

### 5.2 尚不在本轮处理

- 不重写 T02 全量 Step3 内核
- 不进入 Step5-7
- 不新增 repo 官方 CLI

## 6. 回归要求

实现回写后，至少覆盖以下四类回归：

- `forward throat-pass`
- `same-axis conflict -> reverse success`
- `forward/reverse 都不通过 throat`
- `shared component but Δs>5m allowed`

并且至少包含三类真实业务场景：

- 连续分歧 / 连续合流 complex
- multi-diverge / multi-merge
- simple 二分歧 / 二合流

其中连续合流 complex 至少需要一个 real-case 回归样本，显式锁住：

- `unit population` 不扩
- branch continuation 可跨 same-case sibling internal node
- `pair_local_middle within pair_local_structure_face within pair_local_region`
