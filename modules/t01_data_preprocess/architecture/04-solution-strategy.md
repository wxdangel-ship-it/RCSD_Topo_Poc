# 04 方案策略

## 主流程
1. 建立 working `nodes / roads`
2. 执行环岛预处理
3. 通过 `Step1 / Step2 / Step3` 完成首轮构段与 refresh
4. 通过 `Step4 / Step5A / Step5B / Step5C` 在 residual graph 上逐轮扩展
5. 在 `Step5C` refreshed 结果上执行单向补段 continuation
6. 通过 `Step6` 形成 Segment 聚合与合理性反查

## 当前 accepted 策略重点
- Step1 仅输出 `pair_candidates`
- Step2 输出：
  - `validated / rejected`
  - `trunk`
  - `segment_body`
  - `step3_residual`
- final segment 只表达 pair-specific road body
- Step4 与 Step5 各子阶段继续基于当前 refreshed `grade_2 / kind_2` 输入
- Step4 对两端 `grade_2 = 1` 的 validated pair 直接产出 `0-0双`，并用 `segment_build_source = step4_high_grade_terminal_demotion` 标记该段允许在 Step6 穿越中间高等级分歧 / 合流语义节点
- Step5A / Step5B / Step5C 按顺序执行，并在每个子阶段后立即 refresh
- Step5C 使用 adaptive barrier fallback，Step5A / Step5B 仍保持严格 terminate 逻辑
- 单向补段 continuation 只消化 `Step5` refreshed 结果，不回写 `Step1-Step5` 的双向 accepted baseline 语义
- 单向补段允许 `road_kind = 1` 的封闭式 / 高速相关 road 进入候选，并将 `kind_2 = 128` 作为 `0-1单 / 0-2单` 的复杂分歧 / 合流 terminate
- dead-end leaf 补段作为单向补段 continuation 内的受控收尾：只处理单条双向 road 或两条方向互补单向 road bundle，要求一端为合法语义端点、另一端为无其他有效延展的 leaf node
- final single-road fallback 在常规单向 trace 与 dead-end leaf 之后执行；它不放宽前序 terminate 规则，把仍未构段、非排除、端点可解析的单向 road 发布为单 road `0-2单` Segment，把同类双向 road 发布为单 road `0-2双` Segment
- final side-attachment merge 在 final fallback 之后、Step6 之前执行；它只把已构段、挂接到 `0-0双` 主 Segment、且候选自身到主 Segment 最大采样距离不超过 `MAX_SIDE_ACCESS_DISTANCE_M` 的单向 / 双向候选 Segment 并入主 Segment，并保留 `pre_merge_*` 审计字段
- Step6 只消费最新 refreshed 结果，不重新做构段搜索；普通 `0-0双` 仍执行内部高等级 `grade/kind` 冲突反查，只有带 Step4 高等级降级来源标记的 Segment 可以审计豁免该类中间节点

## same-stage arbitration
- Step2 先完成 single-pair validation。
- 对 single-pair legal 的 pair 进入 same-stage pair arbitration。
- arbitration 只在 pair-level conflict component 内部进行。
- 目标是避免“固定顺序先到先得”直接决定 contested corridor 归属。

## 文档策略
- accepted baseline 正文收敛到 `architecture/06-accepted-baseline.md`
- `INTERFACE_CONTRACT.md` 只保留对外契约摘要
- `README.md` 只保留入口、说明和索引
