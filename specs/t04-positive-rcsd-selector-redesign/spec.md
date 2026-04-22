# Spec: T04 Step4 正向 RCSD 选择器重构

## 背景

当前 T04 Step4 的正向 RCSD 结果仍主要来自旧 T02 bridge：

- `pair-local` 为空时仍可能回退到更大的 scoped / case 级 RCSD 世界补对象
- `RCSDRoad` 主要按 `angle <= 35°` 与 nearby fallback 选取
- `RCSDNode` 主要按 `mainnodeid / road buffer / trunk-window` 启发式选取
- `A/B/C` 主要是结果包装，不是基于 local unit role mapping 的正式判定
- `required_rcsd_node` 被 `A` 门槛卡住，不能独立表达

这与当前冻结口径冲突：Step4 正向 RCSD 必须严格在当前 SWSD unit 的 pair-local 语义框架内，先构建 `local RCSD unit`，再做 role mapping，最后判 `A/B/C` 并输出 `required_rcsd_node`。

## 目标

把 Step4 的正向 RCSD 正式链路替换为：

`pair-local raw observation -> rcsd_candidate_scope -> local RCSD unit -> role mapping -> A/B/C -> primary_main_rc_node / required_rcsd_node`

并满足：

- `pair-local` 为空时直接 `C / no_support`
- `required_rcsd_node` 不再依赖 `A`
- 旧 T02 bridge 只保留几何 / legacy debug 角色，不再主导正式输出

## 冻结定义

### 1. pair-local

`pair-local` 是当前 SWSD event unit 的局部语义框架，而不是单一 polygon。至少包括：

- `event_type`
- `boundary_branch_ids`
- `selected_evidence_region_geometry`
- `fact_reference_point`
- `local axis / local normal`
- `local longitudinal stop boundary`

### 2. rcsd_candidate_scope

`rcsd_candidate_scope` 是 pair-local 语义框架内允许 RCSD 对象进入候选讨论的软进入范围，不是 `selected_candidate_region` 的硬裁剪。

允许进入讨论的 RCSD 对象包括：

- 与当前 `selected_evidence_region_geometry` 有稳定关系的 RCSD 对象
- 过 `fact_reference_point` 的局部法线两侧最先命中的 RCSDRoad
- 由这些 first-hit RCSDRoad 沿 reference 方向追溯出来的连续 RCSD 对象

### 3. local RCSD unit

Step4 正向 RCSD 不能先选 road / node 再解释。必须先构 unit。

- `node-centric local_rcsd_unit`
  - 一个 RCSDNode
  - 与该 node 直接挂接、并进入当前局部讨论范围的 RCSDRoad
  - 这些 roads 的 entering / exiting 角色
- `road-only local_rcsd_unit`
  - 当前局部空间无可用 node，但有一组 RCSDRoad 形成明确局部分歧 / 合流结构
  - 最高只能给到 `B`

### 4. role mapping

判定原则冻结为：

- 先比 entering / exiting 角色
- 角色能对应后，再比方向一致性
- 不再用“角度像不像”作为主规则

### 5. A / B / C

- `A`
  - 已匹配的 RCSD local unit 与当前 SWSD unit 在 entering / exiting 上双向一一对应
  - entering 全对应
  - exiting 全对应
  - 方向一致
- `B`
  - RCSD local unit 形成单向子集映射
  - RCSD 已表达出的 entering / exiting arms 都能映射到 SWSD 对应 arms
  - 方向一致
  - 但 SWSD 有 arms 缺失
- `C`
  - `pair-local` 内没有 RCSD unit
  - 或 role mapping 无法成立
  - 或方向不一致到不可接受
  - 或只有零散 roads，连 local unit 都构不出来

### 6. required_rcsd_node

`required_rcsd_node` 必须从已匹配的 local RCSD unit 中独立输出：

- 只要当前主证据附近存在一个已匹配的 forward RCSD node，就输出
- `A/B` 只影响支持强度，不影响其是否应输出
- road-only local unit 时，`required_rcsd_node = none`

## 非目标

- 不进入 Step5/6/7
- 不做 RCSD 二次校验闭环
- 不重写 Step1-3
- 不新增 repo 官方 CLI
- 不把旧 T02 bridge 删除；仅降级为 legacy debug / raw geometry 输入

