# Feature Specification: T04 Step4 Primary Evidence + Positive RCSD Iteration

**Feature Branch**: `codex/t04-step4-primary-evidence-positive-rcsd-20260422`
**Created**: 2026-04-22
**Status**: In Progress
**Input**: 用户要求在 `T04 / Step4` 冻结口径上，完成主证据查找、正向 RCSD 选择、`required_rcsd_node` 输出、审计图增强与 Anchor_2 回归。

## 1. 范围

- 仅处理 `T04 / Step4`
- 仅回写 Step4 相关线程需求、repo 正式文档、Step4 代码与 Step4 review 输出
- 不进入 `Step5-7`
- 不回改 `Step1-3` baseline
- 不新增 repo 官方 CLI / shell 入口

## 2. 已冻结的新口径

### 2.1 候选空间与主证据

- `unit-local branch pair region` 是第一层候选查找单元。
- `unit-local structure face` 是当前 unit 的主事实空间。
- 不再先回到“大走廊高召回空间”再挑主证据。
- 候选不是整个导流带对象或整个道路结构面对象，而是 `local candidate unit`：
  - 上层证据对象
  - 当前 unit 内切出的局部单连通区域
  - 一个代表性参考位置

### 2.2 主证据进入讨论与优先级

- 证据对象满足以下任一条件即可进入讨论：
  - 与当前候选空间有交集
  - 主体进入当前候选空间
  - 尖端虽不在候选空间内，但主体与当前 unit 候选空间连续
  - 明显表达当前 unit 的分歧 / 合流方向变化
- 主证据优先级分三层：
  - 第一层：主体稳定在当前 unit 的 `middle corridor` 内，reference 与事实方向一致；tip 同时在候选空间内时最高
  - 第二层：主体稳定在 `middle corridor` 内，reference 可在候选空间外，但与主体连续且方向一致
  - 第三层：主体仅弱进入 `middle corridor`，或 tip / 主体关系弱，或更像别的 unit；不得直接当主证据
- `axis_position_m = 0` / reference 贴 node 只允许作为弱种子或低优先级 tie-breaker，不得自动排第一。
- 若当前 unit 无合法主证据，必须输出 `selected_evidence = none`。

### 2.3 正向 RCSD

- 正向 RCSD 不参与第一层证据生成，只在主证据成立后进入支持判断。
- 候选池组织顺序冻结为：
  - 先按当前 unit 特征筛
  - 再做邻域匹配
- 一致性等级冻结为：
  - `A / strong_consistent`
  - `B / partial_consistent`
  - `C / no_support`
- 作用边界冻结为：
  - A：可参与主证据支持、主证据修正、下游 polygon 强约束
  - B：只做支持 / 风险提示，不直接推翻主证据
  - C：仅输出 `no_support`，不自动否决主证据
- 若主证据位置存在正向匹配的 RCSD 路口节点，则必须输出 `required_rcsd_node`，供后续 polygon 强制包含。

## 3. 当前实现偏差

- 线程需求与 repo 文档仍停留在“RCSD 是验证器 / 约束器 / 重排器”的旧抽象，没有正式写出 `A/B/C`、`required_rcsd_node` 和输出字段。
- 当前 T04 代码已有 `selected_evidence`、`selected_evidence_state = none` 与 case 内重选，但 RCSD 仍只暴露粗粒度 `rcsd_consistency_result`，无法表达：
  - `selected_rcsdroad_ids`
  - `selected_rcsdnode_ids`
  - `primary_main_rc_node`
  - `positive_rcsd_support_level`
  - `positive_rcsd_consistency_level`
  - `required_rcsd_node`
- 当前审计图只把 RCSD 作为一层统一红色几何，不够支持人工快速判断：
  - 哪个是主支持对象
  - 哪个是 RCSDNode
  - 哪个是 `required_rcsd_node`
  - 当前支持到底是 A / B / C

## 4. 功能性要求

- **FR-001**: 系统必须把主证据选择建立在 `local candidate unit` 上，而不是空间容器本身。
- **FR-002**: 系统必须把 `node_fallback_only` 候选从主排序第一优先级降级为弱候选 / tie-breaker。
- **FR-003**: 系统必须在候选不合法时继续在当前 unit 候选池内重选；全部不合法时显式输出 `selected_evidence = none`。
- **FR-004**: 系统必须在 Step4 输出中显式给出正向 RCSD 的 road/node 选择结果。
- **FR-005**: 系统必须把正向 RCSD 一致性输出为 `A/B/C` 三类稳定字段。
- **FR-006**: 系统必须区分 RCSD 的 `support level` 与 `consistency level`，并把 B/C 的作用边界限制在支持 / 提示层。
- **FR-007**: 系统必须在存在正向匹配主 RCSD 节点时输出 `required_rcsd_node`。
- **FR-008**: 系统必须增强 Step4 review 输出，使人工能一眼判断主证据、reference point、正向 RCSDRoad / RCSDNode、`required_rcsd_node` 及其 A/B/C 关系。
- **FR-009**: 系统必须保持 Step1-3 baseline 与当前 Step4 已通过的 Anchor_2 case 不回退。

## 5. 非目标

- 不做 `Step5/6/7` 规则或输出。
- 不做跨 Case 的 RCSD 二次校验闭环。
- 不重写 T02 Stage4 RCSD 内核。
- 不把当前轮次扩成 repo 大规模重构。

## 6. 验收口径

- `selected_evidence` 更符合新口径，且 `node_fallback_only` 不再自动第一。
- 无主证据时可稳定输出 `selected_evidence = none`。
- 正向 RCSD 能输出 road/node/support/consistency/required-node 全套字段。
- 审计图和 review index / summary 能快速表明 A/B/C 与 `required_rcsd_node`。
- `tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py` 通过。
- `Anchor_2` 跑出 `step4_review_index.csv`、`step4_review_summary.json`、`step4_review_flat` 与 per-case / per-unit review 图。
