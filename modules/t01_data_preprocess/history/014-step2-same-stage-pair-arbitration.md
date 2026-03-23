# 014 - Step2 same-stage pair arbitration

## 背景
- 旧版 Step2 对同一阶段多个合法 pair 竞争同一组 corridor / roads 的情况，采用固定顺序 + 局部贪心处理：
  - pair 按固定顺序验证
  - 每个 pair 只先选自己的局部最优 trunk candidate
  - 前面的 pair 一旦占用 trunk / corridor roads，后面的合法 pair 只能退让或冲突
- 这会导致系统缺少“同阶段合法 pair 冲突仲裁”能力，不能回答：
  - 哪个 pair 更优
  - 哪条 corridor 更应归属给哪个 pair
  - 哪组 segment 组合更符合整体拓扑/语义

## 为什么旧贪心不足
- 单 pair 合法，仅说明其自身通过硬合法校验，不代表它在同阶段竞争环境下应被最终保留。
- 当多个合法 pair 争夺同一组 roads / corridor 时，固定顺序会把“先验证到谁”误当成“谁更合理”。
- 这种策略在 `XXXS7` 里表现明显：
  - `S2:1019883__1026500`
  - `S2:1026500__1026503`
  均合法，但 `500588029` 所在 corridor 更自然地应归属给后者。

## 仲裁对象
- 仲裁对象不是裸 `pair_id`，而是：
  - 合法 pair
  - 加上该 pair 对应的 `trunk / segment_body candidate` 组合
- 也就是说，最终保留结果同时考虑：
  - pair 的合法性
  - contested corridor 的 trunk 归属
  - body 是否更完整
  - 是否引入更多语义冲突

## 当前实现
- Step2 先保留 single-pair validation。
- 之后新增 `same-stage pair arbitration`：
  1. 构建 pair-level conflict graph
  2. 提取 `conflict components`
  3. 在每个 component 内做局部组合仲裁
  4. winners 才进入 final `validated_pairs / segment_body`
- 小型 component 使用 exact 组合搜索。
- 大型 component 使用 fallback greedy，但必须显式审计：
  - `exact_solver_used`
  - `fallback_greedy_used`

## 当前仲裁指标
- `contested_trunk_coverage_count`
- `contested_trunk_coverage_ratio`
- `endpoint_boundary_penalty`
- `internal_endpoint_penalty`
- `body_connectivity_support`
- `semantic_conflict_penalty`
- `strong_anchor_win_count`

## XXXS7 为什么是典型 case
- `S2:1019883__1026500` 与 `S2:1026500__1026503` 在 Step2 中都可以合法。
- 争议不在“是否合法”，而在“`500588029` 所在 corridor 更应归属谁”。
- 该样例可直接验证：
  - 最终保留是否仍由固定顺序决定
  - 仲裁结果是否能表达“两个都合法，但后者更应赢得 corridor”

## 本轮结果口径
- Step2 已显式新增 same-stage pair arbitration。
- 合法 pair 的最终保留不再由固定顺序直接决定。
- `XXXS7` 当前已可输出：
  - conflict component
  - arbitration winner / loser
  - `500588029` 的 corridor 归属结果与原因
