# 014 - Step2 平行 Corridor 策略对齐

## 背景
- 触发样例：
  - 外网补充样例 `XXXS4`
  - 活动基线 `XXXS / XXXS2 / XXXS3`
- 触发问题：
  - `XXXS4 / S2:957177__997989` 中，目视上应纳入的侧向通路在 `Step2` 被过早截断
  - `XXXS4 / S2:950362__998028` 中，挂到其他已验证 pair 内部 support node 的 road 被错误纳入
  - `mainnodeid` 原字段在历史实现中被 working 语义覆写，违反 raw field 保真要求

## 本轮确认的规则方向
- raw field 保真：
  - raw `mainnodeid` 必须保持输入原值
  - 运行期 `mainnode` 语义改写到新增字段 `working_mainnodeid`
- 右转专用道口径：
  - 挂接右转专用道的节点，不应被表述为“through 的硬切断点”
  - 正确口径是：若去除右转专用道后该节点不构成真实路口，则该节点不应作为构段路口
  - 右转专用道自身不参与 Segment 构建
- `Step2` 搜索分层：
  - trunk candidate search 保持窄口径
  - `segment_body` candidate search 可在局部分叉处继续展开
- side corridor 语义：
  - 单向平行于主路的 side corridor 可保留在当前 pair `segment_body`
  - 双向平行于主路的 side corridor 不应并入当前 pair，应进入 `step3_residual`
- support barrier：
  - 若 component 触到其他已验证 pair 的内部 support node，对应 road 不能直接并入当前 pair

## 已落地修复
- Step1 图搜索新增 `incident_degree_exclude_formway_bits_any=[7]` 约束，右转专用道不参与 pair graph / through 搜索
- Step4 / Step5 对“仅由右转专用道挂接形成的 pseudo junction”做统一降级，不再保留为 boundary / endpoint
- raw `mainnodeid` 保真，working 语义迁移到 `working_mainnodeid`
- `Step2` trunk search 与 `segment_body` expansion 分离
- 新增 `hits_other_validated_support_node` barrier
- 新增 `parallel_corridor_directionality` 审计字段
- 新增 side component `component_directionality / bidirectional_road_ids` 审计字段
- 明确：合法“单侧旁路系统”只允许由单向平行侧路构成；包含双向 side road 的 component 一律转 `step3_residual`
- 新增全阶段前置门禁：若 trunk candidate 属于 `bidirectional_minimal_loop`，且内部路径呈“弱 connector node 串接 + 内部 T-support / support anchor 闭合”，则该 pair 在 `single-pair validation` 直接以 `t_junction_vertical_tracking_blocked` 拒绝；该规则对 Step2 / Step4 / Step5A / Step5B / Step5C 全部生效，不再允许后续阶段重新构出同一路径

## 当前验证状态
- 定向单测：
  - `test_working_layers / test_step1_pair_poc / test_step2_segment_poc / test_slice_builder / test_s2_baseline_refresh / test_step4_residual_graph / test_step5_staged_residual_graph`
  - 当前已通过
- 外网样例：
  - `XXXS4`
    - `S2:957177__997989` 已能保留目标单向侧向 corridor
    - `S2:950362__998028` 中 `611944611` 已被 support barrier 切掉
- 字段审计：
  - `XXXS / XXXS2 / XXXS3 / XXXS4` 输出节点原字段与输入逐字段比对为 `0` 差异
  - `mainnodeid` 差异为 `0`

## 当前未完成项
- 活动基线 compare 仍未通过：
  - `XXXS`
  - `XXXS2`
  - `XXXS3`
- 现阶段判定：
  - “单向 / 双向”方向性门本身不是唯一问题
  - 当前 `segment_body` expansion 仍存在对“平行 corridor”几何语义判定不足的问题
  - 因此该策略方向已确认，但尚未收敛为新的 freeze baseline

## 新收敛的候选规则
- 当前不再采用以下过窄或过宽的单条件规则：
  - 仅凭 `one_way_parallel`
  - 仅凭 `attachment_node_ids` 全部命中内部 T 型 support node
  - 仅凭“attachment 恰好 2 个 / 子图必须是简单路径”
- 当前更接近业务口径的候选规则是：
  - 作用范围仅限 `Step2` 的 `non_trunk_component -> segment_body` 判定
  - 在主 Segment 的每个内部 support node 上，先识别 trunk / support path 的本地主通行 `I` 向
  - 只有不属于 `I` 向延续的 incident road，才视为侧向 branch 候选
  - 允许保留的 side subgraph 可以包含：
    - 多条单向平行侧路
    - 这些单向侧路之间的短小连接路
  - 但这些 side roads 本身不得是双向 road；若 component 含双向 side road，则不再视为合法单侧旁路
  - 但整体必须仍然表达“从主 Segment 侧向挂出并最终回到主 Segment 的单侧旁路系统”
  - 单侧旁路的 branch 必须与当前 Segment 该侧通行方向一致；反方向 branch 不能保留
  - 若 component 借内部路口的 `I` 向再次串联多个内部路口，形成内部挂接网，而不是单侧旁路系统，则应转入 `step3_residual`

## 代表性样例
- 应排除：
  - `XXXS / S2:767878__12823253`
    - 当前问题是从内部 T 型 support node 继续吞入侧向结构
  - `XXXS / S2:767738__768622`
    - 当前误纳入 `46336763 / 502148533 / 616663182`
    - 该子图通过中心节点 `40237164` 把 `40237137 / 55225270 / 74463926` 三个内部挂点再次串成内部网
  - `XXXS3 / XXXS4 / S2:950362__998028`
    - 当前 `1253343 / 514222683 / 529159693` 仍表现为内部挂接网
- 应保留：
  - `XXXS4 / S2:957177__997989`
    - `602977049 / 503986070 / 512566307 / 509978909`
    - 该子图更符合“单侧旁路系统”语义，不应因多个单向侧路或短小连接而被误伤

## 下一轮实现拆解
- 首先只改 `Step2 prune`，不改 `Step1 seed / terminate`
- 实现顺序建议：
  - 为内部 support node 增加本地 `I` 向审计
  - 将 candidate side subgraph 的 branch 按“同向 / 反向 / 借 `I` 向延续”分类
  - 先剪掉反方向 branch
  - 再判断剩余子图是“单侧旁路系统”还是“内部挂接网”
  - 合法旁路系统走现有 `50m gate`
  - 内部挂接网统一转 `step3_residual`
- 验证优先级：
  - `XXXS / S2:767738__768622`
  - `XXXS / S2:767878__12823253`
  - `XXXS4 / S2:957177__997989`
  - `XXXS3 / XXXS4 / S2:950362__998028`

## 结论
- 本记录用于固化：
  - 已确认的修复方向
  - 已完成的字段保真与 support barrier 修复
  - corridor 策略当前仍处于 `agreed strategy / pending active-baseline reconciliation`
- 在活动三样例 compare 全部恢复一致前：
  - 不更新 freeze baseline
  - 不将 corridor 策略提升为新的 accepted active baseline contract
