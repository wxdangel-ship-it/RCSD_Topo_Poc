# 01 Introduction And Goals

## 目标

T06 当前目标是在 T01 SWSD Segment 与 T05 Phase 2 SWSD-RCSD 语义路口关系已经产出的前提下，完成 Segment 融合前置判断：

1. 识别具备 EVD 与 anchor/fallback 基础的 SWSD Segment。
2. 基于 SWSD Segment buffer 在 copy-on-write RCSD 网络中构建 RCSDSegment 审查成果。
3. 将 buffer 构建成功结果同步派生为兼容的 candidates / replaceable 输出。

## 成功判据

- Step1 能输出 SWSD Segment 候选集、最终可融合集合、兼容 EVD candidates / fusion units、rejected 与 summary。
- Step2 能输出 buffer RCSDSegment、兼容 candidates、兼容 replaceable、rejected 与 summary。
- `fail4_fallback` 作为可融合 anchor 被正确接受。
- Step2 不执行 pair-to-pair 路径搜索、SWSD 单向方向推导、RCSD 方向一致性或趋势硬筛。
- `junc_nodes` 中非豁免 relation 节点作为 required semantic nodes；`junc_kind2_exempt_nodes` 只作为 optional allowed 审计节点。
- 所有失败都有稳定 reason 与审计字段。

## 当前非目标

- 不执行 Segment 替换。
- 不重塑路口。
- 不修改 T01 / T05 输出。
- 不新增 repo 官方入口。
