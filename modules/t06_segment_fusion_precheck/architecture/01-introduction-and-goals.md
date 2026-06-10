# 01 Introduction And Goals

## 目标

T06 当前目标是在 T01 SWSD Segment 与 T05 Phase 2 SWSD-RCSD 语义路口关系已经产出的前提下，完成 Segment 融合判断与融合输出：

1. 识别具备 EVD 与 anchor/fallback 基础的 SWSD Segment。
2. 基于 SWSD Segment buffer 在 copy-on-write RCSD 网络中构建 RCSDSegment 审查成果。
3. 将 buffer 构建成功结果输出为 candidates，并在特殊路口组门控后输出最终 replaceable 集合。
4. 消费 Step2 replaceable RCSDSegment，输出融合后的 F-RCSD Road / Node，并重建涉及的语义路口关系。

## 成功判据

- Step1 能输出 SWSD Segment 候选集、最终可融合集合、rejected、summary 与按 `sgrade` 分组的统计 CSV，且不重复输出相同业务成果。
- Step2 能输出 buffer RCSDSegment、candidates、最终 replaceable、rejected、buffer-only probe、repair candidates、failure business audit、特殊路口组审计与 summary。
- Step3 能输出 F-RCSD Road / Node、replacement unit 审计、junction C 重建审计与 summary。
- `fail4_fallback` 作为可融合 anchor 被正确接受。
- Step2 不执行 pair-to-pair 路径搜索或趋势硬筛；`swsd_directionality=single` 的 source/target 必须由 SWSDRoad `snodeid / enodeid / direction` 推导，`swsd_directionality=dual` 的 retained RCSD graph 必须通过 pair 两端双向可达审计。
- Step2 required semantic nodes 只来自 `pair_nodes` relation；`junc_nodes` relation 成功时作为 optional junc 审计和 corridor 解释节点，缺失、无效或被剪除时必须输出 dropped / lost attach 审计。
- 所有失败都有稳定 reason 与审计字段。

## 当前非目标

- 不修改 T01 / T05 输出。
- 不处理 Step2 rejected Segment 的替换。
- 不通过几何猜测静默补救 Step2 未通过的 Segment；buffer-only probe 输出诊断、候选 pair 与 pair 锚定错误位置，不覆盖 T05 relation，也不把候选 pair 直接写入 replaceable。
- 不新增 repo 官方入口。
